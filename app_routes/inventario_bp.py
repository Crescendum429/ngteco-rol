"""Blueprint de inventario v2: piezas, molido, auxiliar, lotes, BOM, registros v2."""
import re
from datetime import date, datetime

from flask import Blueprint, jsonify, request

import audit
from app_routes._auth import require_auth
from logger import get_logger
from storage import (
    append_aux_consumo,
    load_bom,
    load_cambios_molde,
    load_inv_aux_consumo,
    load_inv_auxiliar,
    load_inv_lotes,
    load_inv_molido,
    load_inv_piezas,
    load_movimientos_inventario,
    load_qc_templates,
    load_registro_diario,
    save_bom,
    save_cambios_molde,
    save_inv_auxiliar,
    save_inv_lotes,
    save_inv_molido,
    save_inv_piezas,
    save_movimientos_inventario,
    save_qc_templates,
    save_registro_diario,
)

log = get_logger("inventario")

inventario_bp = Blueprint("inventario", __name__)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def append_mov(clase, tipo, item_id, cantidad, unidad, ref="", nota=""):
    """Anade un movimiento atomico al log de movimientos."""
    movs = load_movimientos_inventario() or []
    nid = (max([int(m.get("id", 0)) for m in movs], default=0)) + 1
    movs.insert(0, {
        "id": nid,
        "fecha": date.today().isoformat(),
        "tipo": tipo,
        "clase": clase,
        "item_id": item_id,
        "cantidad": float(cantidad),
        "unidad": unidad,
        "ref": ref,
        "nota": nota,
    })
    save_movimientos_inventario(movs)
    return nid


def piezas_inc(pieza, estado, cliente_id, unidades, minimo=0):
    """Incrementa stock de pieza (estado cruda o impresa-cliente)."""
    if unidades == 0:
        return
    items = load_inv_piezas() or []
    cli = cliente_id if estado == "impresa" else None
    found = None
    for it in items:
        if it.get("pieza") == pieza and it.get("estado") == estado and it.get("cliente_id") == cli:
            found = it
            break
    if found:
        found["unidades"] = float(found.get("unidades", 0)) + float(unidades)
        found["ultima_actualizacion"] = _now_iso()
    else:
        items.append({
            "id": f"{pieza}_{estado}_{cli or 'na'}",
            "pieza": pieza, "estado": estado, "cliente_id": cli,
            "unidades": float(unidades), "minimo": float(minimo),
            "ultima_actualizacion": _now_iso(),
        })
    save_inv_piezas(items)


def molido_inc(tipo, kg):
    if kg == 0:
        return
    mol = load_inv_molido() or {}
    mol[tipo] = round(float(mol.get(tipo, 0)) + float(kg), 3)
    save_inv_molido(mol)


def gen_lote_id(producto_id, cliente_codigo, secuencial):
    """Genera ID de lote estilo JD10FARBIO-2003."""
    pid = (producto_id or "").upper().replace(" ", "")[:8]
    cli = (cliente_codigo or "").upper().replace(" ", "")[:8]
    return f"{pid}-{cli}-{int(secuencial):04d}" if cli else f"{pid}-{int(secuencial):04d}"


# ─── Piezas / Molido / Auxiliar ───

@inventario_bp.route("/api/inventario/piezas", methods=["GET"])
@require_auth
def get_inv_piezas():
    return jsonify(load_inv_piezas() or [])


@inventario_bp.route("/api/inventario/piezas", methods=["PUT"])
@require_auth
def put_inv_piezas():
    data = request.get_json(force=True) or []
    save_inv_piezas(data)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/molido", methods=["GET"])
@require_auth
def get_inv_molido():
    return jsonify(load_inv_molido() or {})


@inventario_bp.route("/api/inventario/molido", methods=["PUT"])
@require_auth
def put_inv_molido():
    data = request.get_json(force=True) or {}
    save_inv_molido(data)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/auxiliar", methods=["GET"])
@require_auth
def get_inv_auxiliar():
    return jsonify(load_inv_auxiliar() or {})


