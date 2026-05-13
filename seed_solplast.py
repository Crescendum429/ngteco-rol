"""Seeder inicial para Solplast ERP basado en las hojas fisicas de la planta.

Productos inferidos de hoja "Material Producido" (mes 03/2026):
  V. Amosan, V. Life, V. Kromex, Vaso Farma 1/2, Cucharita, Cuchara 30cc,
  Vaso sin logo (tapon/acordeon), Jeringa generica, Jeringa 8ml, Camillas,
  Farm/Pharma, Gotero.

Auxiliares inferidos de hoja "Material Auxiliar" (mes 05/2026):
  Rollo empacadora, Cartones, Fundas vasos/jeringas/cucharas, Pintura,
  Guantes nitrilo, Cintas, Esparadrapos.

Idempotente: solo agrega items que no existan por id.
Ejecutar con: python seed_solplast.py
"""
from __future__ import annotations

import logging
from typing import Any

from storage import (
    load_inv_auxiliar,
    load_inv_molido,
    load_inv_piezas,
    load_productos,
    save_inv_auxiliar,
    save_inv_molido,
    save_inv_piezas,
    save_productos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed")


# shape interno: clave = id, value = dict con (kind, nombre, unidades_caja, peso_g,
# material_desc, factor_complejidad, costo_unit, costo_caja, empaques)
PRODUCTOS_SEED: dict[str, dict[str, Any]] = {
    "v_amosan":         {"kind": "vaso",    "nombre": "Vaso Amosan",              "unidades_caja": 2500, "peso_g": 2.85,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0078, "costo_caja": 19.50, "empaques": {"caja": 1}},
    "v_life":           {"kind": "vaso",    "nombre": "Vaso Life",                "unidades_caja": 2500, "peso_g": 2.920, "material_desc": "PP Clarificado",             "factor_complejidad": 1.0, "costo_unit": 0.0082, "costo_caja": 20.50, "empaques": {"caja": 1}},
    "v_kromex":         {"kind": "vaso",    "nombre": "Vaso Kromex",              "unidades_caja": 2500, "peso_g": 2.90,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0080, "costo_caja": 20.00, "empaques": {"caja": 1}},
    "v_farma1":         {"kind": "vaso",    "nombre": "Vaso Farma 1",             "unidades_caja": 2000, "peso_g": 3.30,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0082, "costo_caja": 16.40, "empaques": {"caja": 1}},
    "v_farma2":         {"kind": "vaso",    "nombre": "Vaso Farma 2",             "unidades_caja": 2000, "peso_g": 3.18,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0080, "costo_caja": 16.00, "empaques": {"caja": 1}},
    "v_lamosan":        {"kind": "vaso",    "nombre": "Vaso Lamosan",             "unidades_caja": 2500, "peso_g": 2.87,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0076, "costo_caja": 19.00, "empaques": {"caja": 1}},
    "v_sin_logo_tapon": {"kind": "vaso",    "nombre": "Vaso sin logo (tapon)",    "unidades_caja": 2500, "peso_g": 2.85,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0075, "costo_caja": 18.75, "empaques": {"caja": 1}},
    "v_sin_logo_acord": {"kind": "vaso",    "nombre": "Vaso sin logo (acordeon)", "unidades_caja": 2500, "peso_g": 2.85,  "material_desc": "PP Homopolimero",            "factor_complejidad": 1.0, "costo_unit": 0.0075, "costo_caja": 18.75, "empaques": {"caja": 1}},
    "cuchara_chica":    {"kind": "cuchara", "nombre": "Cucharita",                "unidades_caja": 8000, "peso_g": 0.26,  "material_desc": "PP Clarificado",             "factor_complejidad": 1.0, "costo_unit": 0.0011, "costo_caja": 8.80,  "empaques": {"caja": 1}},
    "cuchara_30cc":     {"kind": "cuchara", "nombre": "Cuchara 30cc",             "unidades_caja": 5000, "peso_g": 0.95,  "material_desc": "PP Clarificado",             "factor_complejidad": 1.1, "costo_unit": 0.0028, "costo_caja": 14.00, "empaques": {"caja": 1}},
    "gotero":           {"kind": "gotero",  "nombre": "Gotero completo",          "unidades_caja": 1000, "peso_g": 3.29,  "material_desc": "Mezcla + PVC",               "factor_complejidad": 1.8, "costo_unit": 0.0194, "costo_caja": 19.40, "empaques": {"caja": 1}},
    "j_generic":        {"kind": "jeringa", "nombre": "Jeringa generica",         "unidades_caja": 1000, "peso_g": 7.886, "material_desc": "PP Clarif + PE Alta + PE Baja", "factor_complejidad": 2.5, "costo_unit": 0.0231, "costo_caja": 23.10, "empaques": {"caja": 1}},
    "j_farmayala":      {"kind": "jeringa", "nombre": "Jeringa Farmayala",        "unidades_caja": 1000, "peso_g": 7.886, "material_desc": "PP Clarif + PE Alta + PE Baja", "factor_complejidad": 3.0, "costo_unit": 0.0256, "costo_caja": 25.60, "empaques": {"caja": 1}},
    "j_life":           {"kind": "jeringa", "nombre": "Jeringa Life",             "unidades_caja": 1200, "peso_g": 7.058, "material_desc": "PP Clarif + PE Alta + PE Baja", "factor_complejidad": 3.3, "costo_unit": 0.0249, "costo_caja": 29.88, "empaques": {"caja": 1}},
    "j_8ml":            {"kind": "jeringa", "nombre": "Jeringa 8ml",              "unidades_caja": 1000, "peso_g": 9.20,  "material_desc": "PP Clarif + PE Alta + PE Baja", "factor_complejidad": 3.5, "costo_unit": 0.0285, "costo_caja": 28.50, "empaques": {"caja": 1}},
    "camillas":         {"kind": "vaso",    "nombre": "Camillas",                 "unidades_caja": 500,  "peso_g": 12.0,  "material_desc": "PP Homopolimero",            "factor_complejidad": 2.0, "costo_unit": 0.0250, "costo_caja": 12.50, "empaques": {"caja": 1}},
}


AUX_SEED: list[dict[str, Any]] = [
    {"id": "aux-rollo-empacadora", "nombre": "Rollo empacadora",     "categoria": "empacadora", "unidad": "rollos",   "stock": 0, "minimo": 2,    "costo_unit": 0},
    {"id": "aux-cartones",         "nombre": "Cartones",             "categoria": "empacadora", "unidad": "unidades", "stock": 0, "minimo": 50,   "costo_unit": 0},
    {"id": "aux-fundas-vasos",     "nombre": "Fundas vasos",         "categoria": "fundas",     "unidad": "unidades", "stock": 0, "minimo": 1000, "costo_unit": 0},
    {"id": "aux-fundas-jeringas",  "nombre": "Fundas jeringas",      "categoria": "fundas",     "unidad": "unidades", "stock": 0, "minimo": 500,  "costo_unit": 0},
    {"id": "aux-fundas-cucharas",  "nombre": "Fundas cucharas",      "categoria": "fundas",     "unidad": "unidades", "stock": 0, "minimo": 500,  "costo_unit": 0},
    {"id": "aux-pintura",          "nombre": "Pintura tampo",        "categoria": "impresion",  "unidad": "kg",       "stock": 0, "minimo": 0.5,  "costo_unit": 0},
    {"id": "aux-guantes-nitrilo",  "nombre": "Guantes nitrilo",      "categoria": "seguridad",  "unidad": "cajas",    "stock": 0, "minimo": 2,    "costo_unit": 0},
    {"id": "aux-cintas",           "nombre": "Cintas",               "categoria": "empacadora", "unidad": "rollos",   "stock": 0, "minimo": 6,    "costo_unit": 0},
    {"id": "aux-esparadrapos",     "nombre": "Esparadrapos",         "categoria": "seguridad",  "unidad": "rollos",   "stock": 0, "minimo": 3,    "costo_unit": 0},
]


PIEZAS_SEED: list[dict[str, Any]] = [
    {"id": "ps-canula-cruda",   "pieza": "Canula",       "producto": "j_generic",   "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-piston-cruda",   "pieza": "Piston",       "producto": "j_generic",   "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-tapon-cruda",    "pieza": "Tapon",        "producto": "j_generic",   "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-tapon-nuevo",    "pieza": "Tapon nuevo",  "producto": "j_generic",   "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-acordeon-cruda", "pieza": "Acordeon",     "producto": "j_generic",   "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-gotero-cruda",   "pieza": "Gotero base",  "producto": "gotero",      "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
    {"id": "ps-capuchon-cruda", "pieza": "Capuchon",     "producto": "gotero",      "estado": "cruda",   "cantidad": 0, "unidad": "unidades"},
]


MOLIDO_SEED: dict[str, float] = {
    "mol-canula": 0,
    "mol-vaso": 0,
    "mol-piston": 0,
    "mol-tapon": 0,
    "mol-acordeon": 0,
    "mol-alta": 0,
    "mol-baja": 0,
    "mol-mazarota": 0,
}


def seed_productos() -> int:
    existentes = load_productos() or {}
    if not isinstance(existentes, dict):
        existentes = {}
    nuevos = {k: v for k, v in PRODUCTOS_SEED.items() if k not in existentes}
    if nuevos:
        merged = {**existentes, **nuevos}
        save_productos(merged)
    log.info(f"productos: {len(nuevos)} nuevos, {len(existentes)} preservados")
    return len(nuevos)


def seed_auxiliar() -> int:
    existentes = load_inv_auxiliar() or []
    ids_existentes = {a.get("id") for a in existentes if isinstance(a, dict)}
    nuevos = [a for a in AUX_SEED if a["id"] not in ids_existentes]
    if nuevos:
        save_inv_auxiliar(list(existentes) + nuevos)
    log.info(f"auxiliar: {len(nuevos)} nuevos, {len(existentes)} preservados")
    return len(nuevos)


def seed_piezas() -> int:
    existentes = load_inv_piezas() or []
    ids_existentes = {p.get("id") for p in existentes if isinstance(p, dict)}
    nuevas = [p for p in PIEZAS_SEED if p["id"] not in ids_existentes]
    if nuevas:
        save_inv_piezas(list(existentes) + nuevas)
    log.info(f"piezas: {len(nuevas)} nuevas, {len(existentes)} preservadas")
    return len(nuevas)


def seed_molido() -> int:
    existente = load_inv_molido() or {}
    nuevos = {k: v for k, v in MOLIDO_SEED.items() if k not in existente}
    if nuevos:
        merged = {**existente, **nuevos}
        save_inv_molido(merged)
    log.info(f"molido: {len(nuevos)} nuevos bins, {len(existente)} preservados")
    return len(nuevos)


def main() -> None:
    log.info("Seed inicial Solplast iniciando...")
    seed_productos()
    seed_auxiliar()
    seed_piezas()
    seed_molido()
    log.info("Seed completado.")


if __name__ == "__main__":
    main()
