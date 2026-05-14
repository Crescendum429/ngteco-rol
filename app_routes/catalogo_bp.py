"""Blueprint de catalogo: empleados, materiales, productos, empaques, gastos fijos,
y endpoints de desactivar para cada tipo."""
from flask import Blueprint, jsonify, request

import audit
from app_helpers import emp_to_js, empaque_to_js, mat_to_js, prod_to_js
from app_routes._auth import require_auth
from logger import get_logger
from procesar_rol import normalize
from storage import (
    load_empaques,
    load_empleados,
    load_gastos_fijos,
    load_materiales,
    load_productos,
    save_empaques,
    save_empleados,
    save_gastos_fijos,
    save_materiales,
    save_productos,
)

log = get_logger("catalogo")

catalogo_bp = Blueprint("catalogo", __name__)


# ─── Empleados ───

@catalogo_bp.route("/api/empleados", methods=["GET"])
@require_auth
def get_empleados():
    emp_db = load_empleados()
    return jsonify([emp_to_js(k, v, i) for i, (k, v) in enumerate(emp_db.items())])


@catalogo_bp.route("/api/empleados", methods=["POST"])
@require_auth
def create_empleado():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    emp_db = load_empleados()
    key = normalize(nombre)
    emp_db[key] = {
        "nombre": nombre,
        "cargo": data.get("cargo", ""),
        "salario": float(data.get("salario", 0)),
        "horas_base": int(data.get("horas_base", 8)),
        "transporte_dia": float(data.get("transporte", 0)),
        "transporte_gravable": bool(data.get("transporte_gravable", True)),
        "region": data.get("region", "Sierra/Amazonia"),
        "fondos_reserva": bool(data.get("fondos_reserva", False)),
        "prestamo_iess": float(data.get("prestamo_iess", 0)),
        "descuento_iess": bool(data.get("descuento_iess", True)),
        "fecha_ingreso": data.get("fecha_ingreso", "") or "",
        "ocultar": False,
    }
    save_empleados(emp_db)
    audit.record("empleado", "create", key, before=None, after=emp_db[key])
    log.info(f"empleado creado: {key}")
    return jsonify({"id": key})


@catalogo_bp.route("/api/empleados/<emp_id>", methods=["PUT"])
@require_auth
def update_empleado(emp_id):
    data = request.get_json(force=True) or {}
    emp_db = load_empleados()
    if emp_id not in emp_db:
        return jsonify({"error": "No encontrado"}), 404
    emp = emp_db[emp_id]
    before = dict(emp)  # snapshot del estado anterior
    emp["nombre"] = data.get("nombre", emp.get("nombre", ""))
    emp["cargo"] = data.get("cargo", emp.get("cargo", ""))
    emp["salario"] = float(data.get("salario", emp.get("salario", 0)))
    emp["horas_base"] = int(data.get("horas_base", emp.get("horas_base", 8)))
    emp["transporte_dia"] = float(data.get("transporte", emp.get("transporte_dia", 0)))
    emp["transporte_gravable"] = bool(data.get("transporte_gravable", emp.get("transporte_gravable", True)))
    emp["region"] = data.get("region", emp.get("region", "Sierra/Amazonia"))
    emp["fondos_reserva"] = bool(data.get("fondos_reserva", emp.get("fondos_reserva", False)))
    emp["prestamo_iess"] = float(data.get("prestamo_iess", emp.get("prestamo_iess", 0)))
    emp["descuento_iess"] = bool(data.get("descuento_iess", emp.get("descuento_iess", True)))
    emp["fecha_ingreso"] = data.get("fecha_ingreso", emp.get("fecha_ingreso", ""))
    # Roles operativos: flags opcionales que determinan que acciones puede hacer.
    for flag in ("responsable_calidad", "revisor_calidad",
                 "puede_aprobar_despacho", "puede_emitir_factura"):
        if flag in data:
            emp[flag] = bool(data[flag])
    save_empleados(emp_db)
    audit.record("empleado", "update", emp_id, before=before, after=dict(emp))
    return jsonify({"ok": True})


@catalogo_bp.route("/api/empleados/<emp_id>", methods=["DELETE"])
@require_auth
def delete_empleado(emp_id):
    emp_db = load_empleados()
    if emp_id not in emp_db:
        return jsonify({"error": "No encontrado"}), 404
    before = dict(emp_db[emp_id])
    del emp_db[emp_id]
    save_empleados(emp_db)
    audit.record("empleado", "delete", emp_id, before=before, after=None)
    log.info(f"empleado eliminado: {emp_id}")
    return jsonify({"ok": True})


