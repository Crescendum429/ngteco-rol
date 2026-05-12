"""Tests de caracterizacion end-to-end de calcular_nomina.

Estos tests congelan el comportamiento ACTUAL del sistema. Cualquier cambio que
afecte estos valores debe ser deliberado y documentado. Si un test falla por
cambio intencional, actualizar los valores esperados Y agregar nota.

Las cifras esperadas provienen de ejecutar el codigo actual con inputs conocidos.
Sirven como red de seguridad antes de refactorizar.
"""
import pytest

from nomina_logic import calc_horas_periodo
from procesar_rol import calcular_nomina


# ──────────────────────────────────────────────────────────────────
# Fixtures de cls_emp y cfg comunes
# ──────────────────────────────────────────────────────────────────

def _cfg_basico(salario=500, base_h=8, transporte_dia=1.50, prestamo=0,
                fondos=False, descuento_iess=True):
    return {
        "salario": salario,
        "horas_base": base_h,
        "transporte_dia": transporte_dia,
        "prestamo_iess": prestamo,
        "fondos_reserva": fondos,
        "descuento_iess": descuento_iess,
        "horas_comp_anterior": 0,
    }


def _dia(h1, h2, h3, h4, **kw):
    """Helper. Minutos desde medianoche: 7am=420, 12pm=720, 13=780, 16=960."""
    base = {"h1": h1, "h2": h2, "h3": h3, "h4": h4, "flags": []}
    base.update(kw)
    return base


# ──────────────────────────────────────────────────────────────────
# Escenarios de calc_horas_periodo
# ──────────────────────────────────────────────────────────────────

def test_e2e_lunes_8h_normales():
    """8h en un lunes — 8h regulares, 0 extras, 0 banco."""
    cls = {"26-03-02": _dia(420, 720, 780, 960)}  # lunes 7-12 + 13-16
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["dias"] == 1
    assert hrs["horas_total"] == 8.0
    assert hrs["horas_regular"] == 8.0
    assert hrs["horas_50"] == 0.0
    assert hrs["horas_100"] == 0.0
    assert hrs["banco_excedente"] == 0.0
    assert hrs["horas_cubiertas"] == 0.0


def test_e2e_lunes_10h_modo_banco():
    """10h lunes modo=banco (default) — 8h regulares + 2h al banco."""
    cls = {"26-03-02": _dia(420, 720, 780, 1080)}  # 7-12 + 13-18 = 10h
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 8.0
    assert hrs["banco_excedente"] == 2.0
    assert hrs["horas_50"] == 0.0
    assert hrs["horas_100"] == 0.0


def test_e2e_lunes_10h_modo_pagar():
    """10h lunes modo=pagar — 8h regulares + 2h al 50%."""
    cls = {"26-03-02": _dia(420, 720, 780, 1080, modo_extra="pagar")}
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 8.0
    assert hrs["horas_50"] == 2.0
    assert hrs["banco_excedente"] == 0.0


def test_e2e_lunes_13h_modo_pagar_4h_cap_a_100():
    """13h lunes modo=pagar — 8h regulares + 4h al 50% + 1h al 100%.

    Importante: el sistema cap suplementarias a 4h diarias por dia (Art. 55).
    """
    cls = {"26-03-02": _dia(420, 720, 780, 1260, modo_extra="pagar")}  # 5+8 = 13h
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 8.0
    assert hrs["horas_50"] == 4.0
    assert hrs["horas_100"] == 1.0


def test_e2e_sabado_completo_va_a_banco():
    """8h sabado modo=banco (default) — todo al banco como 100%."""
    cls = {"26-03-07": _dia(420, 720, 780, 960)}  # sabado 1 marzo 2026 = sab
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["banco_excedente"] == 8.0
    assert hrs["horas_100"] == 0.0
    assert hrs["horas_regular"] == 0.0


def test_e2e_sabado_modo_pagar_va_a_100():
    cls = {"26-03-07": _dia(420, 720, 780, 960, modo_extra="pagar")}
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_100"] == 8.0
    assert hrs["banco_excedente"] == 0.0


def test_e2e_deficit_sin_cubrir():
    """6h lunes — solo 6h regulares, no se cubre del banco."""
    cls = {"26-03-02": _dia(420, 720, 780, 840)}  # 5+1=6h
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 6.0
    assert hrs["horas_cubiertas"] == 0.0


def test_e2e_deficit_con_cubrir():
    """6h lunes con cubrir_banco — 8h regular + 2h descontadas del banco."""
    cls = {"26-03-02": _dia(420, 720, 780, 840, cubrir_banco=True)}
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 8.0
    assert hrs["horas_cubiertas"] == 2.0


