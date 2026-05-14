"""Blueprint de endpoints comerciales: clientes, cotizaciones, OCs, facturas, guias,
certificados, emisor, inventario MP/PT legacy, movimientos, beneficios recurrentes."""
from datetime import date
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
    load_notas_credito,
    load_notas_debito,
    load_ordenes_compra,
    load_pagos_recibidos,
    load_retenciones_recibidas,
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
    save_notas_credito,
    save_notas_debito,
    save_ordenes_compra,
    save_pagos_recibidos,
    save_retenciones_recibidas,
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
    "notas_credito": (load_notas_credito, save_notas_credito),
    "notas_debito": (load_notas_debito, save_notas_debito),
    "retenciones_recibidas": (load_retenciones_recibidas, save_retenciones_recibidas),
    "pagos_recibidos": (load_pagos_recibidos, save_pagos_recibidos),
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
    import audit
    if kind not in COLLECTION_MAP:
        return jsonify({"error": "Coleccion desconocida"}), 404
    loader, saver = COLLECTION_MAP[kind]
    before = loader()
    data = request.get_json(force=True)
    # Lock: facturas y guias autorizadas no se pueden modificar (es ley SRI).
    # Verificamos que ninguna entrada autorizada haya cambiado.
    if kind in ("facturas", "guias") and isinstance(before, list) and isinstance(data, list):
        autorizadas_before = {x["id"]: x for x in before if isinstance(x, dict) and x.get("estado_sri") == "autorizada"}
        for nuevo in data:
            if not isinstance(nuevo, dict):
                continue
            aut = autorizadas_before.get(nuevo.get("id"))
            if aut and nuevo != aut:
                return jsonify({"error": f"{kind[:-1].capitalize()} {nuevo.get('id')} esta autorizada por el SRI y no puede modificarse. Use nota de credito."}), 409
    saver(data)
    log.info(f"collection {kind}: actualizada ({len(data) if isinstance(data, list) else 'dict'} items)")
    n_before = len(before) if isinstance(before, list) else (len(before) if isinstance(before, dict) else 0)
    n_after = len(data) if isinstance(data, list) else (len(data) if isinstance(data, dict) else 0)
    audit.record(kind, "bulk_update", "all", before=None, after={"count_before": n_before, "count_after": n_after})
    return jsonify({"ok": True})


@comercial_bp.route("/api/collection/<kind>/<item_id>", methods=["DELETE"])
@require_auth
def delete_collection_item(kind, item_id):
    """Elimina un item de una coleccion list-based. La coleccion debe tener objetos con 'id'."""
    import audit
    if kind not in COLLECTION_MAP:
        return jsonify({"error": "Coleccion desconocida"}), 404
    loader, saver = COLLECTION_MAP[kind]
    data = loader() or []
    if not isinstance(data, list):
        return jsonify({"error": "Coleccion no es lista"}), 400
    target = next((x for x in data if isinstance(x, dict) and x.get("id") == item_id), None)
    nuevo = [x for x in data if isinstance(x, dict) and x.get("id") != item_id]
    if len(nuevo) == len(data):
        return jsonify({"error": "Item no encontrado"}), 404
    saver(nuevo)
    log.info(f"collection {kind}: eliminado {item_id} ({len(nuevo)} restantes)")
    audit.record(kind, "delete", item_id, before=target, after=None)
    return jsonify({"ok": True})


