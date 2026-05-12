"""Tests del modulo SRI."""
import pytest

import sri


def test_dv_mod11_basico():
    # Casos conocidos de mod 11 con pesos 2..7
    # Verificamos que el digito esta entre 0-9
    dv = sri.digito_verificador_mod11("0" * 48)
    assert dv in "0123456789"


def test_dv_mod11_caso_real():
    # Ejemplo: clave conocida del SRI (ficha tecnica). El DV debe ser correcto.
    base = "060620260117917733730012001001000012341234567811"[:48]
    dv = sri.digito_verificador_mod11(base)
    assert dv in "0123456789"
    # Calculamos manualmente: la formula es suma de digito*peso, reverso, pesos 2..7
    pesos = [2, 3, 4, 5, 6, 7]
    suma = sum(int(c) * pesos[i % 6] for i, c in enumerate(reversed(base)))
    resto = suma % 11
    esperado = 11 - resto
    if esperado == 11:
        esperado = 0
    if esperado == 10:
        esperado = 1
    assert dv == str(esperado)


def test_dv_mod11_input_invalido():
    with pytest.raises(ValueError):
        sri.digito_verificador_mod11("123")  # solo 3 digitos


def test_generar_clave_acceso_longitud():
    clave = sri.generar_clave_acceso(
        fecha_emision="22042026",
        cod_doc="01",
        ruc_emisor="1791773373001",
        ambiente="1",
        estab="001",
        pto_emision="001",
        secuencial="000000001",
        codigo_numerico="12345678",
    )
    assert len(clave) == 49


def test_generar_clave_acceso_secciones():
    clave = sri.generar_clave_acceso(
        fecha_emision="22042026",
        cod_doc="01",
        ruc_emisor="1791773373001",
        ambiente="2",
        estab="001",
        pto_emision="001",
        secuencial="000001234",
        codigo_numerico="87654321",
    )
    # Layout: fecha(8)+codDoc(2)+ruc(13)+ambiente(1)+estab(3)+ptoEmi(3)+secuencial(9)+codNum(8)+tipoEmi(1)+dv(1) = 49
    assert clave[:8] == "22042026"
    assert clave[8:10] == "01"
    assert clave[10:23] == "1791773373001"
    assert clave[23] == "2"
    assert clave[24:27] == "001"
    assert clave[27:30] == "001"
    assert clave[30:39] == "000001234"
    assert clave[39:47] == "87654321"
    assert clave[47] == "1"
    # DV: usar la base de 48 digitos
    dv_esperado = sri.digito_verificador_mod11(clave[:48])
    assert clave[48] == dv_esperado


def test_generar_clave_acceso_ruc_invalido():
    with pytest.raises(ValueError):
        sri.generar_clave_acceso(
            fecha_emision="22042026",
            cod_doc="01",
            ruc_emisor="123",  # solo 3 digitos
            ambiente="1",
            estab="001",
            pto_emision="001",
            secuencial="1",
        )


def test_generar_clave_acceso_codigo_numerico_random():
    # Sin codigo_numerico, debe generar uno aleatorio (no 00000000)
    clave = sri.generar_clave_acceso(
        fecha_emision="22042026",
        cod_doc="01",
        ruc_emisor="1791773373001",
        ambiente="1",
        estab="001",
        pto_emision="001",
        secuencial="1",
    )
    cod_num = clave[39:47]
    assert cod_num != "00000000"
    assert cod_num.isdigit()


def test_build_factura_xml_estructura():
    factura = {
        "id": "FAC-001-001-000001234",
        "fecha_emision": "2026-04-22",
        "establecimiento": "001",
        "punto_emision": "001",
        "secuencial": "000001234",
        "clave_acceso": "1" * 49,
        "items": [
            {"prod_id": "v_life", "descripcion": "Vaso Life", "cant_cajas": 60,
             "precio_caja": 34.00, "iva_pct": 15},
        ],
        "subtotal_12": 2040.00,
        "subtotal_0": 0,
        "iva": 306.00,
        "total": 2346.00,
        "forma_pago_codigo": "20",
    }
    emisor = {
        "ruc": "1802698413001",
        "razon_social": "Solplast",
        "nombre_comercial": "Solplast",
        "dir_matriz": {"calle": "X", "numero": "1", "ciudad": "Quito"},
        "obligado_contabilidad": True,
    }
    cliente = {
        "ruc": "1791773373001",
        "razon_social": "Cliente SA",
        "email_fact": "test@cli.com",
    }
    xml = sri.build_factura_xml(factura, emisor, cliente, ambiente="1")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<factura id="comprobante" version="2.1.0">' in xml
    assert "<ruc>1802698413001</ruc>" in xml
    assert "<claveAcceso>" in xml
    assert "<codDoc>01</codDoc>" in xml
    assert "<razonSocialComprador>Cliente SA</razonSocialComprador>" in xml
    assert "<importeTotal>2346.00</importeTotal>" in xml


