import io
import json
import os
import tempfile
from datetime import date, datetime
from functools import wraps

from flask import Flask, jsonify, request, send_file, session

from costos import calcular_costos, sumar_gastos_fijos
from procesar_rol import (
    calcular_horas_clasificadas,
    calcular_nomina,
    clasificar_todo,
    emp_name,
    match_empleados,
    normalize,
    parse_xls,
    write_excel_nomina,
)
from storage import (
    delete_registro_diario,
    export_json,
    get_arrastre_anterior,
    import_json,
    list_registros_diarios,
    list_reportes,
    load_all_costos_snapshots,
    load_all_nomina_resumenes,
    load_arrastre,
    load_beneficios_recurrentes,
    load_certificados,
    load_clientes,
    load_cotizaciones,
    load_emisor,
    load_empaques,
    load_empleados,
    load_facturas,
    load_gastos_fijos,
    load_guias,
    load_inventario_mp,
    load_inventario_pt,
    load_materiales,
    load_movimientos_inventario,
    load_nomina_overrides,
    load_ordenes_compra,
    load_productos,
    load_registro_diario,
    load_reporte,
    save_arrastre,
    save_beneficios_recurrentes,
    save_certificados,
    save_clientes,
    save_costos_snapshot,
    save_cotizaciones,
    save_emisor,
    save_empaques,
    save_empleados,
    save_facturas,
    save_gastos_fijos,
    save_guias,
    save_inventario_mp,
    save_inventario_pt,
    save_materiales,
    save_movimientos_inventario,
    save_nomina_overrides,
    save_nomina_resumen,
    save_ordenes_compra,
    save_productos,
    save_registro_diario,
    save_reporte,
)

APP_VERSION = "4.0"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "solplast-dev-secret-2026")

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
APP_PASSWORD_OP = os.environ.get("APP_PASSWORD_OP", "")

HTML_PATH = os.path.join(os.path.dirname(__file__), "Solplast-ERP.html")

_EMP_COLORS = [
    "oklch(72% 0.14 295)", "oklch(72% 0.14 30)",  "oklch(72% 0.14 200)",
    "oklch(72% 0.14 140)", "oklch(72% 0.14 70)",  "oklch(72% 0.14 330)",
    "oklch(72% 0.14 260)", "oklch(72% 0.14 100)",
]


def _emp_to_js(key, emp, idx=0):
    nombre = emp.get("nombre", key)
    words = nombre.split()
    iniciales = "".join(w[0].upper() for w in words[:2]) if len(words) >= 2 else nombre[:2].upper()
    return {
        "id": key,
        "nombre": nombre,
        "cargo": emp.get("cargo", ""),
        "iniciales": iniciales,
        "color": _EMP_COLORS[idx % len(_EMP_COLORS)],
        "salario": float(emp.get("salario", 0)),
        "transporte": float(emp.get("transporte_dia", 0)),
        "horas_base": int(emp.get("horas_base", 8)),
        "region": emp.get("region", "Sierra/Amazonia"),
        "fondos_reserva": bool(emp.get("fondos_reserva", False)),
        "prestamo_iess": float(emp.get("prestamo_iess", 0)),
        "descuento_iess": bool(emp.get("descuento_iess", True)),
        "ocultar": bool(emp.get("ocultar", False)),
    }


def _mat_to_js(key, mat):
    return {
        "id": key,
        "nombre": mat.get("nombre", key),
        "costo_kg": float(mat.get("costo_kg", 0)),
        "merma": float(mat.get("merma_pct", 3.0)),
        "color": "oklch(70% 0.12 220)",
        "desactivado": bool(mat.get("desactivado", False)),
    }


def _prod_to_js(key, prod):
    return {
        "id": key,
        "kind": prod.get("kind", "vaso"),
        "nombre": prod.get("nombre", key),
        "unidades_caja": int(prod.get("unidades_caja", 1000)),
        "peso_g": float(prod.get("peso_g", 0)),
        "material": prod.get("material_desc", ""),
        "factor": float(prod.get("factor_complejidad", 1.0)),
        "costo_unit": float(prod.get("costo_unit", 0)),
        "costo_caja": float(prod.get("costo_caja", 0)),
        "desactivado": bool(prod.get("desactivado", False)),
    }


def _min_to_hhmm(mins):
    if mins is None:
        return ""
    try:
        m = int(mins)
        return f"{m // 60:02d}:{m % 60:02d}"
    except Exception:
        return ""


def _es_finde_ds(ds):
    try:
        parts = ds.split("-")
        y = int(parts[0])
        y_full = 2000 + y if y < 100 else y
        return date(y_full, int(parts[1]), int(parts[2])).weekday() >= 5
    except Exception:
        return False


def _horas_dia_dict(d):
    horas = 0.0
    if d.get("h1") is not None and d.get("h2") is not None:
        horas += (d["h2"] - d["h1"]) / 60
    if d.get("h3") is not None and d.get("h4") is not None:
        horas += (d["h4"] - d["h3"]) / 60
    return horas


def _horas_detalle_one(data_r, cls_r, emp_db):
    """Retorna {emp_id: [days]} para un reporte."""
    if not data_r or not cls_r:
        return {}
    matched_r, _, _ = match_empleados(data_r, emp_db)
    result = {}
    for emp_full, days, _ in data_r:
        name = emp_name(emp_full)
        dk = matched_r.get(name, name)
        cfg = emp_db.get(dk, {}) if dk else {}
        base_h = cfg.get("horas_base", 8)
        emp_days = []
        cls_emp = cls_r.get(name, {})
        for ds in sorted(cls_emp.keys()):
            d = cls_emp[ds]
            horas = _horas_dia_dict(d)
            flags = d.get("flags") or []
            finde = _es_finde_ds(ds)
            base_dia = 0 if finde else base_h
            excedente = max(0.0, horas - base_dia) if horas > 0 else 0.0
            deficit = max(0.0, base_dia - horas) if not finde else 0.0
            emp_days.append({
                "fecha": ds,
                "h1": _min_to_hhmm(d.get("h1")),
                "h2": _min_to_hhmm(d.get("h2")),
                "h3": _min_to_hhmm(d.get("h3")),
                "h4": _min_to_hhmm(d.get("h4")),
                "total": round(horas, 1),
                "flag": flags[0] if flags else "",
                "modo_extra": d.get("modo_extra", "banco"),
                "cubrir_banco": bool(d.get("cubrir_banco", False)),
                "es_finde": finde,
                "base_dia": base_dia,
                "excedente": round(excedente, 2),
                "deficit": round(deficit, 2),
            })
        result[dk] = emp_days
    return result


