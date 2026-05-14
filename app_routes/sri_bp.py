"""Blueprint de endpoints SRI (facturacion electronica Ecuador)."""
import os
import tempfile
from datetime import date, datetime

from flask import Blueprint, jsonify, request, send_file

import audit
import sri as sri_mod
from app_routes._auth import require_auth
from logger import get_logger
from storage import _cfg_get, _cfg_set, load_clientes, load_emisor, load_facturas, save_facturas

log = get_logger("sri")

sri_bp = Blueprint("sri", __name__)


def _find_factura(factura_id):
    facturas = load_facturas() or []
    for f in facturas:
        if f.get("id") == factura_id:
            return f, facturas
    return None, facturas


def _find_cliente(cliente_id):
    clientes = load_clientes() or []
    for c in clientes:
        if c.get("id") == cliente_id:
            return c
    return None


@sri_bp.route("/api/sri/emitir/<path:factura_id>", methods=["POST"])
@require_auth
def sri_emitir(factura_id):
    """Genera clave de acceso, XML, firma y envia al SRI. Actualiza la factura.

    Endurecido v5.5: valida RUC/cedula, totales reconciliados, lock si ya
    autorizada, reserva secuencial atomico, no envia sin firma (excepto modo
    simulado), permite re-emision con mismo secuencial si esta rechazada.
    """
    factura, facturas = _find_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404

    # Lock: factura autorizada no se puede re-emitir
    if factura.get("estado_sri") == "autorizada":
        return jsonify({"error": "Factura ya autorizada. Para corregir use nota de credito."}), 409

    emisor = load_emisor() or {}
    if not emisor.get("ruc"):
        return jsonify({"error": "Configura los datos del emisor (RUC) antes de emitir"}), 400
    if not sri_mod.validar_ruc_ecuador(emisor["ruc"]):
        return jsonify({"error": f"RUC del emisor invalido: {emisor['ruc']}"}), 400

    cliente = _find_cliente(factura.get("cliente")) or {}
    cli_ident = (cliente.get("ruc") or cliente.get("cedula") or "").strip()
    if cli_ident:
        if len(cli_ident) == 13 and not sri_mod.validar_ruc_ecuador(cli_ident):
            return jsonify({"error": f"RUC del cliente invalido: {cli_ident}"}), 400
        if len(cli_ident) == 10 and not sri_mod.validar_cedula_ecuador(cli_ident):
            return jsonify({"error": f"Cedula del cliente invalida: {cli_ident}"}), 400

    # Validacion forma de pago (tabla 4 SRI)
    fp = factura.get("forma_pago_codigo") or "20"
    if fp not in sri_mod.FORMAS_PAGO_SRI:
        return jsonify({"error": f"Forma de pago invalida: {fp}. Validas: {list(sri_mod.FORMAS_PAGO_SRI)}"}), 400

    ambiente = os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS)
    simulado = os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes")

    fecha_em = factura.get("fecha_emision") or date.today().isoformat()
    try:
        fecha_dt = datetime.strptime(fecha_em, "%Y-%m-%d")
    except Exception:
        log.warning(f"factura {factura_id}: fecha_emision invalida ({fecha_em}), usando hoy")
        fecha_dt = datetime.now()
    fecha_str = fecha_dt.strftime("%d%m%Y")

    # Secuencial: si la factura ya tiene uno (re-emision tras rechazo), reusar.
    # Si es factura nueva o no tiene secuencial, reservar atomico.
    estab = str(factura.get("establecimiento", "001")).zfill(3)
    pto = str(factura.get("punto_emision", "001")).zfill(3)
    estado_prev = factura.get("estado_sri")
    if factura.get("secuencial") and estado_prev == "rechazada":
        secuencial = str(factura["secuencial"]).zfill(9)
        log.info(f"sri_emitir {factura_id}: re-emision con secuencial existente {secuencial}")
    else:
        from storage import reservar_secuencial_sri
        sec_num = reservar_secuencial_sri(sri_mod.COD_DOC["factura"], estab, pto)
        secuencial = str(sec_num).zfill(9)
        factura["secuencial"] = secuencial
        factura["establecimiento"] = estab
        factura["punto_emision"] = pto
        log.info(f"sri_emitir {factura_id}: secuencial reservado {secuencial}")

    clave = sri_mod.generar_clave_acceso(
        fecha_emision=fecha_str,
        cod_doc=sri_mod.COD_DOC["factura"],
        ruc_emisor=emisor["ruc"],
        ambiente=ambiente,
        estab=estab,
        pto_emision=pto,
        secuencial=secuencial,
    )
    log.info(f"sri_emitir {factura_id}: clave generada {clave} (ambiente={ambiente})")

    factura["clave_acceso"] = clave
    factura["ambiente"] = ambiente

    # build_factura_xml valida reconciliacion totales; si falla, abortamos
    # ANTES de quemar la firma o llamar al SRI.
    try:
        xml_str = sri_mod.build_factura_xml(factura, emisor, cliente, ambiente=ambiente)
    except ValueError as ve:
        log.warning(f"sri_emitir {factura_id}: validacion fallo: {ve}")
        return jsonify({"error": f"Factura invalida: {ve}"}), 422

    xml_firmado, firma_estado = sri_mod.firmar_xml(xml_str)
    factura["xml_firma_estado"] = firma_estado
    log.info(f"sri_emitir {factura_id}: firma estado={firma_estado}")

    # Guard: no enviar al SRI sin firma valida (excepto modo simulado)
    if not firma_estado.startswith("FIRMADO") and not simulado:
        idx = next((i for i, f in enumerate(facturas) if f.get("id") == factura_id), None)
        if idx is not None:
            facturas[idx] = factura
            save_facturas(facturas)
        return jsonify({
            "error": "XML sin firma valida. Configura SRI_CERT_PATH y SRI_CERT_PASSWORD, o SRI_SIMULADO=true.",
            "firma_estado": firma_estado,
        }), 422

    rec = sri_mod.enviar_recepcion(xml_firmado, ambiente=ambiente)
    factura["sri_recepcion"] = rec

    aut = sri_mod.consultar_autorizacion(clave, ambiente=ambiente)
    factura["estado_sri"] = aut.get("estado", "EN_PROCESO")
    factura["autorizacion_sri"] = aut.get("numero_autorizacion", "")
    factura["fecha_autorizacion"] = aut.get("fecha_autorizacion", "")
    factura["sri_mensajes"] = aut.get("mensajes", []) + rec.get("mensajes", [])
    log.info(f"sri_emitir {factura_id}: estado SRI={factura['estado_sri']}")

    try:
        _cfg_set(f"sri:xml:{clave}", {"xml": xml_firmado, "factura_id": factura_id})
    except Exception:
        log.exception(f"sri_emitir {factura_id}: error guardando XML en storage")

    idx = next((i for i, f in enumerate(facturas) if f.get("id") == factura_id), None)
    if idx is not None:
        facturas[idx] = factura
    save_facturas(facturas)

    audit.record("factura", "emitir_sri", factura_id, before=None, after={
        "clave_acceso": clave,
        "estado_sri": factura["estado_sri"],
        "autorizacion_sri": factura["autorizacion_sri"],
        "ambiente": ambiente,
        "total": factura.get("total"),
    })

    return jsonify({
        "ok": True,
        "clave_acceso": clave,
        "estado_sri": factura["estado_sri"],
        "autorizacion_sri": factura["autorizacion_sri"],
        "fecha_autorizacion": factura["fecha_autorizacion"],
        "firma_estado": firma_estado,
        "mensajes": factura["sri_mensajes"],
    })


