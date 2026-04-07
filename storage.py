import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DATA_FILE = os.path.join(DATA_DIR, "empleados.enc")


def _get_key():
    pwd = os.environ.get("APP_PASSWORD", "default-key-change-me")
    key = hashlib.pbkdf2_hmac("sha256", pwd.encode(), b"ngteco-rol-salt", 100_000)
    return base64.urlsafe_b64encode(key)


def _fernet():
    return Fernet(_get_key())


def load_empleados():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "rb") as f:
        data = f.read()
    try:
        decrypted = _fernet().decrypt(data)
        return json.loads(decrypted)
    except Exception:
        return {}


def save_empleados(empleados):
    os.makedirs(DATA_DIR, exist_ok=True)
    data = json.dumps(empleados, ensure_ascii=False, indent=2).encode()
    encrypted = _fernet().encrypt(data)
    with open(DATA_FILE, "wb") as f:
        f.write(encrypted)


def export_json(empleados):
    return json.dumps(empleados, ensure_ascii=False, indent=2)


def import_json(raw):
    return json.loads(raw)