def _calc_horas_periodo(cls_emp, base_h):
    """Calcula horas considerando modo_extra y cubrir_banco por dia."""
    res = {
        "dias": 0, "dias_anomalia": 0,
        "horas_regular": 0.0, "horas_50": 0.0, "horas_100": 0.0,
        "banco_excedente": 0.0, "horas_cubiertas": 0.0,
        "horas_total": 0.0,
    }
    for ds, d in cls_emp.items():
        horas = _horas_dia_dict(d)
        modo = d.get("modo_extra", "banco")
        cubrir = bool(d.get("cubrir_banco", False))
        flags = d.get("flags") or []
        finde = _es_finde_ds(ds)

        if horas > 0:
            res["dias"] += 1
            if any(f.startswith("REVISAR:") for f in flags):
                res["dias_anomalia"] += 1
            res["horas_total"] += horas

        if finde:
            if horas > 0:
                if modo == "pagar":
                    res["horas_100"] += horas
                else:
                    res["banco_excedente"] += horas
        else:
            if horas > 0:
                reg = min(horas, base_h)
                res["horas_regular"] += reg
                excedente = max(0.0, horas - base_h)
                if excedente > 0:
                    if modo == "pagar":
                        res["horas_50"] += min(excedente, 4.0)
                        res["horas_100"] += max(0.0, excedente - 4.0)
                    else:
                        res["banco_excedente"] += excedente
                elif horas < base_h and cubrir:
                    deficit = base_h - horas
                    res["horas_regular"] += deficit
                    res["horas_cubiertas"] += deficit
            elif cubrir:
                res["horas_regular"] += base_h
                res["horas_cubiertas"] += base_h
                res["dias"] += 1

    for k in ("horas_regular", "horas_50", "horas_100", "banco_excedente", "horas_cubiertas", "horas_total"):
        res[k] = round(res[k], 2)
    return res


def _banco_por_empleado(emp_db):
    """Balance acumulado por empleado cronologicamente."""
    balances = {k: 0.0 for k in emp_db}
    reps = sorted([r["id"] for r in list_reportes()])
    for rid in reps:
        try:
            data_r, cls_r = load_reporte(rid)
        except Exception:
            continue
        if not data_r or not cls_r:
            continue
        matched_r, _, _ = match_empleados(data_r, emp_db)
        for emp_full, days, _ in data_r:
            name = emp_name(emp_full)
            dk = matched_r.get(name)
            if not dk or dk not in emp_db:
                continue
            base = emp_db[dk].get("horas_base", 8)
            hrs = _calc_horas_periodo(cls_r.get(name, {}), base)
            balances[dk] += hrs["banco_excedente"] - hrs["horas_cubiertas"]
    return {k: round(v, 2) for k, v in balances.items()}


def _build_horas_por_periodo(emp_db):
    """Retorna {periodo_id: {emp_id: [days]}}."""
    result = {}
    for rep in list_reportes():
        try:
            data_r, cls_r = load_reporte(rep["id"])
            result[rep["id"]] = _horas_detalle_one(data_r, cls_r, emp_db)
        except Exception:
            result[rep["id"]] = {}
    return result


_OVERRIDE_FIELDS = ("prestamo_iess", "transporte_dia", "descuento_iess", "fondos_reserva")


def _apply_overrides(cfg, overrides_emp):
    """Devuelve cfg con los campos override aplicados."""
    if not overrides_emp:
        return dict(cfg)
    out = dict(cfg)
    for f in _OVERRIDE_FIELDS:
        if f in overrides_emp:
            out[f] = overrides_emp[f]
    return out


def _vigente_en_periodo(desde: str, hasta: str | None, periodo_id: str) -> bool:
    """Verifica si una regla con vigencia desde/hasta aplica en periodo_id (YYYY-MM)."""
    if not periodo_id:
        return False
    if desde and periodo_id < desde:
        return False
    if hasta and periodo_id > hasta:
        return False
    return True


def _apply_recurrentes(cfg, empleado_id, periodo_id, recurrentes_all):
    """Aplica reglas de beneficios recurrentes vigentes al cfg.

    Las reglas tipo prestamo_iess y prestamo_empresa se suman a prestamo_iess.
    transporte_bono se suma al transporte_dia.
    alimentacion, comision, otro_ben se registran como bonos adicionales.
    """
    out = dict(cfg)
    prestamo_total = 0.0
    transporte_extra = 0.0
    bonos = 0.0
    otros_desc = 0.0
    for regla in (recurrentes_all or []):
        if regla.get("empleado_id") != empleado_id:
            continue
        if not _vigente_en_periodo(regla.get("desde"), regla.get("hasta"), periodo_id):
            continue
        tipo = regla.get("tipo")
        monto = float(regla.get("monto", 0))
        if tipo in ("prestamo_iess", "prestamo_empresa"):
            prestamo_total += monto
        elif tipo == "transporte_bono":
            transporte_extra += monto
        elif tipo in ("alimentacion", "comision", "otro_ben"):
            bonos += monto
        elif tipo == "otro_desc":
            otros_desc += monto
    if prestamo_total > 0:
        out["prestamo_iess"] = float(out.get("prestamo_iess", 0)) + prestamo_total
    if transporte_extra > 0:
        out["transporte_dia"] = float(out.get("transporte_dia", 0)) + transporte_extra
    if bonos > 0 or otros_desc > 0:
        out["_bonos_recurrentes"] = bonos
        out["_otros_desc_recurrentes"] = otros_desc
    return out


def _calc_nomina_one(periodo_id, data_r, cls_r, emp_db):
    if not data_r or not cls_r:
        return []
    matched_r, _, _ = match_empleados(data_r, emp_db)
    overrides = load_nomina_overrides(periodo_id) or {}
    recurrentes = load_beneficios_recurrentes() or []
    result = []
    for emp_full, days, nid in data_r:
        name = emp_name(emp_full)
        dk = matched_r.get(name)
        cfg_base = emp_db.get(dk, {}) if dk else {}
        cfg = _apply_overrides(cfg_base, overrides.get(dk or name, {}))
        cfg = _apply_recurrentes(cfg, dk or name, periodo_id, recurrentes)
        if not cfg.get("salario"):
            continue
        base_h = cfg.get("horas_base", 8)
        hrs = _calc_horas_periodo(cls_r.get(name, {}), base_h)
        hrs_for_nomina = {
            "dias": hrs["dias"],
            "horas_total": hrs["horas_total"],
            "horas_50": hrs["horas_50"],
            "horas_100": hrs["horas_100"],
            "horas_regular": hrs["horas_regular"],
        }
        cfg_c = dict(cfg)
        cfg_c["horas_comp_anterior"] = 0
        nom = calcular_nomina(hrs_for_nomina, cfg_c, {})
        result.append({
            "id": dk or name,
            "nombre": name,
            "dias": hrs["dias"],
            "horas": round(hrs["horas_total"], 1),
            "h50": round(hrs["horas_50"], 2),
            "h100": round(hrs["horas_100"], 2),
            "banco_delta": round(hrs["banco_excedente"] - hrs["horas_cubiertas"], 2),
            "quincena": round(nom["quincena"], 2),
            "extras": round(nom["horas_extras"], 2),
            "transporte": round(nom["transporte"], 2),
            "ingresos": round(nom["total_ingresos"], 2),
            "iess": round(nom["iess"], 2),
            "neto": round(nom["valor_recibir"], 2),
            "fondos": round(nom["fondos_reserva"], 2),
            "total": round(nom["total_transferido"], 2),
        })
    return result


