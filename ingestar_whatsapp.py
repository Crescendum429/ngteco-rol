"""Ingesta manual de jornadas reportadas en el chat de WhatsApp del grupo Solplastuio.

Cada jornada se construyo razonando individualmente:
  - Cantidades de piezas reportadas = numero de TACHOS (cada tacho ~ 1000 piezas)
  - "X cajas empacadas de [cliente]" => empaque a ese cliente
  - "Canulas impresas N" => N tachos de canulas impresas (cliente Farbio default)
  - "X tachos armados de [cliente]" => intermedio: jeringa armada (no empacada)
  - Material en kg distribuido al consumo del dia
  - Desechos kg pasan al bin de molido correspondiente
  - Desecho empacadora en unidades = descarte final

Idempotente: cada fecha se sobreescribe en cada corrida.
"""
from __future__ import annotations

import logging
from typing import Any

from storage import (
    append_aux_consumo,
    load_inv_lotes,
    load_inv_molido,
    load_inv_piezas,
    save_inv_lotes,
    save_inv_molido,
    save_inv_piezas,
    save_registro_diario,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wa-ingesta")


# -----------------------------------------------------------------------------
# Helpers para mutar inventarios

def piezas_inc(pieza: str, estado: str, cliente_id: str | None, delta_unidades: float):
    """Suma `delta_unidades` al bin de piezas. Recarga + muta + guarda atomicamente."""
    piezas = load_inv_piezas() or []
    matched = None
    for p in piezas:
        if (p.get("pieza", "").lower() == pieza.lower()
                and p.get("estado") == estado
                and (p.get("cliente_id") or None) == (cliente_id or None)):
            matched = p
            break
    if matched is None:
        piezas.append({
            "id": f"ps-{pieza}-{estado}" + (f"-{cliente_id}" if cliente_id else ""),
            "pieza": pieza.capitalize(),
            "producto": "j_generic",
            "estado": estado,
            "cliente_id": cliente_id,
            "cantidad": max(0, delta_unidades),
            "unidad": "unidades",
            "ultima_actualizacion": "",
        })
    else:
        matched["cantidad"] = max(0, float(matched.get("cantidad", 0)) + delta_unidades)
    save_inv_piezas(piezas)


def molido_inc(tipo: str, delta_kg: float):
    mol = load_inv_molido() or {}
    mol[tipo] = round(float(mol.get(tipo, 0)) + delta_kg, 3)
    save_inv_molido(mol)


def crear_lote(prod_id: str, cliente_id: str | None, fecha: str, cajas: int, unidades_caja: int, responsable: str = ""):
    lotes = load_inv_lotes() or []
    seq = max(
        [int((s.get("id", "0").split("-")[-1] or "2000")) for s in lotes if s.get("id", "").split("-")[-1].isdigit()],
        default=2000,
    ) + 1
    cliid = (cliente_id or "").upper().replace("CLI-", "")
    yymmdd = fecha[2:].replace("-", "")
    lote_id = f"L-{yymmdd}-{cliid or 'GEN'}-{seq:04d}"
    lotes.append({
        "id": lote_id,
        "producto_id": prod_id,
        "cliente_id": cliente_id,
        "fecha_elaboracion": fecha,
        "fecha_caducidad": "",
        "cantidad_cajas": cajas,
        "unidades_caja": unidades_caja,
        "peso_neto": 0,
        "peso_total": 0,
        "responsable": responsable,
        "despachado": False,
        "despachado_en": "",
    })
    save_inv_lotes(lotes)
    return lote_id


# -----------------------------------------------------------------------------
# Datos: cada jornada como dict, en orden cronologico

# Convenciones:
#   piezas:    [{pieza, estado, cliente_id, unidades}]
#   empaques:  [{producto_id, cliente_id, cajas, unidades_caja}]
#   material_virgen: { pp_clarificado, pe_alta, pe_baja, pp_omo, pvc } kg
#   molido_reusado:  { mol-canula, mol-vaso, mol-piston, mol-tapon, mol-acordeon, mol-alta, mol-baja, mol-mazarota } kg
#   desechos_maquina: { mol-canula, mol-vaso, ... } kg que vuelven al bin
#   desecho_empacadora: unidades
#   tachos_armados: [{producto_id, cliente_id, tachos}]  (intermedio, no empacado)

JORNADAS: list[dict[str, Any]] = [
    # ─── Lun 20 abril — Alicia ───
    {
        "fecha": "2026-04-20",
        "responsables": ["Alicia Bone"],
        "obs": "22 cajas Life con tapon. 1 tacho armado tapon.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 13_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 3_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 4_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 8_000},
        ],
        "empaques": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "cajas": 22, "unidades_caja": 1200},
        ],
        "tachos_armados": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "tachos": 1},
        ],
        "material_virgen": {"pp_clarificado": 75, "pe_baja": 25, "pe_alta": 29},
        "desechos_maquina": {"mol-canula": 0.450, "mol-tapon": 0.130, "mol-piston": 0.490, "mol-mazarota": 0.380},
        "desecho_empacadora": 4400,
    },
    # ─── Mar 21 abril — 593 99 546 5013 ───
    {
        "fecha": "2026-04-21",
        "responsables": ["+593 99 546 5013"],
        "obs": "4 tachos armados con tapon.",
        "piezas": [
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 9_000},
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 13_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 2_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 8_000},
        ],
        "tachos_armados": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "tachos": 4},
        ],
        "material_virgen": {"pp_clarificado": 67, "pe_alta": 72, "pe_baja": 25},
        "molido_reusado": {"mol-baja": 2},
        "desechos_maquina": {"mol-canula": 0.440, "mol-tapon": 0.070, "mol-piston": 0.200, "mol-mazarota": 0.330},
    },
    # ─── Mie 22 abril — Katy ───
    {
        "fecha": "2026-04-22",
        "responsables": ["Katy"],
        "obs": "22 cajas Life con tapon. 2 tachos armados.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 17_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 13_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 3_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 14_000},
        ],
        "empaques": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "cajas": 22, "unidades_caja": 1200},
        ],
        "tachos_armados": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "tachos": 2},
        ],
        "material_virgen": {"pp_clarificado": 95, "pe_alta": 82, "pe_baja": 25},
        "molido_reusado": {"mol-alta": 12, "mol-baja": 15},
        "desechos_maquina": {"mol-canula": 0.190, "mol-piston": 0.230, "mol-tapon": 0.140, "mol-mazarota": 0.310},
        "desecho_empacadora": 4330,
    },
    # ─── Jue 23 abril — Katy (2 reportes en el dia) ───
    {
        "fecha": "2026-04-23",
        "responsables": ["Katy"],
        "obs": "12 cajas + 5 tachos Life con tapon.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 13_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 3_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 13_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 13_000},
        ],
        "empaques": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "cajas": 12, "unidades_caja": 1200},
        ],
        "tachos_armados": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "tachos": 5},
        ],
        "material_virgen": {"pp_clarificado": 38, "pe_alta": 82, "pe_baja": 25},
        "molido_reusado": {"mol-canula": 43, "mol-alta": 12},
        "desechos_maquina": {"mol-canula": 0.360, "mol-tapon": 0.080, "mol-piston": 0.340, "mol-mazarota": 0.480},
    },
    # ─── Vie 24 abril — Fernando ───
    {
        "fecha": "2026-04-24",
        "responsables": ["Fernando Pinargote"],
        "obs": "19 cajas Life. 1 tacho farbiopharma. 12 fundas impresas.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 17_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 12_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 3_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 12_000},
        ],
        "empaques": [
            {"producto_id": "j_life", "cliente_id": "cli-life", "cajas": 19, "unidades_caja": 1200},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 1},
        ],
        "material_virgen": {"pp_clarificado": 75, "pe_alta": 75, "pe_baja": 25},
        "molido_reusado": {"mol-baja": 16, "mol-canula": 20},
        "desechos_maquina": {"mol-mazarota": 0.130, "mol-canula": 0.660, "mol-tapon": 0.240, "mol-piston": 0.430},
        "desecho_empacadora": 4790,
    },
    # ─── Lun 27 abril — Fernando ───
    {
        "fecha": "2026-04-27",
        "responsables": ["Fernando Pinargote"],
        "obs": "3 cajas Alvesa. 2 tachos farbio. 8 fundas impresas.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 11_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "tapon",  "estado": "cruda", "cliente_id": None, "unidades": 2_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 8_000},
        ],
        "empaques": [
            # Alvesa - no esta en CLIENTES_MOCK; uso generico
            {"producto_id": "j_generic", "cliente_id": None, "cajas": 3, "unidades_caja": 1000},
            # V. Farmayala 7 tachos => empaque parcial vaso farma2
            {"producto_id": "v_farma2", "cliente_id": "cli-farmayala", "cajas": 7, "unidades_caja": 2000},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 2},
        ],
        "material_virgen": {"pp_clarificado": 65, "pp_omo": 11, "pe_alta": 50},
        "molido_reusado": {"mol-canula": 47, "mol-vaso": 68, "mol-tapon": 27, "mol-piston": 16},
        "desechos_maquina": {
            "mol-tapon": 0.100, "mol-canula": 0.350, "mol-vaso": 0.220,
            "mol-piston": 0.380, "mol-mazarota": 0.500,
        },
        "desecho_empacadora": 1150,
    },
    # ─── Mar 28 abril — Alicia (subio molde acordeon nuevo) ───
    {
        "fecha": "2026-04-28",
        "responsables": ["Alicia Bone"],
        "obs": "Se subio molde Acordeon nuevo. 3 cajas farbio + 5 cajas sin logo con tapon. 5 tachos farbio.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 9_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 1_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 10_000},
        ],
        "empaques": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "cajas": 3, "unidades_caja": 1000},
            {"producto_id": "v_sin_logo_tapon", "cliente_id": None, "cajas": 5, "unidades_caja": 2500},
            {"producto_id": "v_farma2", "cliente_id": "cli-farmayala", "cajas": 9, "unidades_caja": 2000},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 5},
        ],
        "material_virgen": {"pp_clarificado": 85, "pe_alta": 75, "pe_baja": 25},
        "molido_reusado": {"mol-vaso": 60},
        "desechos_maquina": {
            "mol-piston": 0.340, "mol-canula": 0.240, "mol-acordeon": 0.170,
            "mol-vaso": 0.420, "mol-mazarota": 0.790,
        },
        "desecho_empacadora": 1440,
        "cambios_molde": [{"maquina": "ML-1", "de_producto": "", "a_producto": "acordeon_nuevo"}],
    },
    # ─── Mie 29 abril — Fernando + Katy ───
    {
        "fecha": "2026-04-29",
        "responsables": ["Fernando Pinargote", "Katy"],
        "obs": "5 cajas (Fernando AM) + 12 cajas Farbio (Katy).",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 7_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 3_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 6_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 6_000},
        ],
        "empaques": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "cajas": 12, "unidades_caja": 1000},
            {"producto_id": "j_life",    "cliente_id": "cli-life", "cajas": 5,  "unidades_caja": 1200},
            {"producto_id": "v_farma2",  "cliente_id": "cli-farmayala", "cajas": 6, "unidades_caja": 2000},
        ],
        "material_virgen": {"pp_clarificado": 43, "pe_alta": 25},
        "molido_reusado": {"mol-canula": 15, "mol-piston": 15, "mol-vaso": 43, "mol-acordeon": 12},
        "desechos_maquina": {
            "mol-piston": 0.370, "mol-canula": 0.230, "mol-acordeon": 0.420, "mol-mazarota": 0.400,
        },
        "desecho_empacadora": 2010,
    },
    # ─── Lun 04 mayo — 593 ───
    {
        "fecha": "2026-05-04",
        "responsables": ["+593 99 546 5013", "Alicia Bone"],
        "obs": "4 tachos armados farbio.",
        "piezas": [
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 8_000},
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 9_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 4_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 10_000},
        ],
        "empaques": [
            {"producto_id": "v_farma2", "cliente_id": "cli-farmayala", "cajas": 7, "unidades_caja": 2000},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 4},
        ],
        "material_virgen": {"pp_clarificado": 57, "pe_alta": 75, "pe_baja": 39},
        "molido_reusado": {"mol-vaso": 51, "mol-canula": 15},
        "desechos_maquina": {
            "mol-vaso": 0.220, "mol-canula": 0.150, "mol-acordeon": 0.210,
            "mol-piston": 0.230, "mol-mazarota": 0.850,
        },
    },
    # ─── Mar 05 mayo — 593 ───
    {
        "fecha": "2026-05-05",
        "responsables": ["+593 99 546 5013", "Fernando Pinargote"],
        "obs": "19 cajas farbio. 3 tachos farbio. Recibido 20 fundas clarificado.",
        "piezas": [
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 9_000},
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 5_000},
        ],
        "empaques": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "cajas": 19, "unidades_caja": 1000},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 3},
        ],
        "material_virgen": {"pp_clarificado": 25, "pe_alta": 50, "pe_baja": 25},
        "molido_reusado": {"mol-canula": 20, "mol-acordeon": 20},
        "desechos_maquina": {
            "mol-piston": 0.380, "mol-canula": 0.390, "mol-acordeon": 0.320, "mol-mazarota": 0.320,
        },
        "desecho_empacadora": 2560,
    },
    # ─── Mie 06 mayo — Fernando + Katy ───
    {
        "fecha": "2026-05-06",
        "responsables": ["Fernando Pinargote", "Katy"],
        "obs": "45 cajas (AM Fernando). 6 tachos Farbio.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 5_000},
            {"pieza": "canula", "estado": "impresa", "cliente_id": "cli-farbiopharma", "unidades": 9_000},
        ],
        "empaques": [
            {"producto_id": "v_farma2", "cliente_id": "cli-farmayala", "cajas": 7, "unidades_caja": 2000},
            {"producto_id": "j_life",   "cliente_id": "cli-life", "cajas": 45, "unidades_caja": 1200},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 6},
        ],
        "material_virgen": {"pp_clarificado": 50, "pp_omo": 14, "pe_alta": 69, "pe_baja": 47},
        "molido_reusado": {"mol-canula": 20, "mol-vaso": 56},
        "desechos_maquina": {
            "mol-vaso": 0.160, "mol-canula": 0.230, "mol-piston": 0.210,
            "mol-acordeon": 0.200, "mol-mazarota": 0.340,
        },
    },
    # ─── Jue 07 mayo — Fernando ───
    {
        "fecha": "2026-05-07",
        "responsables": ["Fernando Pinargote"],
        "obs": "20 cajas empacadas. 10 fundas impresas.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 11_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 4_000},
        ],
        "empaques": [
            {"producto_id": "v_farma2", "cliente_id": "cli-farmayala", "cajas": 7,  "unidades_caja": 2000},
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "cajas": 20, "unidades_caja": 1000},
        ],
        "material_virgen": {"pp_clarificado": 75, "pp_omo": 11, "pe_alta": 32, "pe_baja": 14},
        "molido_reusado": {"mol-vaso": 40, "mol-piston": 23, "mol-acordeon": 20, "mol-canula": 12},
        "desechos_maquina": {
            "mol-acordeon": 0.350, "mol-piston": 0.150, "mol-vaso": 0.600,
            "mol-canula": 0.050, "mol-mazarota": 0.750,
        },
        "desecho_empacadora": 4610,
    },
    # ─── Vie 08 mayo — Fernando ───
    {
        "fecha": "2026-05-08",
        "responsables": ["Fernando Pinargote"],
        "obs": "5 tachos farbio. 8 fundas impresas.",
        "piezas": [
            {"pieza": "canula", "estado": "cruda", "cliente_id": None, "unidades": 10_000},
            {"pieza": "acordeon", "estado": "cruda", "cliente_id": None, "unidades": 5_000},
            {"pieza": "piston", "estado": "cruda", "cliente_id": None, "unidades": 9_000},
        ],
        "tachos_armados": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "tachos": 5},
        ],
        "material_virgen": {"pp_clarificado": 50, "pe_alta": 75, "pe_baja": 41},
        "molido_reusado": {"mol-canula": 20},
        "desechos_maquina": {
            "mol-canula": 0.400, "mol-acordeon": 0.330, "mol-piston": 0.240, "mol-mazarota": 0.200,
        },
    },
    # ─── Lun 11 mayo — Alicia ───
    {
        "fecha": "2026-05-11",
        "responsables": ["Alicia Bone", "Fernando Pinargote"],
        "obs": "24 cajas Farbio. Se limpio maquinas, se saco aceite.",
        "empaques": [
            {"producto_id": "j_generic", "cliente_id": "cli-farbiopharma", "cajas": 24, "unidades_caja": 1000},
        ],
        "desecho_empacadora": 3150,
    },
]


