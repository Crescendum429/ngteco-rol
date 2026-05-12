"""Health y readiness checks. Sin auth — Render los usa para probes."""
import os
from flask import Blueprint, jsonify

from logger import get_logger

log = get_logger("health")

health_bp = Blueprint("health", __name__)


def _get_version():
    # Lazy import para evitar ciclos
    try:
        from server import APP_VERSION, _STARTUP_WARNINGS
        return APP_VERSION, _STARTUP_WARNINGS
    except Exception:
        return "unknown", []


@health_bp.route("/api/health")
def health():
    version, _ = _get_version()
    return jsonify({"status": "ok", "version": version}), 200


@health_bp.route("/api/ready")
def ready():
    version, warnings = _get_version()
    checks = {"version": version, "warnings": warnings}
    try:
        from storage import USE_SUPABASE, _supabase
        if USE_SUPABASE:
            _supabase().table("config").select("key").limit(1).execute()
            checks["db"] = "ok"
        else:
            checks["db"] = "no_configurada"
        return jsonify({"status": "ready", **checks}), 200
    except Exception as e:
        log.error(f"Readiness check fallo: {e}")
        checks["db"] = "error"
        return jsonify({"status": "degraded", **checks}), 503