def _build_nomina_por_periodo(emp_db):
    result = {}
    for rep in list_reportes():
        try:
            data_r, cls_r = load_reporte(rep["id"])
            result[rep["id"]] = _calc_nomina_one(rep["id"], data_r, cls_r, emp_db)
        except Exception:
            result[rep["id"]] = []
    return result


def _build_data_jsx():
    emp_db = load_empleados()
    empleados_js = [_emp_to_js(k, v, i) for i, (k, v) in enumerate(emp_db.items()) if not v.get("ocultar")]

    mats = load_materiales()
    materiales_js = [_mat_to_js(k, v) for k, v in mats.items()]

    prods = load_productos()
    productos_js = [_prod_to_js(k, v) for k, v in prods.items()]

    empaques_raw = load_empaques()
    empaques_js = [
        {
            "id": k,
            "nombre": v.get("nombre", k),
            "costo": float(v.get("costo", 0)),
            "unidad": v.get("unidad", "unidad"),
            "desactivado": bool(v.get("desactivado", False)),
        }
        for k, v in empaques_raw.items()
    ]

    horas_por_periodo = _build_horas_por_periodo(emp_db)
    nomina_por_periodo = _build_nomina_por_periodo(emp_db)
    resumenes = load_all_nomina_resumenes()
    _mes_names = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

    ids_all = set(resumenes.keys()) | set(nomina_por_periodo.keys())
    nomina_historica = []
    for rid in sorted(ids_all):
        try:
            y, m = rid.split("-")
            label = f"{_mes_names[int(m)-1]} {y}"
        except Exception:
            label = rid
        items = nomina_por_periodo.get(rid, [])
        total_real = sum(n["total"] for n in items)
        h50_real = sum(n["h50"] for n in items)
        h100_real = sum(n["h100"] for n in items)
        r = resumenes.get(rid, {})
        total_resumen = float(r.get("total_transferido", 0))
        nomina_historica.append({
            "id": rid,
            "label": label,
            "total": total_resumen if total_resumen > 0 else total_real,
            "h50": h50_real,
            "h100": h100_real,
            "empleados": len(items) or len(emp_db),
        })

    # Home requires at least 2 entries to compute delta — pad if needed
    while len(nomina_historica) < 2:
        from datetime import date as _date
        import calendar as _cal
        _hoy = _date.today()
        _idx = len(nomina_historica)
        _m = (_hoy.month - _idx - 1) % 12
        _y = _hoy.year if _hoy.month - _idx > 0 else _hoy.year - 1
        nomina_historica.insert(0, {
            "id": f"{_y}-{_m+1:02d}",
            "label": f"{_mes_names[_m]} {_y}",
            "total": 0.0, "h50": 0.0, "h100": 0.0, "empleados": len(emp_db),
        })

    hoy = date.today()
    mes_actual = hoy.strftime("%Y-%m")
    registros_diarios = list_registros_diarios(mes_actual)
    # list_registros_diarios returns a dict {fecha: val}
    fechas_recientes = sorted(registros_diarios.keys())[-5:]
    registros = []
    for fecha in fechas_recientes:
        try:
            reg = load_registro_diario(fecha)
            if reg:
                registros.append({
                    "fecha": reg.get("fecha", fecha),
                    "material": float(reg.get("total_material_kg", 0)),
                    "cajas": int(reg.get("total_cajas", 0)),
                    "obs": reg.get("observaciones", ""),
                })
        except Exception:
            pass

    gastos_raw = load_gastos_fijos(mes_actual)
    gastos_fijos_js = {
        "electricidad": float(gastos_raw.get("electricidad", 550)),
        "agua": float(gastos_raw.get("agua", 45)),
        "tinta": float(gastos_raw.get("tinta", 60)),
        "tinner": float(gastos_raw.get("tinner", 30)),
        "solvente": float(gastos_raw.get("solvente", 45)),
        "transporte": float(gastos_raw.get("transporte", 150)),
        "mantenimiento": float(gastos_raw.get("mantenimiento", 80)),
    }
    gastos_desactivados = list(gastos_raw.get("_desactivados", []))

    reps_ids = [r["id"] for r in list_reportes()]
    latest_id = reps_ids[0] if reps_ids else None
    horas_detalle = horas_por_periodo.get(latest_id, {}) if latest_id else {}
    nomina_ultimo = nomina_por_periodo.get(latest_id, []) if latest_id else []
    banco_por_emp = _banco_por_empleado(emp_db)
    overrides_por_periodo = {rid: load_nomina_overrides(rid) or {} for rid in reps_ids}

    beneficios_rec = load_beneficios_recurrentes() or []
    clientes_js = load_clientes()
    inv_mp = load_inventario_mp()
    inv_pt = load_inventario_pt()
    cotizaciones = load_cotizaciones()
    ordenes = load_ordenes_compra()
    facturas = load_facturas()
    guias = load_guias()
    certificados = load_certificados()
    emisor = load_emisor()

    overrides_js = [
        f"window.EMPLEADOS_MOCK = {json.dumps(empleados_js, ensure_ascii=False)};",
        f"window.MATERIALES_MOCK = {json.dumps(materiales_js, ensure_ascii=False)};",
        f"window.EMPAQUES_MOCK = {json.dumps(empaques_js, ensure_ascii=False)};",
        f"window.PRODUCTOS_MOCK = {json.dumps(productos_js, ensure_ascii=False)};",
        f"window.GASTOS_FIJOS_MOCK = {json.dumps(gastos_fijos_js, ensure_ascii=False)};",
        f"window.GASTOS_DESACTIVADOS = {json.dumps(gastos_desactivados, ensure_ascii=False)};",
        f"window.NOMINA_HISTORICA = {json.dumps(nomina_historica, ensure_ascii=False)};",
        f"window.NOMINA_ULTIMO = {json.dumps(nomina_ultimo, ensure_ascii=False)};",
        f"window.HORAS_DETALLE = {json.dumps(horas_detalle, ensure_ascii=False)};",
        f"window.HORAS_POR_PERIODO = {json.dumps(horas_por_periodo, ensure_ascii=False)};",
        f"window.NOMINA_POR_PERIODO = {json.dumps(nomina_por_periodo, ensure_ascii=False)};",
        f"window.BANCO_POR_EMP = {json.dumps(banco_por_emp, ensure_ascii=False)};",
        f"window.OVERRIDES_POR_PERIODO = {json.dumps(overrides_por_periodo, ensure_ascii=False)};",
        f"window.LATEST_PERIODO = {json.dumps(latest_id)};",
        f"window.REGISTROS_RECIENTES = {json.dumps(registros, ensure_ascii=False)};",
        f"window.COSTOS_EVOLUCION_MESES = window.NOMINA_HISTORICA.map(m => m.label);",
        f"window.BENEFICIOS_RECURRENTES_MOCK = {json.dumps(beneficios_rec, ensure_ascii=False)};",
    ]

    if clientes_js is not None:
        overrides_js.append(f"window.CLIENTES_MOCK = {json.dumps(clientes_js, ensure_ascii=False)};")
    if inv_mp is not None:
        overrides_js.append(f"window.INVENTARIO_MP_MOCK = {json.dumps(inv_mp, ensure_ascii=False)};")
    if inv_pt is not None:
        overrides_js.append(f"window.INVENTARIO_PT_MOCK = {json.dumps(inv_pt, ensure_ascii=False)};")
    if cotizaciones is not None:
        overrides_js.append(f"window.COTIZACIONES_MOCK = {json.dumps(cotizaciones, ensure_ascii=False)};")
    if ordenes is not None:
        overrides_js.append(f"window.ORDENES_COMPRA_MOCK = {json.dumps(ordenes, ensure_ascii=False)};")
    if facturas is not None:
        overrides_js.append(f"window.FACTURAS_MOCK = {json.dumps(facturas, ensure_ascii=False)};")
    if guias is not None:
        overrides_js.append(f"window.GUIAS_MOCK = {json.dumps(guias, ensure_ascii=False)};")
    if certificados is not None:
        overrides_js.append(f"window.CERTIFICADOS_MOCK = {json.dumps(certificados, ensure_ascii=False)};")
    if emisor is not None:
        overrides_js.append(f"window.EMISOR = {json.dumps(emisor, ensure_ascii=False)};")

    return "\n// Overrides inyectados por el servidor — v" + APP_VERSION + "\n" + "\n".join(overrides_js) + "\n"


