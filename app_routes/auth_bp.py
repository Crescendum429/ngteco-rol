"""Blueprint de autenticacion. Rate limit basico en memoria por IP."""
import os
from collections import defaultdict
from time import time

from flask import Blueprint, jsonify, request, session

from logger import get_logger

log = get_logger("auth")

auth_bp = Blueprint("auth", __name__)

_rate_buckets = defaultdict(list)


def _rate_limit_check(key: str, max_attempts: int, window_seconds: int) -> bool:
    now = time()
    _rate_buckets[key] = [t for t in _rate_buckets[key] if now - t < window_seconds]
    if len(_rate_buckets[key]) >= max_attempts:
        return False
    _rate_buckets[key].append(now)
    return True


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


@auth_bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    ip = _client_ip()
    if not _rate_limit_check(f"login:{ip}", max_attempts=10, window_seconds=300):
        log.warning(f"Login rate limit excedido para IP {ip}")
        return jsonify({"error": "Demasiados intentos. Espera 5 minutos."}), 429

    data = request.get_json(silent=True) or {}
    role = data.get("role", "admin")
    pwd = data.get("password", "")

    if role not in ("admin", "operario"):
        return jsonify({"error": "Rol invalido"}), 400

    APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
    APP_PASSWORD_OP = os.environ.get("APP_PASSWORD_OP", "")

    if not APP_PASSWORD and not APP_PASSWORD_OP:
        log.warning("Login sin contrasena configurada — admitiendo cualquier credencial (modo dev)")
        session.permanent = True  # Persiste 30 dias, configurado en server.py
        session["_auth"] = True
        session["_role"] = role
        return jsonify({"role": role})

    if role == "admin" and APP_PASSWORD and pwd == APP_PASSWORD:
        session.permanent = True
        session["_auth"] = True
        session["_role"] = "admin"
        log.info(f"Login exitoso admin desde {ip}")
        return jsonify({"role": "admin"})
    if role == "operario" and APP_PASSWORD_OP and pwd == APP_PASSWORD_OP:
        session.permanent = True
        session["_auth"] = True
        session["_role"] = "operario"
        log.info(f"Login exitoso operario desde {ip}")
        return jsonify({"role": "operario"})

    log.info(f"Login fallido para rol={role} desde {ip}")
    return jsonify({"error": "Credenciales incorrectas"}), 401


@auth_bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me")
def auth_me():
    if os.environ.get("APP_PASSWORD") and not session.get("_auth"):
        return jsonify({"role": None})
    return jsonify({"role": session.get("_role", "admin")})
