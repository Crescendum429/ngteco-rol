import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
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
    load_inv_piezas,
    save_inv_piezas,
    load_inv_molido,
    save_inv_molido,
    load_inv_auxiliar,
    save_inv_auxiliar,
    load_inv_lotes,
    save_inv_lotes,
    load_bom,
    save_bom,
    load_cambios_molde,
    save_cambios_molde,
)

APP_VERSION = "5.5.0"  # semver MAJOR.MINOR.PATCH — bump PATCH en cada commit, MINOR en features grandes, MAJOR en breaking changes

from logger import log, get_logger
from validation import ValidationError, make_error_response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "solplast-dev-secret-2026")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB max upload (XLS reloj suele ser <500KB)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") != "development"
# Sesion permanente de 30 dias para que coincida con el localStorage del frontend.
# Sin esto, la sesion se pierde al cerrar el navegador pero el localStorage
# persiste, causando que la UI muestre logueado pero el backend rechace todo.
from datetime import timedelta as _timedelta
app.permanent_session_lifetime = _timedelta(days=30)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
APP_PASSWORD_OP = os.environ.get("APP_PASSWORD_OP", "")

# Validacion de secrets al startup — falla rapido si algo critico falta en prod
_STARTUP_WARNINGS = []
if not app.secret_key or app.secret_key == "solplast-dev-secret-2026":
    if os.environ.get("FLASK_ENV") != "development":
        _STARTUP_WARNINGS.append("SECRET_KEY no configurada (usando default — INSEGURO en produccion)")
if not os.environ.get("SUPABASE_URL"):
    _STARTUP_WARNINGS.append("SUPABASE_URL no configurada — storage funcionara solo en memoria")
if not os.environ.get("SUPABASE_KEY"):
    _STARTUP_WARNINGS.append("SUPABASE_KEY no configurada — storage funcionara solo en memoria")
for w in _STARTUP_WARNINGS:
    log.warning(w)
log.info(f"Solplast ERP v{APP_VERSION} iniciado (ambiente: {os.environ.get('FLASK_ENV', 'production')})")


# Rate limiting movido a app_routes/auth_bp.py


@app.errorhandler(ValidationError)
def _handle_validation_error(e):
    log.info(f"Validation error on {request.path}: {e.message}")
    return make_error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint no encontrado"}), 404
    return e


@app.errorhandler(413)
def _handle_413(e):
    return jsonify({"error": "Archivo demasiado grande (max 20MB)"}), 413


@app.errorhandler(Exception)
def _handle_unexpected(e):
    """Captura cualquier excepcion no manejada. Loggea stack trace pero no fuga al cliente."""
    log.exception(f"Error no manejado en {request.method} {request.path}")
    # Para endpoints JSON, devuelve mensaje generico
    if request.path.startswith("/api/"):
        return jsonify({"error": "Error interno del servidor"}), 500
    # Para resto, deja que Flask muestre su pagina default
    raise e


# Health/ready registrados como Blueprint
from app_routes.health_bp import health_bp
app.register_blueprint(health_bp)

HTML_PATH = os.path.join(os.path.dirname(__file__), "Solplast-ERP.html")

# Helpers de serializacion movidos a app_helpers.py — alias para compatibilidad
from app_helpers import emp_to_js as _emp_to_js, mat_to_js as _mat_to_js, prod_to_js as _prod_to_js, EMP_COLORS as _EMP_COLORS

# Logica de nomina centralizada en nomina_logic.py (importable por blueprints y _build_data_jsx)
from nomina_logic import (
    MES_NAMES as _MES_NAMES,
    banco_por_empleado as _banco_por_empleado,
    build_horas_por_periodo as _build_horas_por_periodo,
    build_nomina_por_periodo as _build_nomina_por_periodo,
)




