"""Validacion centralizada para endpoints de Solplast ERP."""
from flask import jsonify, request


class ValidationError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status


def require_json() -> dict:
    """Garantiza que el body sea JSON y devuelve el dict. Lanza ValidationError si no."""
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError("Body debe ser JSON valido")
    if not isinstance(data, (dict, list)):
        raise ValidationError("Body debe ser objeto o array JSON")
    return data


def require_fields(data: dict, *fields: str) -> None:
    """Valida que los campos requeridos existan y no sean None/vacios."""
    if not isinstance(data, dict):
        raise ValidationError("Se esperaba un objeto JSON")
    missing = [f for f in fields if data.get(f) in (None, "", [])]
    if missing:
        raise ValidationError(f"Campos requeridos: {', '.join(missing)}")


def as_float(value, field: str, min_v: float | None = None, max_v: float | None = None) -> float:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        raise ValidationError(f"{field}: se esperaba numero, llego {type(value).__name__}")
    if min_v is not None and v < min_v:
        raise ValidationError(f"{field}: debe ser >= {min_v}")
    if max_v is not None and v > max_v:
        raise ValidationError(f"{field}: debe ser <= {max_v}")
    return v


def as_int(value, field: str, min_v: int | None = None, max_v: int | None = None) -> int:
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        raise ValidationError(f"{field}: se esperaba entero, llego {type(value).__name__}")
    if min_v is not None and v < min_v:
        raise ValidationError(f"{field}: debe ser >= {min_v}")
    if max_v is not None and v > max_v:
        raise ValidationError(f"{field}: debe ser <= {max_v}")
    return v


def as_str(value, field: str, max_len: int = 500) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if len(s) > max_len:
        raise ValidationError(f"{field}: maximo {max_len} caracteres")
    return s


def make_error_response(error: ValidationError):
    return jsonify({"error": error.message}), error.status
