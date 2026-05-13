"""Crea las alertas persistentes para las 4 OC sugeridas del chat de WhatsApp.

El usuario decide si las convierte en OC reales o las descarta.
"""
from __future__ import annotations

import logging

from storage import load_alertas_persistentes, save_alertas_persistentes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("oc-alertas")


OCS_SUGERIDAS = [
    {
        "id": "oc-sug-lamosan-30k-vasos",
        "tipo": "oc_sugerida",
        "severidad": "info",
        "titulo": "OC sugerida: Lamosan 30.000 vasos",
        "descripcion": "Pedido del 2026-04-23 (chat WhatsApp): preparar 30.000 vasos Lamosan. Falta crear OC formal.",
        "fecha_creacion": "2026-04-23",
        "destino": {"page": "pedidos"},
        "ref": "cli-lamosan",
    },
    {
        "id": "oc-sug-farbio-3k-jeringas-acordeon",
        "tipo": "oc_sugerida",
        "severidad": "info",
        "titulo": "OC sugerida: Farbiopharma 3.000 jeringas con acordeón nuevo",
        "descripcion": "Pedido del 2026-04-24 (chat): 3.000 jeringas con acordeón nuevo armadas para el lunes. Falta crear OC.",
        "fecha_creacion": "2026-04-24",
        "destino": {"page": "pedidos"},
        "ref": "cli-farbiopharma",
    },
    {
        "id": "oc-sug-ariston-45k-cucharitas",
        "tipo": "oc_sugerida",
        "severidad": "warn",
        "titulo": "OC sugerida: Química Ariston 45.000 cucharitas — entrega 2026-05-15",
        "descripcion": "Pedido del 2026-05-08 (chat): 45.000 cucharitas para el 15 de mayo. Plazo corto.",
        "fecha_creacion": "2026-05-08",
        "destino": {"page": "pedidos"},
        "ref": "cli-quimica-ariston",
    },
    {
        "id": "oc-sug-farbio-85k-jeringas",
        "tipo": "oc_sugerida",
        "severidad": "warn",
        "titulo": "OC sugerida: Farbiopharma 85.000 jeringas",
        "descripcion": "Pedido del 2026-05-11 (chat): 85.000 jeringas con todas las fechas de fabricación, entrega 2026-05-12.",
        "fecha_creacion": "2026-05-11",
        "destino": {"page": "pedidos"},
        "ref": "cli-farbiopharma",
    },
]


def main() -> None:
    existentes = load_alertas_persistentes() or []
    ids_existentes = {a.get("id") for a in existentes if isinstance(a, dict)}
    nuevas = [a for a in OCS_SUGERIDAS if a["id"] not in ids_existentes]
    if nuevas:
        save_alertas_persistentes(list(existentes) + nuevas)
    log.info(f"OC alertas: {len(nuevas)} nuevas, {len(existentes)} preservadas")


if __name__ == "__main__":
    main()
