"""Blueprint de nomina: upload XLS reloj, correcciones, calculo, descarga, overrides,
migracion offset historico, importar primer dia, snapshot."""
import os
import tempfile
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, send_file, session

from app_routes._auth import require_auth
from logger import get_logger
from nomina_logic import (
    MES_NAMES,
    apply_overrides,
    apply_recurrentes,
    banco_por_empleado,
    build_horas_por_periodo,
    build_nomina_por_periodo,
    calc_horas_periodo,
    compute_nomina_for_periodo,
    horas_dia_dict,
    es_finde_ds,
    periodo_de_data,
)
from procesar_rol import clasificar_todo, emp_name, match_empleados, parse_xls, write_excel_nomina
from storage import (
    _cfg_get,
    _cfg_set,
    list_registros_diarios,
    list_reportes,
    load_all_nomina_resumenes,
    load_empleados,
    load_nomina_overrides,
    load_registro_diario,
    load_reporte,
    save_nomina_overrides,
    save_nomina_resumen,
    save_registro_diario,
    save_reporte,
)

log = get_logger("nomina")

nomina_bp = Blueprint("nomina", __name__)


# ─── Registros diarios (legacy v1) ───

@nomina_bp.route("/api/registros", methods=["POST"])
@require_auth
def save_registro():
    data = request.get_json(force=True) or {}
    fecha = data.get("date", date.today().isoformat())
    payload = {
        "fecha": fecha,
        "total_material_kg": float(data.get("totalMat", 0)),
        "total_cajas": int(data.get("totalCajas", 0)),
        "observaciones": data.get("obs", ""),
        "merma_pct": float(data.get("mermaPct", 0)),
        "raw": data,
    }
    save_registro_diario(fecha, payload)
    return jsonify({"ok": True})


@nomina_bp.route("/api/registros/<month>", methods=["GET"])
@require_auth
def get_registros(month):
    registros_dict = list_registros_diarios(month)
    result = []
    for fecha in sorted(registros_dict.keys()):
        try:
            r = load_registro_diario(fecha)
            if r:
                result.append({
                    "fecha": r.get("fecha", fecha),
                    "material": float(r.get("total_material_kg", 0)),
                    "cajas": int(r.get("total_cajas", 0)),
                    "obs": r.get("observaciones", ""),
                })
        except Exception:
            log.warning(f"get_registros: error leyendo {fecha}")
    return jsonify(result)


# ─── Nomina core ───

@nomina_bp.route("/api/nomina/reportes", methods=["GET"])
@require_auth
def get_nomina_reportes():
    return jsonify(list_reportes())


@nomina_bp.route("/api/nomina/upload", methods=["POST"])
@require_auth
def nomina_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        f.save(tmp.name)
        try:
            data = parse_xls(tmp.name)
        except Exception as e:
            log.exception("nomina_upload: error parseando XLS")
            return jsonify({"error": str(e)}), 422
        finally:
            os.unlink(tmp.name)

    emp_db = load_empleados()
    matched, nuevos, faltantes = match_empleados(data, emp_db)
    cls = clasificar_todo(data)

    periodo_id, periodo_label = periodo_de_data(data)
    if not periodo_id:
        return jsonify({"error": "No se pudo determinar el periodo del reporte"}), 422

    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    if not force:
        existing_data, _ = load_reporte(periodo_id)
        if existing_data:
            return jsonify({
                "conflict": True,
                "periodo_id": periodo_id,
                "periodo_label": periodo_label,
                "empleados": len(data),
            }), 409

    save_reporte(periodo_id, periodo_label, data, cls)
    log.info(f"nomina_upload: reporte {periodo_id} guardado ({len(data)} empleados)")

    existing = load_all_nomina_resumenes().get(periodo_id) or {}
    resumen_stub = {
        "periodo": periodo_id,
        "periodo_label": periodo_label,
        "total_transferido": existing.get("total_transferido", 0.0),
        "total_h50": existing.get("total_h50", 0.0),
        "total_h100": existing.get("total_h100", 0.0),
        "n_empleados": len(data),
    }
    save_nomina_resumen(periodo_id, resumen_stub)

    session["_nomina_data"] = data
    session["_nomina_cls"] = cls
    session["_nomina_matched"] = matched
    session["_nomina_periodo"] = periodo_id

    n_anom = 0
    for emp_name_x, days_cls in cls.items():
        for ds, c in days_cls.items():
            flags = c.get("flags") or []
            if any(f and not f.startswith("CORREG") for f in flags):
                n_anom += 1

    return jsonify({
        "empleados": len(data),
        "anomalias": n_anom,
        "nuevos": nuevos,
        "faltantes": faltantes,
        "periodo_id": periodo_id,
        "periodo_label": periodo_label,
    })


