"""Logica pura de calculo de nomina — sin Flask, sin storage directo en endpoints.

Importable por blueprints y por server.py.
"""
from datetime import date, datetime, timedelta

from logger import get_logger
from procesar_rol import calcular_nomina, emp_name, match_empleados
from storage import (
    load_arrastre,
    load_beneficios_recurrentes,
    load_empleados,
    load_nomina_overrides,
    load_reporte,
    list_reportes,
)

_log = get_logger("nomina_logic")

MES_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

OVERRIDE_FIELDS = ("prestamo_iess", "transporte_dia", "descuento_iess", "fondos_reserva")

# Feriados nacionales obligatorios de Ecuador (Codigo del Trabajo Art. 65 +
# Ley de Reforma a la Ley Organica para la Optimizacion y Eficiencia de
# Tramites Administrativos, 2016 — feriados con dia trasladable). Trabajar
# en estos dias se paga al 100% como hora extraordinaria (Art. 55).
#
# Algunos feriados son trasladables; verificar cada anio el calendario oficial
# publicado por el MDT. Esta lista es conservadora — preferimos marcar de mas
# (que el contador desmarque) que marcar de menos (pagar menos de lo debido).
FERIADOS_ECUADOR = {
    # 2025
    "2025-01-01",  # Anio Nuevo
    "2025-03-03", "2025-03-04",  # Carnaval (lun-mar)
    "2025-04-18",  # Viernes Santo
    "2025-05-01",  # Dia del Trabajo
    "2025-05-23",  # Batalla de Pichincha (trasladado de 24 a 23, viernes)
    "2025-08-08",  # Primer Grito Independencia (trasladado de 10 a 8, viernes)
    "2025-10-10",  # Independencia Guayaquil (trasladado de 9 a 10, viernes)
    "2025-11-03",  # Independencia Cuenca (trasladado de 3 noviembre)
    "2025-12-25",  # Navidad
    # Dia de los Difuntos: 2 noviembre — observado segun calendario
    # 2026 (verificar oficial — esta lista es preliminar)
    "2026-01-01",
    "2026-02-16", "2026-02-17",  # Carnaval
    "2026-04-03",  # Viernes Santo
    "2026-05-01",
    "2026-05-22",  # Pichincha trasladado a viernes
    "2026-08-10",
    "2026-10-09",
    "2026-11-02",  # Difuntos
    "2026-11-03",  # Cuenca
    "2026-12-25",
    # 2027 — agregar cuando MDT publique calendario oficial
}

# Topes legales Art. 55 Codigo del Trabajo
MAX_SUPLEMENTARIAS_DIA = 4.0
MAX_SUPLEMENTARIAS_SEMANA = 12.0


def es_feriado_ds(ds):
    """Retorna True si el dia es feriado nacional (formato yy-mm-dd interno o YYYY-MM-DD)."""
    if not ds:
        return False
    parts = ds.split("-")
    if len(parts) != 3:
        return False
    try:
        y = int(parts[0])
        y_full = 2000 + y if y < 100 else y
        fecha_iso = f"{y_full}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return fecha_iso in FERIADOS_ECUADOR
    except Exception:
        return False


def semana_iso_ds(ds):
    """Retorna (year, week) ISO para agrupar horas por semana laboral."""
    if not ds:
        return (0, 0)
    parts = ds.split("-")
    if len(parts) != 3:
        return (0, 0)
    try:
        y = int(parts[0])
        y_full = 2000 + y if y < 100 else y
        d = date(y_full, int(parts[1]), int(parts[2]))
        iso = d.isocalendar()
        return (iso[0], iso[1])  # (anio_iso, semana_iso)
    except Exception:
        return (0, 0)


# ─── helpers atomicos ───

def min_to_hhmm(mins):
    if mins is None:
        return ""
    try:
        m = int(mins)
        return f"{m // 60:02d}:{m % 60:02d}"
    except Exception:
        return ""