def _build_panoramica_mes(registros_mes, hoy):
    """Construye lista de 31 dias del mes actual con cajas/material/desecho reales.
    Los dias sin registro quedan en 0. Los dias finde / futuros llevan flag.
    """
    from calendar import monthrange
    anio = hoy.year
    mes = hoy.month
    dias_mes = monthrange(anio, mes)[1]
    by_fecha = {r["fecha"]: r for r in registros_mes if isinstance(r, dict) and r.get("fecha")}
    result = []
    for d in range(1, dias_mes + 1):
        fecha = f"{anio}-{mes:02d}-{d:02d}"
        from datetime import date as _date
        dow = _date(anio, mes, d).weekday()  # 0=lun, 6=dom
        es_finde = dow >= 5
        es_futuro = d > hoy.day
        reg = by_fecha.get(fecha)
        if reg:
            desecho = float(reg.get("desecho_total_kg") or 0)
            result.append({
                "dia": d, "fecha": fecha, "esFinde": es_finde, "esFuturo": False,
                "cajas": int(reg.get("cajas") or 0),
                "material_kg": float(reg.get("material") or 0),
                "desecho_kg": round(desecho, 1),
                "registro_id": reg.get("id") or f"reg-{fecha}",
            })
        else:
            result.append({
                "dia": d, "fecha": fecha, "esFinde": es_finde, "esFuturo": es_futuro,
                "cajas": 0, "material_kg": 0, "desecho_kg": 0,
            })
    return result


def _build_panoramica_prod_diaria(registros_mes):
    """{fecha: {prod_id: cajas}} desde registros_mes[].productos[]."""
    out = {}
    for r in registros_mes:
        if not isinstance(r, dict):
            continue
        fecha = r.get("fecha")
        prods = r.get("productos") or []
        if not fecha or not isinstance(prods, list):
            continue
        out[fecha] = {}
        for p in prods:
            if not isinstance(p, dict):
                continue
            pid = p.get("prod_id")
            cajas = int(p.get("cajas") or 0)
            if pid and cajas > 0:
                out[fecha][pid] = out[fecha].get(pid, 0) + cajas
    return out


_DATA_JSX_CACHE = {"v": None, "exp": 0.0}
_DATA_JSX_TTL = float(os.environ.get("DATA_JSX_CACHE_TTL", "30"))  # segundos


def _invalidate_data_jsx_cache():
    """Llamar despues de cualquier mutacion via API que cambie datos visibles."""
    _DATA_JSX_CACHE["v"] = None
    _DATA_JSX_CACHE["exp"] = 0.0


@app.after_request
def _invalidate_cache_on_mutation(response):
    """Invalida el cache de data.jsx tras cualquier POST/PUT/DELETE exitoso a /api/*."""
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE") and response.status_code < 400:
        _invalidate_data_jsx_cache()
    return response


def _build_data_jsx():
    import time
    now = time.time()
    if _DATA_JSX_CACHE["v"] is not None and _DATA_JSX_CACHE["exp"] > now:
        return _DATA_JSX_CACHE["v"]
    result = _build_data_jsx_uncached()
    _DATA_JSX_CACHE["v"] = result
    _DATA_JSX_CACHE["exp"] = now + _DATA_JSX_TTL
    return result