@nomina_bp.route("/api/nomina/corregir", methods=["POST"])
@require_auth
def nomina_corregir():
    """Recibe correcciones manuales y actualiza cls del reporte."""
    req = request.get_json(force=True) or {}
    periodo_id = req.get("periodo_id") or session.get("_nomina_periodo")
    ediciones = req.get("ediciones") or {}

    if not periodo_id:
        return jsonify({"error": "No hay periodo activo"}), 400

    data, cls = load_reporte(periodo_id)
    if not data or cls is None:
        return jsonify({"error": "Reporte no encontrado"}), 404

    emp_db = load_empleados()
    matched, _, _ = match_empleados(data, emp_db)
    key_to_name = {matched.get(emp_name(e_full), emp_name(e_full)): emp_name(e_full) for e_full, _, _ in data}

    def hhmm_to_min(s):
        if not s or ':' not in s:
            return None
        try:
            h, m = s.split(':')
            return int(h) * 60 + int(m)
        except Exception:
            return None

    # Pre-calcular balance del banco POR empleado para validacion
    # (no podemos cubrir mas horas de las que tiene en banco)
    banco_actual = banco_por_empleado(emp_db)

    n_updates = 0
    alertas = []
    for emp_key, dias in ediciones.items():
        name = key_to_name.get(emp_key, emp_key)
        cls_emp = cls.setdefault(name, {})
        for ds, vals in dias.items():
            day = cls_emp.setdefault(ds, {"h1": None, "h2": None, "h3": None, "h4": None, "flags": []})
            tiene_horas = any(k in vals for k in ("h1", "h2", "h3", "h4"))
            solo_flag = bool(vals.get("_flag")) and not tiene_horas
            solo_verificar = bool(vals.get("_verify")) and not tiene_horas
            solo_modo = ("_modo" in vals or "_cubrir" in vals) and not tiene_horas and not solo_flag and not solo_verificar

            # Validar cubrir_banco — no permitir si banco insuficiente
            if "_cubrir" in vals and bool(vals["_cubrir"]):
                # Calcular horas necesarias para cubrir este dia
                horas_actuales = horas_dia_dict(day)
                base_h = emp_db.get(emp_key, {}).get("horas_base", 8)
                if not es_finde_ds(ds):
                    horas_a_cubrir = max(0, base_h - horas_actuales)
                    saldo = banco_actual.get(emp_key, 0)
                    # Permitimos si banco >= 0 (no estricto a 0 absoluto porque las
                    # ediciones podrian estar acumulando varios cambios). Pero
                    # avisamos al usuario.
                    if saldo < horas_a_cubrir:
                        alertas.append(
                            f"{name} {ds}: banco insuficiente ({saldo}h disponibles, "
                            f"{horas_a_cubrir}h necesarias). El sistema permite cubrir "
                            f"pero el banco quedara negativo."
                        )

            if "h1" in vals: day["h1"] = hhmm_to_min(vals["h1"])
            if "h2" in vals: day["h2"] = hhmm_to_min(vals["h2"])
            if "h3" in vals: day["h3"] = hhmm_to_min(vals["h3"])
            if "h4" in vals: day["h4"] = hhmm_to_min(vals["h4"])
            if "_modo" in vals and vals["_modo"] in ("banco", "pagar"):
                day["modo_extra"] = vals["_modo"]
            if "_cubrir" in vals:
                day["cubrir_banco"] = bool(vals["_cubrir"])
            if solo_flag:
                day["flags"] = [str(vals["_flag"])]
            elif solo_verificar:
                day["flags"] = ["VERIFICADO"]
            elif not solo_modo:
                day["flags"] = ["CORREGIDO MANUALMENTE"]
            n_updates += 1

    y, m = periodo_id.split('-')
    label = f"{MES_NAMES[int(m)-1]} {y}"
    save_reporte(periodo_id, label, data, cls)
    log.info(f"nomina_corregir: {periodo_id}, {n_updates} updates, {len(alertas)} alertas")
    return jsonify({"ok": True, "updates": n_updates, "alertas": alertas})


