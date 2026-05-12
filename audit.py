"""Helper para audit log de cambios sensibles."""
from datetime import datetime

from flask import request, session

from logger import get_logger
from storage import append_audit, load_audit_log

log = get_logger("audit")


def record(entity: str, action: str, entity_id: str, before=None, after=None):
    """Registra un cambio sensible. Append-only.

    Args:
        entity: tipo (empleado, factura, cotizacion, lote, override, etc.)
        action: create, update, delete, emitir, despachar, calcular, etc.
        entity_id: clave de la entidad
        before: estado anterior (dict) o None
        after: estado nuevo (dict) o None
    """
    try:
        user = session.get("_role") or "anonymous"
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        ip = ip.split(",")[0].strip()
    except Exception:
        user = "system"
        ip = ""
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "user": user,
        "ip": ip,
        "entity": entity,
        "action": action,
        "entity_id": entity_id,
        "before": before,
        "after": after,
    }
    try:
        append_audit(entry)
        log.info(f"audit: {user} {action} {entity}/{entity_id}")
    except Exception:
        log.exception(f"audit: error guardando entrada {entity}/{entity_id}")


def query(limit=200, entity_type=None, entity_id=None):
    return load_audit_log(limit=limit, entity_type=entity_type, entity_id=entity_id)