def es_finde_ds(ds):
    try:
        parts = ds.split("-")
        y = int(parts[0])
        y_full = 2000 + y if y < 100 else y
        return date(y_full, int(parts[1]), int(parts[2])).weekday() >= 5
    except Exception:
        return False


def horas_dia_dict(d):
    horas = 0.0
    if d.get("h1") is not None and d.get("h2") is not None:
        horas += (d["h2"] - d["h1"]) / 60
    if d.get("h3") is not None and d.get("h4") is not None:
        horas += (d["h4"] - d["h3"]) / 60
    return horas


def periodo_de_data(data):
    """Extrae periodo_id 'YYYY-MM' y label legible a partir de la primera fecha."""
    for _, days, _ in data:
        for ds in days:
            parts = ds.split('-')
            if len(parts) == 3:
                y = int(parts[0])
                y_full = 2000 + y if y < 100 else y
                m = int(parts[1])
                return f"{y_full}-{m:02d}", f"{MES_NAMES[m-1]} {y_full}"
    return None, None


def fondos_aplica(fecha_ingreso, periodo_id):
    """Determina si los fondos de reserva aplican legalmente (Art. 196 Codigo
    del Trabajo): solo despues del PRIMER ANIO de servicio.

    Args:
        fecha_ingreso: 'YYYY-MM-DD' o '' (vacio = se desconoce, se asume que
                       SI aplica para mantener comportamiento legacy).
        periodo_id: 'YYYY-MM' del periodo de nomina.

    Returns:
        True si: no hay fecha (legacy) O ya transcurrio mas de 1 anio.
    """
    if not fecha_ingreso:
        return True  # legacy/desconocido — conservador a favor del empleado
    try:
        y, m, d = fecha_ingreso.split("-")
        ingreso = date(int(y), int(m), int(d))
    except Exception:
        return True
    try:
        py, pm = periodo_id.split("-")
        # fin del periodo = ultimo dia del mes
        fin_periodo = date(int(py), int(pm), 28)  # 28 es seguro para todos los meses
    except Exception:
        return True
    diff_dias = (fin_periodo - ingreso).days
    return diff_dias >= 365


def decimo_14to_proporcional(fecha_ingreso, periodo_id, sbu):
    """Calcula 14to proporcional al tiempo trabajado en el periodo anual.

    Periodo de calculo del 14to en Sierra/Amazonia: 1 ago del anio anterior al
    31 jul del anio actual (Art. 113 Codigo del Trabajo). Pago hasta 15 ago.

    Si ingreso < 1 anio en el periodo: prorratea.
    Si fecha_ingreso vacia: asume 1 SBU completo (legacy).
    """
    if not fecha_ingreso:
        return sbu
    try:
        y, m, d = fecha_ingreso.split("-")
        ingreso = date(int(y), int(m), int(d))
        py = int(periodo_id.split("-")[0])
    except Exception:
        return sbu

    inicio_ciclo = date(py - 1, 8, 1)
    fin_ciclo = date(py, 7, 31)
    if ingreso > fin_ciclo:
        return 0
    inicio_calc = max(ingreso, inicio_ciclo)
    dias_trabajados = (fin_ciclo - inicio_calc).days + 1
    dias_ciclo = 360  # convencion contable ecuatoriana
    proporcional = sbu * min(dias_trabajados / dias_ciclo, 1.0)
    return round(proporcional, 2)


def vigente_en_periodo(desde, hasta, periodo_id):
    if not periodo_id:
        return False
    if desde and periodo_id < desde:
        return False
    if hasta and periodo_id > hasta:
        return False
    return True


def apply_overrides(cfg, overrides_emp):
    if not overrides_emp:
        return dict(cfg)
    out = dict(cfg)
    for f in OVERRIDE_FIELDS:
        if f in overrides_emp:
            out[f] = overrides_emp[f]
    return out


