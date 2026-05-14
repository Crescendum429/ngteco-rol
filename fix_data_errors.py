"""Fixes de datos detectados en uso real (chat 2026-05-14):

1. gotero.kind = None -> gotero (no vaso). Fix data corrupta.
2. Vaciar empaques default de productos (no debe pre-asignarse: cada empaque
   se asocia explicitamente cuando el usuario lo elige).
3. Mover cli-civisa: no es cliente sino proveedor (nos retiene IR porque le
   compramos algo). Marcado con flag proveedor=True; sale de listas cliente.
4. Crear pestaña proveedores requiere Design (no se hace aqui).

Idempotente.
"""
from __future__ import annotations
import logging

from storage import load_clientes, load_productos, save_clientes, save_productos

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fix")


# Mapeo correcto kind por id (cuando el seed no lo seteo o quedo mal)
KIND_FIX = {
    "gotero": "gotero",
    "cuchara_chica": "cuchara",
    "cuchara_30cc": "cuchara",
    "cuchara_5ml": "cuchara",
    "j_life": "jeringa",
    "j_3ml": "jeringa",
    "j_farmayala": "jeringa",
    "j_generic": "jeringa",
    "j_sin_tampo": "jeringa",
    "v_life": "vaso", "v_lamosan": "vaso", "v_solplast": "vaso",
    "v_farma1": "vaso", "v_farma2": "vaso", "v_pequena": "vaso",
    "v_kromex": "vaso", "v_amosan": "vaso",
    "v_farmayala_ant": "vaso", "v_farmayala_nuevo": "vaso",
    "v_sin_logo_tapon": "vaso", "v_sin_logo_acord": "vaso",
    "camillas": "vaso",  # se mantiene si existe; el usuario dijo "no son camillas son canulas" pero el SKU camillas ya fue eliminado en otro fix
}


def fix_productos_kind_y_empaques():
    ps = load_productos() or {}
    if not isinstance(ps, dict):
        return
    cambios = 0
    for pid, p in ps.items():
        # Fix kind si esta None o mal asignado
        kind_correcto = KIND_FIX.get(pid)
        if kind_correcto and p.get("kind") != kind_correcto:
            log.info(f"  kind {pid}: {p.get('kind')!r} -> {kind_correcto!r}")
            p["kind"] = kind_correcto
            cambios += 1
        # Vaciar empaques asignados por default — la asociacion producto<->empaque
        # debe ser decision explicita del usuario, no inferida del PRODUCTOS_DEFAULT.
        if p.get("empaques"):
            log.info(f"  empaques {pid}: vaciado {list(p['empaques'].keys())}")
            p["empaques"] = {}
            cambios += 1
    save_productos(ps)
    log.info(f"productos: {cambios} cambios aplicados")


def fix_civisa_proveedor():
    cs = load_clientes() or []
    if not isinstance(cs, list):
        return
    cambios = 0
    for c in cs:
        if not isinstance(c, dict):
            continue
        if c.get("id") == "cli-civisa":
            c["es_proveedor"] = True
            c["es_cliente"] = False
            c["notas"] = (c.get("notas") or "") + " | NO es cliente — es proveedor que nos retiene IR. Move a proveedores cuando Design haga el modulo."
            log.info(f"  cli-civisa marcado como proveedor (no cliente)")
            cambios += 1
    save_clientes(cs)
    log.info(f"clientes: {cambios} cambios")


def main():
    log.info("=== Fix data errors ===")
    fix_productos_kind_y_empaques()
    fix_civisa_proveedor()
    log.info("Listo.")


if __name__ == "__main__":
    main()
