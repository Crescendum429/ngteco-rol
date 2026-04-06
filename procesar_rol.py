import re
import xlrd
from datetime import date, time
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment

MORN_MIN  = 5 * 60        # 05:00
MORN_MAX  = 8 * 60 + 45   # 08:45
LUNCH_MIN = 11 * 60       # 11:00
LUNCH_MAX = 15 * 60       # 15:00
AFT_MIN   = 14 * 60       # 14:00
AFT_MAX   = 19 * 60       # 19:00
SHORT_SEG = 60

WEEKDAYS = {'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'}


def to_mins(s):
    if not s or not str(s).strip():
        return None
    m = re.match(r'(\d+):(\d+)', str(s).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def to_time(m):
    return time(m // 60, m % 60) if m is not None else None


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
            emp = re.sub(r'\n', ' ', str(row[3])).strip()
            days = {}
            result.append((emp, days))
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
        flags.append(f'REVISAR: {len(active)} registros en el dia - verificar manualmente')

    return h1, h2, h3, h4, flags


def write_excel(data, dest):
    wb = Workbook()
    wb.remove(wb.active)

    YELLOW = PatternFill('solid', fgColor='FFFF99')
    HDR_BG = PatternFill('solid', fgColor='4472C4')
    HDR_FT = Font(bold=True, color='FFFFFF')

    all_flags = []

    for emp, days in data:
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
            h1, h2, h3, h4, flags = classify(days[ds])

            try:
                p = ds.split('-')
                d = date(2000 + int(p[0]), int(p[1]), int(p[2]))
            except Exception:
                d = ds

            ws.cell(r, 1, d).number_format = 'DD/MM/YY DDD'

            for col, val in [(2, h1), (3, h2), (4, h3), (5, h4)]:
                if val is not None:
                    ws.cell(r, col, to_time(val)).number_format = 'HH:MM'

            if h1 is not None and h2 is not None:
                if h3 is not None and h4 is not None:
                    ws.cell(r, 6).value = f'=((C{r}-B{r})+(E{r}-D{r}))*24'
                    ws.cell(r, 6).number_format = '0.00'
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


if __name__ == '__main__':
    import sys
    xls = sys.argv[1] if len(sys.argv) > 1 else 'NGTimereport.xls'
    out = sys.argv[2] if len(sys.argv) > 2 else 'rol_procesado.xlsx'
    flags = write_excel(parse_xls(xls), out)
    print(f'Generado: {out} | Anomalias: {len(flags)}')