def apply_recurrentes(cfg, empleado_id, periodo_id, recurrentes_all):
    """Aplica reglas de beneficios recurrentes vigentes al cfg.

    Las reglas tipo prestamo_iess y prestamo_empresa suman a prestamo_iess.
    transporte_bono suma al transporte_dia.
    alimentacion, comision, otro_ben se registran como bonos adicionales.
    """
    out = dict(cfg)
    prestamo_total = 0.0
    transporte_extra = 0.0
    bonos = 0.0
    otros_desc = 0.0
    for regla in (recurrentes_all or []):
        if regla.get("empleado_id") != empleado_id:
            continue
        if not vigente_en_periodo(regla.get("desde"), regla.get("hasta"), periodo_id):
            continue
        tipo = regla.get("tipo")
        monto = float(regla.get("monto", 0))
        if tipo in ("prestamo_iess", "prestamo_empresa"):
            prestamo_total += monto
        elif tipo == "transporte_bono":
            transporte_extra += monto
        elif tipo in ("alimentacion", "comision", "otro_ben"):
            bonos += monto
        elif tipo == "otro_desc":
            otros_desc += monto
    if prestamo_total > 0:
        out["prestamo_iess"] = float(out.get("prestamo_iess", 0)) + prestamo_total
    if transporte_extra > 0:
        out["transporte_dia"] = float(out.get("transporte_dia", 0)) + transporte_extra
    if bonos > 0 or otros_desc > 0:
        out["_bonos_recurrentes"] = bonos
        out["_otros_desc_recurrentes"] = otros_desc
    return out


# ─── calculos por periodo ───

def horas_detalle_one(data_r, cls_r, emp_db):
    """Retorna {emp_id: [days]} para un reporte."""
    if not data_r or not cls_r:
        return {}
    matched_r, _, _ = match_empleados(data_r, emp_db)
    result = {}
    for emp_full, days, _ in data_r:
        name = emp_name(emp_full)
        dk = matched_r.get(name, name)
        cfg = emp_db.get(dk, {}) if dk else {}
        base_h = cfg.get("horas_base", 8)
        emp_days = []
        cls_emp = cls_r.get(name, {})
        for ds in sorted(cls_emp.keys()):
            d = cls_emp[ds]
            horas = horas_dia_dict(d)
            flags = d.get("flags") or []
            finde = es_finde_ds(ds)
            base_dia = 0 if finde else base_h
            excedente = max(0.0, horas - base_dia) if horas > 0 else 0.0
            deficit = max(0.0, base_dia - horas) if not finde else 0.0
            emp_days.append({
                "fecha": ds,
                "h1": min_to_hhmm(d.get("h1")),
                "h2": min_to_hhmm(d.get("h2")),
                "h3": min_to_hhmm(d.get("h3")),
                "h4": min_to_hhmm(d.get("h4")),
                "total": round(horas, 1),
                "flag": flags[0] if flags else "",
                "modo_extra": d.get("modo_extra", "banco"),
                "cubrir_banco": bool(d.get("cubrir_banco", False)),
                "es_finde": finde,
                "base_dia": base_dia,
                "excedente": round(excedente, 2),
                "deficit": round(deficit, 2),
            })
        result[dk] = emp_days
    return result