def _reset_molido_baseline():
    """Stock inicial razonable pre-WhatsApp para que el saldo final sea positivo.
    Aprox 100 kg por bin (la planta ya tenia acumulado antes del chat)."""
    baseline = {
        "mol-canula":    250.0,
        "mol-vaso":      400.0,
        "mol-piston":     80.0,
        "mol-tapon":      40.0,
        "mol-acordeon":   60.0,
        "mol-alta":       40.0,
        "mol-baja":       50.0,
        "mol-mazarota":   20.0,
    }
    save_inv_molido(baseline)
    log.info(f"molido reset a baseline: {sum(baseline.values()):.0f} kg total")


def _reset_piezas_baseline():
    """Reset piezas a 0 antes de re-ingestar (idempotencia)."""
    piezas = load_inv_piezas() or []
    for p in piezas:
        p["cantidad"] = 0
    save_inv_piezas(piezas)
    log.info(f"piezas reset a 0: {len(piezas)} bins")


def _reset_lotes_jornadas():
    """Borra lotes con fechas dentro del rango de JORNADAS para evitar duplicados."""
    fechas = {j["fecha"] for j in JORNADAS}
    lotes = load_inv_lotes() or []
    antes = len(lotes)
    lotes = [l for l in lotes if l.get("fecha_elaboracion") not in fechas]
    save_inv_lotes(lotes)
    log.info(f"lotes purgados: {antes - len(lotes)} eliminados ({len(lotes)} preservados)")