@nomina_bp.route("/api/nomina/calcular", methods=["POST"])
@require_auth
def nomina_calcular():
    """Guarda calculo de nomina del periodo de forma INMUTABLE.

    El resumen guardado incluye el snapshot completo de cada empleado:
    salario, horas, decimos, descuentos, transferencias. Si en el futuro
    se edita el salario del empleado, la nomina pasada NO cambia retroactiva­
    mente — porque el calculo se hace desde el snapshot.

    Pre-condicion para auditoria SRI: pagos historicos deben ser reproducibles
    exactamente al centavo.
    """
    req = request.get_json(force=True) or {}
    periodo_id = req.get("periodo") or session.get("_nomina_periodo")
    if not periodo_id:
        return jsonify({"error": "No hay periodo activo"}), 400

    resumen, nomina_list = compute_nomina_for_periodo(periodo_id, req.get("extras_config", {}))
    if resumen is None:
        return jsonify({"error": "Reporte no encontrado"}), 404

    # Snapshot inmutable: guardar TODO el detalle (no solo agregados) en el resumen
    # para que recalcular en el futuro produzca exactamente el mismo numero.
    resumen["snapshot"] = {
        "empleados": [
            {
                "name": item.get("name"),
                "id": item.get("id"),
                "nomina": item.get("nomina"),  # dict completo de calcular_nomina
                "dias": item.get("dias", []),
            }
            for item in nomina_list
        ],
        "extras_config": req.get("extras_config", {}),
        "calculado_en": datetime.now().isoformat(timespec="seconds"),
    }
    # Alertas a nivel de resumen (suma de todas las alertas por empleado)
    todas_alertas = []
    for item in nomina_list:
        nom = item.get("nomina") or {}
        for a in (nom.get("alertas") or []):
            todas_alertas.append(f"[{item.get('name')}] {a}")
    resumen["alertas"] = todas_alertas

    save_nomina_resumen(periodo_id, resumen)
    log.info(
        f"nomina_calcular: {periodo_id} total={resumen['total_transferido']:.2f} "
        f"alertas={len(todas_alertas)}"
    )
    return jsonify(resumen)