def calc_horas_periodo(cls_emp, base_h):
    """Calcula horas considerando modo_extra, cubrir_banco, feriados y tope
    semanal de horas suplementarias.

    Returns dict con:
    - dias            : dias trabajados EFECTIVAMENTE (timbres reales). Para
                        transporte (Art. 42).
    - dias_pagados    : efectivos + cubiertos por banco.
    - horas_regular   : horas regulares pagadas.
    - horas_50/100    : horas extras pagadas. Feriados y findes van al 100%.
    - banco_excedente : horas al banco este periodo.
    - horas_cubiertas : horas descontadas del banco.
    - dias_anomalia   : dias con REVISAR no resuelto.
    - alertas         : strings de problemas legales (ej. excedio 12h/sem).

    Tratamiento de feriados nacionales (FERIADOS_ECUADOR):
    - Trabajar en feriado = 100% como hora extraordinaria (Art. 55).
    - Cap semanal 12h aplica a suplementarias (no a 100%).
    """
    res = {
        "dias": 0, "dias_pagados": 0, "dias_anomalia": 0,
        "horas_regular": 0.0, "horas_50": 0.0, "horas_100": 0.0,
        "banco_excedente": 0.0, "horas_cubiertas": 0.0,
        "horas_total": 0.0,
        "alertas": [],
    }
    # Para tope semanal: acumular suplementarias por (anio, semana ISO)
    sup_por_semana = {}  # (year, week) -> suma horas_50 contadas
    for ds, d in cls_emp.items():
        horas = horas_dia_dict(d)
        modo = d.get("modo_extra", "banco")
        cubrir = bool(d.get("cubrir_banco", False))
        flags = d.get("flags") or []
        es_finde_o_feriado = es_finde_ds(ds) or es_feriado_ds(ds)

        if horas > 0:
            res["dias"] += 1
            res["dias_pagados"] += 1
            if any(f.startswith("REVISAR:") for f in flags):
                res["dias_anomalia"] += 1
            res["horas_total"] += horas

        if es_finde_o_feriado:
            # Findes y feriados — todo al 100% si modo=pagar, sino al banco
            if horas > 0:
                if modo == "pagar":
                    res["horas_100"] += horas
                else:
                    res["banco_excedente"] += horas
        else:
            # Dia laboral normal
            if horas > 0:
                reg = min(horas, base_h)
                res["horas_regular"] += reg
                excedente = max(0.0, horas - base_h)
                if excedente > 0:
                    if modo == "pagar":
                        h50_dia = min(excedente, MAX_SUPLEMENTARIAS_DIA)
                        h100_dia = max(0.0, excedente - MAX_SUPLEMENTARIAS_DIA)
                        res["horas_50"] += h50_dia
                        res["horas_100"] += h100_dia
                        # Acumular para tope semanal
                        wk = semana_iso_ds(ds)
                        sup_por_semana[wk] = sup_por_semana.get(wk, 0) + h50_dia
                    else:
                        res["banco_excedente"] += excedente
                elif horas < base_h and cubrir:
                    deficit = base_h - horas
                    res["horas_regular"] += deficit
                    res["horas_cubiertas"] += deficit
            elif cubrir:
                # Dia sin timbres cubierto por banco — NO cuenta para transporte
                res["horas_regular"] += base_h
                res["horas_cubiertas"] += base_h
                res["dias_pagados"] += 1

    # Validar tope semanal de suplementarias (Art. 55: max 12h/semana)
    for (anio, sem), horas_sem in sup_por_semana.items():
        if horas_sem > MAX_SUPLEMENTARIAS_SEMANA:
            exceso = horas_sem - MAX_SUPLEMENTARIAS_SEMANA
            res["alertas"].append(
                f"Semana {anio}-W{sem}: {horas_sem:.1f}h suplementarias supera tope "
                f"legal de {MAX_SUPLEMENTARIAS_SEMANA}h (exceso {exceso:.1f}h). "
                f"Art. 55 Codigo del Trabajo. Decida con contador: pagar al 50% "
                f"igual, reclasificar a 100%, o no pagar."
            )

    for k in ("horas_regular", "horas_50", "horas_100", "banco_excedente", "horas_cubiertas", "horas_total"):
        res[k] = round(res[k], 2)
    return res


