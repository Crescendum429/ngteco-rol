"""Marca todos los productos / clientes / piezas / auxiliares con flag
`datos_incompletos` cuando los campos criticos no han sido verificados
por el usuario.

Conservador: si un campo viene en 0 o vacio, se marca como incompleto.
Lo que ya tiene flag se respeta (no se sobreescribe).
"""
from __future__ import annotations

import logging

from storage import (
    load_clientes, load_inv_auxiliar, load_inv_piezas,
    load_productos, save_clientes, save_inv_auxiliar,
    save_inv_piezas, save_productos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("flagear")


def flagear_productos():
    ps = load_productos() or {}
    if not isinstance(ps, dict):
        return
    cambios = 0
    for pid, p in ps.items():
        faltantes = list(p.get("datos_incompletos") or [])
        if float(p.get("peso_g") or 0) <= 0 and "peso_g" not in faltantes:
            faltantes.append("peso_g")
        if float(p.get("costo_unit") or 0) <= 0 and "costo_unit" not in faltantes:
            faltantes.append("costo_unit")
        if float(p.get("costo_caja") or 0) <= 0 and "costo_caja" not in faltantes:
            faltantes.append("costo_caja")
        if int(p.get("unidades_caja") or 0) <= 0 and "unidades_caja" not in faltantes:
            faltantes.append("unidades_caja")
        # Todos los productos del PRODUCTOS_DEFAULT tienen valores asumidos.
        # Marcamos los que no fueron explicitamente verificados (no tienen di previo).
        if not p.get("datos_incompletos") and not p.get("_verificado"):
            for campo in ("peso_g", "costo_unit", "factor_complejidad"):
                if campo not in faltantes:
                    faltantes.append(campo + "_revisar")
        if faltantes != (p.get("datos_incompletos") or []):
            p["datos_incompletos"] = faltantes
            cambios += 1
    save_productos(ps)
    log.info(f"productos: {cambios} flageados")


def flagear_clientes():
    cs = load_clientes() or []
    if not isinstance(cs, list):
        return
    cambios = 0
    for c in cs:
        if not isinstance(c, dict):
            continue
        faltantes = list(c.get("datos_incompletos") or [])
        if not (c.get("ruc") or "").strip() and "ruc" not in faltantes:
            faltantes.append("ruc")
        if not (c.get("razon_social") or "").strip() and "razon_social" not in faltantes:
            faltantes.append("razon_social")
        if not (c.get("email_fact") or "").strip() and "email_fact" not in faltantes:
            faltantes.append("email_fact")
        dm = c.get("dir_matriz") or {}
        if not (dm.get("calle") or "").strip() and "direccion" not in faltantes:
            faltantes.append("direccion")
        if faltantes != (c.get("datos_incompletos") or []):
            c["datos_incompletos"] = faltantes
            cambios += 1
    save_clientes(cs)
    log.info(f"clientes: {cambios} flageados")


def flagear_auxiliares():
    aux = load_inv_auxiliar() or []
    if not isinstance(aux, list):
        return
    cambios = 0
    for a in aux:
        if not isinstance(a, dict):
            continue
        faltantes = list(a.get("datos_incompletos") or [])
        if float(a.get("costo_unit") or 0) <= 0 and "costo_unit" not in faltantes:
            faltantes.append("costo_unit")
        if float(a.get("stock") or 0) == 0 and "stock_inicial" not in faltantes:
            faltantes.append("stock_inicial")
        if faltantes != (a.get("datos_incompletos") or []):
            a["datos_incompletos"] = faltantes
            cambios += 1
    save_inv_auxiliar(aux)
    log.info(f"auxiliares: {cambios} flageados")


def flagear_piezas():
    piezas = load_inv_piezas() or []
    if not isinstance(piezas, list):
        return
    cambios = 0
    for p in piezas:
        if not isinstance(p, dict):
            continue
        faltantes = list(p.get("datos_incompletos") or [])
        if not p.get("producto") and "producto" not in faltantes:
            faltantes.append("producto")
        if faltantes != (p.get("datos_incompletos") or []):
            p["datos_incompletos"] = faltantes
            cambios += 1
    save_inv_piezas(piezas)
    log.info(f"piezas: {cambios} flageadas")


def main() -> None:
    flagear_productos()
    flagear_clientes()
    flagear_auxiliares()
    flagear_piezas()


if __name__ == "__main__":
    main()