def _build_login_patch():
    return """
// Auth patch — injected by server
(function() {
  window._api = {
    logout: async () => {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    },
    login: async (role, password) => {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, password }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveEmpleado: async (id, data) => {
      const r = await fetch('/api/empleados/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    createEmpleado: async (data) => {
      const r = await fetch('/api/empleados', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    deleteEmpleado: async (id) => {
      const r = await fetch('/api/empleados/' + encodeURIComponent(id), {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveRegistro: async (data) => {
      const r = await fetch('/api/registros', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    uploadNomina: async (file, force) => {
      const fd = new FormData();
      fd.append('file', file);
      const url = '/api/nomina/upload' + (force ? '?force=1' : '');
      const r = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' });
      try {
        const json = await r.json();
        if (r.status === 409) json.conflict = true;
        return json;
      } catch { return { error: 'Respuesta invalida del servidor' }; }
    },
    saveMaterial: async (id, data) => {
      const r = await fetch('/api/materiales/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveEmpaque: async (id, data) => {
      const r = await fetch('/api/empaques/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveGastos: async (period, data) => {
      const r = await fetch('/api/gastos_fijos/' + encodeURIComponent(period), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    corregirNomina: async (periodo_id, ediciones) => {
      const r = await fetch('/api/nomina/corregir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ periodo_id, ediciones }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveProducto: async (id, data) => {
      const r = await fetch('/api/productos/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    createProducto: async (data) => {
      const r = await fetch('/api/productos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    setDesactivado: async (kind, id, desactivado) => {
      const r = await fetch(`/api/${kind}/${encodeURIComponent(id)}/desactivar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ desactivado }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchEmpleados: async () => {
      const r = await fetch('/api/empleados', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchProductos: async () => {
      const r = await fetch('/api/productos', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchMateriales: async () => {
      const r = await fetch('/api/materiales', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchEmpaques: async () => {
      const r = await fetch('/api/empaques', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchNominaSnapshot: async () => {
      const r = await fetch('/api/nomina/snapshot', { credentials: 'same-origin' });
      return r.ok ? r.json() : null;
    },
    saveOverrides: async (periodo_id, data) => {
      const r = await fetch('/api/nomina/overrides/' + encodeURIComponent(periodo_id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    setGastoDesactivado: async (period, key, desactivado) => {
      const r = await fetch(`/api/gastos_fijos/${encodeURIComponent(period)}/desactivar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, desactivado }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    applySnapshot: (snap) => {
      if (!snap) return;
      const replace = (target, src) => {
        for (const k of Object.keys(target)) delete target[k];
        Object.assign(target, src || {});
      };
      replace(window.HORAS_POR_PERIODO, snap.horas_por_periodo);
      replace(window.NOMINA_POR_PERIODO, snap.nomina_por_periodo);
      replace(window.BANCO_POR_EMP, snap.banco_por_emp);
      replace(window.OVERRIDES_POR_PERIODO, snap.overrides_por_periodo);
      if (Array.isArray(snap.nomina_historica)) {
        window.NOMINA_HISTORICA.length = 0;
        window.NOMINA_HISTORICA.push(...snap.nomina_historica);
        window.COSTOS_EVOLUCION_MESES = window.NOMINA_HISTORICA.map(m => m.label);
      }
    },
    refreshNomina: async () => {
      const snap = await window._api.fetchNominaSnapshot();
      window._api.applySnapshot(snap);
      return snap;
    },
    calcularNomina: async (periodo, extras) => {
      const r = await fetch('/api/nomina/calcular', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ periodo, extras_config: extras || {} }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveRecurrentes: async (empleadoId, rules) => {
      const r = await fetch('/api/nomina/recurrentes/' + encodeURIComponent(empleadoId), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rules }),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    saveCollection: async (kind, data) => {
      const r = await fetch('/api/collection/' + encodeURIComponent(kind), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchCollection: async (kind) => {
      const r = await fetch('/api/collection/' + encodeURIComponent(kind), { credentials: 'same-origin' });
      return r.ok ? r.json() : null;
    },
    emitirFactura: async (factura_id) => {
      const r = await fetch('/api/sri/emitir/' + encodeURIComponent(factura_id), {
        method: 'POST', credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error en emision' };
    },
    consultarAutorizacion: async (clave) => {
      const r = await fetch('/api/sri/autorizar/' + encodeURIComponent(clave), { credentials: 'same-origin' });
      return r.ok ? r.json() : null;
    },
    getSriConfig: async () => {
      const r = await fetch('/api/sri/config', { credentials: 'same-origin' });
      return r.ok ? r.json() : null;
    },
    urlPdfFactura: (factura_id) => '/api/sri/pdf/' + encodeURIComponent(factura_id),
    urlXmlFactura: (factura_id) => '/api/sri/xml/' + encodeURIComponent(factura_id),
  };
})();
"""