def _build_data_jsx_uncached():
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
    fechas_mes = sorted(registros_diarios.keys())
    # registros_mes: TODO el mes (para panoramica). registros_recientes: ultimos 5 (para sidebar Registro).
    registros_mes = []
    for fecha in fechas_mes:
        try:
            reg = load_registro_diario(fecha)
            if reg:
                entry = {
                    "id": reg.get("id") or f"reg-{fecha}",
                    "fecha": reg.get("fecha", fecha),
                    "material": float(reg.get("total_material_kg", 0)),
                    "cajas": int(reg.get("total_cajas", 0)),
                    "obs": reg.get("observaciones", ""),
                }
                for k in ("productos", "loteNum", "desecho_total_kg", "molido_gen_kg",
                          "desecho_empacadora", "tachos_armados"):
                    if k in reg:
                        entry[k] = reg[k]
                registros_mes.append(entry)
        except Exception:
            log.exception(f"cargando registro {fecha}")
    registros = registros_mes[-5:]  # ultimos 5 para la lista de registros recientes

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
    inv_piezas = load_inv_piezas() or []
    inv_molido = load_inv_molido() or {}
    inv_auxiliar = load_inv_auxiliar() or {}
    inv_lotes = load_inv_lotes() or []
    bom_map = load_bom() or {}
    cambios_molde_hist = load_cambios_molde() or []

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
        f"window.REGISTROS_MES = {json.dumps(registros_mes, ensure_ascii=False)};",
        # PANORAMICA_MES_MOCK y PANORAMICA_PROD_DIARIA son const en data.jsx
        # (array/objeto vacio). Aqui los mutamos en sitio para que los componentes
        # los vean poblados sin reasignar la const.
        f"(function() {{"
        f"  const __pmes = {json.dumps(_build_panoramica_mes(registros_mes, hoy), ensure_ascii=False)};"
        f"  if (typeof PANORAMICA_MES_MOCK !== 'undefined') {{"
        f"    PANORAMICA_MES_MOCK.length = 0;"
        f"    PANORAMICA_MES_MOCK.push(...__pmes);"
        f"  }}"
        f"  const __ppd = {json.dumps(_build_panoramica_prod_diaria(registros_mes), ensure_ascii=False)};"
        f"  if (typeof PANORAMICA_PROD_DIARIA !== 'undefined') Object.assign(PANORAMICA_PROD_DIARIA, __ppd);"
        f"}})();",
        f"window.COSTOS_EVOLUCION_MESES = window.NOMINA_HISTORICA.map(m => m.label);",
        f"window.BENEFICIOS_RECURRENTES_MOCK = {json.dumps(beneficios_rec, ensure_ascii=False)};",
    ]

    if clientes_js is not None:
        overrides_js.append(f"window.CLIENTES_MOCK = {json.dumps(clientes_js, ensure_ascii=False)};")
    # Stock MP y PT siempre se calculan dinamicamente desde movimientos/lotes.
    # No leemos inv:mp ni inv:pt del storage. Son derivados, no source-of-truth.
    try:
        from storage import compute_stock_mp, compute_stock_pt
        overrides_js.append(f"window.INVENTARIO_MP_MOCK = {json.dumps(compute_stock_mp(), ensure_ascii=False)};")
        overrides_js.append(f"window.INVENTARIO_PT_MOCK = {json.dumps(compute_stock_pt(), ensure_ascii=False)};")
    except Exception:
        log.exception("error computando stock dinamico")
        overrides_js.append("window.INVENTARIO_MP_MOCK = [];")
        overrides_js.append("window.INVENTARIO_PT_MOCK = [];")
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
    overrides_js.append(f"window.INV_PIEZAS = {json.dumps(inv_piezas, ensure_ascii=False)};")
    overrides_js.append(f"window.INV_MOLIDO = {json.dumps(inv_molido, ensure_ascii=False)};")
    overrides_js.append(f"window.INV_AUXILIAR = {json.dumps(inv_auxiliar, ensure_ascii=False)};")
    overrides_js.append(f"window.INV_LOTES = {json.dumps(inv_lotes, ensure_ascii=False)};")
    overrides_js.append(f"window.BOM = {json.dumps(bom_map, ensure_ascii=False)};")
    overrides_js.append(f"window.CAMBIOS_MOLDE = {json.dumps(cambios_molde_hist, ensure_ascii=False)};")
    try:
        from storage import load_inv_aux_consumo, load_movimientos_inventario, load_qc_templates
        aux_consumo = load_inv_aux_consumo() or []
        qc_tpl = load_qc_templates() or {}
        movimientos = load_movimientos_inventario() or []
        # Reagrupa aux_consumo por aux_id (formato esperado por AUX_CONSUMO_HISTORICO)
        aux_hist_groups = {}
        for r in aux_consumo:
            if not isinstance(r, dict) or not r.get("aux_id"):
                continue
            aux_hist_groups.setdefault(r["aux_id"], []).append({
                "fecha": r.get("fecha"), "usado": r.get("usado"), "stock_tras": r.get("stock_tras"),
            })
        overrides_js.append(f"window.AUX_CONSUMO = {json.dumps(aux_consumo, ensure_ascii=False)};")
        overrides_js.append(f"window.QC_TPL = {json.dumps(qc_tpl, ensure_ascii=False)};")
        overrides_js.append(f"window.INV_MOVIMIENTOS = {json.dumps(movimientos, ensure_ascii=False)};")
        # Mutar AUX_CONSUMO_HISTORICO en sitio
        overrides_js.append(
            f"(function() {{"
            f"  const __ah = {json.dumps(aux_hist_groups, ensure_ascii=False)};"
            f"  if (typeof AUX_CONSUMO_HISTORICO !== 'undefined') Object.assign(AUX_CONSUMO_HISTORICO, __ah);"
            f"}})();"
        )
    except Exception:
        log.exception("error cargando aux_consumo/qc_tpl/movimientos")
    # Inyectar alertas para que Home las muestre en el primer render sin fetch
    try:
        from app_routes.alertas_bp import _generar_alertas
        from storage import load_alertas_descartadas
        descartadas = set(load_alertas_descartadas() or [])
        alertas_activas = [a for a in _generar_alertas() if a.get("id") not in descartadas]
        overrides_js.append(f"window.ALERTAS = {json.dumps(alertas_activas, ensure_ascii=False)};")
    except Exception:
        log.exception("error cargando alertas")
        overrides_js.append("window.ALERTAS = [];")
    overrides_js.append(f"window.APP_VERSION = {json.dumps(APP_VERSION)};")
    # Override SBU del frontend con el valor real del backend (env var SBU_VIGENTE
    # o 470 default). Asi no se desincronizan.
    from procesar_rol import SBU_2026 as _SBU
    overrides_js.append(f"window.SBU_2026 = {_SBU};")

    helpers = """
window.solpExportCSV = (filename, headers, rows) => {
  const esc = v => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const head = headers.map(esc).join(',');
  const body = rows.map(r => headers.map(h => esc(r[h])).join(',')).join('\\n');
  const csv = '\\uFEFF' + head + '\\n' + body;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
};

// Toast no-bloqueante. type: 'ok' | 'warn' | 'bad' | 'info'
window.solpToast = (msg, type) => {
  type = type || 'info';
  const colors = {
    ok:   { bg: 'var(--good-soft)',  br: 'var(--good)', fg: 'var(--good)' },
    warn: { bg: 'var(--warn-soft)',  br: 'var(--warn)', fg: 'var(--warn)' },
    bad:  { bg: 'var(--bad-soft)',   br: 'var(--bad)',  fg: 'var(--bad)'  },
    info: { bg: 'var(--accent-soft)',br: 'var(--accent)', fg: 'var(--accent-hi)' },
  };
  const c = colors[type] || colors.info;
  let host = document.getElementById('solp-toast-host');
  if (!host) {
    host = document.createElement('div');
    host.id = 'solp-toast-host';
    host.style.cssText = 'position:fixed;top:18px;right:18px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none';
    document.body.appendChild(host);
  }
  const el = document.createElement('div');
  el.style.cssText = `background:${c.bg};border:1px solid ${c.br};color:${c.fg};padding:10px 14px;border-radius:8px;font:500 13px var(--sans);max-width:380px;box-shadow:var(--shadow-md);pointer-events:auto;opacity:0;transform:translateY(-6px);transition:opacity 180ms,transform 180ms`;
  el.textContent = msg;
  host.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = '1'; el.style.transform = 'translateY(0)'; });
  setTimeout(() => {
    el.style.opacity = '0'; el.style.transform = 'translateY(-6px)';
    setTimeout(() => el.remove(), 200);
  }, 3500);
};

// Confirm no-bloqueante. Devuelve Promise<boolean>
window.solpConfirm = (msg, opts) => {
  opts = opts || {};
  return new Promise(resolve => {
    const back = document.createElement('div');
    back.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:10000;display:grid;place-items:center;font:var(--sans)';
    const card = document.createElement('div');
    card.style.cssText = 'background:var(--bg-raised);border:1px solid var(--line);border-radius:var(--radius-md);max-width:440px;width:90%;padding:20px;box-shadow:var(--shadow-md);font-family:var(--sans);color:var(--text)';
    const text = document.createElement('div');
    text.style.cssText = 'font-size:14px;line-height:1.5;margin-bottom:16px;white-space:pre-wrap';
    text.textContent = msg;
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px';
    const cancel = document.createElement('button');
    cancel.textContent = opts.cancelLabel || 'Cancelar';
    cancel.className = 'btn';
    cancel.style.cssText = 'padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:transparent;color:var(--text);cursor:pointer;font:500 13px var(--sans)';
    const ok = document.createElement('button');
    ok.textContent = opts.okLabel || 'Confirmar';
    ok.className = 'btn primary';
    ok.style.cssText = 'padding:6px 12px;border:0;border-radius:6px;background:var(--accent);color:var(--bg);cursor:pointer;font:600 13px var(--sans)';
    const close = (v) => { back.remove(); resolve(v); };
    cancel.onclick = () => close(false);
    ok.onclick = () => close(true);
    back.onclick = (e) => { if (e.target === back) close(false); };
    row.appendChild(cancel); row.appendChild(ok);
    card.appendChild(text); card.appendChild(row);
    back.appendChild(card);
    document.body.appendChild(back);
    setTimeout(() => ok.focus(), 50);
  });
};
"""
    return "\n// Overrides inyectados por el servidor — v" + APP_VERSION + "\n" + "\n".join(overrides_js) + "\n" + helpers