def main() -> None:
    log.info(f"Ingestando {len(JORNADAS)} jornadas del chat WhatsApp...")
    _reset_molido_baseline()
    _reset_piezas_baseline()
    _reset_lotes_jornadas()
    total_cajas_global = 0
    total_mat_global = 0.0
    for j in JORNADAS:
        fecha = j["fecha"]
        # Piezas producidas (suma al inventario)
        for p in j.get("piezas", []):
            piezas_inc(p["pieza"], p["estado"], p.get("cliente_id"), float(p["unidades"]))
        # Empaques: cada caja se vuelve lote
        for e in j.get("empaques", []):
            crear_lote(e["producto_id"], e.get("cliente_id"), fecha,
                       int(e["cajas"]), int(e.get("unidades_caja", 1000)),
                       responsable=", ".join(j.get("responsables") or []))
        # Desechos de maquina => molido bin
        for bin_id, kg in (j.get("desechos_maquina") or {}).items():
            molido_inc(bin_id, float(kg))
        # Molido reusado => descuenta del bin
        for bin_id, kg in (j.get("molido_reusado") or {}).items():
            molido_inc(bin_id, -float(kg))
        # Guardar registro_diario crudo
        total_mat = sum(float(v or 0) for v in (j.get("material_virgen") or {}).values())
        total_cajas = sum(int(e.get("cajas", 0)) for e in (j.get("empaques") or []))
        payload = {
            "id": f"reg-{fecha}",
            "fecha": fecha,
            "responsables": j.get("responsables") or [],
            "piezas": j.get("piezas") or [],
            "empaques": j.get("empaques") or [],
            "tachos_armados": j.get("tachos_armados") or [],
            "material_virgen": j.get("material_virgen") or {},
            "molido_reusado": j.get("molido_reusado") or {},
            "desechos_maquina": j.get("desechos_maquina") or {},
            "desecho_empacadora": j.get("desecho_empacadora") or 0,
            "cambios_molde": j.get("cambios_molde") or [],
            "observaciones": j.get("obs", ""),
            "total_material_kg": total_mat,
            "total_cajas": total_cajas,
            "merma_pct": 0,
            "productos": _resumir_productos(j),
        }
        save_registro_diario(fecha, payload)
        total_cajas_global += total_cajas
        total_mat_global += total_mat
        log.info(f"  {fecha}: {total_cajas} cajas, {total_mat:.1f}kg mat")
    log.info(f"Total ingestado: {total_cajas_global} cajas, {total_mat_global:.1f}kg material en {len(JORNADAS)} jornadas")