def _inject_html(raw_html):
    # Inyectamos un script de overrides DESPUÉS del data.jsx del handoff.
    # El HTML ya tiene mocks completos como fallback; sobrescribimos los globales
    # de window.X con los datos reales del backend.
    data_start = raw_html.find('<script type="text/babel" data-file="data.jsx">')
    data_end = raw_html.find('</script>', data_start) + len('</script>')
    if data_start >= 0 and data_end > data_start:
        override_script = (
            '\n<script>\n' + _build_data_jsx() + '\n</script>\n'
        )
        raw_html = raw_html[:data_end] + override_script + raw_html[data_end:]

    old_submit = "    if (!pwd) { setErr('Ingresa la contraseña'); return; }\n    onLogin(role);"
    new_submit = """    if (!pwd) { setErr('Ingresa la contraseña'); return; }
    setErr('');
    setLoading(true);
    (window._api?.login(role, pwd) || Promise.resolve(true)).then(ok => {
      setLoading(false);
      if (ok || !window._api) { onLogin(role); }
      else { setErr('Contraseña incorrecta'); }
    }).catch(() => { setLoading(false); setErr('Error de conexión'); });"""
    if old_submit in raw_html:
        raw_html = raw_html.replace(old_submit, new_submit)
        old_login_state = "  const [err, setErr] = useState('');"
        new_login_state = "  const [err, setErr] = useState('');\n  const [loading, setLoading] = useState(false);"
        raw_html = raw_html.replace(old_login_state, new_login_state, 1)

    api_script = f'<script>\n{_build_login_patch()}\n</script>\n'
    babel_script_pos = raw_html.find('<script src="https://unpkg.com/@babel/standalone')
    if babel_script_pos >= 0:
        end_babel = raw_html.find('>', babel_script_pos) + 1
        end_babel_tag = raw_html.find('\n', end_babel) + 1
        raw_html = raw_html[:end_babel_tag] + api_script + raw_html[end_babel_tag:]

    old_reg_save = "onClick={() => { setSaved(true); }}"
    new_reg_save = "onClick={async () => { if (window._api) { await window._api.saveRegistro({ date, activeProds, prod, consumo, residuos, obs, totalMat, totalCajas, totalDesecho, totalMolidoGen, mermaPct }); } setSaved(true); }}"
    raw_html = raw_html.replace(old_reg_save, new_reg_save, 1)

    return raw_html


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if APP_PASSWORD and not session.get("_auth"):
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    html = _inject_html(html)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True) or {}
    role = data.get("role", "admin")
    pwd = data.get("password", "")

    if not APP_PASSWORD and not APP_PASSWORD_OP:
        session["_auth"] = True
        session["_role"] = role
        return jsonify({"role": role})

    if role == "admin" and APP_PASSWORD and pwd == APP_PASSWORD:
        session["_auth"] = True
        session["_role"] = "admin"
        return jsonify({"role": "admin"})
    if role == "operario" and APP_PASSWORD_OP and pwd == APP_PASSWORD_OP:
        session["_auth"] = True
        session["_role"] = "operario"
        return jsonify({"role": "operario"})

    return jsonify({"error": "Credenciales incorrectas"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me")
def auth_me():
    if APP_PASSWORD and not session.get("_auth"):
        return jsonify({"role": None})
    return jsonify({"role": session.get("_role", "admin")})


@app.route("/api/empleados", methods=["GET"])
@require_auth
def get_empleados():
    emp_db = load_empleados()
    result = [_emp_to_js(k, v, i) for i, (k, v) in enumerate(emp_db.items())]
    return jsonify(result)


@app.route("/api/empleados", methods=["POST"])
@require_auth
def create_empleado():
    data = request.get_json(force=True) or {}
    emp_db = load_empleados()
    nombre = data.get("nombre", "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    key = normalize(nombre)
    emp_db[key] = {
        "nombre": nombre,
        "cargo": data.get("cargo", ""),
        "salario": float(data.get("salario", 0)),
        "horas_base": int(data.get("horas_base", 8)),
        "transporte_dia": float(data.get("transporte", 0)),
        "region": data.get("region", "Sierra/Amazonia"),
        "fondos_reserva": bool(data.get("fondos_reserva", False)),
        "prestamo_iess": float(data.get("prestamo_iess", 0)),
        "descuento_iess": bool(data.get("descuento_iess", True)),
        "ocultar": False,
    }
    save_empleados(emp_db)
    return jsonify({"id": key})


@app.route("/api/empleados/<emp_id>", methods=["PUT"])
@require_auth
def update_empleado(emp_id):
    data = request.get_json(force=True) or {}
    emp_db = load_empleados()
    if emp_id not in emp_db:
        return jsonify({"error": "No encontrado"}), 404
    emp = emp_db[emp_id]
    emp["nombre"] = data.get("nombre", emp.get("nombre", ""))
    emp["cargo"] = data.get("cargo", emp.get("cargo", ""))
    emp["salario"] = float(data.get("salario", emp.get("salario", 0)))
    emp["horas_base"] = int(data.get("horas_base", emp.get("horas_base", 8)))
    emp["transporte_dia"] = float(data.get("transporte", emp.get("transporte_dia", 0)))
    emp["region"] = data.get("region", emp.get("region", "Sierra/Amazonia"))
    emp["fondos_reserva"] = bool(data.get("fondos_reserva", emp.get("fondos_reserva", False)))
    emp["prestamo_iess"] = float(data.get("prestamo_iess", emp.get("prestamo_iess", 0)))
    emp["descuento_iess"] = bool(data.get("descuento_iess", emp.get("descuento_iess", True)))
    save_empleados(emp_db)
    return jsonify({"ok": True})


@app.route("/api/empleados/<emp_id>", methods=["DELETE"])
@require_auth
def delete_empleado(emp_id):
    emp_db = load_empleados()
    if emp_id not in emp_db:
        return jsonify({"error": "No encontrado"}), 404
    del emp_db[emp_id]
    save_empleados(emp_db)
    return jsonify({"ok": True})


@app.route("/api/materiales", methods=["GET"])
@require_auth
def get_materiales():
    mats = load_materiales()
    return jsonify([_mat_to_js(k, v) for k, v in mats.items()])


@app.route("/api/materiales/<mat_id>", methods=["PUT"])
@require_auth
def update_material(mat_id):
    data = request.get_json(force=True) or {}
    mats = load_materiales()
    if mat_id not in mats:
        mats[mat_id] = {}
    mats[mat_id].update({
        "nombre": data.get("nombre", mats[mat_id].get("nombre", mat_id)),
        "costo_kg": float(data.get("costo_kg", mats[mat_id].get("costo_kg", 0))),
        "merma_pct": float(data.get("merma", mats[mat_id].get("merma_pct", 3.0))),
    })
    save_materiales(mats)
    return jsonify({"ok": True})


@app.route("/api/productos", methods=["GET"])
@require_auth
def get_productos():
    prods = load_productos()
    return jsonify([_prod_to_js(k, v) for k, v in prods.items()])


@app.route("/api/productos/<prod_id>", methods=["PUT"])
@require_auth
def update_producto(prod_id):
    data = request.get_json(force=True) or {}
    prods = load_productos()
    if prod_id not in prods:
        prods[prod_id] = {}
    p = prods[prod_id]
    p["nombre"] = data.get("nombre", p.get("nombre", prod_id))
    p["kind"] = data.get("kind", p.get("kind", "vaso"))
    p["unidades_caja"] = int(data.get("unidades_caja", p.get("unidades_caja", 1000)))
    p["peso_g"] = float(data.get("peso_g", p.get("peso_g", 0)))
    p["factor_complejidad"] = float(data.get("factor", p.get("factor_complejidad", 1.0)))
    save_productos(prods)
    return jsonify({"ok": True})


@app.route("/api/productos", methods=["POST"])
@require_auth
def create_producto():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    prods = load_productos()
    key = normalize(nombre).replace(' ', '_')
    prods[key] = {
        "nombre": nombre,
        "kind": data.get("kind", "vaso"),
        "unidades_caja": int(data.get("unidades_caja", 1000)),
        "peso_g": float(data.get("peso_g", 0)),
        "factor_complejidad": float(data.get("factor", 1.0)),
    }
    save_productos(prods)
    return jsonify({"id": key})


@app.route("/api/productos/<prod_id>/desactivar", methods=["POST"])
@require_auth
def toggle_producto_desactivado(prod_id):
    data = request.get_json(force=True) or {}
    prods = load_productos()
    if prod_id not in prods:
        return jsonify({"error": "No encontrado"}), 404
    prods[prod_id]["desactivado"] = bool(data.get("desactivado", True))
    save_productos(prods)
    return jsonify({"ok": True})


@app.route("/api/materiales/<mat_id>/desactivar", methods=["POST"])
@require_auth
def toggle_material_desactivado(mat_id):
    data = request.get_json(force=True) or {}
    mats = load_materiales()
    if mat_id not in mats:
        return jsonify({"error": "No encontrado"}), 404
    mats[mat_id]["desactivado"] = bool(data.get("desactivado", True))
    save_materiales(mats)
    return jsonify({"ok": True})


@app.route("/api/empaques/<emp_id>/desactivar", methods=["POST"])
@require_auth
def toggle_empaque_desactivado(emp_id):
    data = request.get_json(force=True) or {}
    empaques = load_empaques()
    if emp_id not in empaques:
        return jsonify({"error": "No encontrado"}), 404
    empaques[emp_id]["desactivado"] = bool(data.get("desactivado", True))
    save_empaques(empaques)
    return jsonify({"ok": True})


@app.route("/api/gastos_fijos/<period>/desactivar", methods=["POST"])
@require_auth
def toggle_gasto_desactivado(period):
    data = request.get_json(force=True) or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "Key requerida"}), 400
    gf = load_gastos_fijos(period)
    desact = set(gf.get("_desactivados", []))
    if bool(data.get("desactivado", True)):
        desact.add(key)
    else:
        desact.discard(key)
    gf["_desactivados"] = list(desact)
    save_gastos_fijos(period, gf)
    return jsonify({"ok": True})


@app.route("/api/empaques", methods=["GET"])
@require_auth
def get_empaques():
    empaques = load_empaques()
    return jsonify([
        {"id": k, "nombre": v.get("nombre", k), "costo": float(v.get("costo", 0)), "unidad": v.get("unidad", "unidad")}
        for k, v in empaques.items()
    ])


@app.route("/api/empaques/<emp_id>", methods=["PUT"])
@require_auth
def update_empaque(emp_id):
    data = request.get_json(force=True) or {}
    empaques = load_empaques()
    if emp_id not in empaques:
        empaques[emp_id] = {}
    empaques[emp_id].update({
        "nombre": data.get("nombre", empaques[emp_id].get("nombre", emp_id)),
        "costo": float(data.get("costo", empaques[emp_id].get("costo", 0))),
        "unidad": data.get("unidad", empaques[emp_id].get("unidad", "unidad")),
    })
    save_empaques(empaques)
    return jsonify({"ok": True})


@app.route("/api/gastos_fijos/<period>", methods=["GET"])
@require_auth
def get_gastos_fijos(period):
    return jsonify(load_gastos_fijos(period))


@app.route("/api/gastos_fijos/<period>", methods=["PUT"])
@require_auth
def update_gastos_fijos(period):
    data = request.get_json(force=True) or {}
    save_gastos_fijos(period, data)
    return jsonify({"ok": True})


@app.route("/api/registros", methods=["POST"])
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


@app.route("/api/registros/<month>", methods=["GET"])
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
            pass
    return jsonify(result)


@app.route("/api/nomina/reportes", methods=["GET"])
@require_auth
def get_nomina_reportes():
    return jsonify(list_reportes())


_MES_NAMES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]


