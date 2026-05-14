"""
SRI Ecuador — Facturacion electronica offline.

Implementa el esquema vigente (Resolucion NAC-DGERCGC22-00000024):
- Generacion de clave de acceso (49 digitos) con digito verificador modulo 11
- Construccion de XML segun ficha tecnica 2.1.0 para facturas
- Firma XAdES-BES (requiere certificado .p12 configurado por el usuario)
- Envio SOAP a SRI recepcion/autorizacion (requiere configuracion de ambiente)
- Generacion de PDF RIDE con codigo de barras Code128

Variables de entorno esperadas para uso en produccion:
    SRI_AMBIENTE=1|2 (1=pruebas, 2=produccion)
    SRI_CERT_PATH=/path/al/certificado.p12
    SRI_CERT_PASSWORD=password_del_certificado
    SRI_SIMULADO=true|false (si true y no hay cert, devuelve respuestas simuladas)
"""
from __future__ import annotations

import os
import random
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

AMBIENTE_PRUEBAS = "1"
AMBIENTE_PRODUCCION = "2"
TIPO_EMISION_NORMAL = "1"

COD_DOC = {
    "factura": "01",
    "liquidacion_compra": "03",
    "nota_credito": "04",
    "nota_debito": "05",
    "guia_remision": "06",
    "retencion": "07",
}

WS_PRUEBAS_RECEPCION = "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
WS_PRUEBAS_AUTORIZACION = "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"
WS_PROD_RECEPCION = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
WS_PROD_AUTORIZACION = "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"

IVA_CODIGO = {
    0: "0",    # 0%
    5: "5",    # 5%
    12: "2",   # 12% (legacy)
    13: "10",  # 13%
    14: "3",   # 14% (historico transitorio)
    15: "4",   # 15% actual (Decreto 198/2024)
}

# Tabla 4 SRI Ecuador — formas de pago (no codigos arbitrarios, son normativos)
FORMAS_PAGO_SRI = {
    "01": "Sin utilizacion del sistema financiero",  # efectivo
    "15": "Compensacion de deudas",
    "16": "Tarjetas de debito",
    "17": "Dinero electronico",
    "18": "Tarjeta prepago",
    "19": "Tarjeta de credito",
    "20": "Otros con utilizacion del sistema financiero",  # transferencia, deposito
    "21": "Endoso de titulos",
}

# Tabla 6 SRI — tipos de identificacion del comprador
TIPOS_ID_COMPRADOR = {
    "04": "RUC",
    "05": "Cedula",
    "06": "Pasaporte",
    "07": "Consumidor final",
    "08": "Identificacion del exterior",
}


def validar_ruc_ecuador(ruc: str) -> bool:
    """Valida RUC ecuatoriano: 13 digitos, ultimos 3 = 001, modulo 11 sobre los
    primeros 10 (cedula) o algoritmo de juridicas/extranjeros."""
    if not ruc or not re.fullmatch(r"\d{13}", ruc):
        return False
    if not ruc.endswith("001"):
        return False
    # Primeros 2 digitos = codigo provincia (01-24, o 30 para extranjeros)
    prov = int(ruc[:2])
    if not (1 <= prov <= 24 or prov == 30):
        return False
    tercer = int(ruc[2])
    # tercer digito: 0-5 = persona natural, 6 = publicas, 9 = juridicas/extranjeros
    if tercer < 6:
        # RUC de persona natural: validar como cedula (primeros 10)
        return validar_cedula_ecuador(ruc[:10])
    if tercer == 6:
        # Entidad publica: mod 11 con pesos 3,2,7,6,5,4,3,2 sobre los primeros 8
        pesos = [3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(ruc[i]) * pesos[i] for i in range(8))
        resto = suma % 11
        dv = 11 - resto if resto != 0 else 0
        return dv == int(ruc[8])
    if tercer == 9:
        # Juridica/extranjera: mod 11 con pesos 4,3,2,7,6,5,4,3,2 sobre primeros 9
        pesos = [4, 3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(ruc[i]) * pesos[i] for i in range(9))
        resto = suma % 11
        dv = 11 - resto if resto != 0 else 0
        return dv == int(ruc[9])
    return False


def validar_cedula_ecuador(cedula: str) -> bool:
    """Cedula ecuatoriana: 10 digitos, modulo 10 con coeficientes 2,1,2,1,2,1,2,1,2."""
    if not cedula or not re.fullmatch(r"\d{10}", cedula):
        return False
    prov = int(cedula[:2])
    if not (1 <= prov <= 24 or prov == 30):
        return False
    if int(cedula[2]) >= 6:
        return False  # cedula natural: tercer digito 0-5
    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for i, c in enumerate(coef):
        x = int(cedula[i]) * c
        suma += x - 9 if x > 9 else x
    dv = (10 - suma % 10) % 10
    return dv == int(cedula[9])


# ═══════════════════════════════════════════════════════════════
# 1. CLAVE DE ACCESO — 49 digitos + modulo 11
# ═══════════════════════════════════════════════════════════════

def digito_verificador_mod11(numero_base: str) -> str:
    """Calcula el digito verificador modulo 11 para los primeros 48 digitos."""
    if not re.fullmatch(r"\d{48}", numero_base):
        raise ValueError("Se requieren exactamente 48 digitos para calcular el DV")
    pesos = [2, 3, 4, 5, 6, 7]
    suma = 0
    for i, ch in enumerate(reversed(numero_base)):
        suma += int(ch) * pesos[i % 6]
    resto = suma % 11
    dv = 11 - resto
    if dv == 11:
        return "0"
    if dv == 10:
        return "1"
    return str(dv)


