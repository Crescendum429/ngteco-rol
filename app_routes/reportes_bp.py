"""Blueprint de reportes contables y exportaciones para el contador.

Endpoints:
  GET /api/reportes/ventas-mes/<yyyy-mm>            CSV con todas las facturas
  GET /api/reportes/iva-causado/<yyyy-mm>           Resumen IVA por tarifa
  GET /api/reportes/aging-cobros                    Cuentas por cobrar con aging
  GET /api/reportes/ventas-por-cliente/<yyyy-mm>    Acumulado por cliente
  GET /api/reportes/ventas-por-producto/<yyyy-mm>   Acumulado por producto
  GET /api/reportes/xmls-mes/<yyyy-mm>              ZIP con XMLs autorizados
  GET /api/sri/xml-clave/<clave>                    Descarga XML por clave (7 anios)
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, jsonify, request, send_file

from app_routes._auth import require_auth
from logger import get_logger
from storage import (
    _cfg_get, load_clientes, load_facturas, load_pagos_recibidos, load_productos,
)

log = get_logger("reportes")

reportes_bp = Blueprint("reportes", __name__)


def _dec(v):
    return Decimal(str(v or 0))


def _facturas_del_mes(yyyy_mm):
    """Filtra facturas autorizadas del mes indicado."""
    facs = load_facturas() or []
    out = []
    for f in facs:
        if not isinstance(f, dict):
            continue
        fecha = f.get("fecha_emision") or f.get("fecha_autorizacion", "")[:10]
        if not fecha or not fecha.startswith(yyyy_mm):
            continue
        out.append(f)
    return out


@reportes_bp.route("/api/reportes/ventas-mes/<yyyy_mm>", methods=["GET"])
@require_auth
def ventas_mes(yyyy_mm):
    facs = _facturas_del_mes(yyyy_mm)
    clientes = {c.get("id"): c for c in (load_clientes() or []) if isinstance(c, dict)}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["fecha", "factura_id", "secuencial", "clave_acceso", "cliente_id",
                "cliente_ruc", "cliente_razon_social", "subtotal_12", "subtotal_0",
                "iva", "total", "estado_sri", "forma_pago", "pagada"])
    for f in sorted(facs, key=lambda x: x.get("fecha_emision", "")):
        cli = clientes.get(f.get("cliente"), {})
        w.writerow([
            f.get("fecha_emision", ""), f.get("id", ""), f.get("secuencial", ""),
            f.get("clave_acceso", ""), f.get("cliente", ""),
            cli.get("ruc") or cli.get("cedula") or "", cli.get("razon_social", ""),
            f.get("subtotal_12", 0), f.get("subtotal_0", 0),
            f.get("iva", 0), f.get("total", 0),
            f.get("estado_sri", ""), f.get("forma_pago_codigo", ""),
            "si" if f.get("pagada") else "no",
        ])
    csv_bytes = ("﻿" + out.getvalue()).encode("utf-8")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    tmp.write(csv_bytes); tmp.close()
    return send_file(tmp.name, as_attachment=True,
                     download_name=f"ventas_{yyyy_mm}.csv", mimetype="text/csv")


@reportes_bp.route("/api/reportes/iva-causado/<yyyy_mm>", methods=["GET"])
@require_auth
def iva_causado(yyyy_mm):
    """Resumen IVA causado en el mes (facturas autorizadas, excluye anuladas)."""
    facs = _facturas_del_mes(yyyy_mm)
    facs = [f for f in facs if f.get("estado_sri") not in ("anulada", "borrador")]
    base_12 = _dec(sum(_dec(f.get("subtotal_12", 0)) for f in facs))
    base_0 = _dec(sum(_dec(f.get("subtotal_0", 0)) for f in facs))
    iva = _dec(sum(_dec(f.get("iva", 0)) for f in facs))
    total = _dec(sum(_dec(f.get("total", 0)) for f in facs))
    return jsonify({
        "periodo": yyyy_mm,
        "facturas_autorizadas": len(facs),
        "base_imponible_15": float(base_12.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "base_imponible_0": float(base_0.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "iva_causado": float(iva.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_ventas": float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


@reportes_bp.route("/api/reportes/aging-cobros", methods=["GET"])
@require_auth
def aging_cobros():
    """Cuentas por cobrar segmentadas por antiguedad."""
    facs = load_facturas() or []
    pagos = load_pagos_recibidos() or []
    pagos_por_factura = {}
    for p in pagos:
        if isinstance(p, dict):
            fid = p.get("factura_id")
            pagos_por_factura[fid] = pagos_por_factura.get(fid, Decimal("0")) + _dec(p.get("monto", 0))
    hoy = date.today()
    buckets = {"0_30": [], "31_60": [], "61_90": [], "mas_90": []}
    total_buckets = {"0_30": Decimal("0"), "31_60": Decimal("0"), "61_90": Decimal("0"), "mas_90": Decimal("0")}
    for f in facs:
        if not isinstance(f, dict):
            continue
        if f.get("estado_sri") in ("anulada", "borrador") or f.get("pagada"):
            continue
        total = _dec(f.get("total", 0))
        pagado = pagos_por_factura.get(f.get("id"), Decimal("0"))
        saldo = total - pagado
        if saldo <= Decimal("0.01"):
            continue
        try:
            fe = datetime.strptime(f.get("fecha_emision", "1900-01-01"), "%Y-%m-%d").date()
        except Exception:
            fe = hoy
        dias = (hoy - fe).days
        if dias <= 30:
            b = "0_30"
        elif dias <= 60:
            b = "31_60"
        elif dias <= 90:
            b = "61_90"
        else:
            b = "mas_90"
        buckets[b].append({
            "factura_id": f.get("id"), "cliente": f.get("cliente"),
            "fecha_emision": f.get("fecha_emision"), "dias_vencido": dias,
            "total": float(total), "pagado": float(pagado), "saldo": float(saldo),
        })
        total_buckets[b] += saldo
    return jsonify({
        "fecha_corte": hoy.isoformat(),
        "totales": {k: float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for k, v in total_buckets.items()},
        "buckets": buckets,
    })


@reportes_bp.route("/api/reportes/ventas-por-cliente/<yyyy_mm>", methods=["GET"])
@require_auth
def ventas_por_cliente(yyyy_mm):
    facs = _facturas_del_mes(yyyy_mm)
    facs = [f for f in facs if f.get("estado_sri") != "anulada"]
    clientes = {c.get("id"): c for c in (load_clientes() or []) if isinstance(c, dict)}
    acc = {}
    for f in facs:
        cli_id = f.get("cliente")
        if cli_id not in acc:
            cli = clientes.get(cli_id, {})
            acc[cli_id] = {
                "cliente_id": cli_id,
                "razon_social": cli.get("razon_social", ""),
                "ruc": cli.get("ruc") or cli.get("cedula") or "",
                "facturas": 0,
                "total_sin_iva": Decimal("0"),
                "iva": Decimal("0"),
                "total": Decimal("0"),
            }
        a = acc[cli_id]
        a["facturas"] += 1
        a["total_sin_iva"] += _dec(f.get("subtotal_12", 0)) + _dec(f.get("subtotal_0", 0))
        a["iva"] += _dec(f.get("iva", 0))
        a["total"] += _dec(f.get("total", 0))
    out = []
    for a in acc.values():
        out.append({
            "cliente_id": a["cliente_id"], "razon_social": a["razon_social"], "ruc": a["ruc"],
            "facturas": a["facturas"],
            "total_sin_iva": float(a["total_sin_iva"].quantize(Decimal("0.01"))),
            "iva": float(a["iva"].quantize(Decimal("0.01"))),
            "total": float(a["total"].quantize(Decimal("0.01"))),
        })
    out.sort(key=lambda x: x["total"], reverse=True)
    return jsonify(out)


@reportes_bp.route("/api/reportes/ventas-por-producto/<yyyy_mm>", methods=["GET"])
@require_auth
def ventas_por_producto(yyyy_mm):
    facs = _facturas_del_mes(yyyy_mm)
    facs = [f for f in facs if f.get("estado_sri") != "anulada"]
    productos = load_productos() or {}
    if not isinstance(productos, dict):
        productos = {}
    acc = {}
    for f in facs:
        for it in f.get("items") or []:
            if not isinstance(it, dict):
                continue
            pid = it.get("prod_id")
            if pid not in acc:
                p = productos.get(pid, {})
                acc[pid] = {
                    "prod_id": pid, "nombre": p.get("nombre", pid),
                    "cajas": 0, "subtotal": Decimal("0"), "iva": Decimal("0"),
                }
            a = acc[pid]
            cant = int(it.get("cant_cajas", it.get("cantidad", 0)) or 0)
            sub = _dec(it.get("subtotal", _dec(it.get("cant_cajas", 0)) * _dec(it.get("precio_caja", 0))))
            iva_it = sub * _dec(it.get("iva_pct", 15)) / Decimal("100")
            a["cajas"] += cant
            a["subtotal"] += sub
            a["iva"] += iva_it
    out = []
    for a in acc.values():
        out.append({
            "prod_id": a["prod_id"], "nombre": a["nombre"], "cajas": a["cajas"],
            "subtotal": float(a["subtotal"].quantize(Decimal("0.01"))),
            "iva": float(a["iva"].quantize(Decimal("0.01"))),
            "total": float((a["subtotal"] + a["iva"]).quantize(Decimal("0.01"))),
        })
    out.sort(key=lambda x: x["total"], reverse=True)
    return jsonify(out)


@reportes_bp.route("/api/reportes/xmls-mes/<yyyy_mm>", methods=["GET"])
@require_auth
def xmls_mes(yyyy_mm):
    """ZIP con todos los XMLs autorizados del mes. Util para enviar al contador."""
    facs = _facturas_del_mes(yyyy_mm)
    facs = [f for f in facs if f.get("estado_sri") == "autorizada" and f.get("clave_acceso")]
    if not facs:
        return jsonify({"error": "No hay XMLs autorizados en ese mes"}), 404

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in facs:
            clave = f.get("clave_acceso")
            stored = _cfg_get(f"sri:xml:{clave}", None)
            if isinstance(stored, dict) and stored.get("xml"):
                fname = f"factura_{f.get('id', clave)}_{clave}.xml"
                z.writestr(fname, stored["xml"])
        # Indice CSV
        idx = io.StringIO()
        w = csv.writer(idx)
        w.writerow(["clave_acceso", "factura_id", "fecha", "cliente", "total", "estado"])
        for f in facs:
            w.writerow([f.get("clave_acceso"), f.get("id"), f.get("fecha_emision"),
                        f.get("cliente"), f.get("total"), f.get("estado_sri")])
        z.writestr("indice.csv", "﻿" + idx.getvalue())
    return send_file(tmp.name, as_attachment=True,
                     download_name=f"xmls_solplast_{yyyy_mm}.zip", mimetype="application/zip")


@reportes_bp.route("/api/sri/xml-clave/<clave>", methods=["GET"])
@require_auth
def descargar_xml_por_clave(clave):
    """Descarga el XML autorizado por clave de acceso (conservacion 7 anios)."""
    stored = _cfg_get(f"sri:xml:{clave}", None)
    if not isinstance(stored, dict) or not stored.get("xml"):
        return jsonify({"error": "XML no encontrado para esa clave"}), 404
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8")
    tmp.write(stored["xml"]); tmp.close()
    return send_file(tmp.name, as_attachment=True,
                     download_name=f"comprobante_{clave}.xml", mimetype="application/xml")