def banco_por_empleado(emp_db):
    """Suma cronologica del banco por empleado. Si un reporte falla al cargar,
    lo loggea y devuelve None para banco — NO silencia, porque banco erroneo =
    pago erroneo."""
    balances = {k: 0.0 for k in emp_db}
    errors = []
    reps = sorted([r["id"] for r in list_reportes()])
    for rid in reps:
        try:
            data_r, cls_r = load_reporte(rid)
        except Exception:
            _log.exception(f"banco_por_empleado: error cargando reporte {rid}")
            errors.append(rid)
            continue
        if not data_r or not cls_r:
            continue
        matched_r, _, _ = match_empleados(data_r, emp_db)
        for emp_full, days, _ in data_r:
            name = emp_name(emp_full)
            dk = matched_r.get(name)
            if not dk or dk not in emp_db:
                continue
            base = emp_db[dk].get("horas_base", 8)
            hrs = calc_horas_periodo(cls_r.get(name, {}), base)
            balances[dk] += hrs["banco_excedente"] - hrs["horas_cubiertas"]
    if errors:
        _log.warning(f"banco_por_empleado: {len(errors)} reportes fallaron: {errors}")
    return {k: round(v, 2) for k, v in balances.items()}


def build_horas_por_periodo(emp_db):
    """Retorna {periodo_id: {emp_id: [days]}}. Si un reporte falla al cargar,
    queda como dict vacio Y se loggea para diagnostico."""
    result = {}
    for rep in list_reportes():
        rid = rep["id"]
        try:
            data_r, cls_r = load_reporte(rid)
            result[rid] = horas_detalle_one(data_r, cls_r, emp_db)
        except Exception:
            _log.exception(f"build_horas_por_periodo: error en reporte {rid}")
            result[rid] = {}
    return result


def calc_nomina_one(periodo_id, data_r, cls_r, emp_db):
    if not data_r or not cls_r:
        return []
    matched_r, _, _ = match_empleados(data_r, emp_db)
    overrides = load_nomina_overrides(periodo_id) or {}
    recurrentes = load_beneficios_recurrentes() or []
    result = []
    for emp_full, days, nid in data_r:
        name = emp_name(emp_full)
        dk = matched_r.get(name)
        cfg_base = emp_db.get(dk, {}) if dk else {}
        cfg = apply_overrides(cfg_base, overrides.get(dk or name, {}))
        cfg = apply_recurrentes(cfg, dk or name, periodo_id, recurrentes)
        if not cfg.get("salario"):
            continue

        # Fondos de reserva: derivar de fecha_ingreso si esta configurada
        # (Art. 196 — aplica desde el 2do anio). El campo cfg["fondos_reserva"]
        # del empleado es el flag base; si fecha_ingreso < 1 anio, fuerza a False.
        if cfg.get("fondos_reserva") and not fondos_aplica(cfg.get("fecha_ingreso", ""), periodo_id):
            cfg = dict(cfg)
            cfg["fondos_reserva"] = False

        base_h = cfg.get("horas_base", 8)
        hrs = calc_horas_periodo(cls_r.get(name, {}), base_h)
        hrs_for_nomina = {
            "dias": hrs["dias"],
            "horas_total": hrs["horas_total"],
            "horas_50": hrs["horas_50"],
            "horas_100": hrs["horas_100"],
            "horas_regular": hrs["horas_regular"],
        }
        cfg_c = dict(cfg)
        cfg_c["horas_comp_anterior"] = 0
        nom = calcular_nomina(hrs_for_nomina, cfg_c, {})
        result.append({
            "id": dk or name,
            "nombre": name,
            "dias": hrs["dias"],
            "horas": round(hrs["horas_total"], 1),
            "h50": round(hrs["horas_50"], 2),
            "h100": round(hrs["horas_100"], 2),
            "banco_delta": round(hrs["banco_excedente"] - hrs["horas_cubiertas"], 2),
            "quincena": round(nom["quincena"], 2),
            "extras": round(nom["horas_extras"], 2),
            "transporte": round(nom["transporte"], 2),
            "ingresos": round(nom["total_ingresos"], 2),
            "iess": round(nom["iess"], 2),
            "neto": round(nom["valor_recibir"], 2),
            "fondos": round(nom["fondos_reserva"], 2),
            "total": round(nom["total_transferido"], 2),
        })
    return result