@sri_bp.route("/api/sri/autorizar/<clave>", methods=["GET"])
@require_auth
def sri_autorizar(clave):
    """Consulta estado de autorizacion al SRI."""
    ambiente = os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS)
    return jsonify(sri_mod.consultar_autorizacion(clave, ambiente=ambiente))


@sri_bp.route("/api/sri/pdf/<path:factura_id>", methods=["GET"])
@require_auth
def sri_pdf(factura_id):
    factura, _ = _find_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404
    emisor = load_emisor() or {}
    cliente = _find_cliente(factura.get("cliente")) or {}

    tmp_path = tempfile.mkstemp(suffix=".pdf")[1]
    try:
        sri_mod.render_factura_pdf(
            factura, emisor, cliente, tmp_path,
            estado_sri=factura.get("estado_sri", "PENDIENTE"),
            numero_autorizacion=factura.get("autorizacion_sri", ""),
            fecha_autorizacion=factura.get("fecha_autorizacion", ""),
        )
        return send_file(tmp_path, as_attachment=True, download_name=f"factura_{factura_id}.pdf", mimetype="application/pdf")
    except Exception as e:
        log.exception(f"sri_pdf {factura_id}: fallo generando PDF")
        return jsonify({"error": f"Error generando PDF: {e}"}), 500