def _periodo_de_data(data):
    """Extrae periodo_id 'YYYY-MM' a partir de la primera fecha."""
    for _, days, _ in data:
        for ds in days:
            parts = ds.split('-')
            if len(parts) == 3:
                y = int(parts[0])
                y_full = 2000 + y if y < 100 else y
                m = int(parts[1])
                return f"{y_full}-{m:02d}", f"{_MES_NAMES[m-1]} {y_full}"
    return None, None


@app.route("/api/nomina/upload", methods=["POST"])
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
            return jsonify({"error": str(e)}), 422
        finally:
            os.unlink(tmp.name)

    emp_db = load_empleados()
    matched, nuevos, faltantes = match_empleados(data, emp_db)
    cls = clasificar_todo(data)

    periodo_id, periodo_label = _periodo_de_data(data)
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


@app.route("/api/nomina/corregir", methods=["POST"])
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

    n_updates = 0
    for emp_key, dias in ediciones.items():
        name = key_to_name.get(emp_key, emp_key)
        cls_emp = cls.setdefault(name, {})
        for ds, vals in dias.items():
            day = cls_emp.setdefault(ds, {"h1": None, "h2": None, "h3": None, "h4": None, "flags": []})
            tiene_horas = any(k in vals for k in ("h1", "h2", "h3", "h4"))
            solo_flag = bool(vals.get("_flag")) and not tiene_horas
            solo_verificar = bool(vals.get("_verify")) and not tiene_horas
            solo_modo = ("_modo" in vals or "_cubrir" in vals) and not tiene_horas and not solo_flag and not solo_verificar
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
    label = f"{_MES_NAMES[int(m)-1]} {y}"
    save_reporte(periodo_id, label, data, cls)
    return jsonify({"ok": True, "updates": n_updates})