@inventario_bp.route("/api/inventario/auxiliar", methods=["PUT"])
@require_auth
def put_inv_auxiliar():
    data = request.get_json(force=True)
    save_inv_auxiliar(data)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/auxiliar/registrar-dia", methods=["POST"])
@require_auth
def registrar_consumo_aux():
    """Registra el consumo diario de material auxiliar.
    Body: { fecha: 'YYYY-MM-DD', items: [{aux_id, usado}] }
    Descuenta del stock, anade entradas al historico de consumo y crea movimientos.
    """
    data = request.get_json(force=True) or {}
    fecha = data.get("fecha") or date.today().isoformat()
    items = data.get("items") or []
    aux_list = load_inv_auxiliar()
    aux_idx = {a["id"]: a for a in aux_list if isinstance(a, dict)}
    nuevas_entradas = []
    movimientos_creados = 0
    for it in items:
        aid = it.get("aux_id")
        usado = float(it.get("usado") or 0)
        if not aid or usado <= 0 or aid not in aux_idx:
            continue
        aux = aux_idx[aid]
        stock_actual = float(aux.get("stock") or 0)
        stock_tras = max(0.0, stock_actual - usado)
        aux["stock"] = stock_tras
        nuevas_entradas.append({
            "aux_id": aid, "fecha": fecha,
            "usado": usado, "stock_tras": stock_tras,
        })
        append_mov("aux", "consumo", aid, usado, aux.get("unidad", "u"),
                   ref=f"aux-dia-{fecha}", nota=f"Consumo diario {aux.get('nombre', aid)}")
        movimientos_creados += 1
    if nuevas_entradas:
        append_aux_consumo(nuevas_entradas)
        save_inv_auxiliar(aux_list)
    log.info(f"registrar-dia aux: fecha={fecha} items={len(nuevas_entradas)}")
    return jsonify({
        "ok": True, "registrados": len(nuevas_entradas),
        "movimientos": movimientos_creados, "auxiliar": aux_list,
    })


