"""Tests de la logica pura de nomina."""
from nomina_logic import (
    apply_overrides,
    apply_recurrentes,
    calc_horas_periodo,
    es_finde_ds,
    horas_dia_dict,
    min_to_hhmm,
    periodo_de_data,
    vigente_en_periodo,
)


def test_min_to_hhmm():
    assert min_to_hhmm(0) == "00:00"
    assert min_to_hhmm(60) == "01:00"
    assert min_to_hhmm(450) == "07:30"
    assert min_to_hhmm(1439) == "23:59"
    assert min_to_hhmm(None) == ""
    assert min_to_hhmm("invalid") == ""


def test_es_finde_ds():
    # 1 marzo 2026 = domingo (sabado=5, domingo=6)
    assert es_finde_ds("26-03-01") is True
    # 2 marzo 2026 = lunes
    assert es_finde_ds("26-03-02") is False
    # 7 marzo 2026 = sabado
    assert es_finde_ds("26-03-07") is True
    # Formato invalido devuelve False
    assert es_finde_ds("invalid") is False


def test_horas_dia_dict():
    # 7:00 - 12:00 + 13:00 - 16:00 = 5 + 3 = 8h
    d = {"h1": 420, "h2": 720, "h3": 780, "h4": 960}
    assert horas_dia_dict(d) == 8.0

    # Solo manana
    d = {"h1": 420, "h2": 720, "h3": None, "h4": None}
    assert horas_dia_dict(d) == 5.0

    # Vacio
    assert horas_dia_dict({"h1": None, "h2": None, "h3": None, "h4": None}) == 0.0


def test_periodo_de_data_marzo():
    data = [("Juan", {"26-03-15": []}, "1")]
    pid, label = periodo_de_data(data)
    assert pid == "2026-03"
    assert label == "Mar 2026"


def test_periodo_de_data_vacio():
    assert periodo_de_data([]) == (None, None)


def test_apply_overrides():
    cfg = {"salario": 500, "prestamo_iess": 0, "fondos_reserva": True}
    out = apply_overrides(cfg, {"prestamo_iess": 50, "fondos_reserva": False})
    assert out["prestamo_iess"] == 50
    assert out["fondos_reserva"] is False
    assert out["salario"] == 500  # no tocado


def test_apply_overrides_vacio():
    cfg = {"salario": 500}
    out = apply_overrides(cfg, None)
    assert out == cfg
    assert out is not cfg  # copia


def test_vigente_en_periodo():
    # Sin desde ni hasta = aplica siempre
    assert vigente_en_periodo(None, None, "2026-05") is True
    # Desde marzo 2026 — aplica desde marzo en adelante
    assert vigente_en_periodo("2026-03", None, "2026-03") is True
    assert vigente_en_periodo("2026-03", None, "2026-05") is True
    assert vigente_en_periodo("2026-03", None, "2026-02") is False
    # Hasta agosto 2026 — no aplica despues
    assert vigente_en_periodo("2026-01", "2026-08", "2026-09") is False
    assert vigente_en_periodo("2026-01", "2026-08", "2026-08") is True


def test_apply_recurrentes_prestamo():
    cfg = {"salario": 500, "prestamo_iess": 0}
    reglas = [
        {"empleado_id": "jp", "tipo": "prestamo_iess", "monto": 45, "desde": "2025-11", "hasta": "2026-10"},
        {"empleado_id": "otro", "tipo": "prestamo_iess", "monto": 100, "desde": None, "hasta": None},
    ]
    out = apply_recurrentes(cfg, "jp", "2026-05", reglas)
    assert out["prestamo_iess"] == 45  # solo el de jp


def test_apply_recurrentes_transporte_bono():
    cfg = {"transporte_dia": 1.5}
    reglas = [
        {"empleado_id": "mr", "tipo": "transporte_bono", "monto": 0.5, "desde": "2026-01", "hasta": None},
    ]
    out = apply_recurrentes(cfg, "mr", "2026-05", reglas)
    assert out["transporte_dia"] == 2.0


def test_apply_recurrentes_fuera_de_vigencia():
    cfg = {"prestamo_iess": 0}
    reglas = [
        {"empleado_id": "jp", "tipo": "prestamo_iess", "monto": 45, "desde": "2026-03", "hasta": "2026-04"},
    ]
    # Periodo fuera de vigencia
    out = apply_recurrentes(cfg, "jp", "2026-05", reglas)
    assert out["prestamo_iess"] == 0


