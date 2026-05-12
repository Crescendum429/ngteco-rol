"""Blueprint de observability: metricas internas, info de configuracion runtime."""
import os

from flask import Blueprint, jsonify

from app_routes._auth import require_auth
from logger import get_logger

log = get_logger("observability")

obs_bp = Blueprint("obs", __name__)


@obs_bp.route("/api/metrics", methods=["GET"])
@require_auth
def metrics():
    """Metricas basicas internas: cantidades por entidad para detectar
    crecimiento anomalo o caidas de datos."""
    from storage import (
        list_reportes,
        load_beneficios_recurrentes,
        load_certificados,
        load_clientes,
        load_cotizaciones,
        load_empleados,
        load_facturas,
        load_guias,
        load_inv_lotes,
        load_inv_piezas,
        load_movimientos_inventario,
        load_ordenes_compra,
        load_productos,
    )

    safe_count = lambda fn, default=0: (lambda v: len(v) if v is not None else default)(
        _safe_call(fn)
    )
    return jsonify({
        "empleados": safe_count(load_empleados),
        "productos": safe_count(load_productos),
        "clientes": safe_count(load_clientes),
        "cotizaciones": safe_count(load_cotizaciones),
        "ordenes_compra": safe_count(load_ordenes_compra),
        "facturas": safe_count(load_facturas),
        "guias": safe_count(load_guias),
        "certificados": safe_count(load_certificados),
        "reportes_nomina": safe_count(list_reportes),
        "beneficios_recurrentes": safe_count(load_beneficios_recurrentes),
        "lotes": safe_count(load_inv_lotes),
        "piezas_stock_items": safe_count(load_inv_piezas),
        "movimientos_inventario": safe_count(load_movimientos_inventario),
    })


@obs_bp.route("/api/admin/backup", methods=["GET"])
@require_auth
def backup():
    """Exporta toda la data del sistema como JSON. Sirve para snapshot/backup."""
    from datetime import datetime as _dt
    from storage import (
        list_reportes,
        load_arrastre,
        load_beneficios_recurrentes,
        load_bom,
        load_cambios_molde,
        load_certificados,
        load_clientes,
        load_cotizaciones,
        load_emisor,
        load_empaques,
        load_empleados,
        load_facturas,
        load_guias,
        load_inv_auxiliar,
        load_inv_lotes,
        load_inv_molido,
        load_inv_piezas,
        load_inventario_mp,
        load_inventario_pt,
        load_materiales,
        load_movimientos_inventario,
        load_ordenes_compra,
        load_productos,
        load_reporte,
    )

    reportes_full = {}
    for rep in (list_reportes() or []):
        rid = rep.get("id")
        if rid:
            try:
                data, cls = load_reporte(rid)
                reportes_full[rid] = {"meta": rep, "data": data, "cls": cls,
                                      "arrastre": load_arrastre(rid)}
            except Exception as e:
                log.warning(f"backup: error con reporte {rid}: {e}")

    return jsonify({
        "version_backup": 1,
        "fecha": _dt.now().isoformat(),
        "empleados": load_empleados(),
        "productos": load_productos(),
        "materiales": load_materiales(),
        "empaques": load_empaques(),
        "emisor": load_emisor(),
        "clientes": load_clientes(),
        "cotizaciones": load_cotizaciones(),
        "ordenes_compra": load_ordenes_compra(),
        "facturas": load_facturas(),
        "guias": load_guias(),
        "certificados": load_certificados(),
        "inventario_mp_legacy": load_inventario_mp(),
        "inventario_pt_legacy": load_inventario_pt(),
        "movimientos_inventario": load_movimientos_inventario(),
        "inv_piezas": load_inv_piezas(),
        "inv_molido": load_inv_molido(),
        "inv_auxiliar": load_inv_auxiliar(),
        "inv_lotes": load_inv_lotes(),
        "bom": load_bom(),
        "cambios_molde": load_cambios_molde(),
        "beneficios_recurrentes": load_beneficios_recurrentes(),
        "reportes_nomina": reportes_full,
    })


@obs_bp.route("/api/audit", methods=["GET"])
@require_auth
def audit_log():
    """Consulta el audit log. Filtros opcionales: entity, entity_id, limit."""
    from flask import request as _req
    from audit import query
    limit = int(_req.args.get("limit", 200))
    entity = _req.args.get("entity")
    entity_id = _req.args.get("entity_id")
    return jsonify(query(limit=limit, entity_type=entity, entity_id=entity_id))


@obs_bp.route("/api/config", methods=["GET"])
@require_auth
def runtime_config():
    """Configuracion runtime no-sensible (sin secrets, passwords, etc)."""
    return jsonify({
        "ambiente_flask": os.environ.get("FLASK_ENV", "production"),
        "log_level": os.environ.get("LOG_LEVEL", "INFO"),
        "sri_ambiente": os.environ.get("SRI_AMBIENTE", "1"),
        "sri_simulado": os.environ.get("SRI_SIMULADO", "true"),
        "sri_cert_configurado": bool(os.environ.get("SRI_CERT_PATH")),
        "supabase_configurada": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
        "auth_admin_configurada": bool(os.environ.get("APP_PASSWORD")),
        "auth_operario_configurada": bool(os.environ.get("APP_PASSWORD_OP")),
    })


def _safe_call(fn):
    try:
        return fn()
    except Exception as e:
        log.warning(f"metrics: error llamando {fn.__name__}: {e}")
        return None