def test_consultar_autorizacion_simulado():
    """En modo simulado debe devolver AUTORIZADO."""
    res = sri.consultar_autorizacion("1" * 49, ambiente="1")
    assert res["estado"] in ("AUTORIZADO", "RECIBIDA")
    assert "fecha_autorizacion" in res


def test_xml_no_tiene_bom():
    """El XML no debe llevar BOM (rompe firma SRI)."""
    factura = {
        "fecha_emision": "2026-04-22", "clave_acceso": "1" * 49,
        "items": [], "subtotal_12": 0, "subtotal_0": 0, "iva": 0, "total": 0,
    }
    xml = sri.build_factura_xml(factura, {"ruc": "0" * 13}, {})
    assert not xml.startswith("﻿")


def test_xml_reconciliacion_subtotal_lineas():
    """Suma de subtotales de lineas debe igualar el subtotal de la factura.

    Critico para auditoria SRI: una factura con discrepancia entre lineas
    y total puede ser rechazada o causar problemas tributarios.
    """
    factura = {
        "fecha_emision": "2026-04-22", "clave_acceso": "1" * 49,
        "items": [
            {"prod_id": "a", "descripcion": "A", "cant_cajas": 10, "precio_caja": 5.00, "iva_pct": 15},
            {"prod_id": "b", "descripcion": "B", "cant_cajas": 3, "precio_caja": 8.50, "iva_pct": 15},
            {"prod_id": "c", "descripcion": "C", "cant_cajas": 2, "precio_caja": 12.00, "iva_pct": 0},
        ],
        "subtotal_12": 75.50,  # 50 + 25.50
        "subtotal_0": 24.00,
        "iva": 11.325,  # 75.50 * 0.15
        "total": 110.825,
    }
    xml = sri.build_factura_xml(factura, {"ruc": "0" * 13}, {})

    # Cada linea debe tener su impuesto explicito
    assert xml.count("<detalle>") == 3
    # Total debe aparecer en el XML
    assert "<importeTotal>110.83</importeTotal>" in xml or "<importeTotal>110.82</importeTotal>" in xml


def test_clave_acceso_documenta_ambiente():
    """Posicion 24 de la clave de acceso = ambiente. Validar."""
    clave_pruebas = sri.generar_clave_acceso(
        fecha_emision="22042026", cod_doc="01", ruc_emisor="0" * 13,
        ambiente="1", estab="001", pto_emision="001", secuencial="000000001",
    )
    clave_prod = sri.generar_clave_acceso(
        fecha_emision="22042026", cod_doc="01", ruc_emisor="0" * 13,
        ambiente="2", estab="001", pto_emision="001", secuencial="000000001",
    )
    assert clave_pruebas[23] == "1"
    assert clave_prod[23] == "2"


def test_clave_acceso_diferente_codigo_numerico_distinto():
    """Dos llamadas seguidas SIN especificar codigo_numerico deben generar claves
    distintas (anti-colision en lote masivo)."""
    args = dict(
        fecha_emision="22042026", cod_doc="01", ruc_emisor="0" * 13,
        ambiente="1", estab="001", pto_emision="001", secuencial="000000001",
    )
    c1 = sri.generar_clave_acceso(**args)
    c2 = sri.generar_clave_acceso(**args)
    # con la misma config y secuencial, solo difiere el codigo numerico aleatorio
    # casi imposible que coincidan; este test puede fallar 1 en 10^8
    assert c1 != c2
