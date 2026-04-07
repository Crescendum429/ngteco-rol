import re
import unicodedata
import xlrd
from datetime import date, time
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SBU_2026 = 482.0
IESS_EMPLEADO = 0.0945

MORN_MIN  = 5 * 60
MORN_MAX  = 8 * 60 + 45
LUNCH_MIN = 11 * 60
LUNCH_MAX = 15 * 60
AFT_MIN   = 14 * 60
AFT_MAX   = 19 * 60
SHORT_SEG = 60

WEEKDAYS = {'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'}


# ── Utilidades ────────────────────────────────────────────────

def normalize(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.strip().lower()


def to_mins(s):
    if not s or not str(s).strip():
        return None
    m = re.match(r'(\d+):(\d+)', str(s).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def to_time(m):
    return time(m // 60, m % 60) if m is not None else None


def parse_date(ds):
    p = ds.split('-')
    return date(2000 + int(p[0]), int(p[1]), int(p[2]))


# ── Parseo XLS ────────────────────────────────────────────────

def parse_xls(path):
    wb = xlrd.open_workbook(path)
    ws = wb.sheet_by_index(0)
    result = []
    emp = None
    days = None
    cur_day = None

    for i in range(ws.nrows):
        row = [ws.cell(i, j).value for j in range(7)]

        if row[0] == 'Employee':
            raw = str(row[3])
            emp = re.sub(r'\n', ' ', raw).strip()
            m_id = re.search(r'\((\d+)\)', raw)
            ngteco_id = m_id.group(1) if m_id else ''
            days = {}
            result.append((emp, days, ngteco_id))
            cur_day = None

        elif emp and row[0] in WEEKDAYS and row[1]:
            cur_day = str(row[1])
            in_t = to_mins(row[2])
            out_t = to_mins(row[3])
            note = str(row[6]) if row[6] else ''
            days[cur_day] = []
            if in_t is not None or out_t is not None or 'Missing' in note:
                days[cur_day].append((in_t, out_t, note))

        elif emp and row[0] == '' and row[1] == '' and cur_day and (row[2] or row[6]):
            in_t = to_mins(row[2])
            out_t = to_mins(row[3])
            note = str(row[6]) if row[6] else ''
            days[cur_day].append((in_t, out_t, note))

    return result


# ── Matching empleados ────────────────────────────────────────

def match_empleados(data, emp_db):
    """Retorna (matched, nuevos, faltantes).
    matched: {xls_name: db_key}
    nuevos: [(xls_name, ngteco_id)] - en XLS pero no en DB
    faltantes: [db_key] - en DB pero no en XLS
    """
    matched = {}
    nuevos = []

    db_norm = {}
    for key, emp in emp_db.items():
        nombre = emp.get('nombre', '')
        db_norm[normalize(nombre)] = key

    xls_names_norm = set()
    for emp_full, days, nid in data:
        name = emp_full.split('(')[0].strip()
        n = normalize(name)
        xls_names_norm.add(n)

        if n in db_norm:
            matched[name] = db_norm[n]
        else:
            nuevos.append((name, nid))

    faltantes = []
    for key, emp in emp_db.items():
        n = normalize(emp.get('nombre', ''))
        if n and n not in xls_names_norm:
            if not emp.get('ocultar', False):
                faltantes.append(key)

    return matched, nuevos, faltantes


# ── Clasificacion ─────────────────────────────────────────────

def classify(pairs):
    active = [(i, o, n) for i, o, n in pairs if i is not None or o is not None]
    missing_out = any('Missing' in (n or '') for _, _, n in pairs)

    if not active:
        return None, None, None, None, []

    h1 = h2 = h3 = h4 = None
    flags = []

    if len(active) == 1:
        i, o, n = active[0]
        if i is not None and o is not None:
            dur = o - i
            if MORN_MIN <= i <= MORN_MAX:
                h1, h2 = i, o
                if missing_out:
                    flags.append('REVISAR: salida no registrada')
            elif LUNCH_MIN <= i <= LUNCH_MAX:
                if dur < SHORT_SEG:
                    flags.append('REVISAR: entrada manana no registrada')
                    h2, h3 = i, o
                else:
                    h1, h2 = i, o
            else:
                h1, h2 = i, o
                flags.append('REVISAR: horario fuera de rango esperado')
        elif i is not None:
            h1 = i
            flags.append('REVISAR: timbre sin salida correspondiente')

    elif len(active) == 2:
        i1, o1, n1 = active[0]
        i2, o2, n2 = active[1]
        if (i1 is not None and o1 is not None and
                LUNCH_MIN <= i1 <= LUNCH_MAX and (o1 - i1) < SHORT_SEG):
            flags.append('REVISAR: entrada manana no registrada')
            h2, h3 = i1, o1
            h4 = i2
            return h1, h2, h3, h4, flags
        if i1 is not None and MORN_MIN <= i1 <= MORN_MAX:
            h1, h2, h3, h4 = i1, o1, i2, o2
            if o2 is None:
                flags.append('REVISAR: salida tarde no registrada')
            elif not (AFT_MIN <= o2 <= AFT_MAX):
                flags.append('REVISAR: hora de salida inusual')
        else:
            h1, h2, h3, h4 = i1, o1, i2, o2
            flags.append('REVISAR: verificar horarios')
    else:
        h1 = active[0][0]
        h4 = active[-1][1] or active[-1][0]
        flags.append(f'REVISAR: {len(active)} registros - verificar manualmente')

    return h1, h2, h3, h4, flags


def clasificar_todo(data):
    result = {}
    for emp, days, *_ in data:
        name = emp.split('(')[0].strip()
        result[name] = {}
        for ds in days:
            h1, h2, h3, h4, flags = classify(days[ds])
            result[name][ds] = {
                'h1': h1, 'h2': h2, 'h3': h3, 'h4': h4,
                'flags': list(flags),
            }
    return result


def _get_cls(days, ds, overrides, emp_name):
    if overrides and emp_name in overrides and ds in overrides[emp_name]:
        d = overrides[emp_name][ds]
        return d['h1'], d['h2'], d['h3'], d['h4'], d['flags']
    return classify(days[ds])


# ── Calculo de horas ──────────────────────────────────────────

def _sumar_horas_dia(h1, h2, h3, h4):
    horas = 0.0
    if h1 is not None and h2 is not None:
        horas += (h2 - h1) / 60
    if h3 is not None and h4 is not None:
        horas += (h4 - h3) / 60
    return horas


def _acumular(ds, horas, flags, base_hours, acum):
    if horas <= 0:
        return
    acum['dias'] += 1
    if any(f.startswith('REVISAR:') for f in flags):
        acum['dias_anomalia'] += 1
    try:
        es_finde = parse_date(ds).weekday() >= 5
    except Exception:
        es_finde = False
    if es_finde:
        acum['ext_100'] += horas
    else:
        reg = min(horas, base_hours)
        acum['regular'] += reg
        extra = max(0.0, horas - base_hours)
        acum['sup_50'] += min(extra, 4.0)
        acum['ext_100'] += max(0.0, extra - 4.0)


def _resultado(acum):
    return {
        'dias': acum['dias'],
        'dias_anomalia': acum['dias_anomalia'],
        'horas_regular': round(acum['regular'], 2),
        'horas_50': round(acum['sup_50'], 2),
        'horas_100': round(acum['ext_100'], 2),
        'horas_total': round(acum['regular'] + acum['sup_50'] + acum['ext_100'], 2),
    }


def calcular_horas_clasificadas(classified_days, base_hours=8):
    acum = {'dias': 0, 'dias_anomalia': 0, 'regular': 0.0, 'sup_50': 0.0, 'ext_100': 0.0}
    for ds, d in classified_days.items():
        horas = _sumar_horas_dia(d['h1'], d['h2'], d['h3'], d['h4'])
        _acumular(ds, horas, d['flags'], base_hours, acum)
    return _resultado(acum)


# ── Calculo nomina completa ───────────────────────────────────

def calcular_nomina(hrs, cfg, extras=None):
    """Calcula nomina completa para un empleado.
    cfg: dict con salario, horas_base, transporte_dia, prestamo_iess, fondos_reserva,
         horas_comp_anterior
    extras: dict con decimo_13 (bool), decimo_14 (bool), bonus
    """
    extras = extras or {}
    salario = cfg.get('salario', 0)
    base_h = cfg.get('horas_base', 8)
    transp_dia = cfg.get('transporte_dia', 0)
    prestamo = cfg.get('prestamo_iess', 0)
    tiene_fondos = cfg.get('fondos_reserva', False)
    h_anterior = cfg.get('horas_comp_anterior', 0)

    hourly = salario / 30 / base_h if salario > 0 and base_h > 0 else 0

    # Horas compensatorias con arrastre opcional
    h_50_total = hrs['horas_50'] + h_anterior
    h_50_pagar = max(h_50_total, 0)
    h_50_arrastre = min(h_50_total, 0)

    pay_50 = h_50_pagar * hourly * 1.5
    pay_100 = hrs['horas_100'] * hourly * 2.0
    transporte = hrs['dias'] * transp_dia

    quincena = salario / 2
    horas_extras = pay_50 + pay_100

    # Ingresos
    total_ingresos = salario + horas_extras + transporte

    # Decimos (se suman a ingresos si aplican)
    d13 = salario if extras.get('decimo_13') else 0
    d14 = SBU_2026 if extras.get('decimo_14') else 0
    bonus = extras.get('bonus', 0)

    total_ingresos_con_extras = total_ingresos + d13 + d14 + bonus

    # Egresos
    iess = round(total_ingresos * IESS_EMPLEADO, 2)
    total_egresos = iess + prestamo

    # Neto
    valor_recibir = total_ingresos_con_extras - total_egresos

    # Fondos de reserva
    fondos = round(total_ingresos / 12, 2) if tiene_fondos else 0

    # Detalle transferencias
    transf_15 = quincena
    transf_fin = valor_recibir - quincena + fondos
    total_transferido = transf_15 + transf_fin

    return {
        'salario': salario,
        'hourly': hourly,
        'hours': hrs,
        'quincena': quincena,
        'horas_comp_anterior': h_anterior,
        'h_50_total': h_50_total,
        'h_50_pagar': h_50_pagar,
        'h_50_arrastre': round(h_50_arrastre, 2),
        'pay_50': round(pay_50, 2),
        'pay_100': round(pay_100, 2),
        'horas_extras': round(horas_extras, 2),
        'transporte': round(transporte, 2),
        'total_ingresos': round(total_ingresos, 2),
        'decimo_13': d13,
        'decimo_14': d14,
        'bonus': bonus,
        'iess': iess,
        'prestamo_iess': prestamo,
        'total_egresos': round(total_egresos, 2),
        'valor_recibir': round(valor_recibir, 2),
        'fondos_reserva': fondos,
        'transf_15': round(transf_15, 2),
        'transf_fin': round(transf_fin, 2),
        'total_transferido': round(total_transferido, 2),
    }


# ── Excel horas ───────────────────────────────────────────────

def write_excel(data, dest, overrides=None):
    wb = Workbook()
    wb.remove(wb.active)

    YELLOW = PatternFill('solid', fgColor='FFFF99')
    HDR_BG = PatternFill('solid', fgColor='4472C4')
    HDR_FT = Font(bold=True, color='FFFFFF')

    all_flags = []

    for emp, days, *_ in data:
        sheet_name = emp.split('(')[0].strip()[:31]
        ws = wb.create_sheet(title=sheet_name)

        headers = ['Fecha', 'Hora 1', 'Hora 2', 'Hora 3', 'Hora 4', 'Total (h)', 'Comentarios']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(1, c, h)
            cell.fill = HDR_BG
            cell.font = HDR_FT
            cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 16
        for ltr in 'BCDE':
            ws.column_dimensions[ltr].width = 9
        ws.column_dimensions['F'].width = 11
        ws.column_dimensions['G'].width = 58
        ws.freeze_panes = 'A2'

        r = 2
        for ds in sorted(days):
            h1, h2, h3, h4, flags = _get_cls(days, ds, overrides, sheet_name)
            try:
                d = parse_date(ds)
            except Exception:
                d = ds
            ws.cell(r, 1, d).number_format = 'DD/MM/YY DDD'
            for col, val in [(2, h1), (3, h2), (4, h3), (5, h4)]:
                if val is not None:
                    ws.cell(r, col, to_time(val)).number_format = 'HH:MM'
            if h1 is not None and h2 is not None:
                if h3 is not None and h4 is not None:
                    ws.cell(r, 6).value = f'=((C{r}-B{r})+(E{r}-D{r}))*24'
                elif h3 is None and h4 is None:
                    ws.cell(r, 6).value = f'=(C{r}-B{r})*24'
                ws.cell(r, 6).number_format = '0.00'
            if flags:
                comment = '; '.join(flags)
                ws.cell(r, 7, comment)
                for c in range(1, 8):
                    ws.cell(r, c).fill = YELLOW
                all_flags.append((sheet_name, d, comment))
            r += 1

    ws_sum = wb.create_sheet(title='Resumen', index=0)
    for c, h in enumerate(['Empleado', 'Fecha', 'Observacion'], 1):
        cell = ws_sum.cell(1, c, h)
        cell.fill = HDR_BG
        cell.font = HDR_FT
        cell.alignment = Alignment(horizontal='center')
    ws_sum.column_dimensions['A'].width = 26
    ws_sum.column_dimensions['B'].width = 16
    ws_sum.column_dimensions['C'].width = 62
    ws_sum.freeze_panes = 'A2'
    ws_sum.cell(1, 5, f'Total anomalias: {len(all_flags)}').font = Font(bold=True)
    for r, (emp, d, comment) in enumerate(all_flags, 2):
        ws_sum.cell(r, 1, emp)
        ws_sum.cell(r, 2, d).number_format = 'DD/MM/YY DDD'
        ws_sum.cell(r, 3, comment)
        for c in range(1, 4):
            ws_sum.cell(r, c).fill = YELLOW

    wb.save(dest)
    return all_flags


# ── Excel nomina (formato Rol de Pagos) ───────────────────────

def write_excel_nomina(nomina_data, periodo, dest):
    """nomina_data: [{name, nomina (dict from calcular_nomina)}]
    periodo: str como 'Marzo 2026'
    """
    wb = Workbook()
    wb.remove(wb.active)

    HDR_BG = PatternFill('solid', fgColor='4472C4')
    HDR_FT = Font(bold=True, color='FFFFFF')
    GREEN  = PatternFill('solid', fgColor='E2EFDA')
    BOLD   = Font(bold=True)
    BOLD_L = Font(bold=True, size=11)
    THIN   = Border(
        bottom=Side(style='thin'),
        top=Side(style='thin'),
    )

    # Hoja resumen
    ws = wb.create_sheet('Resumen Nomina', 0)
    cols = ['Empleado', '1ra Quinc.', '2da Quinc.', 'H. Extras',
            'Transp.', 'Total Ing.', 'IESS', 'Prest.', 'Total Egr.',
            'Neto', 'F. Reserva', 'Total Transf.']
    for c, h in enumerate(cols, 1):
        cell = ws.cell(1, c, h)
        cell.fill = HDR_BG
        cell.font = HDR_FT
        cell.alignment = Alignment(horizontal='center')
    for i in range(1, len(cols) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.column_dimensions['A'].width = 24
    ws.freeze_panes = 'A2'

    for ri, item in enumerate(nomina_data, 2):
        n = item['nomina']
        ws.cell(ri, 1, item['name'])
        ws.cell(ri, 2, n['quincena']).number_format = '$#,##0.00'
        ws.cell(ri, 3, n['quincena']).number_format = '$#,##0.00'
        ws.cell(ri, 4, n['horas_extras']).number_format = '$#,##0.00'
        ws.cell(ri, 5, n['transporte']).number_format = '$#,##0.00'
        ws.cell(ri, 6, n['total_ingresos']).number_format = '$#,##0.00'
        ws.cell(ri, 7, n['iess']).number_format = '$#,##0.00'
        ws.cell(ri, 8, n['prestamo_iess']).number_format = '$#,##0.00'
        ws.cell(ri, 9, n['total_egresos']).number_format = '$#,##0.00'
        ws.cell(ri, 10, n['valor_recibir']).number_format = '$#,##0.00'
        ws.cell(ri, 10).fill = GREEN
        ws.cell(ri, 10).font = BOLD
        ws.cell(ri, 11, n['fondos_reserva']).number_format = '$#,##0.00'
        ws.cell(ri, 12, n['total_transferido']).number_format = '$#,##0.00'
        ws.cell(ri, 12).fill = GREEN

    # Hojas individuales - formato Rol de Pagos
    for item in nomina_data:
        name = item['name']
        n = item['nomina']
        hrs = n['hours']
        ws = wb.create_sheet(title=name[:31])

        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 14
        ws.column_dimensions['C'].width = 30
        ws.column_dimensions['D'].width = 14

        r = 1
        ws.merge_cells('A1:D1')
        ws.cell(r, 1, 'ROL DE PAGOS').font = Font(bold=True, size=14)
        ws.cell(r, 1).alignment = Alignment(horizontal='center')
        r += 2

        ws.cell(r, 1, 'FECHA:').font = BOLD
        ws.cell(r, 2, periodo)
        r += 1
        ws.cell(r, 1, 'EMPLEADO:').font = BOLD
        ws.cell(r, 2, name)
        r += 2

        # Ingresos / Egresos
        for ci in range(1, 5):
            ws.cell(r, ci).fill = HDR_BG
            ws.cell(r, ci).font = HDR_FT
        ws.cell(r, 1, 'INGRESOS')
        ws.cell(r, 3, 'EGRESOS')
        r += 1

        def _ing(label, val):
            nonlocal r
            ws.cell(r, 1, label)
            ws.cell(r, 2, val).number_format = '$#,##0.00'

        def _egr(label, val):
            ws.cell(r, 3, label)
            ws.cell(r, 4, val).number_format = '$#,##0.00'

        _ing('Primera Quincena', n['quincena'])
        _egr(f"Aporte IESS ({IESS_EMPLEADO*100:.2f}%)", n['iess'])
        r += 1
        _ing('Segunda Quincena', n['quincena'])
        if n['prestamo_iess']:
            _egr('Prestamo IESS', n['prestamo_iess'])
        r += 1
        _ing(f"Horas Extras 50% ({n['h_50_pagar']:.2f}h)", n['pay_50'])
        r += 1
        _ing(f"Horas Extras 100% ({hrs['horas_100']:.2f}h)", n['pay_100'])
        r += 1
        if n['transporte']:
            _ing(f"Transporte/Comida ({hrs['dias']}d)", n['transporte'])
            r += 1
        if n['decimo_13']:
            _ing('Decimo Tercer Sueldo', n['decimo_13'])
            r += 1
        if n['decimo_14']:
            _ing('Decimo Cuarto Sueldo', n['decimo_14'])
            r += 1
        if n['bonus']:
            _ing('Bono / Ajuste', n['bonus'])
            r += 1

        r += 1
        for ci in range(1, 5):
            ws.cell(r, ci).border = THIN
            ws.cell(r, ci).font = BOLD
        ws.cell(r, 1, 'TOTAL INGRESOS')
        ws.cell(r, 2, n['total_ingresos'] + n['decimo_13'] + n['decimo_14'] + n['bonus'])
        ws.cell(r, 2).number_format = '$#,##0.00'
        ws.cell(r, 3, 'TOTAL EGRESOS')
        ws.cell(r, 4, n['total_egresos']).number_format = '$#,##0.00'
        r += 1
        ws.cell(r, 1, 'VALOR A RECIBIR').font = BOLD_L
        ws.cell(r, 2, n['valor_recibir']).number_format = '$#,##0.00'
        ws.cell(r, 2).font = BOLD_L
        ws.cell(r, 2).fill = GREEN
        r += 2

        # Detalle de pagos
        for ci in range(1, 3):
            ws.cell(r, ci).fill = HDR_BG
            ws.cell(r, ci).font = HDR_FT
        ws.cell(r, 1, 'DETALLE DE PAGOS')
        r += 1
        ws.cell(r, 1, 'Transferencia del 15')
        ws.cell(r, 2, n['transf_15']).number_format = '$#,##0.00'
        r += 1
        ws.cell(r, 1, 'Transferencia fin de mes')
        ws.cell(r, 2, n['transf_fin']).number_format = '$#,##0.00'
        r += 1
        if n['fondos_reserva']:
            ws.cell(r, 1, 'Fondos de Reserva (incluido)')
            ws.cell(r, 2, n['fondos_reserva']).number_format = '$#,##0.00'
            r += 1
        ws.cell(r, 1, 'TOTAL TRANSFERIDO').font = BOLD
        ws.cell(r, 2, n['total_transferido']).number_format = '$#,##0.00'
        ws.cell(r, 2).font = BOLD
        ws.cell(r, 2).fill = GREEN

        if n['horas_comp_anterior'] != 0:
            r += 2
            ws.cell(r, 1, 'Horas compensatorias mes anterior').font = BOLD
            ws.cell(r, 2, n['horas_comp_anterior']).number_format = '0.00'
            r += 1
            ws.cell(r, 1, 'Arrastre sugerido proximo mes').font = BOLD
            ws.cell(r, 2, n['h_50_arrastre']).number_format = '0.00'

    wb.save(dest)


if __name__ == '__main__':
    import sys
    xls = sys.argv[1] if len(sys.argv) > 1 else 'NGTimereport.xls'
    out = sys.argv[2] if len(sys.argv) > 2 else 'rol_procesado.xlsx'
    flags = write_excel(parse_xls(xls), out)
    print(f'Generado: {out} | Anomalias: {len(flags)}')
