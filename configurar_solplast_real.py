"""Configura el sistema con los datos reales de Solplast obtenidos del
contador (chat WhatsApp + PDFs de facturacion).

- Emisor: datos fiscales reales tal como aparecen en facturas vigentes.
- Establecimiento 002, punto emision 001. Secuenciales:
  factura=34, guia=34, nota_credito=14, retencion=37 (proximos: 35, 35, 15, 38).
- Clientes nuevos: Alvesa SCC, Qualipharm S.A., Civisa.
- Solplast SI es agente de retencion.
- IVA: producto Vaso Life para cliente Lamosan = 15%, resto = 0%.

Idempotente.
"""
from __future__ import annotations
import logging

from storage import (
    load_clientes, load_emisor, load_productos,
    save_clientes, save_emisor, save_productos, setear_secuencial_inicial,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("config")


EMISOR_REAL = {
    "razon_social": "AGUIRRE ESPIN MARICELA JAZMINA",
    "nombre_comercial": "SOLPLAST",
    "ruc": "1802698413001",
    "obligado_contabilidad": True,
    "agente_retencion": "Resolución No. 1",
    "dir_matriz": {
        "barrio": "LAS RETAMAS",
        "calle": "DE LAS MAGNOLIAS",
        "numero": "S9-129",
        "interseccion": "DE LAS BUGANVILLAS",
        "ciudad": "Quito",
        "referencia": "Alangasi",
    },
    "dir_sucursal": {
        "barrio": "LAS RETAMAS",
        "calle": "DE LAS MAGNOLIAS",
        "numero": "S9-129",
        "interseccion": "DE LAS BUGANVILLAS",
        "ciudad": "Quito",
        "referencia": "Alangasi",
    },
    "telefono": "022 796-189",
    "movil": "087 558021 / 098 836869",
    "email": "ventas@solplastuio.com",
    "pais_origen": "Ecuador",
    "responsable_calidad": "Alicia Bone",
    "revisor_calidad": "Fernando Pinargote",
    "establecimiento_default": "002",
    "punto_emision_default": "001",
}


CLIENTES_NUEVOS = [
    {
        "id": "cli-alvesa",
        "razon_social": "ALVESA S.C.C.",
        "nombre_comercial": "Alvesa",
        "ruc": "1791813685001",
        "tipo": "Sociedad",
        "obligado_contabilidad": True,
        "email_fact": "edyroberto75@yahoo.com",
        "telefono": "023790872",
        "dir_matriz": {"calle": "Vía Quinindé Km 2,3", "numero": "", "interseccion": "",
                        "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Vía Quinindé Km 2,3", "numero": "", "interseccion": "",
                          "ciudad": "Quito", "referencia": "Punto de entrega"},
        "credito_dias": 30, "credito_limite": 0,
        "agente_retencion": False,
        "notas": "Cliente activo. Facturas y guias bajo serie 002-001.",
    },
    {
        "id": "cli-qualipharm",
        "razon_social": "QUALIPHARM LABORATORIO FARMACEUTICO S.A.",
        "nombre_comercial": "Qualipharm",
        "ruc": "1792161886001",
        "tipo": "Sociedad",
        "obligado_contabilidad": True,
        "email_fact": "compras@qualipharmlab.com",
        "telefono": "022494733",
        "dir_matriz": {"calle": "Av. Manuel Cordova Galarza", "numero": "OE4-175",
                        "interseccion": "Esperanza", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. Manuel Cordova Galarza", "numero": "OE4-175",
                          "interseccion": "Esperanza", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 30, "credito_limite": 0,
        "agente_retencion": True,
        "resolucion_retencion": "",
        "notas": "Cliente con devoluciones registradas (nota credito 014 abril 2024).",
    },
    {
        "id": "cli-civisa",
        "razon_social": "MATERIALES PARA LA INDUSTRIA CIVISA S.C.C.",
        "nombre_comercial": "Civisa",
        "ruc": "1791782143001",
        "tipo": "Sociedad",
        "obligado_contabilidad": True,
        "email_fact": "civisascc@gmail.com",
        "telefono": "022082010",
        "dir_matriz": {"calle": "Av. Abdón Calderón", "numero": "8-24",
                        "interseccion": "Calle Quito", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. Abdón Calderón", "numero": "8-24",
                          "interseccion": "Calle Quito", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 30, "credito_limite": 0,
        "agente_retencion": True,
        "notas": "Cliente que nos retiene IR 1% (comprobante de retencion 037).",
    },
]


def aplicar_emisor():
    save_emisor(EMISOR_REAL)
    log.info("emisor actualizado con datos reales")


def aplicar_clientes():
    existentes = load_clientes() or []
    if not isinstance(existentes, list):
        existentes = []
    by_id = {c.get("id"): c for c in existentes if isinstance(c, dict)}
    cambios = 0
    for nuevo in CLIENTES_NUEVOS:
        if nuevo["id"] in by_id:
            # Update con datos del PDF si los anteriores eran placeholder
            existente = by_id[nuevo["id"]]
            if not existente.get("ruc") or existente.get("ruc") != nuevo["ruc"]:
                existente.update(nuevo)
                cambios += 1
        else:
            existentes.append(nuevo)
            cambios += 1
    save_clientes(existentes)
    log.info(f"clientes: {cambios} actualizados/agregados ({len(existentes)} total)")


def aplicar_secuenciales():
    """Secuenciales actuales segun PDFs. El proximo emitido seria +1."""
    setear_secuencial_inicial("01", "002", "001", 34)   # ultima factura 34
    setear_secuencial_inicial("04", "002", "001", 14)   # ultima nota credito 14
    setear_secuencial_inicial("06", "002", "001", 34)   # ultima guia 34
    setear_secuencial_inicial("07", "002", "001", 37)   # ultima retencion recibida 37
    log.info("secuenciales seteados: factura=34, nota_credito=14, guia=34, retencion=37 (estab 002, pto 001)")


def aplicar_iva_productos():
    """Setea IVA 0% en todos los productos excepto Vaso Life (que se vende
    a Lamosan con 15%). Esto sigue la regla del contador."""
    ps = load_productos() or {}
    if not isinstance(ps, dict):
        return
    cambios = 0
    for pid, p in ps.items():
        if pid == "v_life":
            # Vaso Life para Lamosan grava 15%
            if p.get("iva_pct") != 15:
                p["iva_pct"] = 15
                cambios += 1
        else:
            # Todos los demas son 0% por regla general
            if p.get("iva_pct") not in (0, None):
                p["iva_pct"] = 0
                cambios += 1
            elif p.get("iva_pct") is None:
                p["iva_pct"] = 0
                cambios += 1
    save_productos(ps)
    log.info(f"IVA aplicado: {cambios} productos actualizados. v_life=15%, resto=0%.")


def main():
    log.info("=== Configurando datos reales de Solplast ===")
    aplicar_emisor()
    aplicar_clientes()
    aplicar_secuenciales()
    aplicar_iva_productos()
    log.info("Listo.")


if __name__ == "__main__":
    main()