@inventario_bp.route("/api/inventario/auxiliar/<aux_id>", methods=["DELETE"])
@require_auth
def delete_aux_item(aux_id):
    aux_list = load_inv_auxiliar()
    target = next((a for a in aux_list if a.get("id") == aux_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    if float(target.get("stock") or 0) > 0:
        return jsonify({"error": "Tiene stock > 0. Desactivelo en su lugar."}), 400
    aux_list = [a for a in aux_list if a.get("id") != aux_id]
    save_inv_auxiliar(aux_list)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/aux-consumo", methods=["GET"])
@require_auth
def get_aux_consumo():
    aid = request.args.get("aux_id")
    desde = request.args.get("desde")  # YYYY-MM-DD
    hasta = request.args.get("hasta")
    rows = load_inv_aux_consumo()
    if aid:
        rows = [r for r in rows if r.get("aux_id") == aid]
    if desde:
        rows = [r for r in rows if r.get("fecha", "") >= desde]
    if hasta:
        rows = [r for r in rows if r.get("fecha", "") <= hasta]
    return jsonify(rows)


# ─── Plantillas QC ───

@inventario_bp.route("/api/qc/<prod_id>", methods=["GET"])
@require_auth
def get_qc(prod_id):
    qc = load_qc_templates()
    return jsonify(qc.get(prod_id) or {"parametros": []})


@inventario_bp.route("/api/qc/<prod_id>", methods=["PUT"])
@require_auth
def put_qc(prod_id):
    data = request.get_json(force=True) or {}
    qc = load_qc_templates()
    qc[prod_id] = data
    save_qc_templates(qc)
    return jsonify({"ok": True})


@inventario_bp.route("/api/qc", methods=["GET"])
@require_auth
def get_qc_all():
    return jsonify(load_qc_templates() or {})


# ─── Sub-componentes (por kind de producto) ───

@inventario_bp.route("/api/subcomponentes", methods=["GET"])
@require_auth
def get_subcomponentes():
    from storage import load_sub_componentes
    return jsonify(load_sub_componentes() or {})


@inventario_bp.route("/api/subcomponentes", methods=["PUT"])
@require_auth
def put_subcomponentes():
    from storage import load_sub_componentes, save_sub_componentes
    before = load_sub_componentes()
    data = request.get_json(force=True) or {}
    save_sub_componentes(data)
    audit.record("subcomponentes", "update", "global", before=before, after=data)
    return jsonify({"ok": True})


# ─── Emisor (datos fiscales Solplast) ───

@inventario_bp.route("/api/emisor", methods=["GET"])
@require_auth
def get_emisor():
    from storage import load_emisor
    return jsonify(load_emisor() or {})


@inventario_bp.route("/api/emisor", methods=["PUT"])
@require_auth
def put_emisor():
    from storage import load_emisor, save_emisor
    before = load_emisor()
    data = request.get_json(force=True) or {}
    save_emisor(data)
    audit.record("emisor", "update", "solplast", before=before, after=data)
    return jsonify({"ok": True})


# ─── Piezas CRUD por item ───

@inventario_bp.route("/api/inventario/piezas/<pieza_id>", methods=["PUT"])
@require_auth
def update_pieza(pieza_id):
    """Actualiza un bin de piezas concreto (nombre, producto, cantidad, datos_incompletos)."""
    data = request.get_json(force=True) or {}
    piezas = load_inv_piezas() or []
    if not isinstance(piezas, list):
        return jsonify({"error": "Storage no es lista"}), 500
    found = False
    for p in piezas:
        if isinstance(p, dict) and p.get("id") == pieza_id:
            for k in ("pieza", "producto", "estado", "cliente_id", "cantidad", "unidad", "datos_incompletos"):
                if k in data:
                    p[k] = data[k]
            found = True
            break
    if not found:
        return jsonify({"error": "No existe"}), 404
    save_inv_piezas(piezas)
    audit.record("pieza", "update", pieza_id, before=None, after=data)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/piezas/<pieza_id>", methods=["DELETE"])
@require_auth
def delete_pieza(pieza_id):
    piezas = load_inv_piezas() or []
    target = next((p for p in piezas if isinstance(p, dict) and p.get("id") == pieza_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    if float(target.get("cantidad") or 0) > 0:
        return jsonify({"error": "Tiene unidades en stock. Vaciar primero o desactivar."}), 400
    piezas = [p for p in piezas if p.get("id") != pieza_id]
    save_inv_piezas(piezas)
    audit.record("pieza", "delete", pieza_id, before=target, after=None)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/piezas", methods=["POST"])
@require_auth
def create_pieza():
    """Crea un nuevo bin de pieza."""
    data = request.get_json(force=True) or {}
    if not data.get("pieza"):
        return jsonify({"error": "campo pieza obligatorio"}), 400
    piezas = load_inv_piezas() or []
    if not isinstance(piezas, list):
        piezas = []
    pid = data.get("id") or f"ps-{(data['pieza'] or '').lower()}-{data.get('estado', 'cruda')}"
    if data.get("cliente_id"):
        pid += f"-{data['cliente_id']}"
    if any(p.get("id") == pid for p in piezas if isinstance(p, dict)):
        return jsonify({"error": "Ya existe pieza con ese id"}), 409
    nueva = {
        "id": pid,
        "pieza": data.get("pieza"),
        "producto": data.get("producto"),
        "estado": data.get("estado", "cruda"),
        "cliente_id": data.get("cliente_id"),
        "cantidad": float(data.get("cantidad") or 0),
        "unidad": data.get("unidad", "unidades"),
        "ultima_actualizacion": _now_iso(),
        "datos_incompletos": data.get("datos_incompletos") or [],
    }
    piezas.append(nueva)
    save_inv_piezas(piezas)
    audit.record("pieza", "create", pid, before=None, after=nueva)
    return jsonify({"ok": True, "pieza": nueva})


# ─── Molido CRUD ───

@inventario_bp.route("/api/inventario/molido/<bin_id>", methods=["PUT"])
@require_auth
def update_molido_bin(bin_id):
    """Actualiza un bin de molido en sitio (kg, origen, producto, color)."""
    data = request.get_json(force=True) or {}
    mol = load_inv_molido() or {}
    if not isinstance(mol, dict):
        return jsonify({"error": "Storage no es dict"}), 500
    if bin_id not in mol:
        return jsonify({"error": "No existe bin"}), 404
    if "kg" in data:
        mol[bin_id] = float(data["kg"])
    save_inv_molido(mol)
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/molido/<bin_id>", methods=["DELETE"])
@require_auth
def delete_molido_bin(bin_id):
    mol = load_inv_molido() or {}
    if bin_id not in mol:
        return jsonify({"error": "No existe bin"}), 404
    if float(mol.get(bin_id, 0)) > 0:
        return jsonify({"error": "Bin con stock > 0. Vaciar primero."}), 400
    del mol[bin_id]
    save_inv_molido(mol)
    return jsonify({"ok": True})


# ─── Movimientos: editar y eliminar ───

@inventario_bp.route("/api/inventario/movimientos/<int:mov_id>", methods=["PUT"])
@require_auth
def update_movimiento(mov_id):
    """Editar nota/ref/fecha de un movimiento pasado (no cambia la cantidad)."""
    data = request.get_json(force=True) or {}
    movs = load_movimientos_inventario() or []
    target = next((m for m in movs if isinstance(m, dict) and int(m.get("id", 0)) == mov_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    before = dict(target)
    for k in ("ref", "nota", "fecha"):
        if k in data:
            target[k] = data[k]
    save_movimientos_inventario(movs)
    audit.record("movimiento", "update", str(mov_id), before=before, after=dict(target))
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/movimientos/<int:mov_id>", methods=["DELETE"])
@require_auth
def delete_movimiento(mov_id):
    """Elimina un movimiento. Si tiene side-effects ya aplicados al stock, NO los revierte
    automaticamente; el usuario debe revisar el impacto. Audit log preserva el evento."""
    movs = load_movimientos_inventario() or []
    target = next((m for m in movs if isinstance(m, dict) and int(m.get("id", 0)) == mov_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    movs = [m for m in movs if int(m.get("id", 0)) != mov_id]
    save_movimientos_inventario(movs)
    audit.record("movimiento", "delete", str(mov_id), before=target, after=None)
    return jsonify({"ok": True})


# ─── Lotes: editar y eliminar ───

@inventario_bp.route("/api/inventario/lotes/<lote_id>", methods=["PUT"])
@require_auth
def update_lote(lote_id):
    data = request.get_json(force=True) or {}
    lotes = load_inv_lotes() or []
    target = next((l for l in lotes if isinstance(l, dict) and l.get("id") == lote_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    if target.get("despachado"):
        return jsonify({"error": "Lote despachado no editable"}), 400
    before = dict(target)
    for k in ("producto_id", "cliente_id", "fecha_elaboracion", "fecha_caducidad",
              "cantidad_cajas", "unidades_caja", "peso_neto", "peso_total", "responsable"):
        if k in data:
            target[k] = data[k]
    save_inv_lotes(lotes)
    audit.record("lote", "update", lote_id, before=before, after=dict(target))
    return jsonify({"ok": True})


@inventario_bp.route("/api/inventario/lotes/<lote_id>", methods=["DELETE"])
@require_auth
def delete_lote(lote_id):
    lotes = load_inv_lotes() or []
    target = next((l for l in lotes if isinstance(l, dict) and l.get("id") == lote_id), None)
    if not target:
        return jsonify({"error": "No existe"}), 404
    if target.get("despachado"):
        return jsonify({"error": "Lote despachado, no eliminable"}), 400
    lotes = [l for l in lotes if l.get("id") != lote_id]
    save_inv_lotes(lotes)
    audit.record("lote", "delete", lote_id, before=target, after=None)
    return jsonify({"ok": True})


# ─── Audit log ───

# audit endpoint canonico vive en observability_bp como /api/audit
# (acepta entity, entity_id, limit). El v3 lo consume desde alli.


# ─── Movimientos manuales ───

@inventario_bp.route("/api/inventario/movimientos", methods=["GET"])
@require_auth
def get_movimientos():
    clase = request.args.get("clase")
    tipo = request.args.get("tipo")
    limit = int(request.args.get("limit", 200))
    movs = load_movimientos_inventario() or []
    if clase:
        movs = [m for m in movs if m.get("clase") == clase]
    if tipo:
        movs = [m for m in movs if m.get("tipo") == tipo]
    return jsonify(movs[:limit])


@inventario_bp.route("/api/inventario/movimientos", methods=["POST"])
@require_auth
def create_movimiento():
    """Crea un movimiento manual y opcionalmente ajusta el stock.

    Body:
      clase: mp | pt | aux | pieza | molido
      tipo:  entrada | salida | consumo | ajuste | produccion
      item_id: id del item
      cantidad: numero (positivo)
      unidad: kg | cajas | unidades
      ref: referencia libre (opcional)
      nota: nota (opcional)
      ajusta_stock: bool (default True) — si actualiza el stock
    """
    data = request.get_json(force=True) or {}
    clase = data.get("clase")
    tipo = data.get("tipo")
    item_id = data.get("item_id")
    try:
        cant = float(data.get("cantidad", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Cantidad invalida"}), 400
    unidad = data.get("unidad", "u")
    ref = data.get("ref", "")
    nota = data.get("nota", "")
    ajusta = data.get("ajusta_stock", True)
    # MP puede llevar conteo paralelo en fundas (operario lo registra asi).
    try:
        cant_fundas = int(data.get("cantidad_fundas") or 0)
    except (TypeError, ValueError):
        cant_fundas = 0

    if not clase or not tipo or not item_id or cant <= 0:
        return jsonify({"error": "clase, tipo, item_id y cantidad>0 son obligatorios"}), 400

    # Direccion del ajuste por tipo
    delta_signo = {"entrada": 1, "produccion": 1, "salida": -1, "consumo": -1, "ajuste": 1}.get(tipo, 1)
    delta = cant * delta_signo

    if ajusta:
        if clase == "molido":
            molido_inc(item_id, delta)
        elif clase == "aux":
            aux = load_inv_auxiliar() or []
            if isinstance(aux, list):
                for a in aux:
                    if a.get("id") == item_id:
                        a["stock"] = max(0, float(a.get("stock") or 0) + delta)
                        break
                save_inv_auxiliar(aux)
        elif clase == "pieza":
            # item_id formato "pieza:estado[:cliente_id]"
            parts = (item_id or "").split(":")
            piezas_inc(parts[0], parts[1] if len(parts) > 1 else "cruda",
                       parts[2] if len(parts) > 2 else None, delta)
        # mp / pt: ajuste solo se loguea, el stock se calcula desde lotes y movimientos
        # (no hay tabla simple de stock para esos)

    mid = append_mov(clase, tipo, item_id, cant, unidad, ref=ref, nota=nota)
    # Si vino cantidad_fundas, persistirlo en el movimiento ya creado
    if cant_fundas > 0:
        movs = load_movimientos_inventario() or []
        for m in movs:
            if isinstance(m, dict) and int(m.get("id", 0)) == mid:
                m["cantidad_fundas"] = cant_fundas
                break
        save_movimientos_inventario(movs)
    log.info(f"movimiento manual #{mid}: {tipo} {cant} {unidad} de {item_id} ({clase}) fundas={cant_fundas}")
    audit.record("movimiento", "create", str(mid),
                 after={"clase": clase, "tipo": tipo, "item_id": item_id, "cantidad": cant, "unidad": unidad, "cantidad_fundas": cant_fundas})
    return jsonify({"ok": True, "id": mid})


# ─── Lotes ───

@inventario_bp.route("/api/inventario/lotes", methods=["GET"])
@require_auth
def get_inv_lotes():
    producto = request.args.get("producto")
    cliente = request.args.get("cliente")
    solo_disponibles = request.args.get("disponibles") == "1"
    lotes = load_inv_lotes() or []
    if producto:
        lotes = [l for l in lotes if l.get("producto_id") == producto]
    if cliente:
        lotes = [l for l in lotes if l.get("cliente_id") == cliente]
    if solo_disponibles:
        lotes = [l for l in lotes if not l.get("despachado")]
    lotes.sort(key=lambda l: l.get("fecha_elaboracion", "9999-99-99"))
    return jsonify(lotes)


@inventario_bp.route("/api/inventario/lotes", methods=["POST"])
@require_auth
def create_lote():
    """Crea un lote nuevo (empaque registrado)."""
    data = request.get_json(force=True) or {}
    lotes = load_inv_lotes() or []
    secuencial = (max([int(re.findall(r"\d+", l.get("id", "0"))[-1]) for l in lotes if re.findall(r"\d+", l.get("id", "0"))], default=2000)) + 1
    cliente_id = data.get("cliente_id") or ""
    lote_id = data.get("id") or gen_lote_id(data.get("producto_id", ""), cliente_id.upper(), secuencial)
    nuevo = {
        "id": lote_id,
        "producto_id": data.get("producto_id"),
        "cliente_id": cliente_id or None,
        "fecha_elaboracion": data.get("fecha_elaboracion") or date.today().isoformat(),
        "fecha_caducidad": data.get("fecha_caducidad") or "",
        "cantidad_cajas": int(data.get("cantidad_cajas", 1)),
        "unidades_caja": int(data.get("unidades_caja", 0)),
        "peso_neto": float(data.get("peso_neto", 0)),
        "peso_total": float(data.get("peso_total", 0)),
        "responsable": data.get("responsable", ""),
        "despachado": False,
        "despachado_en": "",
    }
    lotes.append(nuevo)
    save_inv_lotes(lotes)
    append_mov("pt", "produccion", nuevo["producto_id"], nuevo["cantidad_cajas"], "cajas",
               ref=nuevo["id"], nota=f"Lote {nuevo['id']} creado")
    log.info(f"lote creado: {lote_id}")
    audit.record("lote", "create", lote_id, after=nuevo)
    return jsonify({"ok": True, "lote": nuevo})


@inventario_bp.route("/api/inventario/lotes/<lote_id>/despachar", methods=["POST"])
@require_auth
def despachar_lote(lote_id):
    lotes = load_inv_lotes() or []
    cambiado = False
    for l in lotes:
        if l.get("id") == lote_id and not l.get("despachado"):
            l["despachado"] = True
            l["despachado_en"] = _now_iso()
            cambiado = True
            append_mov("pt", "salida", l.get("producto_id"), l.get("cantidad_cajas", 0), "cajas",
                       ref=lote_id, nota="Despacho")
            log.info(f"lote despachado: {lote_id}")
            audit.record("lote", "despachar", lote_id, before=None, after=dict(l))
            break
    if cambiado:
        save_inv_lotes(lotes)
    return jsonify({"ok": cambiado})


# ─── BOM y cambios de molde ───

@inventario_bp.route("/api/bom/<prod_id>", methods=["GET"])
@require_auth
def get_bom(prod_id):
    bom = load_bom() or {}
    return jsonify(bom.get(prod_id) or {})


@inventario_bp.route("/api/bom/<prod_id>", methods=["PUT"])
@require_auth
def put_bom(prod_id):
    data = request.get_json(force=True) or {}
    bom = load_bom() or {}
    bom[prod_id] = data
    save_bom(bom)
    log.info(f"bom actualizado para {prod_id}: {data}")
    return jsonify({"ok": True})


@inventario_bp.route("/api/cambios_molde", methods=["GET"])
@require_auth
def get_cambios_molde():
    return jsonify(load_cambios_molde() or [])


# ─── Registro Diario v2 ───

@inventario_bp.route("/api/registros/v2", methods=["POST"])
@require_auth
def save_registro_v2():
    """Guarda un registro extendido y actualiza inventario de forma atomica."""
    data = request.get_json(force=True) or {}
    fecha = data.get("fecha") or date.today().isoformat()

    # 1. Piezas producidas
    for p in data.get("piezas") or []:
        unidades = float(p.get("unidades", 0))
        if unidades == 0:
            continue
        piezas_inc(p.get("pieza"), p.get("estado", "cruda"), p.get("cliente_id"), unidades)
        append_mov("pieza", "produccion", p.get("pieza"), unidades, "unidades",
                   ref=fecha, nota=f"{p.get('estado','cruda')} {p.get('cliente_id') or ''}".strip())

    # 2. Empaque -> lotes + mov + consume piezas segun BOM
    bom = load_bom() or {}
    lotes_existentes = load_inv_lotes() or []
    for e in data.get("empaques") or []:
        cajas = int(e.get("cajas", 0))
        if cajas <= 0:
            continue
        prod_id = e.get("producto_id")
        cliente_id = e.get("cliente_id") or ""
        unidades_caja = int(e.get("unidades_caja", 0))
        secuencial = (max([int((re.findall(r"\d+", l.get("id", "0")) or ["0"])[-1]) for l in lotes_existentes], default=2000)) + 1
        lote_id = gen_lote_id(prod_id, cliente_id.upper(), secuencial)
        nuevo_lote = {
            "id": lote_id,
            "producto_id": prod_id,
            "cliente_id": cliente_id or None,
            "fecha_elaboracion": fecha,
            "fecha_caducidad": "",
            "cantidad_cajas": cajas,
            "unidades_caja": unidades_caja,
            "peso_neto": float(e.get("peso_neto", 0)),
            "peso_total": float(e.get("peso_total", 0)),
            "responsable": ", ".join(data.get("responsables") or []),
            "despachado": False,
            "despachado_en": "",
        }
        lotes_existentes.append(nuevo_lote)
        append_mov("pt", "produccion", prod_id, cajas, "cajas", ref=lote_id, nota=fecha)
        receta = bom.get(prod_id) or {}
        for pieza, cant_por_caja in receta.items():
            unidades_consumidas = float(cant_por_caja) * cajas * (unidades_caja or 1)
            piezas_inc(pieza, "impresa" if cliente_id else "cruda", cliente_id or None, -unidades_consumidas)
            append_mov("pieza", "consumo", pieza, unidades_consumidas, "unidades",
                       ref=lote_id, nota=f"empaque {prod_id}")
    save_inv_lotes(lotes_existentes)

    # 3. Material virgen consumido
    for mat_key, kg in (data.get("material_virgen") or {}).items():
        if not kg:
            continue
        mat_id = mat_key.replace("_kg", "")
        append_mov("mp", "consumo", mat_id, float(kg), "kg", ref=fecha, nota="virgen")

    # 4. Molido reusado
    mol = load_inv_molido() or {}
    for tipo, kg in (data.get("molido_reusado") or {}).items():
        if not kg:
            continue
        mol[tipo] = round(float(mol.get(tipo, 0)) - float(kg), 3)
        append_mov("molido", "consumo", tipo, float(kg), "kg", ref=fecha, nota="reuso")
    save_inv_molido(mol)

    # 5. Desechos de maquina vuelven a molido
    for pieza_key, kg in (data.get("desechos_maquina") or {}).items():
        if not kg:
            continue
        tipo = pieza_key.replace("_kg", "")
        molido_inc(tipo, float(kg))
        append_mov("molido", "entrada", tipo, float(kg), "kg", ref=fecha, nota="desecho_maquina")

    # 6. Desecho empacadora (descarte final)
    if data.get("desecho_empacadora"):
        append_mov("descarte", "baja", "empacadora", float(data["desecho_empacadora"]), "unidades",
                   ref=fecha, nota="empacadora")

    # 7. Auxiliar consumido
    aux = load_inv_auxiliar() or {}
    for item_id, cant in (data.get("auxiliar_consumido") or {}).items():
        if not cant:
            continue
        cur = aux.get(item_id) or {"nombre": item_id, "actual": 0, "minimo": 0, "unidad": "unid"}
        cur["actual"] = float(cur.get("actual", 0)) - float(cant)
        aux[item_id] = cur
        append_mov("auxiliar", "consumo", item_id, float(cant), cur.get("unidad", "unid"), ref=fecha)
    save_inv_auxiliar(aux)

    # 8. Cambios de molde
    if data.get("cambios_molde"):
        historial = load_cambios_molde() or []
        for c in data["cambios_molde"]:
            historial.insert(0, {
                "fecha": fecha,
                "maquina": c.get("maquina", ""),
                "de_producto": c.get("de_producto", ""),
                "a_producto": c.get("a_producto", ""),
                "responsable": ", ".join(data.get("responsables") or []),
            })
        save_cambios_molde(historial)

    # 9. Guardar registro raw
    payload = {
        "fecha": fecha,
        "responsables": data.get("responsables") or [],
        "piezas": data.get("piezas") or [],
        "empaques": data.get("empaques") or [],
        "material_virgen": data.get("material_virgen") or {},
        "molido_reusado": data.get("molido_reusado") or {},
        "desechos_maquina": data.get("desechos_maquina") or {},
        "desecho_empacadora": data.get("desecho_empacadora") or 0,
        "auxiliar_consumido": data.get("auxiliar_consumido") or {},
        "cambios_molde": data.get("cambios_molde") or [],
        "observaciones": data.get("obs", ""),
        "raw": data,
        "total_material_kg": sum(float(v or 0) for v in (data.get("material_virgen") or {}).values()),
        "total_cajas": sum(int(e.get("cajas", 0)) for e in (data.get("empaques") or [])),
        "merma_pct": 0,
    }
    save_registro_diario(fecha, payload)
    log.info(f"registro v2 guardado: {fecha} ({payload['total_cajas']} cajas, {payload['total_material_kg']:.1f}kg mat)")
    return jsonify({"ok": True, "fecha": fecha})


@inventario_bp.route("/api/registros/v2/<fecha>", methods=["GET"])
@require_auth
def get_registro_v2(fecha):
    reg = load_registro_diario(fecha) or {}
    return jsonify(reg)


@inventario_bp.route("/api/registros/v2/<fecha>", methods=["PUT"])
@require_auth
def update_registro_v2(fecha):
    """Edita un registro pasado. Reemplaza el payload completo.
    NOTA: no revierte movimientos / lotes / piezas previamente creados —
    el operador debe ajustar manualmente si cambia mucho. Audit log preserva el evento."""
    from storage import load_registro_diario, save_registro_diario
    data = request.get_json(force=True) or {}
    existing = load_registro_diario(fecha)
    if not existing:
        return jsonify({"error": "Registro no existe"}), 404
    save_registro_diario(fecha, data)
    audit.record("registro_diario", "update", fecha, before=existing, after=data)
    log.info(f"registro {fecha} editado")
    return jsonify({"ok": True})


@inventario_bp.route("/api/registros/v2/<fecha>", methods=["DELETE"])
@require_auth
def delete_registro_v2(fecha):
    """Elimina un registro diario. Los movimientos / lotes / piezas creados
    en su momento NO se revierten automaticamente (mantienen audit). El
    operador debe corregir manualmente si necesita rollback."""
    from storage import delete_registro_diario, load_registro_diario
    existing = load_registro_diario(fecha)
    if not existing:
        return jsonify({"error": "Registro no existe"}), 404
    delete_registro_diario(fecha)
    audit.record("registro_diario", "delete", fecha, before=existing, after=None)
    log.info(f"registro {fecha} eliminado")
    return jsonify({"ok": True})
