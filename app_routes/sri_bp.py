"""Blueprint de endpoints SRI (facturacion electronica Ecuador)."""
import os
import tempfile
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, jsonify, send_file, session

import sri as sri_mod
from logger import get_logger
from storage import _cfg_get, _cfg_set, load_clientes, load_emisor, load_facturas, save_facturas

log = get_logger("sri")

sri_bp = Blueprint("sri", __name__)


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if os.environ.get("APP_PASSWORD") and not session.get("_auth"):
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return decorated


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
@_require_auth
def sri_emitir(factura_id):
    """Genera clave de acceso, XML, firma y envia al SRI. Actualiza la factura."""
    factura, facturas = _find_factura(factura_id)
    if not factura:
        return jsonify({"error": "Factura no encontrada"}), 404

    emisor = load_emisor() or {}
    if not emisor.get("ruc"):
        return jsonify({"error": "Configura los datos del emisor (RUC) antes de emitir"}), 400

    cliente = _find_cliente(factura.get("cliente")) or {}
    ambiente = os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS)

    fecha_em = factura.get("fecha_emision") or date.today().isoformat()
    try:
        fecha_dt = datetime.strptime(fecha_em, "%Y-%m-%d")
    except Exception:
        log.warning(f"factura {factura_id}: fecha_emision invalida ({fecha_em}), usando hoy")
        fecha_dt = datetime.now()
    fecha_str = fecha_dt.strftime("%d%m%Y")

    clave = sri_mod.generar_clave_acceso(
        fecha_emision=fecha_str,
        cod_doc=sri_mod.COD_DOC["factura"],
        ruc_emisor=emisor["ruc"],
        ambiente=ambiente,
        estab=str(factura.get("establecimiento", "001")),
        pto_emision=str(factura.get("punto_emision", "001")),
        secuencial=str(factura.get("secuencial", "1")),
    )
    log.info(f"sri_emitir {factura_id}: clave generada {clave} (ambiente={ambiente})")

    factura["clave_acceso"] = clave
    factura["ambiente"] = ambiente

    xml_str = sri_mod.build_factura_xml(factura, emisor, cliente, ambiente=ambiente)
    xml_firmado, firma_estado = sri_mod.firmar_xml(xml_str)
    factura["xml_firma_estado"] = firma_estado
    log.info(f"sri_emitir {factura_id}: firma estado={firma_estado}")

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
@_require_auth
def sri_autorizar(clave):
    """Consulta estado de autorizacion al SRI."""
    ambiente = os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS)
    return jsonify(sri_mod.consultar_autorizacion(clave, ambiente=ambiente))


@sri_bp.route("/api/sri/pdf/<path:factura_id>", methods=["GET"])
@_require_auth
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
@_require_auth
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
@_require_auth
def sri_config():
    """Retorna configuracion actual del SRI (sin password del cert)."""
    return jsonify({
        "ambiente": os.environ.get("SRI_AMBIENTE", sri_mod.AMBIENTE_PRUEBAS),
        "ambiente_nombre": "PRODUCCION" if os.environ.get("SRI_AMBIENTE") == "2" else "PRUEBAS",
        "cert_configurado": bool(os.environ.get("SRI_CERT_PATH") and os.path.exists(os.environ.get("SRI_CERT_PATH", ""))),
        "simulado": os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes"),
    })