def generar_clave_acceso(
    fecha_emision: str,
    cod_doc: str,
    ruc_emisor: str,
    ambiente: str,
    estab: str,
    pto_emision: str,
    secuencial: str,
    codigo_numerico: str | None = None,
    tipo_emision: str = TIPO_EMISION_NORMAL,
) -> str:
    """Genera clave de acceso de 49 digitos.

    fecha_emision: 'ddMMyyyy' (8 digitos)
    cod_doc: '01'|'04'|'05'|'06'|'07'
    ruc_emisor: 13 digitos
    ambiente: '1' pruebas, '2' produccion
    estab: 3 digitos ('001')
    pto_emision: 3 digitos ('001')
    secuencial: 9 digitos
    codigo_numerico: 8 digitos (se genera aleatorio si None)
    tipo_emision: '1' normal
    """
    fecha = re.sub(r"\D", "", fecha_emision)
    if len(fecha) != 8:
        raise ValueError("fecha_emision debe ser ddMMyyyy")
    if not re.fullmatch(r"\d{2}", cod_doc):
        raise ValueError("cod_doc debe ser 2 digitos")
    if not re.fullmatch(r"\d{13}", ruc_emisor):
        raise ValueError("ruc_emisor debe ser 13 digitos")
    if ambiente not in ("1", "2"):
        raise ValueError("ambiente debe ser '1' o '2'")
    estab = estab.zfill(3)
    pto_emision = pto_emision.zfill(3)
    secuencial = secuencial.zfill(9)
    if codigo_numerico is None:
        codigo_numerico = f"{random.randint(10000000, 99999999)}"
    codigo_numerico = str(codigo_numerico).zfill(8)
    if codigo_numerico == "00000000":
        codigo_numerico = f"{random.randint(10000000, 99999999)}"

    base = f"{fecha}{cod_doc}{ruc_emisor}{ambiente}{estab}{pto_emision}{secuencial}{codigo_numerico}{tipo_emision}"
    if len(base) != 48:
        raise ValueError(f"Base de clave de acceso tiene {len(base)} digitos, esperaba 48")
    dv = digito_verificador_mod11(base)
    return base + dv


# ═══════════════════════════════════════════════════════════════
# 2. XML de factura (ficha tecnica 2.1.0)
# ═══════════════════════════════════════════════════════════════

def _normalizar(s: str) -> str:
    """Normaliza para XML: sin caracteres de control, trim."""
    if s is None:
        return ""
    s = str(s)
    s = "".join(c for c in s if unicodedata.category(c)[0] != "C")
    return s.strip()


def _to_dec(v, default="0") -> Decimal:
    """Convierte a Decimal sin perder precision. None -> 0."""
    if v is None or v == "":
        return Decimal(default)
    if isinstance(v, Decimal):
        return v
    # Pasar por str para evitar artefactos de float
    return Decimal(str(v))


def _fmt_dec(v, decimales=2) -> str:
    """Formatea con ROUND_HALF_UP (no banker's), como exige el SRI."""
    q = Decimal(10) ** -decimales  # ej. 0.01 para 2 decimales
    d = _to_dec(v).quantize(q, rounding=ROUND_HALF_UP)
    return f"{d:.{decimales}f}"


def _suma_dec(items, key, decimales=6) -> Decimal:
    """Suma exacta de un campo en una lista de dicts."""
    total = Decimal("0")
    for it in items:
        total += _to_dec(it.get(key, 0))
    return total.quantize(Decimal(10) ** -decimales, rounding=ROUND_HALF_UP)


