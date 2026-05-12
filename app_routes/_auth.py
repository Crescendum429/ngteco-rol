"""Decoradores y helpers de autenticacion compartidos por todos los blueprints."""
import os
from functools import wraps

from flask import jsonify, session


def require_auth(f):
    """Bloquea acceso si APP_PASSWORD esta configurada y no hay sesion activa."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if os.environ.get("APP_PASSWORD") and not session.get("_auth"):
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return decorated