def _compute_nomina_for_periodo(periodo_id, extras_config=None):
    """Calcula nomina completa del periodo. Retorna (resumen, nomina_list)."""
    extras_config = extras_config or {}
    data, cls = load_reporte(periodo_id)
    if not data:
        return None, None
    emp_db = load_empleados()
    matched, _, _ = match_empleados(data, emp_db)
    overrides = load_nomina_overrides(periodo_id) or {}
    recurrentes = load_beneficios_recurrentes() or []

    nomina_list = []
    total = 0.0
    h50 = 0.0
    h100 = 0.0
    for emp_full, days, _ in data:
        name = emp_name(emp_full)
        dk = matched.get(name)
        cfg_base = emp_db.get(dk, {}) if dk else {}
        cfg = _apply_overrides(cfg_base, overrides.get(dk or name, {}))
        cfg = _apply_recurrentes(cfg, dk or name, periodo_id, recurrentes)
        if not cfg.get("salario"):
            continue
        base_h = cfg.get("horas_base", 8)
        hrs_detail = _calc_horas_periodo(cls.get(name, {}), base_h)
        hrs_for_nomina = {
            "dias": hrs_detail["dias"],
            "horas_total": hrs_detail["horas_total"],
            "horas_50": hrs_detail["horas_50"],
            "horas_100": hrs_detail["horas_100"],
            "horas_regular": hrs_detail["horas_regular"],
        }
        cfg_c = dict(cfg)
        cfg_c["horas_comp_anterior"] = 0
        nom = calcular_nomina(hrs_for_nomina, cfg_c, extras_config)
        dias_detalle = []
        cls_emp = cls.get(name, {})
        for ds in sorted(cls_emp.keys()):
            d = cls_emp[ds]
            horas = _horas_dia_dict(d)
            flags = d.get("flags") or []
            finde = _es_finde_ds(ds)
            base_dia = 0 if finde else base_h
            dias_detalle.append({
                "fecha": ds,
                "h1": _min_to_hhmm(d.get("h1")),
                "h2": _min_to_hhmm(d.get("h2")),
                "h3": _min_to_hhmm(d.get("h3")),
                "h4": _min_to_hhmm(d.get("h4")),
                "total": round(horas, 1),
                "flag": flags[0] if flags else "",
                "modo_extra": d.get("modo_extra", "banco"),
                "cubrir_banco": bool(d.get("cubrir_banco", False)),
                "es_finde": finde,
                "excedente": round(max(0.0, horas - base_dia) if horas > 0 else 0, 2),
                "deficit": round(max(0.0, base_dia - horas) if not finde else 0, 2),
            })
        nomina_list.append({"name": name, "nomina": nom, "dias": dias_detalle})
        total += nom.get("total_transferido", 0)
        h50 += hrs_detail.get("horas_50", 0)
        h100 += hrs_detail.get("horas_100", 0)

    y, m = periodo_id.split('-')
    label = f"{_MES_NAMES[int(m)-1]} {y}"
    resumen = {
        "periodo": periodo_id,
        "periodo_label": label,
        "total_transferido": total,
        "total_h50": h50,
        "total_h100": h100,
        "n_empleados": len(nomina_list),
    }
    return resumen, nomina_list


@app.route("/api/nomina/calcular", methods=["POST"])
@require_auth
def nomina_calcular():
    req = request.get_json(force=True) or {}
    periodo_id = req.get("periodo") or session.get("_nomina_periodo")
    if not periodo_id:
        return jsonify({"error": "No hay periodo activo"}), 400

    resumen, nomina_list = _compute_nomina_for_periodo(periodo_id, req.get("extras_config", {}))
    if resumen is None:
        return jsonify({"error": "Reporte no encontrado"}), 404

    save_nomina_resumen(periodo_id, resumen)
    return jsonify(resumen)


