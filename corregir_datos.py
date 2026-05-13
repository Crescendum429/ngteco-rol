"""Correcciones segun feedback del usuario sobre la ingesta inicial:

1. Eliminar productos erroneos: camillas (eran canulas), v_amosan (era Lamosan),
   v_kromex (Kronos es cliente, no producto), v_sin_logo_tapon, v_sin_logo_acord
   (van como piezas, no productos).
2. Renombrar j_8ml -> j_3ml.
3. Marcar todos los productos sin datos verificados con datos_incompletos = [campos faltantes].
4. Eliminar cliente cli-alvesa (no existe).
5. Agregar cliente cli-jb (James Brown) con datos_incompletos.
6. Agregar piezas "sin logo tapon" y "sin logo acordeon" como piezas (no como producto).
7. Registrar entrada de MP: 20 fundas pp_clarificado x 25kg = 500kg (recibido 2026-05-05).

Idempotente. Conservador: nunca borra datos sin razón.
"""
from __future__ import annotations

import logging
from datetime import date as _date

from storage import (
    load_clientes, load_inv_piezas, load_movimientos_inventario,
    load_productos, save_clientes, save_inv_piezas,
    save_movimientos_inventario, save_productos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("corregir")


PRODUCTOS_A_ELIMINAR = {
    "camillas",          # son canulas (sub-componente, ya esta como pieza)
    "v_amosan",          # no existe Amosan, era Lamosan
    "v_kromex",          # Kronos es cliente, no producto separado
    "v_sin_logo_tapon",  # va como pieza
    "v_sin_logo_acord",  # va como pieza
}

# Renombrar j_8ml -> j_3ml
RENAMES = {"j_8ml": "j_3ml"}

# Campos faltantes por producto (datos asumidos durante la ingesta)
DATOS_INCOMPLETOS_POR_PRODUCTO = {
    "v_amosan":      None,  # se elimina
    "v_kromex":      None,  # se elimina
    "v_farma1":      ["peso_g", "costo_unit", "costo_caja", "unidades_caja"],
    "v_farma2":      ["peso_g", "costo_unit", "costo_caja", "unidades_caja"],
    "cuchara_chica": ["peso_g", "costo_unit", "costo_caja", "unidades_caja"],
    "cuchara_30cc":  ["peso_g", "costo_unit", "costo_caja", "unidades_caja"],
    "j_generic":     ["peso_g", "costo_unit", "costo_caja", "factor_complejidad"],
    "j_3ml":         ["peso_g", "costo_unit", "costo_caja", "unidades_caja", "factor_complejidad"],
}

PIEZAS_NUEVAS = [
    {
        "id": "ps-sin-logo-tapon",
        "pieza": "Sin logo tapon",
        "producto": None,
        "estado": "cruda",
        "cliente_id": None,
        "cantidad": 0,
        "unidad": "unidades",
        "ultima_actualizacion": "",
        "datos_incompletos": ["producto", "unidad_caja", "peso_unit"],
    },
    {
        "id": "ps-sin-logo-acordeon",
        "pieza": "Sin logo acordeon",
        "producto": None,
        "estado": "cruda",
        "cliente_id": None,
        "cantidad": 0,
        "unidad": "unidades",
        "ultima_actualizacion": "",
        "datos_incompletos": ["producto", "unidad_caja", "peso_unit"],
    },
]

CLIENTE_JB = {
    "id": "cli-jb",
    "razon_social": "",
    "nombre_comercial": "James Brown",
    "ruc": "",
    "tipo": "Sociedad",
    "obligado_contabilidad": False,
    "email_fact": "",
    "email_contacto": "",
    "telefono": "",
    "celular": "",
    "contacto_nombre": "",
    "contacto_cargo": "",
    "dir_matriz": {"calle": "", "numero": "", "interseccion": "", "ciudad": "", "referencia": ""},
    "dir_sucursal": {"calle": "", "numero": "", "interseccion": "", "ciudad": "", "referencia": ""},
    "credito_dias": 30,
    "credito_limite": 0,
    "agente_retencion": False,
    "resolucion_retencion": "",
    "notas": "Cliente detectado en chat 2026-05-06 (referencia 'JB todas las fechas').",
    "datos_incompletos": ["razon_social", "ruc", "direccion", "email_fact", "telefono", "contacto"],
}


def corregir_productos():
    ps = load_productos() or {}
    if not isinstance(ps, dict):
        ps = {}
    cambios = 0
    eliminados = []
    for pid in list(ps.keys()):
        if pid in PRODUCTOS_A_ELIMINAR:
            del ps[pid]
            eliminados.append(pid)
            cambios += 1
    # Rename j_8ml -> j_3ml
    for old, new in RENAMES.items():
        if old in ps:
            data = ps.pop(old)
            data["nombre"] = "Jeringa 3ml"
            ps[new] = data
            cambios += 1
            log.info(f"renombrado {old} -> {new}")
    # Aplicar flags datos_incompletos
    for pid, faltantes in DATOS_INCOMPLETOS_POR_PRODUCTO.items():
        if faltantes is None:
            continue
        if pid in ps:
            ps[pid]["datos_incompletos"] = faltantes
            cambios += 1
    save_productos(ps)
    log.info(f"productos: {len(eliminados)} eliminados {eliminados}, {cambios} cambios totales")


def corregir_clientes():
    cs = load_clientes() or []
    if not isinstance(cs, list):
        cs = []
    cs = [c for c in cs if isinstance(c, dict)]
    antes = len(cs)
    cs = [c for c in cs if c.get("id") != "cli-alvesa"]
    eliminados = antes - len(cs)
    # Agregar JB si no existe
    if not any(c.get("id") == "cli-jb" for c in cs):
        cs.append(CLIENTE_JB)
        log.info("cliente JB agregado")
    save_clientes(cs)
    log.info(f"clientes: -{eliminados} (alvesa eliminado), {len(cs)} total")


def agregar_piezas_sin_logo():
    piezas = load_inv_piezas() or []
    if not isinstance(piezas, list):
        piezas = []
    ids_existentes = {p.get("id") for p in piezas if isinstance(p, dict)}
    nuevas = [p for p in PIEZAS_NUEVAS if p["id"] not in ids_existentes]
    if nuevas:
        save_inv_piezas(piezas + nuevas)
    log.info(f"piezas: {len(nuevas)} nuevas (sin logo)")


def registrar_entrada_clarificado():
    """20 fundas × 25kg = 500kg de pp_clarificado recibido 2026-05-05."""
    movs = load_movimientos_inventario() or []
    if not isinstance(movs, list):
        movs = []
    # Buscar si ya existe para idempotencia
    ya_existe = any(
        m.get("clase") == "mp" and m.get("item_id") == "pp_clarificado"
        and m.get("fecha") == "2026-05-05" and float(m.get("cantidad", 0)) == 500
        for m in movs if isinstance(m, dict)
    )
    if ya_existe:
        log.info("entrada clarificado 5/5 ya existe, no se duplica")
        return
    nid = (max([int(m.get("id", 0)) for m in movs if isinstance(m, dict)], default=0)) + 1
    movs.insert(0, {
        "id": nid,
        "fecha": "2026-05-05",
        "tipo": "entrada",
        "clase": "mp",
        "item_id": "pp_clarificado",
        "cantidad": 500.0,
        "unidad": "kg",
        "ref": "20 fundas",
        "nota": "Recepcion 20 fundas clarificado (25kg c/u)",
    })
    save_movimientos_inventario(movs)
    log.info("entrada registrada: +500kg pp_clarificado (5/5)")


def main() -> None:
    log.info("=== Correcciones de datos ===")
    corregir_productos()
    corregir_clientes()
    agregar_piezas_sin_logo()
    registrar_entrada_clarificado()
    log.info("Correcciones aplicadas.")


if __name__ == "__main__":
    main()
