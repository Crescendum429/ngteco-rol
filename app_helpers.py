"""Helpers de serializacion compartidos por server.py y blueprints.

Convertidores entre el formato de storage y el formato esperado por el frontend.
"""

EMP_COLORS = [
    "oklch(72% 0.14 295)", "oklch(72% 0.14 30)",  "oklch(72% 0.14 200)",
    "oklch(72% 0.14 140)", "oklch(72% 0.14 70)",  "oklch(72% 0.14 330)",
    "oklch(72% 0.14 260)", "oklch(72% 0.14 100)",
]


def emp_to_js(key, emp, idx=0):
    nombre = emp.get("nombre", key)
    words = nombre.split()
    iniciales = "".join(w[0].upper() for w in words[:2]) if len(words) >= 2 else nombre[:2].upper()
    return {
        "id": key,
        "nombre": nombre,
        "cargo": emp.get("cargo", ""),
        "iniciales": iniciales,
        "color": EMP_COLORS[idx % len(EMP_COLORS)],
        "salario": float(emp.get("salario", 0)),
        "transporte": float(emp.get("transporte_dia", 0)),
        "transporte_gravable": bool(emp.get("transporte_gravable", True)),
        "horas_base": int(emp.get("horas_base", 8)),
        "region": emp.get("region", "Sierra/Amazonia"),
        "fondos_reserva": bool(emp.get("fondos_reserva", False)),
        "prestamo_iess": float(emp.get("prestamo_iess", 0)),
        "descuento_iess": bool(emp.get("descuento_iess", True)),
        "fecha_ingreso": emp.get("fecha_ingreso", ""),  # YYYY-MM-DD
        "ocultar": bool(emp.get("ocultar", False)),
    }


def mat_to_js(key, mat):
    return {
        "id": key,
        "nombre": mat.get("nombre", key),
        "costo_kg": float(mat.get("costo_kg", 0)),
        "merma": float(mat.get("merma_pct", 3.0)),
        "color": "oklch(70% 0.12 220)",
        "desactivado": bool(mat.get("desactivado", False)),
    }


def prod_to_js(key, prod):
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
        "iva_pct": float(prod.get("iva_pct", 15)),  # IVA aplicable: 0, 5, 15
        "desactivado": bool(prod.get("desactivado", False)),
    }


def empaque_to_js(key, emp):
    return {
        "id": key,
        "nombre": emp.get("nombre", key),
        "costo": float(emp.get("costo", 0)),
        "unidad": emp.get("unidad", "unidad"),
        "desactivado": bool(emp.get("desactivado", False)),
    }