def _build_login_patch():
    return """
// Auth patch — injected by server
(function() {
  // Interceptor global de fetch: si recibe 401, limpia localStorage y
  // recarga para forzar re-login. Sin esto, la UI muestra logueado pero
  // todas las llamadas API fallan silenciosamente.
  const _originalFetch = window.fetch;
  window.fetch = async function(input, init) {
    const r = await _originalFetch(input, init);
    if (r.status === 401 && String(input).startsWith('/api/') && !String(input).startsWith('/api/auth/')) {
      // No autorizado en endpoint protegido — sesion expirada
      try { localStorage.removeItem('solplast.logged'); } catch {}
      if (window.solpToast) window.solpToast('Sesion expirada. Recarga la pagina.', 'warn');
      // Recargar tras 1s para dar tiempo de leer el toast
      setTimeout(() => location.reload(), 1500);
    }
    return r;
  };

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
    migrarOffsetHistorico: async () => {
      const r = await fetch('/api/nomina/migrar-offset', { method: 'POST', credentials: 'same-origin' });
      try {
        const j = await r.json();
        return r.ok ? j : { error: j.error || `HTTP ${r.status}` };
      } catch {
        return { error: `HTTP ${r.status} (respuesta no es JSON)` };
      }
    },
    rebalancearMeses: async () => {
      const r = await fetch('/api/nomina/rebalancear-meses', { method: 'POST', credentials: 'same-origin' });
      try {
        const j = await r.json();
        return r.ok ? j : { error: j.error || `HTTP ${r.status}` };
      } catch {
        return { error: `HTTP ${r.status} (respuesta no es JSON)` };
      }
    },
    importarPrimerDia: async (periodo_id) => {
      const r = await fetch('/api/nomina/importar-primer-dia/' + encodeURIComponent(periodo_id), {
        method: 'POST', credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    saveRegistroV2: async (data) => {
      const r = await fetch('/api/registros/v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    fetchRegistroV2: async (fecha) => {
      const r = await fetch('/api/registros/v2/' + encodeURIComponent(fecha), { credentials: 'same-origin' });
      return r.ok ? r.json() : null;
    },
    fetchLotes: async (params) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      const r = await fetch('/api/inventario/lotes' + q, { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    crearLote: async (data) => {
      const r = await fetch('/api/inventario/lotes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    despacharLote: async (lote_id) => {
      const r = await fetch('/api/inventario/lotes/' + encodeURIComponent(lote_id) + '/despachar', {
        method: 'POST', credentials: 'same-origin',
      });
      return r.ok;
    },
    saveBom: async (prod_id, bom) => {
      const r = await fetch('/api/bom/' + encodeURIComponent(prod_id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bom), credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchBom: async (prod_id) => {
      const r = await fetch('/api/bom/' + encodeURIComponent(prod_id), { credentials: 'same-origin' });
      return r.ok ? r.json() : {};
    },
    fetchAuxItems: async () => {
      const r = await fetch('/api/inventario/auxiliar', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    saveAuxItems: async (items) => {
      const r = await fetch('/api/inventario/auxiliar', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(items), credentials: 'same-origin',
      });
      return r.ok;
    },
    deleteAuxItem: async (aux_id) => {
      const r = await fetch('/api/inventario/auxiliar/' + encodeURIComponent(aux_id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      try { return r.ok ? { ok: true } : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    registrarConsumoAux: async (fecha, items) => {
      const r = await fetch('/api/inventario/auxiliar/registrar-dia', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fecha, items }), credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    fetchAuxConsumo: async (params) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      const r = await fetch('/api/inventario/aux-consumo' + q, { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchQc: async (prod_id) => {
      const r = await fetch('/api/qc/' + encodeURIComponent(prod_id), { credentials: 'same-origin' });
      return r.ok ? r.json() : { parametros: [] };
    },
    saveQc: async (prod_id, qc) => {
      const r = await fetch('/api/qc/' + encodeURIComponent(prod_id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(qc), credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchPiezas: async () => {
      const r = await fetch('/api/inventario/piezas', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    savePiezas: async (data) => {
      const r = await fetch('/api/inventario/piezas', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchMolido: async () => {
      const r = await fetch('/api/inventario/molido', { credentials: 'same-origin' });
      return r.ok ? r.json() : {};
    },
    saveMolido: async (data) => {
      const r = await fetch('/api/inventario/molido', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchMovimientos: async (params) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      const r = await fetch('/api/inventario/movimientos' + q, { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    crearMovimiento: async (data) => {
      const r = await fetch('/api/inventario/movimientos', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      try { return r.ok ? await r.json() : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    fetchAlertas: async () => {
      const r = await fetch('/api/alertas', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    descartarAlerta: async (id) => {
      const r = await fetch('/api/alertas/' + encodeURIComponent(id) + '/descartar', {
        method: 'POST', credentials: 'same-origin',
      });
      return r.ok;
    },
    crearAlertaPersistente: async (data) => {
      const r = await fetch('/api/alertas/persistente', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    actualizarAlertaPersistente: async (id, data) => {
      const r = await fetch('/api/alertas/persistente/' + encodeURIComponent(id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    eliminarAlertaPersistente: async (id) => {
      const r = await fetch('/api/alertas/persistente/' + encodeURIComponent(id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchAlertasPersistentes: async () => {
      const r = await fetch('/api/alertas/persistentes', { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    fetchEmisor: async () => {
      const r = await fetch('/api/emisor', { credentials: 'same-origin' });
      return r.ok ? r.json() : {};
    },
    saveEmisor: async (data) => {
      const r = await fetch('/api/emisor', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    fetchSubcomponentes: async () => {
      const r = await fetch('/api/subcomponentes', { credentials: 'same-origin' });
      return r.ok ? r.json() : {};
    },
    saveSubcomponentes: async (data) => {
      const r = await fetch('/api/subcomponentes', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    crearPieza: async (data) => {
      const r = await fetch('/api/inventario/piezas', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok ? r.json() : { error: 'Error' };
    },
    actualizarPieza: async (id, data) => {
      const r = await fetch('/api/inventario/piezas/' + encodeURIComponent(id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    eliminarPieza: async (id) => {
      const r = await fetch('/api/inventario/piezas/' + encodeURIComponent(id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      try { return r.ok ? { ok: true } : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    actualizarMolido: async (id, kg) => {
      const r = await fetch('/api/inventario/molido/' + encodeURIComponent(id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kg }), credentials: 'same-origin',
      });
      return r.ok;
    },
    eliminarMolido: async (id) => {
      const r = await fetch('/api/inventario/molido/' + encodeURIComponent(id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      try { return r.ok ? { ok: true } : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    actualizarMovimiento: async (id, data) => {
      const r = await fetch('/api/inventario/movimientos/' + id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      return r.ok;
    },
    eliminarMovimiento: async (id) => {
      const r = await fetch('/api/inventario/movimientos/' + id, {
        method: 'DELETE', credentials: 'same-origin',
      });
      return r.ok;
    },
    actualizarLote: async (id, data) => {
      const r = await fetch('/api/inventario/lotes/' + encodeURIComponent(id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data), credentials: 'same-origin',
      });
      try { return r.ok ? { ok: true } : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    eliminarLote: async (id) => {
      const r = await fetch('/api/inventario/lotes/' + encodeURIComponent(id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      try { return r.ok ? { ok: true } : await r.json(); } catch { return { error: `HTTP ${r.status}` }; }
    },
    fetchAuditLog: async (params) => {
      const q = params ? '?' + new URLSearchParams(params).toString() : '';
      const r = await fetch('/api/audit' + q, { credentials: 'same-origin' });
      return r.ok ? r.json() : [];
    },
    eliminarItemColeccion: async (kind, item_id) => {
      const r = await fetch('/api/collection/' + encodeURIComponent(kind) + '/' + encodeURIComponent(item_id), {
        method: 'DELETE', credentials: 'same-origin',
      });
      return r.ok;
    },
  };
})();
"""