@sri_bp.route("/api/sri/xml/<path:factura_id>", methods=["GET"])
@require_auth
def sri_xml(factura_id):
    factura, _ = _find_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404
    clave = factura.get("clave_acceso")
    if not clave:
        return jsonify({"error": "Factura sin clave de acceso. Emitela primero."}), 400
    try:
        rec = _cfg_get(f"sri:xml:{clave}", None)
        if not rec:
            return jsonify({"error": "XML no encontrado en storage"}), 404
        xml = rec.get("xml", "")
    except Exception as e:
        log.exception(f"sri_xml {factura_id}: error leyendo storage")
        return jsonify({"error": str(e)}), 500

    tmp_path = tempfile.mkstemp(suffix=".xml")[1]
    with open(tmp_path, "w", encoding="utf-8") as fp:
        fp.write(xml)
    return send_file(tmp_path, as_attachment=True, download_name=f"factura_{factura_id}.xml", mimetype="application/xml")


@sri_bp.route("/api/sri/config", methods=["GET"])
@require_auth
def sri_config():
    """Retorna configuracion actual del SRI (sin password del cert)."""
    from storage import consultar_secuencial_actual
    return jsonify({
        "ambiente": os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS),
        "ambiente_nombre": "PRODUCCION" if os.environ.get("SRI_AMBIENTE") == "2" else "PRUEBAS",
        "cert_configurado": bool(os.environ.get("SRI_CERT_PATH") and os.path.exists(os.environ.get("SRI_CERT_PATH", ""))),
        "simulado": os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes"),
        "formas_pago": sri_mod.FORMAS_PAGO_SRI,
        "tipos_identificacion": sri_mod.TIPOS_ID_COMPRADOR,
        "secuenciales_actuales": {
            "factura": consultar_secuencial_actual("01"),
            "nota_credito": consultar_secuencial_actual("04"),
            "nota_debito": consultar_secuencial_actual("05"),
            "guia_remision": consultar_secuencial_actual("06"),
            "retencion": consultar_secuencial_actual("07"),
        },
    })


@sri_bp.route("/api/sri/secuenciales", methods=["GET"])
@require_auth
def get_secuenciales():
    """Consulta el secuencial actual para un cod_doc / establecimiento / punto."""
    from storage import consultar_secuencial_actual
    cod_doc = request.args.get("cod_doc", "01")
    estab = request.args.get("establecimiento", "001")
    pto = request.args.get("punto_emision", "001")
    return jsonify({
        "cod_doc": cod_doc,
        "establecimiento": estab,
        "punto_emision": pto,
        "ultimo": consultar_secuencial_actual(cod_doc, estab, pto),
        "proximo": consultar_secuencial_actual(cod_doc, estab, pto) + 1,
    })


@sri_bp.route("/api/sri/secuenciales", methods=["PUT"])
@require_auth
def set_secuenciales():
    """Inicializa o ajusta un secuencial (uso del contador, no operativo normal).
    Body: { cod_doc, establecimiento, punto_emision, valor }"""
    from storage import setear_secuencial_inicial
    data = request.get_json(force=True) or {}
    cod_doc = data.get("cod_doc")
    estab = data.get("establecimiento", "001")
    pto = data.get("punto_emision", "001")
    valor = int(data.get("valor", 0))
    if not cod_doc or cod_doc not in sri_mod.COD_DOC.values():
        return jsonify({"error": f"cod_doc invalido. Validos: {list(sri_mod.COD_DOC.values())}"}), 400
    if valor < 0:
        return jsonify({"error": "valor debe ser >= 0"}), 400
    setear_secuencial_inicial(cod_doc, estab, pto, valor)
    audit.record("sri_secuencial", "update", f"{cod_doc}-{estab}-{pto}", after={"valor": valor})
    log.info(f"secuencial seteado: cod_doc={cod_doc} estab={estab} pto={pto} valor={valor}")
    return jsonify({"ok": True})