# ─── Materiales ───

@catalogo_bp.route("/api/materiales", methods=["GET"])
@require_auth
def get_materiales():
    return jsonify([mat_to_js(k, v) for k, v in load_materiales().items()])


@catalogo_bp.route("/api/materiales/<mat_id>", methods=["PUT"])
@require_auth
def update_material(mat_id):
    data = request.get_json(force=True) or {}
    mats = load_materiales()
    if mat_id not in mats:
        mats[mat_id] = {}
    mats[mat_id].update({
        "nombre": data.get("nombre", mats[mat_id].get("nombre", mat_id)),
        "costo_kg": float(data.get("costo_kg", mats[mat_id].get("costo_kg", 0))),
        "merma_pct": float(data.get("merma", mats[mat_id].get("merma_pct", 3.0))),
    })
    save_materiales(mats)
    audit.record("material", "update", mat_id, before=None, after=dict(mats[mat_id]))
    return jsonify({"ok": True})


@catalogo_bp.route("/api/materiales/<mat_id>/desactivar", methods=["POST"])
@require_auth
def toggle_material_desactivado(mat_id):
    data = request.get_json(force=True) or {}
    mats = load_materiales()
    if mat_id not in mats:
        return jsonify({"error": "No encontrado"}), 404
    nuevo = bool(data.get("desactivado", True))
    mats[mat_id]["desactivado"] = nuevo
    save_materiales(mats)
    audit.record("material", "desactivar" if nuevo else "reactivar", mat_id)
    return jsonify({"ok": True})


# ─── Productos ───

@catalogo_bp.route("/api/productos", methods=["GET"])
@require_auth
def get_productos():
    return jsonify([prod_to_js(k, v) for k, v in load_productos().items()])


@catalogo_bp.route("/api/productos/<prod_id>", methods=["PUT"])
@require_auth
def update_producto(prod_id):
    data = request.get_json(force=True) or {}
    prods = load_productos()
    if prod_id not in prods:
        prods[prod_id] = {}
    p = prods[prod_id]
    p["nombre"] = data.get("nombre", p.get("nombre", prod_id))
    p["kind"] = data.get("kind", p.get("kind", "vaso"))
    p["unidades_caja"] = int(data.get("unidades_caja", p.get("unidades_caja", 1000)))
    p["peso_g"] = float(data.get("peso_g", p.get("peso_g", 0)))
    p["factor_complejidad"] = float(data.get("factor", p.get("factor_complejidad", 1.0)))
    # IVA por producto (Decreto 198/2024: tarifa general 15%). Validamos a
    # valores admitidos por el SRI.
    if "iva_pct" in data:
        iva = float(data["iva_pct"])
        if iva not in (0, 5, 15):
            return jsonify({"error": f"IVA invalido: {iva}. Permitidos: 0, 5, 15"}), 400
        p["iva_pct"] = iva
    save_productos(prods)
    audit.record("producto", "update", prod_id, before=None, after=dict(p))
    return jsonify({"ok": True})


@catalogo_bp.route("/api/productos", methods=["POST"])
@require_auth
def create_producto():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    prods = load_productos()
    key = normalize(nombre).replace(' ', '_')
    prods[key] = {
        "nombre": nombre,
        "kind": data.get("kind", "vaso"),
        "unidades_caja": int(data.get("unidades_caja", 1000)),
        "peso_g": float(data.get("peso_g", 0)),
        "factor_complejidad": float(data.get("factor", 1.0)),
    }
    save_productos(prods)
    audit.record("producto", "create", key, before=None, after=dict(prods[key]))
    log.info(f"producto creado: {key}")
    return jsonify({"id": key})


@catalogo_bp.route("/api/productos/<prod_id>/desactivar", methods=["POST"])
@require_auth
def toggle_producto_desactivado(prod_id):
    data = request.get_json(force=True) or {}
    prods = load_productos()
    if prod_id not in prods:
        return jsonify({"error": "No encontrado"}), 404
    nuevo = bool(data.get("desactivado", True))
    prods[prod_id]["desactivado"] = nuevo
    save_productos(prods)
    audit.record("producto", "desactivar" if nuevo else "reactivar", prod_id)
    return jsonify({"ok": True})


