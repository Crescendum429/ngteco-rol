"""Agrega clientes nuevos detectados en el chat de WhatsApp.

Quimica Ariston: datos verificados via web search (SRI/Paginas Amarillas/LinkedIn).
Alvesa: no se encontro registro publico, queda con placeholders para que el
usuario complete manualmente.
"""
from __future__ import annotations

import logging

from storage import load_clientes, save_clientes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("clientes")


CLIENTES_NUEVOS = [
    # Originales del mock (cargados a BD para persistencia)
    {
        "id": "cli-farbiopharma",
        "razon_social": "FARBIOPHARMA S.A.", "nombre_comercial": "Farbiopharma",
        "ruc": "1791773373001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "contabildad@farbiopharma.com", "email_contacto": "compras@farbiopharma.com",
        "telefono": "02-2555-444", "celular": "099-1234567",
        "contacto_nombre": "Ing. Paola Romero", "contacto_cargo": "Jefa de Compras",
        "dir_matriz":   {"calle": "Guayas", "numero": "E3 296", "interseccion": "Pichincha", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Guayas", "numero": "E3 296", "interseccion": "Pichincha", "ciudad": "Quito", "referencia": "Bodega planta baja"},
        "credito_dias": 30, "credito_limite": 25000,
        "agente_retencion": False, "resolucion_retencion": "",
        "notas": "Cliente frecuente. Pedidos recurrentes de jeringas dosificadoras.",
    },
    {
        "id": "cli-farmayala",
        "razon_social": "Farmayala Pharmaceutical Company S.A.", "nombre_comercial": "Farmayala",
        "ruc": "1792438576001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "facturacion@farmayala.com.ec", "email_contacto": "compras@farmayala.com.ec",
        "telefono": "02-2445-678", "celular": "099-2233445",
        "contacto_nombre": "Ec. Luis Morales", "contacto_cargo": "Gerente de Abastecimiento",
        "dir_matriz":   {"calle": "Av. Eloy Alfaro", "numero": "N34-551", "interseccion": "Portugal", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. Eloy Alfaro", "numero": "N34-551", "interseccion": "Portugal", "ciudad": "Quito", "referencia": "Bodega posterior, horario 8am-4pm"},
        "credito_dias": 30, "credito_limite": 40000,
        "agente_retencion": True, "resolucion_retencion": "Res. SRI 2024-001",
        "notas": "Exige certificado de calidad firmado en cada entrega.",
    },
    {
        "id": "cli-life",
        "razon_social": "Laboratorios Life C.A.", "nombre_comercial": "Life",
        "ruc": "1790012393001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "facturacion@life.com.ec", "email_contacto": "abastecimiento@life.com.ec",
        "telefono": "02-2461-111", "celular": "",
        "contacto_nombre": "Ing. Carla Benitez", "contacto_cargo": "Coordinadora de Compras",
        "dir_matriz":   {"calle": "Av. 10 de Agosto", "numero": "N50-123", "interseccion": "El Inca", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. 10 de Agosto", "numero": "N50-123", "interseccion": "El Inca", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 45, "credito_limite": 60000,
        "agente_retencion": True, "resolucion_retencion": "Res. SRI 2023-047",
        "notas": "",
    },
    {
        "id": "cli-lamosan",
        "razon_social": "Laboratorios Lamosan CIA. LTDA.", "nombre_comercial": "Lamosan",
        "ruc": "0990057128001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "contabilidad@lamosan.com", "email_contacto": "compras@lamosan.com",
        "telefono": "04-2288-432", "celular": "098-8812345",
        "contacto_nombre": "Sra. Martha Cedeno", "contacto_cargo": "Compras",
        "dir_matriz":   {"calle": "Av. Francisco de Orellana", "numero": "204", "interseccion": "Kennedy Norte", "ciudad": "Guayaquil", "referencia": ""},
        "dir_sucursal": {"calle": "Av. Francisco de Orellana", "numero": "204", "interseccion": "Kennedy Norte", "ciudad": "Guayaquil", "referencia": ""},
        "credito_dias": 30, "credito_limite": 20000,
        "agente_retencion": False, "resolucion_retencion": "",
        "notas": "Pedidos trimestrales. Solicita muestra antes de cada lote nuevo.",
    },
    {
        "id": "cli-solgen",
        "razon_social": "Solgen Distribuidora S.A.", "nombre_comercial": "Solgen",
        "ruc": "1793167432001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "facturacion@solgen.ec", "email_contacto": "info@solgen.ec",
        "telefono": "02-3983-211", "celular": "",
        "contacto_nombre": "Sr. Jorge Paredes", "contacto_cargo": "Gerente",
        "dir_matriz":   {"calle": "Av. Eloy Alfaro", "numero": "N50-118", "interseccion": "Carcelen Industrial", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. Eloy Alfaro", "numero": "N50-118", "interseccion": "Carcelen Industrial", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 15, "credito_limite": 8000,
        "agente_retencion": False, "resolucion_retencion": "",
        "notas": "",
    },
    {
        "id": "cli-kronos",
        "razon_social": "Laboratorios Kronos S.A.", "nombre_comercial": "Kronos",
        "ruc": "1790345678001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "facturacion@kronos.com.ec", "email_contacto": "compras@kronos.com.ec",
        "telefono": "02-2456-789", "celular": "099-8877665",
        "contacto_nombre": "Sr. Alejandro Mercado", "contacto_cargo": "Desarrollo de Proveedores",
        "dir_matriz":   {"calle": "Av. 6 de Diciembre", "numero": "N34-556", "interseccion": "Gaspar de Villarroel", "ciudad": "Quito", "referencia": ""},
        "dir_sucursal": {"calle": "Av. 6 de Diciembre", "numero": "N34-556", "interseccion": "Gaspar de Villarroel", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 45, "credito_limite": 30000,
        "agente_retencion": True, "resolucion_retencion": "Res. SRI 2024-015",
        "notas": "Cliente nuevo.",
    },
    {
        "id": "cli-farmacorp",
        "razon_social": "Farmacorp Ecuador S.A.", "nombre_comercial": "Farmacorp",
        "ruc": "1790765432001", "tipo": "Sociedad", "obligado_contabilidad": True,
        "email_fact": "facturacion@farmacorp.ec", "email_contacto": "compras@farmacorp.ec",
        "telefono": "02-2445-999", "celular": "",
        "contacto_nombre": "Dra. Silvia Rueda", "contacto_cargo": "Procurement",
        "dir_matriz":   {"calle": "Av. Naciones Unidas", "numero": "N36-99", "interseccion": "Corea", "ciudad": "Quito", "referencia": "Edificio Metropolitan, piso 5"},
        "dir_sucursal": {"calle": "Av. Naciones Unidas", "numero": "N36-99", "interseccion": "Corea", "ciudad": "Quito", "referencia": ""},
        "credito_dias": 30, "credito_limite": 35000,
        "agente_retencion": True, "resolucion_retencion": "Res. SRI 2023-089",
        "notas": "",
    },
    # Nuevos detectados en el chat
    {
        "id": "cli-quimica-ariston",
        "razon_social": "QUIMICA ARISTON ECUADOR CIA. LTDA.",
        "nombre_comercial": "Quimica Ariston",
        "ruc": "1790074889001",
        "tipo": "Sociedad",
        "obligado_contabilidad": True,
        "email_fact": "",
        "email_contacto": "",
        "telefono": "02-2470817",
        "celular": "",
        "contacto_nombre": "",
        "contacto_cargo": "",
        "dir_matriz": {
            "calle": "Panamericana Norte Km 6 1/2",
            "numero": "",
            "interseccion": "Joaquin Mancheno y Francisco Garcia",
            "ciudad": "Quito",
            "referencia": "Parroquia Cotocollao, Pichincha",
        },
        "dir_sucursal": {
            "calle": "Panamericana Norte Km 6 1/2",
            "numero": "",
            "interseccion": "Joaquin Mancheno y Francisco Garcia",
            "ciudad": "Quito",
            "referencia": "",
        },
        "credito_dias": 30,
        "credito_limite": 0,
        "agente_retencion": False,
        "resolucion_retencion": "",
        "notas": "Laboratorio farmaceutico desde 1972. Pedido 45.000 cucharitas (chat 2026-05-08).",
    },
    {
        "id": "cli-alvesa",
        "razon_social": "",
        "nombre_comercial": "Alvesa",
        "ruc": "",
        "tipo": "Sociedad",
        "obligado_contabilidad": True,
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
        "notas": "Datos pendientes — agregar manualmente. Cliente detectado en chat 2026-04-27 (3 cajas).",
    },
]


def main() -> None:
    existentes = load_clientes() or []
    if not isinstance(existentes, list):
        existentes = []
    ids_existentes = {c.get("id") for c in existentes if isinstance(c, dict)}
    nuevos = [c for c in CLIENTES_NUEVOS if c["id"] not in ids_existentes]
    if nuevos:
        merged = list(existentes) + nuevos
        save_clientes(merged)
    log.info(f"clientes: {len(nuevos)} nuevos, {len(existentes)} preservados")
    for c in nuevos:
        log.info(f"  + {c['id']} — {c['nombre_comercial']}")


if __name__ == "__main__":
    main()
