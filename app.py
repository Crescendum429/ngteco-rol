import io
import os
import tempfile
from datetime import time as dt_time

import pandas as pd
import streamlit as st

from procesar_rol import (
    IESS_EMPLEADO,
    SBU_2026,
    calcular_horas_clasificadas,
    calcular_nomina,
    clasificar_todo,
    match_empleados,
    parse_date,
    parse_xls,
    to_time,
    write_excel,
    write_excel_nomina,
)
from storage import (
    export_json, import_json, load_empleados, save_empleados,
    list_reportes, load_reporte, save_reporte, reporte_exists,
    is_changelog_dismissed, dismiss_changelog,
)

APP_VERSION = "3.1"

CHANGELOG = {
    "version": APP_VERSION,
    "titulo": "Nuevo sistema de Roles",
    "items": [
        ("Correccion de fechas",
         "Las fechas del reloj estaban desfasadas un dia. "
         "Ahora se corrigen automaticamente para que coincidan con el dia real de trabajo."),
        ("Registro de empleados",
         "Ya no es necesario ingresar el ID del reloj. "
         "El sistema reconoce a los empleados por nombre al cargar el reporte. "
         "Si detecta alguien nuevo, te pregunta si deseas agregarlo."),
        ("Calculo de sueldos completo",
         "El sistema ahora calcula quincenas, horas extras (50% y 100%), "
         "aportes al IESS, prestamos, fondos de reserva, transporte "
         "y genera un rol de pagos formal en Excel."),
        ("Reportes guardados",
         "Los reportes mensuales se guardan en la nube. "
         "Puedes consultar meses anteriores sin necesidad de volver a subir el archivo."),
        ("Edicion de horas",
         "Puedes corregir las horas de cualquier empleado directamente en la tabla. "
         "Los cambios se guardan automaticamente."),
        ("Datos de empleados seguros",
         "Los salarios y datos de empleados se almacenan de forma segura "
         "y persisten entre sesiones. Ya no se pierden al cerrar la aplicacion."),
    ],
}