@nomina_bp.route("/api/nomina/descargar/<periodo_id>", methods=["GET"])
@require_auth
def nomina_descargar(periodo_id):
    resumen, nomina_list = compute_nomina_for_periodo(periodo_id)
    if resumen is None:
        return jsonify({"error": "Reporte no encontrado"}), 404

    tmp_path = tempfile.mkstemp(suffix=".xlsx")[1]
    try:
        write_excel_nomina(nomina_list, resumen["periodo_label"], tmp_path)
        return send_file(tmp_path, as_attachment=True, download_name=f"nomina_{periodo_id}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        log.exception(f"nomina_descargar {periodo_id}: fallo generando XLSX")
        return jsonify({"error": f"Error generando XLSX: {e}"}), 500


@nomina_bp.route("/api/nomina/resumenes", methods=["GET"])
@require_auth
def get_nomina_resumenes():
    return jsonify(load_all_nomina_resumenes())


@nomina_bp.route("/api/nomina/overrides/<periodo_id>", methods=["GET"])
@require_auth
def get_nomina_overrides(periodo_id):
    return jsonify(load_nomina_overrides(periodo_id) or {})


@nomina_bp.route("/api/nomina/overrides/<periodo_id>", methods=["PUT"])
@require_auth
def put_nomina_overrides(periodo_id):
    data = request.get_json(force=True) or {}
    save_nomina_overrides(periodo_id, data)
    return jsonify({"ok": True})


@nomina_bp.route("/api/nomina/migrar-offset", methods=["POST"])
@require_auth
def migrar_offset_reportes():
    """Aplica shift +1 dia a TODAS las fechas de los reportes guardados.

    Soluciona reportes subidos antes del fix del parser. Idempotente.
    """
    try:
        reps = list_reportes() or []
    except Exception as e:
        log.exception("migrar-offset: error listando reportes")
        return jsonify({"error": f"No se pudo listar reportes: {e}"}), 500

    migrados = []
    saltados = []
    fallidos = []

    def _shift(ds_str):
        if not isinstance(ds_str, str):
            return ds_str
        parts = ds_str.split("-")
        if len(parts) != 3:
            return ds_str
        try:
            d = date(2000 + int(parts[0]), int(parts[1]), int(parts[2])) + timedelta(days=1)
            return d.strftime("%y-%m-%d")
        except Exception:
            return ds_str

    log.info(f"migrar-offset: encontrados {len(reps)} reportes")
    for rep in reps:
        rid = rep.get("id") if isinstance(rep, dict) else None
        if not rid:
            continue
        flag_key = f"nomina:offset_migrado:{rid}"
        try:
            if _cfg_get(flag_key, False):
                saltados.append(rid)
                continue
        except Exception as e:
            log.warning(f"migrar-offset: error leyendo flag de {rid}: {e}")

        try:
            data, cls = load_reporte(rid)
            if not data or cls is None:
                saltados.append(rid)
                continue

            new_data = []
            for tup in data:
                try:
                    emp, days, nid = tup
                except Exception:
                    continue
                new_days = {_shift(ds): pairs for ds, pairs in (days or {}).items()}
                new_data.append((emp, new_days, nid))

            new_cls = {}
            for emp_name_x, days_cls in (cls or {}).items():
                new_cls[emp_name_x] = {_shift(ds): d for ds, d in (days_cls or {}).items()}

            try:
                y, m = rid.split("-")
                label = f"{MES_NAMES[int(m)-1]} {y}"
            except Exception:
                label = rid

            save_reporte(rid, label, new_data, new_cls)
            _cfg_set(flag_key, True)
            migrados.append(rid)
        except Exception as e:
            log.exception(f"migrar-offset: error en reporte {rid}")
            fallidos.append({"id": rid, "error": str(e)})

    log.info(f"migrar-offset: migrados={len(migrados)} saltados={len(saltados)} fallidos={len(fallidos)}")
    return jsonify({
        "migrados": migrados,
        "saltados_ya_migrados": saltados,
        "fallidos": fallidos,
        "total": len(migrados),
    })


@nomina_bp.route("/api/nomina/importar-primer-dia/<periodo_id>", methods=["POST"])
@require_auth
def importar_primer_dia(periodo_id):
    """Copia horas del ultimo dia del reporte anterior al primer dia del actual."""
    data_act, cls_act = load_reporte(periodo_id)
    if not data_act or cls_act is None:
        return jsonify({"error": "Reporte actual no encontrado"}), 404

    try:
        y, m = periodo_id.split("-")
        y_int, m_int = int(y), int(m)
        m_prev = m_int - 1
        y_prev = y_int
        if m_prev == 0:
            m_prev = 12
            y_prev -= 1
        periodo_prev = f"{y_prev}-{m_prev:02d}"
    except Exception:
        return jsonify({"error": "Periodo invalido"}), 400

    data_prev, cls_prev = load_reporte(periodo_prev)
    if not data_prev or not cls_prev:
        return jsonify({"error": f"No hay reporte guardado para {periodo_prev}"}), 404

    primer_dia_ds = f"{y[-2:]}-{m}-01"
    n_updates = 0
    for emp_name_x, days_prev in cls_prev.items():
        if not days_prev:
            continue
        ult_ds = max(days_prev.keys())
        ult_dia = days_prev[ult_ds]
        cls_act.setdefault(emp_name_x, {})
        cls_act[emp_name_x][primer_dia_ds] = {
            "h1": ult_dia.get("h1"),
            "h2": ult_dia.get("h2"),
            "h3": ult_dia.get("h3"),
            "h4": ult_dia.get("h4"),
            "flags": ["IMPORTADO DEL MES ANTERIOR"],
            "modo_extra": ult_dia.get("modo_extra", "banco"),
        }
        n_updates += 1

    label = f"{MES_NAMES[m_int-1]} {y}"
    save_reporte(periodo_id, label, data_act, cls_act)
    return jsonify({"ok": True, "updates": n_updates, "desde_periodo": periodo_prev})


@nomina_bp.route("/api/nomina/snapshot", methods=["GET"])
@require_auth
def get_nomina_snapshot():
    """Retorna todos los datos derivados de nomina: horas, banco, historica, overrides."""
    emp_db = load_empleados()
    horas_por_periodo = build_horas_por_periodo(emp_db)
    nomina_por_periodo = build_nomina_por_periodo(emp_db)
    banco_por_emp = banco_por_empleado(emp_db)
    reps_ids = [r["id"] for r in list_reportes()]
    overrides_por_periodo = {rid: load_nomina_overrides(rid) or {} for rid in reps_ids}

    resumenes = load_all_nomina_resumenes()
    ids_all = set(resumenes.keys()) | set(nomina_por_periodo.keys())
    nomina_historica = []
    for rid in sorted(ids_all):
        try:
            y, m = rid.split("-")
            label = f"{MES_NAMES[int(m)-1]} {y}"
        except Exception:
            label = rid
        items = nomina_por_periodo.get(rid, [])
        total_real = sum(n["total"] for n in items)
        h50_real = sum(n["h50"] for n in items)
        h100_real = sum(n["h100"] for n in items)
        r = resumenes.get(rid, {})
        total_resumen = float(r.get("total_transferido", 0))
        nomina_historica.append({
            "id": rid, "label": label,
            "total": total_resumen if total_resumen > 0 else total_real,
            "h50": h50_real, "h100": h100_real,
            "empleados": len(items) or len(emp_db),
        })

    return jsonify({
        "horas_por_periodo": horas_por_periodo,
        "nomina_por_periodo": nomina_por_periodo,
        "banco_por_emp": banco_por_emp,
        "overrides_por_periodo": overrides_por_periodo,
        "nomina_historica": nomina_historica,
    })