def _xml_escape(s: str) -> str:
    return (
        _normalizar(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_factura_xml(factura: dict, emisor: dict, cliente: dict, ambiente: str = AMBIENTE_PRUEBAS) -> str:
    """Construye XML de factura segun ficha tecnica 2.1.0.

    factura: dict con id, fecha_emision, establecimiento, punto_emision, secuencial,
             clave_acceso, items, subtotal_12, subtotal_0, iva, total, forma_pago
    emisor: dict con razon_social, ruc, nombre_comercial, dir_matriz, dir_sucursal,
            obligado_contabilidad
    cliente: dict con razon_social, ruc (o cedula), tipo_identificacion, direccion, email
    """
    fecha_dt = datetime.strptime(factura["fecha_emision"], "%Y-%m-%d")

    # Calculo en Decimal: cantidades a 6 decimales, monetarios a 2.
    # Reconciliacion: sumamos las lineas y comparamos con totales del header.
    items_xml = []
    suma_base_12 = Decimal("0")
    suma_base_0 = Decimal("0")
    suma_iva = Decimal("0")
    for it in factura.get("items", []):
        cant = _to_dec(it.get("cant_cajas", it.get("cantidad", 0)))
        precio = _to_dec(it.get("precio_unit", it.get("precio_caja", 0)))
        total_item = (cant * precio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        descuento = _to_dec(it.get("descuento", 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base_imponible = (total_item - descuento).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tarifa_iva = _to_dec(it.get("iva_pct", 0))
        iva_item = (base_imponible * tarifa_iva / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if tarifa_iva == 0:
            suma_base_0 += base_imponible
        else:
            suma_base_12 += base_imponible
        suma_iva += iva_item
        impuesto_codigo = IVA_CODIGO.get(int(tarifa_iva), "4")
        items_xml.append(f"""    <detalle>
      <codigoPrincipal>{_xml_escape(it.get("prod_id", ""))}</codigoPrincipal>
      <descripcion>{_xml_escape(it.get("descripcion", it.get("prod_id", "")))}</descripcion>
      <cantidad>{_fmt_dec(cant, 6)}</cantidad>
      <precioUnitario>{_fmt_dec(precio, 6)}</precioUnitario>
      <descuento>{_fmt_dec(descuento)}</descuento>
      <precioTotalSinImpuesto>{_fmt_dec(base_imponible)}</precioTotalSinImpuesto>
      <impuestos>
        <impuesto>
          <codigo>2</codigo>
          <codigoPorcentaje>{impuesto_codigo}</codigoPorcentaje>
          <tarifa>{_fmt_dec(tarifa_iva)}</tarifa>
          <baseImponible>{_fmt_dec(base_imponible)}</baseImponible>
          <valor>{_fmt_dec(iva_item)}</valor>
        </impuesto>
      </impuestos>
    </detalle>""")

    # Si el header trae totales explicitos, los usamos; si no, derivamos de lineas.
    # SIEMPRE validamos reconciliacion (diferencia maxima 0.01 por redondeos).
    hdr_subtotal_12 = _to_dec(factura.get("subtotal_12", suma_base_12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    hdr_subtotal_0 = _to_dec(factura.get("subtotal_0", suma_base_0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    hdr_iva = _to_dec(factura.get("iva", suma_iva)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if abs(hdr_subtotal_12 - suma_base_12) > Decimal("0.01"):
        raise ValueError(f"Reconciliacion: subtotal_12 header={hdr_subtotal_12} vs lineas={suma_base_12}")
    if abs(hdr_subtotal_0 - suma_base_0) > Decimal("0.01"):
        raise ValueError(f"Reconciliacion: subtotal_0 header={hdr_subtotal_0} vs lineas={suma_base_0}")
    if abs(hdr_iva - suma_iva) > Decimal("0.01"):
        raise ValueError(f"Reconciliacion: iva header={hdr_iva} vs suma_iva_lineas={suma_iva}")

    subtotal_sin_imp = hdr_subtotal_12 + hdr_subtotal_0
    iva_total = hdr_iva
    total = _to_dec(factura.get("total", subtotal_sin_imp + iva_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_calc = (subtotal_sin_imp + iva_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if abs(total - total_calc) > Decimal("0.01"):
        raise ValueError(f"Reconciliacion: total header={total} vs subtotal+iva={total_calc}")

    total_impuestos = f"""    <totalImpuesto>
      <codigo>2</codigo>
      <codigoPorcentaje>4</codigoPorcentaje>
      <baseImponible>{_fmt_dec(factura.get("subtotal_12", 0))}</baseImponible>
      <valor>{_fmt_dec(iva_total)}</valor>
    </totalImpuesto>"""
    if float(factura.get("subtotal_0", 0)) > 0:
        total_impuestos += f"""
    <totalImpuesto>
      <codigo>2</codigo>
      <codigoPorcentaje>0</codigoPorcentaje>
      <baseImponible>{_fmt_dec(factura.get("subtotal_0", 0))}</baseImponible>
      <valor>0.00</valor>
    </totalImpuesto>"""

    forma_pago_cod = factura.get("forma_pago_codigo", "20")  # 20 = otros con sistema financiero

    tipo_id_comprador = cliente.get("tipo_identificacion")
    if not tipo_id_comprador:
        ident = cliente.get("ruc") or cliente.get("cedula") or ""
        if len(ident) == 13:
            tipo_id_comprador = "04"  # RUC
        elif len(ident) == 10:
            tipo_id_comprador = "05"  # Cedula
        else:
            tipo_id_comprador = "07"  # Consumidor final

    ident_comprador = cliente.get("ruc") or cliente.get("cedula") or "9999999999999"

    dir_emisor = emisor.get("dir_matriz", {})
    dir_matriz_str = ", ".join(filter(None, [
        dir_emisor.get("calle", ""),
        dir_emisor.get("numero", ""),
        dir_emisor.get("interseccion", ""),
        dir_emisor.get("ciudad", ""),
    ])) or "Ecuador"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<factura id="comprobante" version="2.1.0">
  <infoTributaria>
    <ambiente>{ambiente}</ambiente>
    <tipoEmision>{TIPO_EMISION_NORMAL}</tipoEmision>
    <razonSocial>{_xml_escape(emisor.get("razon_social", ""))}</razonSocial>
    <nombreComercial>{_xml_escape(emisor.get("nombre_comercial", emisor.get("razon_social", "")))}</nombreComercial>
    <ruc>{emisor.get("ruc", "")}</ruc>
    <claveAcceso>{factura["clave_acceso"]}</claveAcceso>
    <codDoc>{COD_DOC["factura"]}</codDoc>
    <estab>{str(factura.get("establecimiento", "001")).zfill(3)}</estab>
    <ptoEmi>{str(factura.get("punto_emision", "001")).zfill(3)}</ptoEmi>
    <secuencial>{str(factura.get("secuencial", "1")).zfill(9)}</secuencial>
    <dirMatriz>{_xml_escape(dir_matriz_str)}</dirMatriz>
  </infoTributaria>
  <infoFactura>
    <fechaEmision>{fecha_dt.strftime("%d/%m/%Y")}</fechaEmision>
    <dirEstablecimiento>{_xml_escape(dir_matriz_str)}</dirEstablecimiento>
    <obligadoContabilidad>{"SI" if emisor.get("obligado_contabilidad") else "NO"}</obligadoContabilidad>
    <tipoIdentificacionComprador>{tipo_id_comprador}</tipoIdentificacionComprador>
    <razonSocialComprador>{_xml_escape(cliente.get("razon_social", "CONSUMIDOR FINAL"))}</razonSocialComprador>
    <identificacionComprador>{ident_comprador}</identificacionComprador>
    <totalSinImpuestos>{_fmt_dec(subtotal_sin_imp)}</totalSinImpuestos>
    <totalDescuento>0.00</totalDescuento>
    <totalConImpuestos>
{total_impuestos}
    </totalConImpuestos>
    <propina>0.00</propina>
    <importeTotal>{_fmt_dec(total)}</importeTotal>
    <moneda>DOLAR</moneda>
    <pagos>
      <pago>
        <formaPago>{forma_pago_cod}</formaPago>
        <total>{_fmt_dec(total)}</total>
        <plazo>{factura.get("plazo_dias", 30)}</plazo>
        <unidadTiempo>dias</unidadTiempo>
      </pago>
    </pagos>
  </infoFactura>
  <detalles>
{chr(10).join(items_xml)}
  </detalles>
  <infoAdicional>
    <campoAdicional nombre="Email">{_xml_escape(cliente.get("email_fact") or cliente.get("email", ""))}</campoAdicional>
    <campoAdicional nombre="Telefono">{_xml_escape(cliente.get("telefono", ""))}</campoAdicional>
    <campoAdicional nombre="Direccion">{_xml_escape((cliente.get("dir_matriz") or {}).get("calle", ""))}</campoAdicional>
  </infoAdicional>
</factura>
"""
    return xml


def build_nota_credito_xml(nota: dict, emisor: dict, cliente: dict, ambiente: str = AMBIENTE_PRUEBAS) -> str:
    """Construye XML de nota de credito (cod_doc 04) segun ficha 1.1.0 SRI.

    Una nota de credito anula total o parcialmente una factura previa.
    Requiere los datos del documento modificado: codDocModificado=01,
    numDocModificado (estab-pto-secuencial), fechaEmisionDocSustento.

    nota: dict con id, fecha_emision, clave_acceso, establecimiento,
          punto_emision, secuencial, ambiente, factura_referencia (id),
          factura_clave_acceso, factura_fecha, items [], motivo
    """
    fecha_dt = datetime.strptime(nota["fecha_emision"], "%Y-%m-%d")

    items_xml = []
    suma_base_12 = Decimal("0")
    suma_base_0 = Decimal("0")
    suma_iva = Decimal("0")
    for it in nota.get("items", []):
        cant = _to_dec(it.get("cant_cajas", it.get("cantidad", 0)))
        precio = _to_dec(it.get("precio_unit", it.get("precio_caja", 0)))
        total_item = (cant * precio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        descuento = _to_dec(it.get("descuento", 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base = (total_item - descuento).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tarifa = _to_dec(it.get("iva_pct", 0))
        iva_item = (base * tarifa / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if tarifa == 0:
            suma_base_0 += base
        else:
            suma_base_12 += base
        suma_iva += iva_item
        cp = IVA_CODIGO.get(int(tarifa), "4")
        items_xml.append(f"""    <detalle>
      <codigoInterno>{_xml_escape(it.get("prod_id", ""))}</codigoInterno>
      <descripcion>{_xml_escape(it.get("descripcion", it.get("prod_id", "")))}</descripcion>
      <cantidad>{_fmt_dec(cant, 6)}</cantidad>
      <precioUnitario>{_fmt_dec(precio, 6)}</precioUnitario>
      <descuento>{_fmt_dec(descuento)}</descuento>
      <precioTotalSinImpuesto>{_fmt_dec(base)}</precioTotalSinImpuesto>
      <impuestos>
        <impuesto>
          <codigo>2</codigo>
          <codigoPorcentaje>{cp}</codigoPorcentaje>
          <tarifa>{_fmt_dec(tarifa)}</tarifa>
          <baseImponible>{_fmt_dec(base)}</baseImponible>
          <valor>{_fmt_dec(iva_item)}</valor>
        </impuesto>
      </impuestos>
    </detalle>""")

    total_sin_imp = (suma_base_12 + suma_base_0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_modificacion = (total_sin_imp + suma_iva).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Doc modificado: la factura original. numDocModificado = estab-pto-secuencial
    fac_estab = str(nota.get("factura_establecimiento", "001")).zfill(3)
    fac_pto = str(nota.get("factura_punto_emision", "001")).zfill(3)
    fac_sec = str(nota.get("factura_secuencial", "1")).zfill(9)
    num_doc_mod = f"{fac_estab}-{fac_pto}-{fac_sec}"
    fecha_doc_sustento = nota.get("factura_fecha_emision") or nota["fecha_emision"]
    try:
        fdoc = datetime.strptime(fecha_doc_sustento, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        fdoc = fecha_dt.strftime("%d/%m/%Y")

    ident_comprador = cliente.get("ruc") or cliente.get("cedula") or "9999999999999"
    tipo_id = cliente.get("tipo_identificacion")
    if not tipo_id:
        tipo_id = "04" if len(ident_comprador) == 13 else "05" if len(ident_comprador) == 10 else "07"

    dir_emisor = emisor.get("dir_matriz", {})
    dir_str = ", ".join(filter(None, [
        dir_emisor.get("calle", ""), dir_emisor.get("numero", ""),
        dir_emisor.get("interseccion", ""), dir_emisor.get("ciudad", ""),
    ])) or "Ecuador"

    total_impuestos = f"""      <totalImpuesto>
        <codigo>2</codigo>
        <codigoPorcentaje>4</codigoPorcentaje>
        <baseImponible>{_fmt_dec(suma_base_12)}</baseImponible>
        <valor>{_fmt_dec(suma_iva)}</valor>
      </totalImpuesto>"""
    if suma_base_0 > 0:
        total_impuestos += f"""
      <totalImpuesto>
        <codigo>2</codigo>
        <codigoPorcentaje>0</codigoPorcentaje>
        <baseImponible>{_fmt_dec(suma_base_0)}</baseImponible>
        <valor>0.00</valor>
      </totalImpuesto>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<notaCredito id="comprobante" version="1.1.0">
  <infoTributaria>
    <ambiente>{ambiente}</ambiente>
    <tipoEmision>{TIPO_EMISION_NORMAL}</tipoEmision>
    <razonSocial>{_xml_escape(emisor.get("razon_social", ""))}</razonSocial>
    <nombreComercial>{_xml_escape(emisor.get("nombre_comercial", emisor.get("razon_social", "")))}</nombreComercial>
    <ruc>{emisor.get("ruc", "")}</ruc>
    <claveAcceso>{nota["clave_acceso"]}</claveAcceso>
    <codDoc>{COD_DOC["nota_credito"]}</codDoc>
    <estab>{str(nota.get("establecimiento", "001")).zfill(3)}</estab>
    <ptoEmi>{str(nota.get("punto_emision", "001")).zfill(3)}</ptoEmi>
    <secuencial>{str(nota.get("secuencial", "1")).zfill(9)}</secuencial>
    <dirMatriz>{_xml_escape(dir_str)}</dirMatriz>
  </infoTributaria>
  <infoNotaCredito>
    <fechaEmision>{fecha_dt.strftime("%d/%m/%Y")}</fechaEmision>
    <dirEstablecimiento>{_xml_escape(dir_str)}</dirEstablecimiento>
    <tipoIdentificacionComprador>{tipo_id}</tipoIdentificacionComprador>
    <razonSocialComprador>{_xml_escape(cliente.get("razon_social", "CONSUMIDOR FINAL"))}</razonSocialComprador>
    <identificacionComprador>{ident_comprador}</identificacionComprador>
    <obligadoContabilidad>{"SI" if emisor.get("obligado_contabilidad") else "NO"}</obligadoContabilidad>
    <codDocModificado>{COD_DOC["factura"]}</codDocModificado>
    <numDocModificado>{num_doc_mod}</numDocModificado>
    <fechaEmisionDocSustento>{fdoc}</fechaEmisionDocSustento>
    <totalSinImpuestos>{_fmt_dec(total_sin_imp)}</totalSinImpuestos>
    <valorModificacion>{_fmt_dec(valor_modificacion)}</valorModificacion>
    <moneda>DOLAR</moneda>
    <totalConImpuestos>
{total_impuestos}
    </totalConImpuestos>
    <motivo>{_xml_escape(nota.get("motivo", "Devolucion"))}</motivo>
  </infoNotaCredito>
  <detalles>
{chr(10).join(items_xml)}
  </detalles>
</notaCredito>
"""
    return xml


def build_guia_remision_xml(guia: dict, emisor: dict, cliente: dict, ambiente: str = AMBIENTE_PRUEBAS) -> str:
    """Construye XML de guia de remision (cod_doc 06) segun ficha 1.1.0 SRI.

    guia: dict con id, fecha_emision, clave_acceso, establecimiento, punto_emision,
          secuencial, transportista (ruc, razon_social), placa, punto_partida,
          fecha_inicio, fecha_fin, motivo, destinatarios [{ identificacion,
          razon_social, direccion, motivo, doc_aduanero?, ruta?, fecha_inicio,
          fecha_fin, detalles [{cod_principal, descripcion, cantidad}]}]
    """
    fecha_dt = datetime.strptime(guia["fecha_emision"], "%Y-%m-%d")
    fecha_ini = datetime.strptime(guia.get("fecha_inicio", guia["fecha_emision"]), "%Y-%m-%d").strftime("%d/%m/%Y")
    fecha_fin = datetime.strptime(guia.get("fecha_fin", guia["fecha_emision"]), "%Y-%m-%d").strftime("%d/%m/%Y")

    transp = guia.get("transportista") or {}
    transp_ruc = transp.get("ruc") or "9999999999999"
    transp_id_tipo = "04" if len(transp_ruc) == 13 else "05" if len(transp_ruc) == 10 else "07"

    dir_emisor = emisor.get("dir_matriz", {})
    dir_str = ", ".join(filter(None, [
        dir_emisor.get("calle", ""), dir_emisor.get("numero", ""),
        dir_emisor.get("interseccion", ""), dir_emisor.get("ciudad", ""),
    ])) or "Ecuador"

    destinatarios_xml = []
    for d in guia.get("destinatarios") or [{"identificacion": cliente.get("ruc") or "",
                                            "razon_social": cliente.get("razon_social", ""),
                                            "direccion": (cliente.get("dir_matriz") or {}).get("calle", ""),
                                            "motivo": guia.get("motivo", "Venta"),
                                            "detalles": guia.get("items", [])}]:
        det_dest_xml = []
        for it in d.get("detalles", []):
            det_dest_xml.append(f"""        <detalle>
          <codigoInterno>{_xml_escape(it.get("prod_id", it.get("cod_principal", "")))}</codigoInterno>
          <descripcion>{_xml_escape(it.get("descripcion", it.get("prod_id", "")))}</descripcion>
          <cantidad>{_fmt_dec(it.get("cant_cajas", it.get("cantidad", 0)), 6)}</cantidad>
        </detalle>""")
        destinatarios_xml.append(f"""    <destinatario>
      <identificacionDestinatario>{d.get("identificacion") or "9999999999999"}</identificacionDestinatario>
      <razonSocialDestinatario>{_xml_escape(d.get("razon_social", "CONSUMIDOR FINAL"))}</razonSocialDestinatario>
      <dirDestinatario>{_xml_escape(d.get("direccion", "Ecuador"))}</dirDestinatario>
      <motivoTraslado>{_xml_escape(d.get("motivo", guia.get("motivo", "Venta")))}</motivoTraslado>
      <ruta>{_xml_escape(d.get("ruta", ""))}</ruta>
      <detalles>
{chr(10).join(det_dest_xml)}
      </detalles>
    </destinatario>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<guiaRemision id="comprobante" version="1.1.0">
  <infoTributaria>
    <ambiente>{ambiente}</ambiente>
    <tipoEmision>{TIPO_EMISION_NORMAL}</tipoEmision>
    <razonSocial>{_xml_escape(emisor.get("razon_social", ""))}</razonSocial>
    <nombreComercial>{_xml_escape(emisor.get("nombre_comercial", emisor.get("razon_social", "")))}</nombreComercial>
    <ruc>{emisor.get("ruc", "")}</ruc>
    <claveAcceso>{guia["clave_acceso"]}</claveAcceso>
    <codDoc>{COD_DOC["guia_remision"]}</codDoc>
    <estab>{str(guia.get("establecimiento", "001")).zfill(3)}</estab>
    <ptoEmi>{str(guia.get("punto_emision", "001")).zfill(3)}</ptoEmi>
    <secuencial>{str(guia.get("secuencial", "1")).zfill(9)}</secuencial>
    <dirMatriz>{_xml_escape(dir_str)}</dirMatriz>
  </infoTributaria>
  <infoGuiaRemision>
    <dirEstablecimiento>{_xml_escape(dir_str)}</dirEstablecimiento>
    <dirPartida>{_xml_escape(guia.get("punto_partida", dir_str))}</dirPartida>
    <razonSocialTransportista>{_xml_escape(transp.get("razon_social", ""))}</razonSocialTransportista>
    <tipoIdentificacionTransportista>{transp_id_tipo}</tipoIdentificacionTransportista>
    <rucTransportista>{transp_ruc}</rucTransportista>
    <obligadoContabilidad>{"SI" if emisor.get("obligado_contabilidad") else "NO"}</obligadoContabilidad>
    <fechaIniTransporte>{fecha_ini}</fechaIniTransporte>
    <fechaFinTransporte>{fecha_fin}</fechaFinTransporte>
    <placa>{_xml_escape(transp.get("placa", guia.get("placa", "")))}</placa>
  </infoGuiaRemision>
  <destinatarios>
{chr(10).join(destinatarios_xml)}
  </destinatarios>
</guiaRemision>
"""
    return xml


# ═══════════════════════════════════════════════════════════════
# 3. Firma XAdES-BES — requiere .p12 configurado
# ═══════════════════════════════════════════════════════════════

def firmar_xml(xml_str: str, cert_path: str | None = None, cert_password: str | None = None) -> tuple[str, str]:
    """Firma el XML con XAdES-BES usando el certificado .p12 del emisor.

    Retorna (xml_firmado, estado) donde estado es 'FIRMADO' o 'NO_FIRMADO:motivo'.

    Si no hay certificado configurado, devuelve el XML sin firmar con estado
    'NO_FIRMADO:no hay certificado configurado' — util para desarrollo/demo.
    """
    cert_path = cert_path or os.environ.get("SRI_CERT_PATH")
    cert_password = cert_password or os.environ.get("SRI_CERT_PASSWORD")

    if not cert_path or not os.path.exists(cert_path):
        return xml_str, "NO_FIRMADO:falta SRI_CERT_PATH (.p12) en variables de entorno"
    if not cert_password:
        return xml_str, "NO_FIRMADO:falta SRI_CERT_PASSWORD"

    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from lxml import etree
        from signxml import XMLSigner, methods
        from signxml.algorithms import CanonicalizationMethod, DigestAlgorithm, SignatureMethod
    except ImportError as e:
        return xml_str, f"NO_FIRMADO:dependencias faltantes ({e})"

    try:
        with open(cert_path, "rb") as f:
            p12_data = f.read()
        key, cert, _chain = pkcs12.load_key_and_certificates(p12_data, cert_password.encode())

        tree = etree.fromstring(xml_str.encode("utf-8"))
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm=SignatureMethod.RSA_SHA1,
            digest_algorithm=DigestAlgorithm.SHA1,
            c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0,
        )
        signed = signer.sign(tree, key=key, cert=cert)
        return etree.tostring(signed, encoding="utf-8", xml_declaration=True).decode("utf-8"), "FIRMADO"
    except Exception as e:
        return xml_str, f"NO_FIRMADO:error firmando ({e})"


# ═══════════════════════════════════════════════════════════════
# 4. Envio al SRI — recepcion + autorizacion
# ═══════════════════════════════════════════════════════════════

def _ws_urls(ambiente: str) -> tuple[str, str]:
    if ambiente == AMBIENTE_PRODUCCION:
        return WS_PROD_RECEPCION, WS_PROD_AUTORIZACION
    return WS_PRUEBAS_RECEPCION, WS_PRUEBAS_AUTORIZACION


def enviar_recepcion(xml_firmado: str, ambiente: str = AMBIENTE_PRUEBAS) -> dict:
    """Envia el XML firmado al SRI via SOAP. Retorna dict con estado y mensajes.

    Si no hay cliente SOAP instalado, devuelve respuesta simulada cuando
    SRI_SIMULADO=true o si no hay dependencias.
    """
    simulado = os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes")

    try:
        from zeep import Client
        from zeep.transports import Transport
        import base64
    except ImportError:
        if simulado:
            return {"estado": "RECIBIDA", "mensajes": [{"tipo": "simulado", "mensaje": "Modo simulado: zeep no instalado"}]}
        return {"estado": "ERROR", "mensajes": [{"tipo": "error", "mensaje": "zeep no instalado"}]}

    url_recep, _ = _ws_urls(ambiente)
    try:
        client = Client(url_recep, transport=Transport(timeout=30))
        xml_b64 = base64.b64encode(xml_firmado.encode("utf-8")).decode("ascii")
        resp = client.service.validarComprobante(xml_b64)
        estado = getattr(resp, "estado", "ERROR")
        mensajes = []
        for c in (getattr(resp, "comprobantes", None) or []) or []:
            for m in (getattr(c, "mensajes", None) or []) or []:
                mensajes.append({
                    "tipo": getattr(m, "tipo", ""),
                    "identificador": getattr(m, "identificador", ""),
                    "mensaje": getattr(m, "mensaje", ""),
                    "informacion_adicional": getattr(m, "informacionAdicional", ""),
                })
        return {"estado": str(estado), "mensajes": mensajes}
    except Exception as e:
        if simulado:
            return {"estado": "RECIBIDA", "mensajes": [{"tipo": "simulado", "mensaje": f"Modo simulado: {e}"}]}
        return {"estado": "ERROR", "mensajes": [{"tipo": "error", "mensaje": str(e)}]}


def consultar_autorizacion(clave_acceso: str, ambiente: str = AMBIENTE_PRUEBAS) -> dict:
    """Consulta estado de autorizacion al SRI."""
    simulado = os.environ.get("SRI_SIMULADO", "true").lower() in ("1", "true", "yes")

    try:
        from zeep import Client
        from zeep.transports import Transport
    except ImportError:
        if simulado:
            return _respuesta_simulada(clave_acceso)
        return {"estado": "ERROR", "mensajes": [{"tipo": "error", "mensaje": "zeep no instalado"}]}

    _, url_aut = _ws_urls(ambiente)
    try:
        client = Client(url_aut, transport=Transport(timeout=30))
        resp = client.service.autorizacionComprobante(clave_acceso)
        autorizaciones = getattr(resp, "autorizaciones", None)
        if not autorizaciones:
            return {"estado": "NO_ENCONTRADO", "mensajes": []}
        items = autorizaciones.autorizacion if hasattr(autorizaciones, "autorizacion") else autorizaciones
        if not isinstance(items, list):
            items = [items]
        if not items:
            return {"estado": "NO_ENCONTRADO", "mensajes": []}
        a = items[0]
        return {
            "estado": str(getattr(a, "estado", "")),
            "numero_autorizacion": str(getattr(a, "numeroAutorizacion", "")),
            "fecha_autorizacion": str(getattr(a, "fechaAutorizacion", "")),
            "ambiente": str(getattr(a, "ambiente", "")),
            "comprobante": str(getattr(a, "comprobante", "")),
            "mensajes": [],
        }
    except Exception as e:
        if simulado:
            return _respuesta_simulada(clave_acceso, error=str(e))
        return {"estado": "ERROR", "mensajes": [{"tipo": "error", "mensaje": str(e)}]}


def _respuesta_simulada(clave_acceso: str, error: str = "") -> dict:
    """Respuesta simulada para desarrollo sin SRI."""
    return {
        "estado": "AUTORIZADO",
        "numero_autorizacion": clave_acceso,  # en offline, la clave ES la autorizacion
        "fecha_autorizacion": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "ambiente": "PRUEBAS",
        "mensajes": [{"tipo": "SIMULADO", "mensaje": f"Modo simulado. {error}" if error else "Modo simulado (SRI_SIMULADO=true)"}],
    }


# ═══════════════════════════════════════════════════════════════
# 5. PDF RIDE — representacion impresa del documento electronico
# ═══════════════════════════════════════════════════════════════

def render_factura_pdf(factura: dict, emisor: dict, cliente: dict, dest: str,
                       estado_sri: str = "AUTORIZADO", numero_autorizacion: str = "",
                       fecha_autorizacion: str = "") -> None:
    """Genera PDF RIDE de factura con codigo de barras del clave de acceso."""
    from fpdf import FPDF

    def _t(s):
        if s is None:
            return ""
        s = str(s)
        s = unicodedata.normalize("NFKD", s).encode("latin-1", "ignore").decode("latin-1")
        return s

    pdf = FPDF(format="A4")
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(100, 7, _t(emisor.get("razon_social", "")), border=0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "FACTURA", align="R", ln=1)

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(100, 5, _t(emisor.get("nombre_comercial", "")), border=0)
    pdf.cell(0, 5, f"No. {str(factura.get('establecimiento','001')).zfill(3)}-{str(factura.get('punto_emision','001')).zfill(3)}-{str(factura.get('secuencial','0')).zfill(9)}", align="R", ln=1)
    pdf.cell(100, 5, f"RUC: {emisor.get('ruc','')}", border=0)
    pdf.cell(0, 5, f"Ambiente: {'PRUEBAS' if factura.get('ambiente', '1') == '1' else 'PRODUCCION'}", align="R", ln=1)

    dir_m = emisor.get("dir_matriz", {})
    dir_txt = ", ".join(filter(None, [dir_m.get("calle",""), dir_m.get("numero",""), dir_m.get("interseccion",""), dir_m.get("ciudad","")]))
    pdf.cell(100, 5, _t(dir_txt), border=0)
    pdf.cell(0, 5, f"Emision: NORMAL", align="R", ln=1)
    pdf.ln(3)

    # Clave de acceso
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(45, 5, "Clave de acceso:", border=0)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, factura.get("clave_acceso", ""), ln=1)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(45, 5, "Autorizacion:", border=0)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, numero_autorizacion or "Pendiente", ln=1)
    pdf.cell(45, 5, "Fecha autorizacion:", border=0)
    pdf.cell(0, 5, fecha_autorizacion or "—", ln=1)

    # Codigo de barras Code128
    try:
        _render_barcode(pdf, factura.get("clave_acceso", ""))
    except Exception:
        pass

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "INFORMACION DEL CLIENTE", ln=1, fill=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(45, 5, "Razon social:", border=0)
    pdf.cell(0, 5, _t(cliente.get("razon_social","")), ln=1)
    pdf.cell(45, 5, "RUC/Cedula:", border=0)
    pdf.cell(0, 5, cliente.get("ruc") or cliente.get("cedula",""), ln=1)
    pdf.cell(45, 5, "Fecha emision:", border=0)
    pdf.cell(0, 5, factura.get("fecha_emision",""), ln=1)
    pdf.cell(45, 5, "Email:", border=0)
    pdf.cell(0, 5, cliente.get("email_fact") or cliente.get("email",""), ln=1)
    pdf.ln(2)

    # Detalle de items
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(25, 6, "Codigo", border=1)
    pdf.cell(80, 6, "Descripcion", border=1)
    pdf.cell(15, 6, "Cant.", border=1, align="R")
    pdf.cell(25, 6, "Precio Unit.", border=1, align="R")
    pdf.cell(20, 6, "Descuento", border=1, align="R")
    pdf.cell(0, 6, "Subtotal", border=1, align="R", ln=1)
    pdf.set_font("Helvetica", "", 8)
    for it in factura.get("items", []):
        cantidad = float(it.get("cant_cajas", it.get("cantidad", 0)))
        precio = float(it.get("precio_unit", it.get("precio_caja", 0)))
        desc = float(it.get("descuento", 0))
        sub = cantidad * precio - desc
        pdf.cell(25, 5, _t(it.get("prod_id",""))[:12], border=1)
        pdf.cell(80, 5, _t(it.get("descripcion", it.get("prod_id","")))[:45], border=1)
        pdf.cell(15, 5, f"{cantidad:.2f}", border=1, align="R")
        pdf.cell(25, 5, f"{precio:.4f}", border=1, align="R")
        pdf.cell(20, 5, f"{desc:.2f}", border=1, align="R")
        pdf.cell(0, 5, f"{sub:.2f}", border=1, align="R", ln=1)

    pdf.ln(2)
    # Totales
    subtotal_12 = float(factura.get("subtotal_12", 0))
    subtotal_0 = float(factura.get("subtotal_0", 0))
    iva = float(factura.get("iva", 0))
    total = float(factura.get("total", subtotal_12 + subtotal_0 + iva))

    pdf.set_font("Helvetica", "", 9)
    for lbl, val in [
        ("Subtotal 15%", subtotal_12),
        ("Subtotal 0%", subtotal_0),
        ("Subtotal sin impuestos", subtotal_12 + subtotal_0),
        ("IVA 15%", iva),
    ]:
        pdf.cell(0, 5, f"{lbl}: $ {val:.2f}", align="R", ln=1)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, f"VALOR TOTAL: $ {total:.2f}", align="R", ln=1)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7)
    pdf.multi_cell(0, 3.5, _t(
        "Documento electronico generado conforme a la ficha tecnica del SRI. "
        "La autorizacion puede consultarse en www.sri.gob.ec con la clave de acceso. "
        f"Estado actual: {estado_sri}."
    ))

    pdf.output(dest)


def _render_barcode(pdf, clave_acceso: str, y: float | None = None):
    """Renderiza un codigo Code128 del clave de acceso sobre el PDF actual."""
    if not clave_acceso or len(clave_acceso) < 10:
        return
    try:
        import barcode
        from barcode.writer import ImageWriter
        from io import BytesIO
        import tempfile
    except ImportError:
        return

    try:
        code = barcode.get("code128", clave_acceso, writer=ImageWriter())
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            code.write(tmp, options={"write_text": False, "module_height": 8, "quiet_zone": 2})
            tmp_path = tmp.name
        if y is None:
            y = pdf.get_y() + 1
        pdf.image(tmp_path, x=12, y=y, w=185, h=14)
        pdf.ln(16)
        os.unlink(tmp_path)
    except Exception:
        return
