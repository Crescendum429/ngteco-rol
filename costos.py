"""Calculo de costos de produccion SOLPLAST."""

# ── Defaults editables desde la UI ────────────────────────────

MATERIALES_DEFAULT = {
    "pp_omo":         {"nombre": "PP Homopolimero",   "costo_kg": 1.75},
    "pp_clarificado": {"nombre": "PP Clarificado",    "costo_kg": 2.25},
    "pe_baja":        {"nombre": "PE Baja Densidad",  "costo_kg": 2.00},
    "pe_alta":        {"nombre": "PE Alta Densidad",  "costo_kg": 1.85},
    "pvc":            {"nombre": "PVC",               "costo_kg": 2.10},
}

_MEZCLA_STD = {"pp_clarificado": 0.6667, "pp_omo": 0.3333}

PRODUCTOS_DEFAULT = {
    "v_life": {
        "nombre": "Vaso Life",
        "unidades_caja": 2500,
        "componentes": [
            {"nombre": "Cuerpo", "peso_g": 2.920, "material": "mezcla",
             "proporcion": dict(_MEZCLA_STD)},
        ],
        "empaques": {"caja": 1, "funda_exterior_doble": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "v_solplast": {
        "nombre": "Vaso Solplast",
        "unidades_caja": 2500,
        "componentes": [{"nombre": "Cuerpo", "peso_g": 2.546, "material": "pp_omo"}],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "v_farmayala_ant": {
        "nombre": "Vaso Farmayala antiguo",
        "unidades_caja": 2000,
        "componentes": [{"nombre": "Cuerpo", "peso_g": 3.296, "material": "pp_omo"}],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "v_lamosan": {
        "nombre": "Vaso Lamosan",
        "unidades_caja": 2500,
        "componentes": [{"nombre": "Cuerpo", "peso_g": 2.874, "material": "pp_omo"}],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "v_farmayala_nuevo": {
        "nombre": "Vaso Farmayala nuevo",
        "unidades_caja": 2000,
        "componentes": [{"nombre": "Cuerpo", "peso_g": 3.182, "material": "pp_omo"}],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "v_pequena": {
        "nombre": "Vaso Pequeno",
        "unidades_caja": 3500,
        "componentes": [{"nombre": "Cuerpo", "peso_g": 2.208, "material": "pp_omo"}],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "cuchara_5ml": {
        "nombre": "Cuchara 5ml",
        "unidades_caja": 8000,
        "componentes": [
            {"nombre": "Cuerpo", "peso_g": 0.260, "material": "mezcla",
             "proporcion": dict(_MEZCLA_STD)},
        ],
        "empaques": {"caja": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.0,
    },
    "gotero": {
        "nombre": "Gotero",
        "unidades_caja": 1000,
        "componentes": [
            {"nombre": "Cuerpo", "peso_g": 0.994, "material": "mezcla",
             "proporcion": dict(_MEZCLA_STD)},
            {"nombre": "Capuchon", "peso_g": 2.296, "material": "pvc"},
        ],
        "empaques": {"caja": 1, "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 1.8,
    },
    "j_sin_tampo": {
        "nombre": "Jeringa sin tampo",
        "unidades_caja": 1000,
        "componentes": [
            {"nombre": "Canula",   "peso_g": 2.960, "material": "pp_clarificado"},
            {"nombre": "Piston",   "peso_g": 3.068, "material": "pe_alta"},
            {"nombre": "Acordeon", "peso_g": 1.858, "material": "pe_baja"},
        ],
        "empaques": {"caja": 1, "funda_individual": 1,
                     "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 2.5,
    },
    "j_farmayala": {
        "nombre": "Jeringa Farmayala (con tampo)",
        "unidades_caja": 1000,
        "componentes": [
            {"nombre": "Canula",   "peso_g": 2.960, "material": "pp_clarificado"},
            {"nombre": "Piston",   "peso_g": 3.068, "material": "pe_alta"},
            {"nombre": "Acordeon", "peso_g": 1.858, "material": "pe_baja"},
        ],
        "empaques": {"caja": 1, "funda_individual": 1, "tinta_tampo": 1,
                     "funda_exterior_simple": 1, "cinta_embalaje": 1},
        "factor_complejidad": 3.0,
    },
    "j_life": {
        "nombre": "Jeringa Life",
        "unidades_caja": 1200,
        "componentes": [
            {"nombre": "Canula", "peso_g": 2.960, "material": "pp_clarificado"},
            {"nombre": "Piston", "peso_g": 3.068, "material": "pe_alta"},
            {"nombre": "Tapon",  "peso_g": 1.030, "material": "pe_baja"},
        ],
        "empaques": {"caja": 1, "funda_individual": 1, "tinta_tampo": 1,
                     "funda_exterior_doble": 1, "cinta_embalaje": 1},
        "factor_complejidad": 3.3,
    },
}

EMPAQUES_DEFAULT = {
    "caja":                  {"nombre": "Caja",                   "costo": 1.00,  "unidad": "caja"},
    "funda_individual":      {"nombre": "Funda individual",       "costo": 0.004, "unidad": "unidad"},
    "funda_exterior_simple": {"nombre": "Funda exterior simple",  "costo": 0.08,  "unidad": "caja"},
    "funda_exterior_doble":  {"nombre": "Funda exterior doble",   "costo": 0.15,  "unidad": "caja"},
    "cinta_embalaje":        {"nombre": "Cinta embalaje",         "costo": 0.015, "unidad": "caja"},
    "tinta_tampo":           {"nombre": "Tinta de tampo",         "costo": 0.002, "unidad": "unidad"},
}

GASTOS_FIJOS_DEFAULT = {
    "electricidad":  550.0,
    "agua":          45.0,
    "tinta":         60.0,
    "tinner":        30.0,
    "solvente":      45.0,
    "transporte":    150.0,
    "mantenimiento": 80.0,
}

MERMA_DEFAULT_PCT = 3.0

# Mapeo de subproductos (partes) a su material principal
SUBPRODUCTO_MATERIAL = {
    "canula":   "pp_clarificado",
    "piston":   "pe_alta",
    "acordeon": "pe_baja",
    "tapon":    "pe_baja",
    "capuchon": "pvc",
}


# ── Calculos ──────────────────────────────────────────────────

def materiales_por_unidad(componente):
    """{material_id: gramos_por_unidad} para un componente."""
    peso = componente.get("peso_g", 0) or 0
    mat = componente.get("material", "")
    if mat == "mezcla":
        prop = componente.get("proporcion", {}) or {}
        return {mid: peso * float(p) for mid, p in prop.items() if float(p) > 0}
    if mat:
        return {mat: peso}
    return {}


def costo_material_producto(producto, materiales, merma_pcts=None):
    """Costo de materia prima por unidad del producto (aplica factor de merma)."""
    merma_pcts = merma_pcts or {}
    total = 0.0
    for comp in producto.get("componentes", []):
        for mid, g in materiales_por_unidad(comp).items():
            mat = materiales.get(mid)
            if not mat:
                continue
            costo_kg = float(mat.get("costo_kg", 0) or 0)
            merma = float(merma_pcts.get(mid, MERMA_DEFAULT_PCT)) / 100.0
            divisor = max(1 - merma, 0.01)
            total += (g / 1000.0) * costo_kg / divisor
    return total


def costo_empaque_producto(producto, empaques):
    """Costo de empaque por unidad del producto."""
    u_caja = producto.get("unidades_caja", 1) or 1
    total = 0.0
    for emp_id, qty in producto.get("empaques", {}).items():
        emp = empaques.get(emp_id)
        if not emp:
            continue
        costo = float(emp.get("costo", 0) or 0)
        unidad = emp.get("unidad", "caja")
        cantidad = float(qty) if isinstance(qty, (int, float)) else 1.0
        if unidad == "unidad":
            total += costo * cantidad
        else:
            total += (costo * cantidad) / u_caja
    return total


def calcular_merma_por_material(registros_diarios, productos, materiales):
    """Calcula merma % por material a partir de registros diarios.

    registros_diarios: dict {fecha_str: registro}
    Un registro tiene:
      material_usado: {mat_id: kg}
      desechos_por_producto: {producto_id: kg}
    """
    usado = {mid: 0.0 for mid in materiales}
    desecho = {mid: 0.0 for mid in materiales}

    for reg in registros_diarios.values():
        for mid, kg in (reg.get("material_usado") or {}).items():
            if mid in usado:
                usado[mid] += float(kg or 0)

        for pid, kg in (reg.get("desechos_por_producto") or {}).items():
            prod = productos.get(pid)
            if not prod:
                continue
            kg = float(kg or 0)
            if kg <= 0:
                continue
            peso_total = sum(c.get("peso_g", 0) or 0 for c in prod.get("componentes", []))
            if peso_total <= 0:
                continue
            for comp in prod.get("componentes", []):
                peso_comp = comp.get("peso_g", 0) or 0
                if peso_comp <= 0:
                    continue
                share_comp = peso_comp / peso_total
                kg_comp = kg * share_comp
                for mid, g in materiales_por_unidad(comp).items():
                    share_in_comp = g / peso_comp if peso_comp > 0 else 1.0
                    if mid in desecho:
                        desecho[mid] += kg_comp * share_in_comp

        # Desechos de subproductos (partes sueltas)
        for sid, kg in (reg.get("desechos_subproductos") or {}).items():
            mat_id = SUBPRODUCTO_MATERIAL.get(sid)
            if mat_id and mat_id in desecho:
                desecho[mat_id] += float(kg or 0)

    result = {}
    for mid in materiales:
        if usado[mid] > 0:
            result[mid] = round((desecho[mid] / usado[mid]) * 100.0, 2)
    return result


def calcular_costos(
    productos, materiales, empaques,
    gastos_fijos_total=0.0, nomina_total=0.0,
    produccion_unidades=None, merma_pcts=None,
):
    """Calcula costo unitario de cada producto.

    produccion_unidades: dict {producto_id: total_unidades_mes}
    Retorna: dict {producto_id: {nombre, material, empaque, nomina, gastos_ind, total, por_caja, unidades}}
    """
    produccion_unidades = produccion_unidades or {}

    # Base para asignar gastos: factor_complejidad x unidades
    suma_pond = 0.0
    for pid, prod in productos.items():
        u = float(produccion_unidades.get(pid, 0) or 0)
        suma_pond += float(prod.get("factor_complejidad", 1.0) or 1.0) * u

    fc_total = sum(float(p.get("factor_complejidad", 1.0) or 1.0) for p in productos.values())

    resultados = {}
    for pid, prod in productos.items():
        units = float(produccion_unidades.get(pid, 0) or 0)
        fc = float(prod.get("factor_complejidad", 1.0) or 1.0)

        mat = costo_material_producto(prod, materiales, merma_pcts)
        emp = costo_empaque_producto(prod, empaques)

        if suma_pond > 0:
            if units > 0:
                share = (fc * units) / suma_pond
                nomina_u = (nomina_total * share) / units
                fijos_u = (gastos_fijos_total * share) / units
            else:
                # Hay produccion de otros productos pero no de este:
                # no se le asignan gastos indirectos. Solo material y empaque.
                nomina_u = 0.0
                fijos_u = 0.0
        else:
            # Sin datos de produccion en absoluto: prorratear teoricamente
            # sobre 1000 unidades base para visualizar un costo estimado.
            base_u = 1000.0
            if fc_total > 0:
                nomina_u = (nomina_total * fc / fc_total) / base_u
                fijos_u = (gastos_fijos_total * fc / fc_total) / base_u
            else:
                nomina_u = 0.0
                fijos_u = 0.0

        total = mat + emp + nomina_u + fijos_u
        resultados[pid] = {
            "nombre": prod.get("nombre", pid),
            "unidades": int(units),
            "material": round(mat, 4),
            "empaque": round(emp, 4),
            "nomina": round(nomina_u, 4),
            "gastos_ind": round(fijos_u, 4),
            "total": round(total, 4),
            "por_caja": round(total * (prod.get("unidades_caja", 1) or 1), 2),
        }
    return resultados


def sumar_produccion_mensual(registros_diarios):
    """Suma cantidades producidas (en cajas/fundas) en el mes por producto.

    Soporta formato legacy {pid: int} y nuevo {pid: {cant, uni}}.
    Retorna: dict {producto_id: total_cantidad}
    """
    totales = {}
    for reg in registros_diarios.values():
        for pid, val in (reg.get("produccion") or {}).items():
            if isinstance(val, dict):
                n = float(val.get("cant", 0) or 0)
            else:
                n = float(val or 0)
            totales[pid] = totales.get(pid, 0) + n
    return totales


def sumar_gastos_fijos(gastos):
    return sum(float(v or 0) for v in (gastos or {}).values())