st.set_page_config(
    page_title="SOLPLAST",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }
    [data-testid="stSidebar"] * {
        color: #e0e0e0 !important;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"] {
        background-color: #0f3460;
        border: 1px solid #1a508b;
    }
    [data-testid="stSidebar"] .stButton button[kind="secondary"] {
        background-color: transparent;
        border: 1px solid #333;
    }
    .block-container { padding-top: 2rem; }
    [data-testid="stMetric"] {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 3px solid #0f3460;
    }
    h1 { color: #1a1a2e; }
    h2 { color: #16213e; }
</style>
""", unsafe_allow_html=True)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
if APP_PASSWORD:
    if not st.session_state.get("_auth"):
        st.markdown("<div style='text-align:center; padding-top:4rem;'>", unsafe_allow_html=True)
        st.title("SOLPLAST")
        st.markdown("</div>", unsafe_allow_html=True)
        pwd = st.text_input("Password", type="password")
        if pwd and pwd == APP_PASSWORD:
            st.session_state._auth = True
            st.rerun()
        elif pwd:
            st.error("Password incorrecto")
        st.stop()

if "emp_db" not in st.session_state:
    st.session_state.emp_db = load_empleados()


# ── Changelog dialog ──────────────────────────────────────────
@st.dialog("Novedades", width="large")
def _show_changelog():
    cl = CHANGELOG
    for titulo, desc in cl["items"]:
        st.markdown(f"**{titulo}**")
        st.caption(desc)
    st.divider()
    no_show = st.checkbox("No volver a mostrar")
    if st.button("Entendido", use_container_width=True, type="primary"):
        if no_show:
            dismiss_changelog(cl["version"])
        st.session_state._changelog_shown = True
        st.rerun()


if not st.session_state.get("_changelog_shown"):
    if not is_changelog_dismissed(APP_VERSION):
        _show_changelog()


def _save():
    save_empleados(st.session_state.emp_db)


def _default_emp(nombre=""):
    return {
        "nombre": nombre,
        "salario": 0.0,
        "horas_base": 8,
        "transporte_dia": 0.0,
        "region": "Sierra/Amazonia",
        "cargo": "",
        "prestamo_iess": 0.0,
        "fondos_reserva": False,
        "horas_comp_anterior": 0.0,
        "ocultar": False,
    }


def _time_to_mins(t):
    if t is None or pd.isna(t):
        return None
    if isinstance(t, dt_time):
        return t.hour * 60 + t.minute
    return None


# ── Sidebar ───────────────────────────────────────────────────
st.sidebar.markdown("## SOLPLAST")
st.sidebar.caption("Sistema de gestion")
st.sidebar.divider()

if "pagina" not in st.session_state:
    st.session_state.pagina = "Roles"

for mod, icon in [("Roles", "📋"), ("Empleados", "👥")]:
    active = st.session_state.pagina == mod
    if st.sidebar.button(
        f"{icon}  {mod}", use_container_width=True,
        type="primary" if active else "secondary",
    ):
        st.session_state.pagina = mod
        st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"v{APP_VERSION}")
pagina = st.session_state.pagina


# ── Pagina: Empleados ─────────────────────────────────────────
if pagina == "Empleados":
    st.header("Empleados")
    emp_db = st.session_state.emp_db

    # Alertas de matching
    if st.session_state.get("_file"):
        nuevos = st.session_state.get("nuevos", [])
        faltantes = st.session_state.get("faltantes", [])

        if nuevos:
            st.warning(f"{len(nuevos)} empleado(s) en el reporte no estan en la base de datos.")
            for name, nid in nuevos:
                ca, cb = st.columns([4, 1])
                ca.write(f"**{name}** (ID reloj: {nid})")
                if cb.button(f"Agregar", key=f"add_{nid}"):
                    key = nid or name
                    emp_db[key] = _default_emp(name)
                    emp_db[key]["ngteco_id"] = nid
                    _save()
                    st.rerun()

        if faltantes:
            st.info(f"{len(faltantes)} empleado(s) de la base no aparecen en este reporte.")
            for key in faltantes:
                emp = emp_db[key]
                ca, cb = st.columns([4, 1])
                ca.write(f"**{emp.get('nombre', key)}** — no encontrado en el reporte")
                if cb.checkbox("No preguntar", key=f"hide_{key}"):
                    emp_db[key]["ocultar"] = True
                    _save()
                    st.rerun()

        if nuevos or faltantes:
            st.divider()

    # Backup
    ba, bb = st.columns(2)
    ba.download_button(
        "Descargar respaldo (.json)",
        data=export_json(emp_db),
        file_name="empleados_backup.json",
        mime="application/json",
        use_container_width=True,
    )
    backup_file = bb.file_uploader("Restaurar respaldo", type=["json"], key="cfg_upload")
    if backup_file:
        try:
            st.session_state.emp_db = import_json(backup_file.read().decode())
            _save()
            st.rerun()
        except Exception:
            bb.error("Archivo invalido")

    st.divider()

    # Agregar empleado manual
    with st.expander("Agregar empleado"):
        new_name = st.text_input("Nombre completo", key="new_emp_name")
        if st.button("Agregar") and new_name:
            key = new_name.strip().lower().replace(" ", "_")
            emp_db[key] = _default_emp(new_name.strip())
            _save()
            st.rerun()

    # Lista
    sorted_keys = sorted(emp_db.keys(), key=lambda k: emp_db[k].get("nombre", ""))

    for eid in sorted_keys:
        emp = emp_db[eid]
        nombre = emp.get("nombre", eid)

        with st.container(border=True):
            st.markdown(f"**{nombre}**")
            ca, cb, cc, cd = st.columns(4)

            emp["salario"] = ca.number_input(
                "Salario ($)", min_value=0.0, step=10.0,
                value=float(emp.get("salario", 0)),
                key=f"db_sal_{eid}", format="%.2f",
            )
            emp["horas_base"] = cb.number_input(
                "h/dia", min_value=1, max_value=12,
                value=int(emp.get("horas_base", 8)),
                key=f"db_base_{eid}",
            )
            emp["transporte_dia"] = cc.number_input(
                "Transp. ($/dia)", min_value=0.0, step=0.5,
                value=float(emp.get("transporte_dia", 0)),
                key=f"db_transp_{eid}", format="%.2f",
            )
            emp["prestamo_iess"] = cd.number_input(
                "Prestamo IESS ($)", min_value=0.0, step=1.0,
                value=float(emp.get("prestamo_iess", 0)),
                key=f"db_prest_{eid}", format="%.2f",
            )

            ea, eb, ec, ed = st.columns(4)
            emp["region"] = ea.selectbox(
                "Region", ["Sierra/Amazonia", "Costa/Galapagos"],
                index=0 if emp.get("region") == "Sierra/Amazonia" else 1,
                key=f"db_reg_{eid}",
            )
            emp["cargo"] = eb.text_input(
                "Cargo", value=emp.get("cargo", ""),
                key=f"db_cargo_{eid}",
            )
            emp["fondos_reserva"] = ec.checkbox(
                "Fondos de reserva", value=emp.get("fondos_reserva", False),
                key=f"db_fondos_{eid}",
                help="8.33% mensual, aplica despues de 1 ano de servicio",
            )
            emp["horas_comp_anterior"] = ed.number_input(
                "H. comp. mes ant.", step=0.5,
                value=float(emp.get("horas_comp_anterior", 0)),
                key=f"db_hcomp_{eid}", format="%.2f",
                help="Horas compensatorias arrastradas del mes anterior",
            )

            if st.button("Eliminar", key=f"db_del_{eid}", type="secondary"):
                del emp_db[eid]
                _save()
                st.rerun()

    if st.button("Guardar cambios", use_container_width=True, type="primary"):
        _save()
        st.success("Guardado.")


# ── Pagina: Roles ─────────────────────────────────────────────
if pagina == "Roles":
    st.header("Roles")

    MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
             'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

    def _detect_periodo(data):
        for _, days, _ in data:
            for ds in days:
                try:
                    d = parse_date(ds)
                    return f"{d.year}-{d.month:02d}", f"{MESES[d.month-1]} {d.year}"
                except Exception:
                    pass
        return None, None

    # Reportes guardados
    reportes = list_reportes()
    reportes_ids = [r["id"] for r in reportes]
    reportes_labels = {r["id"]: r["periodo"] for r in reportes}

    # Selector de mes guardado + subir nuevo
    sa, sb = st.columns([3, 2])

    opciones = ["Subir nuevo reporte"] + [reportes_labels.get(rid, rid) for rid in reportes_ids]
    sel = sa.selectbox("Periodo", opciones, key="sel_periodo")

    loaded_from_db = False
    has_data = False

    if sel == "Subir nuevo reporte":
        uploaded = sb.file_uploader("Archivo .xls", type=["xls"], key="xls_upload",
                                    label_visibility="collapsed")
        if uploaded:
            if st.session_state.get("_file") != uploaded.name:
                with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name
                try:
                    st.session_state.data = parse_xls(tmp_path)
                    st.session_state._file = uploaded.name
                    st.session_state.cls = clasificar_todo(st.session_state.data)
                finally:
                    os.unlink(tmp_path)

                rid, periodo = _detect_periodo(st.session_state.data)
                st.session_state._pending_rid = rid
                st.session_state._pending_periodo = periodo

            # Guardar automaticamente o preguntar
            rid = st.session_state.get("_pending_rid")
            periodo = st.session_state.get("_pending_periodo")

            if rid:
                if reporte_exists(rid):
                    st.warning(f"Ya existe un reporte para **{periodo}**.")
                    if st.button(f"Sobreescribir {periodo}"):
                        save_reporte(rid, periodo, st.session_state.data, st.session_state.cls)
                        st.session_state._pending_rid = None
                        st.success("Reporte guardado.")
                        st.rerun()
                else:
                    save_reporte(rid, periodo, st.session_state.data, st.session_state.cls)
                    st.session_state._pending_rid = None
                    st.success(f"Reporte {periodo} guardado.")
                    st.rerun()

            has_data = True

    else:
        sel_idx = opciones.index(sel) - 1
        sel_rid = reportes_ids[sel_idx]
        if st.session_state.get("_loaded_rid") != sel_rid:
            data_loaded, cls_loaded = load_reporte(sel_rid)
            if data_loaded:
                st.session_state.data = data_loaded
                st.session_state.cls = cls_loaded
                st.session_state._loaded_rid = sel_rid
                st.session_state._file = sel_rid
            else:
                st.error("Error cargando reporte.")
                st.stop()
        loaded_from_db = True
        has_data = True

    if not has_data:
        st.stop()

    data = st.session_state.data
    cls = st.session_state.cls
    emp_db = st.session_state.emp_db
    matched, nuevos, faltantes = match_empleados(data, emp_db)
    st.session_state.matched = matched
    st.session_state.nuevos = nuevos
    st.session_state.faltantes = faltantes
    matched = matched

    anomalias = []
    for emp_full, days, nid in data:
        name = emp_full.split("(")[0].strip()
        if name not in cls:
            continue
        for ds, d in cls[name].items():
            for f in d["flags"]:
                if f.startswith("REVISAR:"):
                    anomalias.append({"Empleado": name, "Fecha": ds, "Obs.": f})

    st.divider()
    ba, bb = st.columns(2)
    for col, label, icon in [(ba, "Horas", "🕐"), (bb, "Sueldos", "💰")]:
        active = st.session_state.get("sub_rol", "Horas") == label
        if col.button(f"{icon} {label}", use_container_width=True,
                      type="primary" if active else "secondary"):
            st.session_state.sub_rol = label
            st.rerun()
    sub = st.session_state.get("sub_rol", "Horas")

    # ── Sub: Horas ────────────────────────────────────────────
    if sub == "Horas":
        c1, c2 = st.columns(2)
        c1.metric("Empleados", len(data))
        c2.metric("Anomalias", len(anomalias))

        _, p_label = _detect_periodo(data)
        out_name = (p_label or "reporte").replace(" ", "_") + "_horas.xlsx"
        buf = io.BytesIO()
        write_excel(data, buf, overrides=cls)
        st.download_button(
            "Descargar Horas Corregidas (.xlsx)",
            data=buf.getvalue(),
            file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if anomalias:
            with st.expander(f"Ver {len(anomalias)} anomalias pendientes"):
                st.dataframe(anomalias, hide_index=True, use_container_width=True)

        st.divider()
        emp_names_xls = [e.split("(")[0].strip() for e, _, _ in data]
        selected = st.selectbox("Empleado", emp_names_xls, key="edit_emp")

        day_cls = cls[selected]
        dates_sorted = sorted(day_cls.keys())

        rows = []
        for ds in dates_sorted:
            d = day_cls[ds]
            total_h = 0.0
            if d["h1"] is not None and d["h2"] is not None:
                total_h += (d["h2"] - d["h1"]) / 60
            if d["h3"] is not None and d["h4"] is not None:
                total_h += (d["h4"] - d["h3"]) / 60
            try:
                dt = parse_date(ds)
            except Exception:
                dt = ds
            rows.append({
                "Fecha": dt,
                "Hora 1": to_time(d["h1"]),
                "Hora 2": to_time(d["h2"]),
                "Hora 3": to_time(d["h3"]),
                "Hora 4": to_time(d["h4"]),
                "Total": round(total_h, 2) if total_h > 0 else None,
                "Obs.": "; ".join(d["flags"]) if d["flags"] else "",
            })

        edited_df = st.data_editor(
            pd.DataFrame(rows),
            column_config={
                "Fecha": st.column_config.DateColumn(disabled=True, format="DD/MM ddd"),
                "Hora 1": st.column_config.TimeColumn(format="HH:mm"),
                "Hora 2": st.column_config.TimeColumn(format="HH:mm"),
                "Hora 3": st.column_config.TimeColumn(format="HH:mm"),
                "Hora 4": st.column_config.TimeColumn(format="HH:mm"),
                "Total": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                "Obs.": st.column_config.TextColumn(disabled=True, width="medium"),
            },
            hide_index=True,
            use_container_width=True,
            key=f"ed_{selected}",
        )

        _edits = False
        for idx, ds in enumerate(dates_sorted):
            row = edited_df.iloc[idx]
            new = {
                "h1": _time_to_mins(row["Hora 1"]),
                "h2": _time_to_mins(row["Hora 2"]),
                "h3": _time_to_mins(row["Hora 3"]),
                "h4": _time_to_mins(row["Hora 4"]),
            }
            old = day_cls[ds]
            if any(new[k] != old[k] for k in ("h1", "h2", "h3", "h4")):
                _edits = True
                new_flags = [f for f in old["flags"] if not f.startswith("REVISAR:")]
                if "CORREGIDO" not in " ".join(new_flags):
                    new_flags.append("CORREGIDO MANUALMENTE")
                new["flags"] = new_flags
                st.session_state.cls[selected][ds] = new

        if _edits:
            rid, periodo = _detect_periodo(data)
            if rid:
                save_reporte(rid, periodo, data, st.session_state.cls)
            st.rerun()

    # ── Sub: Sueldos ───────────────────────────────────────────
    if sub == "Sueldos":
        dc1, dc2 = st.columns(2)
        decimo_13 = dc1.toggle(
            "Decimo Tercer Sueldo",
            help="1 salario mensual. Hasta dic 24. (Art. 111-112)",
        )
        decimo_14 = dc2.toggle(
            f"Decimo Cuarto Sueldo (${SBU_2026:.0f})",
            help=f"1 SBU (${SBU_2026:.0f}). Sierra: ago 15 / Costa: mar 15. (Art. 113)",
        )

        nomina_list = []
        any_salary = False

        for emp_full, days, nid in data:
            name = emp_full.split("(")[0].strip()
            db_key = matched.get(name)
            cfg = emp_db.get(db_key, _default_emp()) if db_key else _default_emp()
            salario = cfg.get("salario", 0)

            hrs = calcular_horas_clasificadas(cls.get(name, {}), cfg.get("horas_base", 8))

            with st.container(border=True):
                cargo = f" · {cfg['cargo']}" if cfg.get("cargo") else ""
                st.markdown(f"**{name}**{cargo}")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Dias", hrs["dias"])
                m2.metric("Horas", f"{hrs['horas_total']:.1f}")
                m3.metric("H. 50%", f"{hrs['horas_50']:.2f}")
                m4.metric("H. 100%", f"{hrs['horas_100']:.2f}")

                if hrs["dias_anomalia"]:
                    st.caption(f"⚠ {hrs['dias_anomalia']} dia(s) con datos incompletos")

                if salario <= 0:
                    st.caption("Configura el salario en Empleados.")
                    continue

                any_salary = True
                bonus = st.number_input(
                    "Bono / Ajuste ($)", step=1.0,
                    key=f"bonus_{nid}", format="%.2f",
                )

                n = calcular_nomina(hrs, cfg, {
                    'decimo_13': decimo_13,
                    'decimo_14': decimo_14,
                    'bonus': bonus,
                })
                nomina_list.append({'name': name, 'nomina': n})

                # Ingresos
                st.markdown("**Ingresos**")
                i1, i2, i3, i4 = st.columns(4)
                i1.metric("1ra Quincena", f"${n['quincena']:,.2f}")
                i2.metric("2da Quincena", f"${n['quincena']:,.2f}")
                i3.metric("H. Extras", f"${n['horas_extras']:,.2f}",
                          f"50%: ${n['pay_50']:,.2f} | 100%: ${n['pay_100']:,.2f}")
                i4.metric("Transp.", f"${n['transporte']:,.2f}",
                          f"{hrs['dias']}d x ${cfg.get('transporte_dia', 0):,.2f}")

                # Egresos y neto
                st.markdown("**Resultado**")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Total Ingresos", f"${n['total_ingresos']:,.2f}")
                r2.metric("IESS 9.45%", f"-${n['iess']:,.2f}")
                prestamo_str = f"Prest: -${n['prestamo_iess']:,.2f}" if n['prestamo_iess'] else None
                r3.metric("Neto", f"${n['valor_recibir']:,.2f}", prestamo_str)
                r4.metric("Total Transferido", f"${n['total_transferido']:,.2f}",
                          f"F.Reserva: ${n['fondos_reserva']:,.2f}" if n['fondos_reserva'] else None)

                # Arrastre sugerido
                if n['h_50_arrastre'] != 0:
                    st.caption(
                        f"Arrastre sugerido para proximo mes: {n['h_50_arrastre']:.2f}h compensatorias"
                    )

        if any_salary:
            st.divider()
            buf2 = io.BytesIO()
            _, periodo_label = _detect_periodo(data)
            write_excel_nomina(nomina_list, periodo_label or "Periodo", buf2)
            _, p_label2 = _detect_periodo(data)
            out2 = (p_label2 or "reporte").replace(" ", "_") + "_nomina.xlsx"
            st.download_button(
                "Descargar Nomina Completa (.xlsx)",
                data=buf2.getvalue(),
                file_name=out2,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
            st.caption(
                f"H. 50%: Art. 55 · H. 100%: Art. 55 · IESS: {IESS_EMPLEADO*100:.2f}% · "
                f"13ro: Art. 111 · 14to: Art. 113 (SBU ${SBU_2026:.0f})"
            )