@app.route("/api/nomina/descargar/<periodo_id>", methods=["GET"])
@require_auth
def nomina_descargar(periodo_id):
    resumen, nomina_list = _compute_nomina_for_periodo(periodo_id)
    if resumen is None:
        return jsonify({"error": "Reporte no encontrado"}), 404

    tmp_path = tempfile.mkstemp(suffix=".xlsx")[1]
    try:
        write_excel_nomina(nomina_list, resumen["periodo_label"], tmp_path)
        return send_file(tmp_path, as_attachment=True, download_name=f"nomina_{periodo_id}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        return jsonify({"error": f"Error generando XLSX: {e}"}), 500


@app.route("/api/nomina/resumenes", methods=["GET"])
@require_auth
def get_nomina_resumenes():
    return jsonify(load_all_nomina_resumenes())


@app.route("/api/nomina/overrides/<periodo_id>", methods=["GET"])
@require_auth
def get_nomina_overrides(periodo_id):
    return jsonify(load_nomina_overrides(periodo_id) or {})


@app.route("/api/nomina/overrides/<periodo_id>", methods=["PUT"])
@require_auth
def put_nomina_overrides(periodo_id):
    data = request.get_json(force=True) or {}
    save_nomina_overrides(periodo_id, data)
    return jsonify({"ok": True})


@app.route("/api/nomina/snapshot", methods=["GET"])
@require_auth
def get_nomina_snapshot():
    """Retorna todos los datos derivados: horas, nomina, banco, historica, overrides.
    Permite refrescar en cliente tras una mutacion sin recargar la pagina."""
    emp_db = load_empleados()
    horas_por_periodo = _build_horas_por_periodo(emp_db)
    nomina_por_periodo = _build_nomina_por_periodo(emp_db)
    banco_por_emp = _banco_por_empleado(emp_db)
    reps_ids = [r["id"] for r in list_reportes()]
    overrides_por_periodo = {rid: load_nomina_overrides(rid) or {} for rid in reps_ids}

    resumenes = load_all_nomina_resumenes()
    ids_all = set(resumenes.keys()) | set(nomina_por_periodo.keys())
    nomina_historica = []
    for rid in sorted(ids_all):
        try:
            y, m = rid.split("-")
            label = f"{_MES_NAMES[int(m)-1]} {y}"
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


@app.route("/api/costos/calcular", methods=["POST"])
@require_auth
def costos_calcular():
    req = request.get_json(force=True) or {}
    periodo = req.get("periodo", date.today().strftime("%Y-%m"))
    mats = load_materiales()
    prods = load_productos()
    empaques = load_empaques()
    gastos_raw = load_gastos_fijos(periodo)
    gastos_total = sumar_gastos_fijos(gastos_raw)

    resumenes = load_all_nomina_resumenes()
    nomina_total = 0.0
    if resumenes and periodo in resumenes:
        nomina_total = float(resumenes[periodo].get("total_transferido", 0))

    costos = calcular_costos(prods, mats, empaques, gastos_total, nomina_total)
    snap = {"periodo": periodo, "periodo_label": periodo, "costos": costos}
    save_costos_snapshot(periodo, snap)
    return jsonify(costos)


@app.route("/api/costos/snapshots", methods=["GET"])
@require_auth
def get_costos_snapshots():
    return jsonify(load_all_costos_snapshots())


@app.route("/api/dashboard", methods=["GET"])
@require_auth
def get_dashboard():
    emp_db = load_empleados()
    reps = list_reportes()
    resumenes = load_all_nomina_resumenes()
    last_nom, last_lab = 0.0, ""
    if resumenes:
        lk = max(resumenes.keys())
        last_nom = float(resumenes[lk].get("total_transferido", 0))
        last_lab = resumenes[lk].get("periodo_label", lk)
    hoy = date.today()
    today_regs = list_registros_diarios(hoy.strftime("%Y-%m"))
    return jsonify({
        "empleados": len(emp_db),
        "reportes": len(reps),
        "ultima_nomina": last_nom,
        "ultima_nomina_label": last_lab,
        "registros_mes": len(today_regs),
    })


@app.route("/api/nomina/recurrentes/<emp_id>", methods=["PUT"])
@require_auth
def put_recurrentes(emp_id):
    data = request.get_json(force=True) or {}
    rules = data.get("rules") or []
    all_rules = load_beneficios_recurrentes() or []
    kept = [r for r in all_rules if r.get("empleado_id") != emp_id]
    for r in rules:
        r["empleado_id"] = emp_id
    save_beneficios_recurrentes(kept + rules)
    return jsonify({"ok": True})


_COLLECTION_MAP = {
    "clientes": (load_clientes, save_clientes),
    "cotizaciones": (load_cotizaciones, save_cotizaciones),
    "ordenes_compra": (load_ordenes_compra, save_ordenes_compra),
    "facturas": (load_facturas, save_facturas),
    "guias": (load_guias, save_guias),
    "certificados": (load_certificados, save_certificados),
    "emisor": (load_emisor, save_emisor),
    "inventario_mp": (load_inventario_mp, save_inventario_mp),
    "inventario_pt": (load_inventario_pt, save_inventario_pt),
    "movimientos_inventario": (load_movimientos_inventario, save_movimientos_inventario),
    "beneficios_recurrentes": (load_beneficios_recurrentes, save_beneficios_recurrentes),
}


@app.route("/api/collection/<kind>", methods=["GET"])
@require_auth
def get_collection(kind):
    if kind not in _COLLECTION_MAP:
        return jsonify({"error": "Unknown collection"}), 404
    data = _COLLECTION_MAP[kind][0]()
    return jsonify(data if data is not None else [])


@app.route("/api/collection/<kind>", methods=["PUT"])
@require_auth
def put_collection(kind):
    if kind not in _COLLECTION_MAP:
        return jsonify({"error": "Unknown collection"}), 404
    data = request.get_json(force=True)
    _COLLECTION_MAP[kind][1](data)
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════
# SRI — Facturacion electronica
# ═══════════════════════════════════════════════════════════════

def _buscar_factura(factura_id):
    facturas = load_facturas() or []
    for f in facturas:
        if f.get("id") == factura_id:
            return f, facturas
    return None, facturas


def _buscar_cliente(cliente_id):
    clientes = load_clientes() or []
    for c in clientes:
        if c.get("id") == cliente_id:
            return c
    return None


@app.route("/api/sri/emitir/<path:factura_id>", methods=["POST"])
@require_auth
def sri_emitir(factura_id):
    """Genera clave de acceso, XML, firma y envia al SRI. Actualiza la factura."""
    import sri
    factura, facturas = _buscar_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404

    emisor = load_emisor() or {}
    if not emisor.get("ruc"):
        return jsonify({"error": "Configura los datos del emisor (RUC) antes de emitir"}), 400

    cliente = _buscar_cliente(factura.get("cliente")) or {}

    ambiente = os.environ.get("SRI_AMBIENTE", sri.AMBIENTE_PRUEBAS)
    fecha_em = factura.get("fecha_emision") or date.today().isoformat()
    try:
        fecha_dt = datetime.strptime(fecha_em, "%Y-%m-%d")
    except Exception:
        fecha_dt = datetime.now()
    fecha_str = fecha_dt.strftime("%d%m%Y")

    clave = sri.generar_clave_acceso(
        fecha_emision=fecha_str,
        cod_doc=sri.COD_DOC["factura"],
        ruc_emisor=emisor["ruc"],
        ambiente=ambiente,
        estab=str(factura.get("establecimiento", "001")),
        pto_emision=str(factura.get("punto_emision", "001")),
        secuencial=str(factura.get("secuencial", "1")),
    )

    factura["clave_acceso"] = clave
    factura["ambiente"] = ambiente

    xml_str = sri.build_factura_xml(factura, emisor, cliente, ambiente=ambiente)
    xml_firmado, firma_estado = sri.firmar_xml(xml_str)
    factura["xml_firma_estado"] = firma_estado

    rec = sri.enviar_recepcion(xml_firmado, ambiente=ambiente)
    factura["sri_recepcion"] = rec

    aut = sri.consultar_autorizacion(clave, ambiente=ambiente)
    factura["estado_sri"] = aut.get("estado", "EN_PROCESO")
    factura["autorizacion_sri"] = aut.get("numero_autorizacion", "")
    factura["fecha_autorizacion"] = aut.get("fecha_autorizacion", "")
    factura["sri_mensajes"] = aut.get("mensajes", []) + rec.get("mensajes", [])

    # Guardar XML en storage (Supabase config)
    try:
        from storage import _cfg_set
        _cfg_set(f"sri:xml:{clave}", {"xml": xml_firmado, "factura_id": factura_id})
    except Exception:
        pass

    # Upsert factura
    idx = next((i for i, f in enumerate(facturas) if f.get("id") == factura_id), None)
    if idx is not None:
        facturas[idx] = factura
    save_facturas(facturas)

    return jsonify({
        "ok": True,
        "clave_acceso": clave,
        "estado_sri": factura["estado_sri"],
        "autorizacion_sri": factura["autorizacion_sri"],
        "fecha_autorizacion": factura["fecha_autorizacion"],
        "firma_estado": firma_estado,
        "mensajes": factura["sri_mensajes"],
    })


@app.route("/api/sri/autorizar/<clave>", methods=["GET"])
@require_auth
def sri_autorizar(clave):
    """Consulta estado de autorizacion al SRI."""
    import sri
    ambiente = os.environ.get("SRI_AMBIENTE", sri.AMBIENTE_PRUEBAS)
    return jsonify(sri.consultar_autorizacion(clave, ambiente=ambiente))


@app.route("/api/sri/pdf/<path:factura_id>", methods=["GET"])
@require_auth
def sri_pdf(factura_id):
    import sri
    factura, _ = _buscar_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404
    emisor = load_emisor() or {}
    cliente = _buscar_cliente(factura.get("cliente")) or {}

    tmp_path = tempfile.mkstemp(suffix=".pdf")[1]
    try:
        sri.render_factura_pdf(
            factura, emisor, cliente, tmp_path,
            estado_sri=factura.get("estado_sri", "PENDIENTE"),
            numero_autorizacion=factura.get("autorizacion_sri", ""),
            fecha_autorizacion=factura.get("fecha_autorizacion", ""),
        )
        return send_file(tmp_path, as_attachment=True, download_name=f"factura_{factura_id}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": f"Error generando PDF: {e}"}), 500


@app.route("/api/sri/xml/<path:factura_id>", methods=["GET"])
@require_auth
def sri_xml(factura_id):
    factura, _ = _buscar_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404
    clave = factura.get("clave_acceso")
    if not clave:
        return jsonify({"error": "Factura sin clave de acceso. Emitela primero."}), 400
    try:
        from storage import _cfg_get
        rec = _cfg_get(f"sri:xml:{clave}", None)
        if not rec:
            return jsonify({"error": "XML no encontrado en storage"}), 404
        xml = rec.get("xml", "")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    tmp_path = tempfile.mkstemp(suffix=".xml")[1]
    with open(tmp_path, "w", encoding="utf-8") as fp:
        fp.write(xml)
    return send_file(tmp_path, as_attachment=True, download_name=f"factura_{factura_id}.xml", mimetype="application/xml")


@app.route("/api/sri/config", methods=["GET"])
@require_auth
def sri_config():
    """Retorna configuracion actual del SRI (sin el password del cert)."""
    import sri
    return jsonify({
        "ambiente": os.environ.get("SRI_AMBIENTE", sri.AMBIENTE_PRUEBAS),
        "ambiente_nombre": "PRODUCCION" if os.environ.get("SRI_AMBIENTE") == "2" else "PRUEBAS",
        "cert_configurado": bool(os.environ.get("SRI_CERT_PATH") and os.path.exists(os.environ.get("SRI_CERT_PATH", ""))),
        "simulado": os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes"),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