def build_nomina_por_periodo(emp_db):
    result = {}
    for rep in list_reportes():
        rid = rep["id"]
        try:
            data_r, cls_r = load_reporte(rid)
            result[rid] = calc_nomina_one(rid, data_r, cls_r, emp_db)
        except Exception:
            _log.exception(f"build_nomina_por_periodo: error en {rid}")
            result[rid] = []
    return result


def compute_nomina_for_periodo(periodo_id, extras_config=None):
    """Calcula nomina completa del periodo. Retorna (resumen, nomina_list)."""
    extras_config = extras_config or {}
    data, cls = load_reporte(periodo_id)
    if not data:
        return None, None
    emp_db = load_empleados()
    matched, _, _ = match_empleados(data, emp_db)
    overrides = load_nomina_overrides(periodo_id) or {}
    recurrentes = load_beneficios_recurrentes() or []

    nomina_list = []
    total = 0.0
    h50 = 0.0
    h100 = 0.0
    for emp_full, days, _ in data:
        name = emp_name(emp_full)
        dk = matched.get(name)
        cfg_base = emp_db.get(dk, {}) if dk else {}
        cfg = apply_overrides(cfg_base, overrides.get(dk or name, {}))
        cfg = apply_recurrentes(cfg, dk or name, periodo_id, recurrentes)
        if not cfg.get("salario"):
            continue
        # Fondos derivado de fecha_ingreso
        if cfg.get("fondos_reserva") and not fondos_aplica(cfg.get("fecha_ingreso", ""), periodo_id):
            cfg = dict(cfg)
            cfg["fondos_reserva"] = False
        base_h = cfg.get("horas_base", 8)
        hrs_detail = calc_horas_periodo(cls.get(name, {}), base_h)
        hrs_for_nomina = {
            "dias": hrs_detail["dias"],
            "horas_total": hrs_detail["horas_total"],
            "horas_50": hrs_detail["horas_50"],
            "horas_100": hrs_detail["horas_100"],
            "horas_regular": hrs_detail["horas_regular"],
        }
        cfg_c = dict(cfg)
        cfg_c["horas_comp_anterior"] = 0
        nom = calcular_nomina(hrs_for_nomina, cfg_c, extras_config)
        dias_detalle = []
        cls_emp = cls.get(name, {})
        for ds in sorted(cls_emp.keys()):
            d = cls_emp[ds]
            horas = horas_dia_dict(d)
            flags = d.get("flags") or []
            finde = es_finde_ds(ds)
            base_dia = 0 if finde else base_h
            dias_detalle.append({
                "fecha": ds,
                "h1": min_to_hhmm(d.get("h1")),
                "h2": min_to_hhmm(d.get("h2")),
                "h3": min_to_hhmm(d.get("h3")),
                "h4": min_to_hhmm(d.get("h4")),
                "total": round(horas, 1),
                "flag": flags[0] if flags else "",
                "modo_extra": d.get("modo_extra", "banco"),
                "cubrir_banco": bool(d.get("cubrir_banco", False)),
                "es_finde": finde,
                "excedente": round(max(0.0, horas - base_dia) if horas > 0 else 0, 2),
                "deficit": round(max(0.0, base_dia - horas) if not finde else 0, 2),
            })
        nomina_list.append({"name": name, "nomina": nom, "dias": dias_detalle})
        total += nom.get("total_transferido", 0)
        h50 += hrs_detail.get("horas_50", 0)
        h100 += hrs_detail.get("horas_100", 0)

    y, m = periodo_id.split('-')
    label = f"{MES_NAMES[int(m)-1]} {y}"
    resumen = {
        "periodo": periodo_id,
        "periodo_label": label,
        "total_transferido": total,
        "total_h50": h50,
        "total_h100": h100,
        "n_empleados": len(nomina_list),
    }
    return resumen, nomina_list
