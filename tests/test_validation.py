"""Tests del modulo validation."""
import pytest

from validation import ValidationError, as_float, as_int, as_str, require_fields


def test_as_float_basico():
    assert as_float("3.14", "x") == 3.14
    assert as_float(0, "x") == 0.0
    assert as_float(None, "x") == 0.0
    assert as_float("", "x") == 0.0


def test_as_float_rango():
    assert as_float(5, "x", min_v=0, max_v=10) == 5.0
    with pytest.raises(ValidationError):
        as_float(-1, "x", min_v=0)
    with pytest.raises(ValidationError):
        as_float(20, "x", max_v=10)


def test_as_float_no_numerico():
    with pytest.raises(ValidationError):
        as_float("abc", "x")


def test_as_int():
    assert as_int("42", "x") == 42
    assert as_int(None, "x") == 0
    with pytest.raises(ValidationError):
        as_int("abc", "x")
    with pytest.raises(ValidationError):
        as_int(-1, "x", min_v=0)


def test_as_str_basico():
    assert as_str("hola", "x") == "hola"
    assert as_str("  trim  ", "x") == "trim"
    assert as_str(None, "x") == ""


def test_as_str_max_len():
    with pytest.raises(ValidationError):
        as_str("a" * 1000, "x", max_len=10)


def test_require_fields_ok():
    require_fields({"nombre": "X", "edad": 30}, "nombre", "edad")  # no levanta


def test_require_fields_missing():
    with pytest.raises(ValidationError) as exc:
        require_fields({"nombre": "X"}, "nombre", "edad")
    assert "edad" in exc.value.message


def test_require_fields_no_dict():
    with pytest.raises(ValidationError):
        require_fields("no es dict", "x")


def test_require_fields_valores_vacios():
    with pytest.raises(ValidationError):
        require_fields({"nombre": ""}, "nombre")
    with pytest.raises(ValidationError):
        require_fields({"items": []}, "items")