def _resumir_productos(j: dict) -> list[dict]:
    """Genera la lista 'productos' que usa el frontend para drilldown."""
    res = []
    mat_total = sum(float(v or 0) for v in (j.get("material_virgen") or {}).values())
    mol_total = sum(float(v or 0) for v in (j.get("molido_reusado") or {}).values())
    des_total = sum(float(v or 0) for v in (j.get("desechos_maquina") or {}).values())
    empaques = j.get("empaques") or []
    if not empaques:
        return res
    # distribuir material proporcionalmente a cajas (heuristica simple)
    total_cajas = sum(e["cajas"] for e in empaques) or 1
    for e in empaques:
        peso = e["cajas"] / total_cajas
        item = {
            "prod_id": e["producto_id"],
            "cajas": e["cajas"],
            "cliente_id": e.get("cliente_id"),
            "virgen": round(mat_total * peso, 1),
            "molido_usado": round(mol_total * peso, 1),
            "desecho": round(des_total * peso, 2),
            "molido_gen": round(des_total * peso * 0.85, 2),
        }
        # Subcomponentes: si es jeringa/gotero, agrupa piezas crudas del dia
        if e["producto_id"].startswith("j_") or e["producto_id"] == "gotero":
            subcomp = {}
            for p in j.get("piezas", []):
                if p["estado"] == "cruda":
                    subcomp[p["pieza"]] = subcomp.get(p["pieza"], 0) + p["unidades"]
            if subcomp:
                item["subcomp"] = subcomp
        res.append(item)
    # Tachos armados: agregar como producto intermedio
    for t in j.get("tachos_armados") or []:
        res.append({
            "prod_id": t["producto_id"],
            "cliente_id": t.get("cliente_id"),
            "tachos": t["tachos"],
            "cajas": 0,
            "virgen": 0, "molido_usado": 0, "desecho": 0, "molido_gen": 0,
        })
    return res


if __name__ == "__main__":
    main()