@comercial_bp.route("/api/pedidos/cotizacion/<cot_id>/convertir-oc", methods=["POST"])
@require_auth
def cotizacion_convertir_oc(cot_id):
    """Crea una OC a partir de una cotizacion aprobada. Copia items y cliente."""
    import audit
    from datetime import date as _date
    cots = load_cotizaciones() or []
    cot = next((c for c in cots if isinstance(c, dict) and c.get("id") == cot_id), None)
    if not cot:
        return jsonify({"error": "Cotizacion no encontrada"}), 404
    if cot.get("estado") not in ("aprobada", "enviada"):
        return jsonify({"error": f"La cotizacion debe estar 'aprobada' o 'enviada' (estado: {cot.get('estado')})"}), 400
    if cot.get("oc_asociada"):
        return jsonify({"error": f"Ya existe OC asociada: {cot['oc_asociada']}"}), 409
    data = request.get_json(silent=True) or {}
    ocs = load_ordenes_compra() or []
    cli = cot.get("cliente", "X")
    fecha_recep = data.get("fecha_recepcion") or _date.today().isoformat()
    seq = sum(1 for o in ocs if isinstance(o, dict) and o.get("cliente") == cli) + 1
    oc_id = data.get("id") or f"OC-{cli.replace('cli-', '').upper()[:6]}-{fecha_recep.replace('-', '')}-{seq:02d}"
    nueva_oc = {
        "id": oc_id,
        "cliente": cli,
        "cotizacion_id": cot_id,
        "fecha_recepcion": fecha_recep,
        "fecha_entrega": data.get("fecha_entrega", ""),
        "estado": "pendiente",
        "items": [dict(it) for it in (cot.get("items") or [])],
        "nro_pedido_cliente": data.get("nro_pedido_cliente", ""),
        "factura_asociada": None,
    }
    ocs.append(nueva_oc)
    save_ordenes_compra(ocs)
    # Marcar cotizacion como convertida
    cot["oc_asociada"] = oc_id
    cot["estado"] = "convertida"
    save_cotizaciones(cots)
    audit.record("cotizacion", "convertir_oc", cot_id, after={"oc_id": oc_id})
    audit.record("ordenes_compra", "create", oc_id, after=nueva_oc)
    log.info(f"cotizacion {cot_id} convertida en OC {oc_id}")
    return jsonify({"ok": True, "oc": nueva_oc})


def _stock_disponible_producto(prod_id):
    """Cajas disponibles (no despachadas) por producto, leyendo de lotes."""
    from storage import load_inv_lotes
    lotes = load_inv_lotes() or []
    return sum(int(l.get("cantidad_cajas", 0)) for l in lotes
               if isinstance(l, dict) and l.get("producto_id") == prod_id and not l.get("despachado"))