@catalogo_bp.route("/api/productos/<prod_id>", methods=["DELETE"])
@require_auth
def delete_producto(prod_id):
    """Elimina permanentemente un producto. Bloqueado si tiene lotes en stock,
    movimientos historicos o aparece en facturas/OC. Para esos casos, desactivar."""
    from storage import load_facturas, load_inv_lotes, load_movimientos_inventario, load_ordenes_compra
    prods = load_productos()
    if prod_id not in prods:
        return jsonify({"error": "No encontrado"}), 404

    # Validacion: lotes no despachados
    lotes = load_inv_lotes() or []
    lotes_activos = [l for l in lotes if isinstance(l, dict)
                     and l.get("producto_id") == prod_id and not l.get("despachado")]
    if lotes_activos:
        return jsonify({"error": f"Tiene {len(lotes_activos)} lotes activos. Despachalos o desactiva el producto."}), 409

    # Validacion: aparece en facturas
    facs = load_facturas() or []
    en_facturas = [f for f in facs if isinstance(f, dict)
                   and any(it.get("prod_id") == prod_id for it in (f.get("items") or []))]
    if en_facturas:
        return jsonify({"error": f"Aparece en {len(en_facturas)} facturas. Solo puedes desactivarlo (no eliminar) por integridad legal."}), 409

    # Validacion: aparece en OC pendientes
    ocs = load_ordenes_compra() or []
    en_ocs = [o for o in ocs if isinstance(o, dict)
              and o.get("estado") not in ("entregada", "cancelada")
              and any(it.get("prod_id") == prod_id for it in (o.get("items") or []))]
    if en_ocs:
        return jsonify({"error": f"Aparece en {len(en_ocs)} OCs activas. Cancelalas o desactiva el producto."}), 409

    before = dict(prods[prod_id])
    del prods[prod_id]
    save_productos(prods)
    audit.record("producto", "delete", prod_id, before=before, after=None)
    log.info(f"producto eliminado: {prod_id}")
    return jsonify({"ok": True})


# ─── Empaques ───

@catalogo_bp.route("/api/empaques", methods=["GET"])
@require_auth
def get_empaques():
    return jsonify([empaque_to_js(k, v) for k, v in load_empaques().items()])


@catalogo_bp.route("/api/empaques/<emp_id>", methods=["PUT"])
@require_auth
def update_empaque(emp_id):
    data = request.get_json(force=True) or {}
    empaques = load_empaques()
    if emp_id not in empaques:
        empaques[emp_id] = {}
    empaques[emp_id].update({
        "nombre": data.get("nombre", empaques[emp_id].get("nombre", emp_id)),
        "costo": float(data.get("costo", empaques[emp_id].get("costo", 0))),
        "unidad": data.get("unidad", empaques[emp_id].get("unidad", "unidad")),
    })
    save_empaques(empaques)
    audit.record("empaque", "update", emp_id, before=None, after=dict(empaques[emp_id]))
    return jsonify({"ok": True})


@catalogo_bp.route("/api/empaques/<emp_id>/desactivar", methods=["POST"])
@require_auth
def toggle_empaque_desactivado(emp_id):
    data = request.get_json(force=True) or {}
    empaques = load_empaques()
    if emp_id not in empaques:
        return jsonify({"error": "No encontrado"}), 404
    nuevo = bool(data.get("desactivado", True))
    empaques[emp_id]["desactivado"] = nuevo
    save_empaques(empaques)
    audit.record("empaque", "desactivar" if nuevo else "reactivar", emp_id)
    return jsonify({"ok": True})


# ─── Gastos fijos ───

@catalogo_bp.route("/api/gastos_fijos/<period>", methods=["GET"])
@require_auth
def get_gastos_fijos_route(period):
    return jsonify(load_gastos_fijos(period))


@catalogo_bp.route("/api/gastos_fijos/<period>", methods=["PUT"])
@require_auth
def update_gastos_fijos_route(period):
    data = request.get_json(force=True) or {}
    save_gastos_fijos(period, data)
    return jsonify({"ok": True})


@catalogo_bp.route("/api/gastos_fijos/<period>/desactivar", methods=["POST"])
@require_auth
def toggle_gasto_desactivado(period):
    data = request.get_json(force=True) or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "Key requerida"}), 400
    gf = load_gastos_fijos(period)
    desact = set(gf.get("_desactivados", []))
    if bool(data.get("desactivado", True)):
        desact.add(key)
    else:
        desact.discard(key)
    gf["_desactivados"] = list(desact)
    save_gastos_fijos(period, gf)
    return jsonify({"ok": True})