def test_e2e_dia_completo_cubierto_sin_timbres():
    """0h lunes con cubrir_banco — 8h regulares y dia se cuenta."""
    cls = {"26-03-02": _dia(None, None, None, None, cubrir_banco=True)}
    hrs = calc_horas_periodo(cls, base_h=8)
    assert hrs["horas_regular"] == 8.0
    assert hrs["horas_cubiertas"] == 8.0
    assert hrs["dias"] == 1  # dia cuenta (esto es lo que causa pagar transporte)


# ──────────────────────────────────────────────────────────────────
# Escenarios de calcular_nomina (procesar_rol.py)
# ──────────────────────────────────────────────────────────────────

def test_e2e_nomina_minima_sin_extras():
    """Empleado base sin extras: salario 500, 22 dias, 0 horas extras.
    Verifica los numeros exactos que produce el sistema."""
    hrs = {"dias": 22, "horas_total": 176, "horas_50": 0, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500, transporte_dia=1.50)
    nom = calcular_nomina(hrs, cfg, {})

    assert nom["quincena"] == 250.0
    assert nom["horas_extras"] == 0.0
    assert nom["transporte"] == 33.0  # 22 * 1.50
    assert nom["total_ingresos"] == 533.0  # 500 + 0 + 33
    # IESS = 533 * 0.0945 = 50.3685 → 50.37
    assert nom["iess"] == 50.37
    assert nom["prestamo_iess"] == 0
    assert nom["total_egresos"] == 50.37
    assert nom["valor_recibir"] == 482.63
    assert nom["fondos_reserva"] == 0  # No tiene
    # transf_15 = 250, transf_fin = 482.63 - 250 = 232.63
    assert nom["total_transferido"] == 482.63


def test_e2e_nomina_con_extras_pagar():
    """Empleado con 4h al 50% pagadas y fondos reserva."""
    hrs = {"dias": 22, "horas_total": 180, "horas_50": 4, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500, transporte_dia=1.50, fondos=True)
    nom = calcular_nomina(hrs, cfg, {})

    # hourly = 500/30/8 = 2.0833...
    # pay_50 = 4 * 2.0833 * 1.5 = 12.50
    assert abs(nom["pay_50"] - 12.50) < 0.01
    assert abs(nom["horas_extras"] - 12.50) < 0.01

    # total_ingresos = 500 + 12.50 + 33 = 545.50
    assert abs(nom["total_ingresos"] - 545.50) < 0.01

    # fondos = 545.50 / 12 = 45.46 (8.33%)
    assert abs(nom["fondos_reserva"] - 45.46) < 0.01

    # iess = 545.50 * 0.0945 = 51.55
    assert abs(nom["iess"] - 51.55) < 0.01


def test_e2e_nomina_descuento_iess_false():
    """Empleado con descuento_iess=False — IESS debe ser 0."""
    hrs = {"dias": 22, "horas_total": 176, "horas_50": 0, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500, descuento_iess=False)
    nom = calcular_nomina(hrs, cfg, {})
    assert nom["iess"] == 0


def test_e2e_nomina_con_prestamo_iess():
    """Empleado con prestamo IESS — se descuenta del total."""
    hrs = {"dias": 22, "horas_total": 176, "horas_50": 0, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500, prestamo=50)
    nom = calcular_nomina(hrs, cfg, {})
    assert nom["prestamo_iess"] == 50
    # total_egresos = iess(50.37) + prestamo(50) = 100.37
    assert abs(nom["total_egresos"] - 100.37) < 0.01
    # valor_recibir = 533 - 100.37 = 432.63
    assert abs(nom["valor_recibir"] - 432.63) < 0.01


def test_e2e_nomina_decimo_13():
    """Con decimo 13ro flagged, suma salario completo al ingreso."""
    hrs = {"dias": 22, "horas_total": 176, "horas_50": 0, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500)
    nom = calcular_nomina(hrs, cfg, {"decimo_13": True})
    assert nom["decimo_13"] == 500


def test_e2e_nomina_transferencia_fin_negativa():
    """Caso peligroso: prestamo grande → transf_fin queda negativa.

    El sistema actual NO valida esto — registra el numero negativo.
    """
    hrs = {"dias": 22, "horas_total": 176, "horas_50": 0, "horas_100": 0, "horas_regular": 176}
    cfg = _cfg_basico(salario=500, prestamo=400)
    nom = calcular_nomina(hrs, cfg, {})
    # valor_recibir = 533 - 50.37 - 400 = 82.63
    # transf_15 = 250, transf_fin = 82.63 - 250 = -167.37
    assert nom["transf_15"] == 250
    assert nom["transf_fin"] < 0  # Bug: no se valida