def _inject_html(raw_html):
    # Inyectamos un script de overrides DESPUÉS del data.jsx del handoff.
    # IMPORTANTE: debe ser type="text/babel" para que Babel Standalone lo ejecute
    # DESPUES de data.jsx (los scripts text/babel se ejecutan en orden DOM despues
    # de los scripts planos). Si fuera <script> plano, se ejecutaria antes y
    # data.jsx le sobrescribiria los valores con los mocks.
    data_start = raw_html.find('<script type="text/babel" data-file="data.jsx">')
    data_end = raw_html.find('</script>', data_start) + len('</script>')
    if data_start >= 0 and data_end > data_start:
        override_script = (
            '\n<script type="text/babel" data-file="data-overrides.jsx">\n'
            + _build_data_jsx()
            + '\n</script>\n'
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

    # Hook v3: el setSaved esta dentro de un onClick que tambien genera el lote.
    # Interceptamos solo la linea setSaved(true) para insertar el save al backend antes.
    old_reg_save = "          setLoteNum(`L-${yy}-${mm}-${dd}-${nn}`);\n          setSaved(true);"
    new_reg_save = """          setLoteNum(`L-${yy}-${mm}-${dd}-${nn}`);
          if (window._api) {
            try { await window._api.saveRegistro({ date, activeProds, prod, consumo, residuos, obs, tachos, totalMat, totalCajas, totalDesecho, totalMolidoGen, mermaPct, loteNum: `L-${yy}-${mm}-${dd}-${nn}` }); } catch(e) { console.error('saveRegistro', e); }
          }
          setSaved(true);"""
    if old_reg_save in raw_html:
        raw_html = raw_html.replace(old_reg_save, new_reg_save, 1)
        # El onClick padre necesita async
        raw_html = raw_html.replace(
            "<Btn variant=\"primary\" onClick={() => {\n          // Generar número de lote",
            "<Btn variant=\"primary\" onClick={async () => {\n          // Generar número de lote",
            1,
        )

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


# Auth endpoints en app_routes/auth_bp.py





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


# ═══════════════════════════════════════════════════════════════
# Blueprints — registrados al final para que helpers y decoradores
# definidos arriba ya esten disponibles si los blueprints los importan
# ═══════════════════════════════════════════════════════════════
from app_routes.alertas_bp import alertas_bp
from app_routes.auth_bp import auth_bp
from app_routes.catalogo_bp import catalogo_bp
from app_routes.comercial_bp import comercial_bp
from app_routes.inventario_bp import inventario_bp
from app_routes.nomina_bp import nomina_bp
from app_routes.observability_bp import obs_bp
from app_routes.sri_bp import sri_bp

app.register_blueprint(alertas_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(catalogo_bp)
app.register_blueprint(comercial_bp)
app.register_blueprint(inventario_bp)
app.register_blueprint(nomina_bp)
app.register_blueprint(obs_bp)
app.register_blueprint(sri_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