def test_fondos_aplica_sin_fecha_legacy():
    """Sin fecha de ingreso, asume legacy y aplica (conservador)."""
    from nomina_logic import fondos_aplica
    assert fondos_aplica("", "2026-05") is True


def test_fondos_aplica_menos_de_1_anio():
    """Empleado ingreso en febrero 2026, periodo mayo 2026 → solo 3 meses."""
    from nomina_logic import fondos_aplica
    assert fondos_aplica("2026-02-01", "2026-05") is False


def test_fondos_aplica_mas_de_1_anio():
    """Empleado ingreso enero 2025, periodo mayo 2026 → +1 anio."""
    from nomina_logic import fondos_aplica
    assert fondos_aplica("2025-01-15", "2026-05") is True


def test_decimo_14to_proporcional_anio_completo():
    """Ingreso anterior al ciclo (1 ago 2025 - 31 jul 2026) — paga 1 SBU completo."""
    from nomina_logic import decimo_14to_proporcional
    assert decimo_14to_proporcional("2024-05-01", "2026-08", 470) == 470


def test_decimo_14to_proporcional_medio_anio():
    """Ingreso 1 feb 2026 — pertenece al ciclo agosto 2025-julio 2026.
    Solo trabaja desde feb a jul = 6 meses = 180 dias."""
    from nomina_logic import decimo_14to_proporcional
    # Desde 1 feb 2026 hasta 31 jul 2026 = 181 dias (incluyendo ambos)
    # 470 * 181/360 = 236.36
    val = decimo_14to_proporcional("2026-02-01", "2026-08", 470)
    assert 230 < val < 245


def test_decimo_14to_proporcional_ingreso_futuro():
    """Ingreso despues del fin del ciclo — paga 0."""
    from nomina_logic import decimo_14to_proporcional
    assert decimo_14to_proporcional("2026-09-01", "2026-08", 470) == 0


def test_calc_horas_periodo_dia_normal():
    # Un dia de 8h sin extras
    cls_emp = {
        "26-03-02": {"h1": 420, "h2": 720, "h3": 780, "h4": 960, "flags": []},  # lunes 8h
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["dias"] == 1
    assert res["horas_total"] == 8.0
    assert res["horas_regular"] == 8.0
    assert res["horas_50"] == 0.0
    assert res["horas_100"] == 0.0
    assert res["banco_excedente"] == 0.0


def test_calc_horas_periodo_excedente_va_a_banco():
    # 10h en lunes — 8h regular, 2h excedente al banco (default modo=banco)
    cls_emp = {
        "26-03-02": {"h1": 420, "h2": 720, "h3": 780, "h4": 1080, "flags": []},  # 10h
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["horas_regular"] == 8.0
    assert res["banco_excedente"] == 2.0
    assert res["horas_50"] == 0.0  # NO pagado como extra


def test_calc_horas_periodo_excedente_pagar():
    # 10h en lunes con modo=pagar — 2h se pagan como extras 50%
    cls_emp = {
        "26-03-02": {"h1": 420, "h2": 720, "h3": 780, "h4": 1080, "flags": [], "modo_extra": "pagar"},
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["horas_regular"] == 8.0
    assert res["horas_50"] == 2.0
    assert res["banco_excedente"] == 0.0


def test_calc_horas_periodo_finde_va_a_banco():
    # 8h domingo, default modo=banco
    cls_emp = {
        "26-03-01": {"h1": 420, "h2": 720, "h3": 780, "h4": 960, "flags": []},  # domingo
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["banco_excedente"] == 8.0
    assert res["horas_100"] == 0.0


def test_calc_horas_periodo_cubrir_deficit():
    # 6h lunes, default no cubrir — solo 6h regular
    cls_emp = {
        "26-03-02": {"h1": 420, "h2": 720, "h3": 780, "h4": 840, "flags": []},  # 6h
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["horas_regular"] == 6.0
    assert res["horas_cubiertas"] == 0.0

    # Mismo dia con cubrir_banco=True — 8h regular + 2 cubiertas del banco
    cls_emp = {
        "26-03-02": {"h1": 420, "h2": 720, "h3": 780, "h4": 840, "flags": [], "cubrir_banco": True},
    }
    res = calc_horas_periodo(cls_emp, base_h=8)
    assert res["horas_regular"] == 8.0
    assert res["horas_cubiertas"] == 2.0