@comercial_bp.route("/api/pedidos/oc/<oc_id>/facturar", methods=["POST"])
@require_auth
def oc_facturar(oc_id):
    """Crea una factura draft a partir de una OC. Valida stock disponible.
    NO emite al SRI todavia — eso lo hace POST /api/sri/emitir/<factura_id>.

    Verifica:
    - OC existe, no esta cancelada, no esta ya facturada
    - Hay stock suficiente para cada item (en lotes no despachados)
    - Cliente tiene RUC o cedula valida
    """
    import audit
    import sri as sri_mod
    from datetime import date as _date
    from decimal import Decimal, ROUND_HALF_UP

    ocs = load_ordenes_compra() or []
    oc = next((o for o in ocs if isinstance(o, dict) and o.get("id") == oc_id), None)
    if not oc:
        return jsonify({"error": "OC no encontrada"}), 404
    if oc.get("factura_asociada"):
        return jsonify({"error": f"OC ya facturada: {oc['factura_asociada']}"}), 409
    if oc.get("estado") in ("entregada", "cancelada"):
        return jsonify({"error": f"OC en estado {oc['estado']}, no facturable"}), 400

    cli_id = oc.get("cliente")
    clientes = load_clientes() or []
    cli = next((c for c in clientes if isinstance(c, dict) and c.get("id") == cli_id), None) or {}
    cli_ident = (cli.get("ruc") or cli.get("cedula") or "").strip()
    if not cli_ident:
        return jsonify({"error": "Cliente sin RUC/cedula. Completa los datos antes de facturar."}), 400

    # Validacion de stock por item
    faltantes = []
    for it in oc.get("items") or []:
        pid = it.get("prod_id")
        cant = int(it.get("cant_cajas", 0))
        disp = _stock_disponible_producto(pid)
        if disp < cant:
            faltantes.append({"prod_id": pid, "requerido": cant, "disponible": disp})
    if faltantes:
        return jsonify({"error": "Stock insuficiente", "faltantes": faltantes}), 422

    # Construir factura draft (sin secuencial — se reserva al emitir SRI)
    data = request.get_json(silent=True) or {}
    fecha = data.get("fecha_emision") or _date.today().isoformat()
    # Default IVA 0% — Solplast vende mayormente productos exentos. Cada
    # producto tiene su iva_pct configurado en el catalogo.
    iva_pct_default = float(data.get("iva_pct_default", 0))
    items_factura = []
    subtotal_12 = Decimal("0")
    subtotal_0 = Decimal("0")
    iva_total = Decimal("0")
    for it in oc.get("items") or []:
        cant = Decimal(str(it.get("cant_cajas", 0)))
        precio = Decimal(str(it.get("precio_caja", 0)))
        subtotal_item = (cant * precio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        iva_pct = Decimal(str(it.get("iva_pct", iva_pct_default)))
        iva_item = (subtotal_item * iva_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        items_factura.append({
            "prod_id": it.get("prod_id"),
            "descripcion": it.get("descripcion", ""),
            "cant_cajas": int(cant),
            "precio_caja": float(precio),
            "precio_unit": float(precio),
            "iva_pct": float(iva_pct),
            "subtotal": float(subtotal_item),
        })
        if iva_pct == 0:
            subtotal_0 += subtotal_item
        else:
            subtotal_12 += subtotal_item
        iva_total += iva_item

    total = (subtotal_12 + subtotal_0 + iva_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    facturas = load_facturas() or []
    fact_id = data.get("id") or f"FAC-{fecha.replace('-', '')}-{len(facturas)+1:04d}"
    nueva = {
        "id": fact_id,
        "cliente": cli_id,
        "oc_id": oc_id,
        "fecha_emision": fecha,
        "establecimiento": "001",
        "punto_emision": "001",
        "secuencial": None,  # se reserva al emitir SRI
        "items": items_factura,
        "subtotal_12": float(subtotal_12),
        "subtotal_0": float(subtotal_0),
        "iva": float(iva_total),
        "total": float(total),
        "forma_pago_codigo": data.get("forma_pago_codigo", "20"),
        "fecha_vencimiento": data.get("fecha_vencimiento", ""),
        "pagada": False,
        "estado_sri": "borrador",
    }
    facturas.append(nueva)
    save_facturas(facturas)
    oc["factura_asociada"] = fact_id
    oc["estado"] = "facturada"
    save_ordenes_compra(ocs)
    audit.record("factura", "create", fact_id, after={"oc_id": oc_id, "total": float(total)})
    log.info(f"OC {oc_id} -> factura borrador {fact_id} (total {total})")
    return jsonify({"ok": True, "factura": nueva})


@comercial_bp.route("/api/pedidos/oc/<oc_id>/generar-guia", methods=["POST"])
@require_auth
def oc_generar_guia(oc_id):
    """Crea una guia de remision draft a partir de una OC. La guia se asocia
    a los lotes que se despacharan (selección FIFO por defecto)."""
    import audit
    from storage import load_inv_lotes
    from datetime import date as _date
    ocs = load_ordenes_compra() or []
    oc = next((o for o in ocs if isinstance(o, dict) and o.get("id") == oc_id), None)
    if not oc:
        return jsonify({"error": "OC no encontrada"}), 404
    if oc.get("guia_asociada"):
        return jsonify({"error": f"OC ya tiene guia: {oc['guia_asociada']}"}), 409

    data = request.get_json(silent=True) or {}
    cli_id = oc.get("cliente")
    clientes = load_clientes() or []
    cli = next((c for c in clientes if isinstance(c, dict) and c.get("id") == cli_id), None) or {}
    if not (cli.get("ruc") or cli.get("cedula")):
        return jsonify({"error": "Cliente sin identificacion"}), 400

    # FIFO: seleccionar lotes mas antiguos para cada producto, hasta cubrir
    lotes = load_inv_lotes() or []
    items_guia = []
    for it in oc.get("items") or []:
        pid = it.get("prod_id")
        cant_req = int(it.get("cant_cajas", 0))
        cands = sorted(
            [l for l in lotes if isinstance(l, dict) and l.get("producto_id") == pid and not l.get("despachado")],
            key=lambda l: l.get("fecha_elaboracion", "9999-99-99"),
        )
        asignados = []
        rest = cant_req
        for l in cands:
            if rest <= 0:
                break
            c = int(l.get("cantidad_cajas", 0))
            tomar = min(c, rest)
            asignados.append({"lote_id": l.get("id"), "cajas": tomar, "fecha_elaboracion": l.get("fecha_elaboracion")})
            rest -= tomar
        if rest > 0:
            return jsonify({"error": f"Stock insuficiente para {pid}: faltan {rest} cajas"}), 422
        items_guia.append({
            "prod_id": pid,
            "descripcion": it.get("descripcion", ""),
            "cant_cajas": cant_req,
            "lotes_asignados": asignados,
        })

    fecha = data.get("fecha_emision") or _date.today().isoformat()
    guias = load_guias() or []
    guia_id = data.get("id") or f"GR-{fecha.replace('-', '')}-{len(guias)+1:04d}"
    nueva = {
        "id": guia_id,
        "oc_id": oc_id,
        "cliente": cli_id,
        "factura_id": oc.get("factura_asociada"),
        "fecha_emision": fecha,
        "fecha_inicio": fecha,
        "fecha_fin": data.get("fecha_fin", fecha),
        "establecimiento": "001",
        "punto_emision": "001",
        "secuencial": None,
        "punto_partida": data.get("punto_partida", ""),
        "motivo": data.get("motivo", "Venta"),
        "transportista": data.get("transportista") or {},
        "placa": data.get("placa", ""),
        "items": items_guia,
        "destinatarios": [{
            "identificacion": cli.get("ruc") or cli.get("cedula") or "",
            "razon_social": cli.get("razon_social", ""),
            "direccion": (cli.get("dir_sucursal") or cli.get("dir_matriz") or {}).get("calle", ""),
            "motivo": data.get("motivo", "Venta"),
            "detalles": [{"prod_id": x["prod_id"], "descripcion": x["descripcion"], "cant_cajas": x["cant_cajas"]} for x in items_guia],
        }],
        "estado_sri": "borrador",
    }
    guias.append(nueva)
    save_guias(guias)
    oc["guia_asociada"] = guia_id
    save_ordenes_compra(ocs)
    audit.record("guia_remision", "create", guia_id, after={"oc_id": oc_id, "items": len(items_guia)})
    log.info(f"OC {oc_id} -> guia draft {guia_id}")
    return jsonify({"ok": True, "guia": nueva})


@comercial_bp.route("/api/pagos", methods=["POST"])
@require_auth
def registrar_pago():
    """Registra un pago recibido contra una factura (soporta parciales).
    Body: { factura_id, fecha, monto, forma_pago, ref?, retencion_asociada? }"""
    import audit
    from decimal import Decimal, ROUND_HALF_UP
    data = request.get_json(force=True) or {}
    fact_id = data.get("factura_id")
    monto = Decimal(str(data.get("monto", 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not fact_id or monto <= 0:
        return jsonify({"error": "factura_id y monto>0 obligatorios"}), 400

    facturas = load_facturas() or []
    fac = next((f for f in facturas if isinstance(f, dict) and f.get("id") == fact_id), None)
    if not fac:
        return jsonify({"error": "Factura no encontrada"}), 404
    if fac.get("pagada"):
        return jsonify({"error": "Factura ya pagada en total"}), 409

    pagos = load_pagos_recibidos() or []
    pid = data.get("id") or f"PAG-{fact_id}-{len(pagos)+1:03d}"
    nuevo = {
        "id": pid,
        "factura_id": fact_id,
        "fecha": data.get("fecha") or date.today().isoformat(),
        "monto": float(monto),
        "forma_pago": data.get("forma_pago", "20"),
        "ref": data.get("ref", ""),
        "retencion_asociada": data.get("retencion_asociada"),
        "nota": data.get("nota", ""),
    }
    pagos.append(nuevo)
    save_pagos_recibidos(pagos)

    # Actualiza saldo de la factura
    pagos_fac = [Decimal(str(p.get("monto", 0))) for p in pagos if p.get("factura_id") == fact_id]
    total_pagado = sum(pagos_fac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_factura = Decimal(str(fac.get("total", 0)))
    if total_pagado >= total_factura - Decimal("0.01"):
        fac["pagada"] = True
        fac["fecha_pago"] = nuevo["fecha"]
    fac["total_pagado"] = float(total_pagado)
    fac["saldo_pendiente"] = float(max(Decimal("0"), total_factura - total_pagado))
    save_facturas(facturas)
    audit.record("pago", "create", pid, after={"factura_id": fact_id, "monto": float(monto)})
    log.info(f"pago registrado: {pid} ${monto} para {fact_id}")
    return jsonify({"ok": True, "pago": nuevo, "factura": {"total_pagado": fac["total_pagado"],
                    "saldo_pendiente": fac["saldo_pendiente"], "pagada": fac["pagada"]}})


@comercial_bp.route("/api/pedidos/oc/<oc_id>/aprobar-predespacho", methods=["POST"])
@require_auth
def aprobar_predespacho(oc_id):
    """Aprueba el pre-despacho de una OC. Solo usuarios en la lista
    predespacho:autorizados pueden hacerlo (default: Fernando, Carlos).
    Body: { responsable: 'Fernando Pinargote', lotes_despacho: [...] }
    """
    import audit
    from storage import load_predespacho_autorizados
    from datetime import date as _date
    data = request.get_json(force=True) or {}
    responsable = (data.get("responsable") or "").strip()
    if not responsable:
        return jsonify({"error": "Indica el responsable del pre-despacho"}), 400
    autorizados = load_predespacho_autorizados()
    if responsable not in autorizados:
        return jsonify({"error": f"'{responsable}' no esta autorizado. Autorizados: {autorizados}"}), 403

    ocs = load_ordenes_compra() or []
    oc = next((o for o in ocs if isinstance(o, dict) and o.get("id") == oc_id), None)
    if not oc:
        return jsonify({"error": "OC no encontrada"}), 404
    if oc.get("estado") not in ("lista", "en_produccion"):
        return jsonify({"error": f"OC debe estar 'lista' o 'en_produccion' (estado: {oc.get('estado')})"}), 400

    oc["estado"] = "predespacho"
    oc["responsable_predespacho"] = responsable
    oc["fecha_predespacho"] = _date.today().isoformat()
    if data.get("lotes_despacho"):
        oc["lotes_despacho"] = data["lotes_despacho"]
    save_ordenes_compra(ocs)
    audit.record("ordenes_compra", "aprobar_predespacho", oc_id,
                 after={"responsable": responsable, "lotes": oc.get("lotes_despacho", [])})
    log.info(f"OC {oc_id} pre-despacho aprobado por {responsable}")
    return jsonify({"ok": True, "oc": oc})


@comercial_bp.route("/api/predespacho/autorizados", methods=["GET", "PUT"])
@require_auth
def predespacho_autorizados():
    from storage import load_predespacho_autorizados, save_predespacho_autorizados
    if request.method == "GET":
        return jsonify(load_predespacho_autorizados())
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({"error": "Se espera lista de strings"}), 400
    save_predespacho_autorizados([str(x).strip() for x in data if str(x).strip()])
    return jsonify({"ok": True})


@comercial_bp.route("/api/certificados/generar", methods=["POST"])
@require_auth
def generar_certificado_calidad():
    """Genera certificado de calidad para una OC/factura tomando lotes
    despachados + plantilla QC del producto.

    Body: { oc_id?, factura_id?, lote_ids: [], responsable, observaciones?,
            parametros_chequeados: {prod_id: {param_id: {valor, ok}}} }
    """
    import audit
    from storage import load_inv_lotes, load_qc_templates
    from datetime import date as _date
    data = request.get_json(force=True) or {}
    lote_ids = data.get("lote_ids") or []
    if not lote_ids:
        return jsonify({"error": "Se requiere al menos un lote_id"}), 400
    responsable = (data.get("responsable") or "").strip()
    if not responsable:
        return jsonify({"error": "Indica el responsable de calidad"}), 400

    lotes = load_inv_lotes() or []
    lotes_cert = [l for l in lotes if isinstance(l, dict) and l.get("id") in lote_ids]
    if len(lotes_cert) != len(lote_ids):
        encontrados = [l.get("id") for l in lotes_cert]
        faltantes = [x for x in lote_ids if x not in encontrados]
        return jsonify({"error": f"Lotes no encontrados: {faltantes}"}), 404

    qc_tpl = load_qc_templates() or {}
    productos_ids = list({l.get("producto_id") for l in lotes_cert if l.get("producto_id")})

    certs = load_certificados() or []
    cert_id = data.get("id") or f"CC-{_date.today().isoformat().replace('-', '')}-{len(certs)+1:04d}"
    nuevo = {
        "id": cert_id,
        "fecha": _date.today().isoformat(),
        "oc_id": data.get("oc_id"),
        "factura_id": data.get("factura_id"),
        "lote_ids": lote_ids,
        "productos": productos_ids,
        "responsable": responsable,
        "revisor": data.get("revisor", ""),
        "observaciones": data.get("observaciones", ""),
        "parametros_chequeados": data.get("parametros_chequeados") or {},
        "qc_templates_snapshot": {pid: qc_tpl.get(pid, {}) for pid in productos_ids},
    }
    certs.append(nuevo)
    save_certificados(certs)

    # Si esta asociado a factura, marcarla
    if nuevo["factura_id"]:
        facturas = load_facturas() or []
        for f in facturas:
            if isinstance(f, dict) and f.get("id") == nuevo["factura_id"]:
                f["cert_calidad"] = cert_id
                break
        save_facturas(facturas)

    audit.record("certificado", "create", cert_id, after={"lotes": lote_ids, "responsable": responsable})
    log.info(f"certificado {cert_id} generado para lotes {lote_ids}")
    return jsonify({"ok": True, "certificado": nuevo})


@comercial_bp.route("/api/clientes/<cli_id>/cuenta-corriente", methods=["GET"])
@require_auth
def cuenta_corriente_cliente(cli_id):
    """Saldo del cliente: facturas totales - pagos recibidos - retenciones."""
    from decimal import Decimal, ROUND_HALF_UP
    facturas = load_facturas() or []
    pagos = load_pagos_recibidos() or []
    rets = load_retenciones_recibidas() or []
    facs_cli = [f for f in facturas if isinstance(f, dict) and f.get("cliente") == cli_id and f.get("estado_sri") not in ("anulada",)]
    total_facturado = sum(Decimal(str(f.get("total", 0))) for f in facs_cli).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    pagos_cli = [p for p in pagos if isinstance(p, dict) and any(f.get("id") == p.get("factura_id") for f in facs_cli)]
    total_pagado = sum(Decimal(str(p.get("monto", 0))) for p in pagos_cli).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rets_cli = [r for r in rets if isinstance(r, dict) and any(f.get("id") == r.get("factura_id") for f in facs_cli)]
    total_retenido = sum(Decimal(str(r.get("monto_total", 0))) for r in rets_cli).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    saldo = (total_facturado - total_pagado - total_retenido).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return jsonify({
        "cliente": cli_id,
        "total_facturado": float(total_facturado),
        "total_pagado": float(total_pagado),
        "total_retenido": float(total_retenido),
        "saldo_pendiente": float(saldo),
        "facturas": len(facs_cli),
        "pagos": len(pagos_cli),
        "retenciones": len(rets_cli),
    })


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
