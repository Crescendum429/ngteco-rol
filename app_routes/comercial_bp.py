"""Blueprint de endpoints comerciales: clientes, cotizaciones, OCs, facturas, guias,
certificados, emisor, inventario MP/PT legacy, movimientos, beneficios recurrentes."""
from flask import Blueprint, jsonify, request

from app_routes._auth import require_auth
from logger import get_logger
from storage import (
    load_beneficios_recurrentes,
    load_certificados,
    load_clientes,
    load_cotizaciones,
    load_emisor,
    load_facturas,
    load_guias,
    load_inventario_mp,
    load_inventario_pt,
    load_movimientos_inventario,
    load_ordenes_compra,
    save_beneficios_recurrentes,
    save_certificados,
    save_clientes,
    save_cotizaciones,
    save_emisor,
    save_facturas,
    save_guias,
    save_inventario_mp,
    save_inventario_pt,
    save_movimientos_inventario,
    save_ordenes_compra,
)

log = get_logger("comercial")

comercial_bp = Blueprint("comercial", __name__)

# Mapeo coleccion -> (loader, saver). Centraliza endpoints CRUD genericos.
COLLECTION_MAP = {
    "clientes": (load_clientes, save_clientes),
    "cotizaciones": (load_cotizaciones, save_cotizaciones),
    "ordenes_compra": (load_ordenes_compra, save_ordenes_compra),
    "facturas": (load_facturas, save_facturas),
    "guias": (load_guias, save_guias),
    "certificados": (load_certificados, save_certificados),
    "emisor": (load_emisor, save_emisor),
    "inventario_mp": (load_inventario_mp, save_inventario_mp),
    "inventario_pt": (load_inventario_pt, save_inventario_pt),
    "movimientos_inventario": (load_movimientos_inventario, save_movimientos_inventario),
    "beneficios_recurrentes": (load_beneficios_recurrentes, save_beneficios_recurrentes),
}


@comercial_bp.route("/api/collection/<kind>", methods=["GET"])
@require_auth
def get_collection(kind):
    if kind not in COLLECTION_MAP:
        return jsonify({"error": "Coleccion desconocida"}), 404
    data = COLLECTION_MAP[kind][0]()
    return jsonify(data if data is not None else [])


@comercial_bp.route("/api/collection/<kind>", methods=["PUT"])
@require_auth
def put_collection(kind):
    if kind not in COLLECTION_MAP:
        return jsonify({"error": "Coleccion desconocida"}), 404
    data = request.get_json(force=True)
    COLLECTION_MAP[kind][1](data)
    log.info(f"collection {kind}: actualizada ({len(data) if isinstance(data, list) else 'dict'} items)")
    return jsonify({"ok": True})


@comercial_bp.route("/api/collection/<kind>/<item_id>", methods=["DELETE"])
@require_auth
def delete_collection_item(kind, item_id):
    """Elimina un item de una coleccion list-based. La coleccion debe tener objetos con 'id'."""
    if kind not in COLLECTION_MAP:
        return jsonify({"error": "Coleccion desconocida"}), 404
    loader, saver = COLLECTION_MAP[kind]
    data = loader() or []
    if not isinstance(data, list):
        return jsonify({"error": "Coleccion no es lista"}), 400
    nuevo = [x for x in data if isinstance(x, dict) and x.get("id") != item_id]
    if len(nuevo) == len(data):
        return jsonify({"error": "Item no encontrado"}), 404
    saver(nuevo)
    log.info(f"collection {kind}: eliminado {item_id} ({len(nuevo)} restantes)")
    return jsonify({"ok": True})


@comercial_bp.route("/api/nomina/recurrentes/<emp_id>", methods=["PUT"])
@require_auth
def put_recurrentes(emp_id):
    """Reemplaza las reglas recurrentes de un empleado (preserva las de otros)."""
    data = request.get_json(force=True) or {}
    rules = data.get("rules") or []
    all_rules = load_beneficios_recurrentes() or []
    kept = [r for r in all_rules if r.get("empleado_id") != emp_id]
    for r in rules:
        r["empleado_id"] = emp_id
    save_beneficios_recurrentes(kept + rules)
    log.info(f"recurrentes {emp_id}: {len(rules)} reglas")
    return jsonify({"ok": True})
