import io
import json
import os
import tempfile
from datetime import time as dt_time

import pandas as pd
import streamlit as st

from procesar_rol import (
    SBU_2026,
    calcular_horas_clasificadas,
    clasificar_todo,
    parse_date,
    parse_xls,
    to_time,
    write_excel,
    write_excel_nomina,
)

st.set_page_config(page_title="Roles NGTeco", layout="wide")

# Login
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
if APP_PASSWORD:
    if not st.session_state.get("_auth"):
        st.title("Procesador de Roles")
        pwd = st.text_input("Password", type="password")
        if pwd and pwd == APP_PASSWORD:
            st.session_state._auth = True
            st.rerun()
        elif pwd:
            st.error("Password incorrecto")
        st.stop()

st.title("Procesador de Roles")

uploaded = st.file_uploader("Archivo del NGTeco (.xls)", type=["xls"])
if not uploaded:
    st.stop()

# Procesar XLS una sola vez
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

    # Inicializar config de empleados (solo nuevos, no sobreescribir existente)
    if "emp_config" not in st.session_state:
        st.session_state.emp_config = {}
    for emp, _ in st.session_state.data:
        name = emp.split("(")[0].strip()
        if name not in st.session_state.emp_config:
            st.session_state.emp_config[name] = {
                "salario": 0.0,
                "horas_base": 8,
                "transporte_dia": 0.0,
                "region": "Sierra/Amazonia",
                "notas": "",
            }

data = st.session_state.data
cls = st.session_state.cls
emp_names = [e.split("(")[0].strip() for e, _ in data]

# Anomalias
anomalias = []
for name in emp_names:
    for ds, d in cls[name].items():
        for f in d["flags"]:
            if f.startswith("REVISAR:"):
                anomalias.append({"Empleado": name, "Fecha": ds, "Observacion": f})


def _time_to_mins(t):
    if t is None or pd.isna(t):
        return None
    if isinstance(t, dt_time):
        return t.hour * 60 + t.minute
    return None


tab1, tab2, tab3 = st.tabs(["Horas", "Empleados", "Nomina"])

# ── Tab 1: Horas ──────────────────────────────────────────────
with tab1:
    c1, c2 = st.columns(2)
    c1.metric("Empleados", len(data))
    c2.metric("Anomalias", len(anomalias))

    out_name = uploaded.name.rsplit(".", 1)[0] + "_horas.xlsx"
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
    selected = st.selectbox("Empleado", emp_names, key="edit_emp")

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
        st.rerun()


# ── Tab 2: Empleados ──────────────────────────────────────────
with tab2:
    st.caption("Configura los datos de cada empleado. Guarda el archivo JSON para reutilizarlo el proximo mes.")

    ea, eb = st.columns(2)

    config_file = ea.file_uploader("Cargar configuracion guardada", type=["json"], key="cfg_upload")
    if config_file:
        try:
            loaded = json.load(config_file)
            for name, vals in loaded.items():
                if name in st.session_state.emp_config:
                    st.session_state.emp_config[name].update(vals)
                else:
                    st.session_state.emp_config[name] = vals
            st.rerun()
        except json.JSONDecodeError:
            ea.error("Archivo JSON invalido")

    cfg_json = json.dumps(st.session_state.emp_config, indent=2, ensure_ascii=False)
    eb.download_button(
        "Guardar configuracion (.json)",
        data=cfg_json,
        file_name="empleados_config.json",
        mime="application/json",
        use_container_width=True,
    )

    st.divider()

    for name in emp_names:
        cfg = st.session_state.emp_config[name]

        with st.container(border=True):
            st.markdown(f"**{name}**")
            ca, cb, cc, cd = st.columns(4)

            cfg["salario"] = ca.number_input(
                "Salario base ($)", min_value=0.0, step=10.0,
                value=cfg["salario"], key=f"cfg_sal_{name}", format="%.2f",
            )
            cfg["horas_base"] = cb.number_input(
                "Horas base / dia", min_value=1, max_value=12,
                value=cfg["horas_base"], key=f"cfg_base_{name}",
            )
            cfg["transporte_dia"] = cc.number_input(
                "Transporte/comida ($/dia)", min_value=0.0, step=0.5,
                value=cfg["transporte_dia"], key=f"cfg_transp_{name}", format="%.2f",
            )
            cfg["region"] = cd.selectbox(
                "Region", ["Sierra/Amazonia", "Costa/Galapagos"],
                index=0 if cfg["region"] == "Sierra/Amazonia" else 1,
                key=f"cfg_reg_{name}",
            )
            cfg["notas"] = st.text_input(
                "Notas", value=cfg["notas"], key=f"cfg_notas_{name}",
                placeholder="Cargo, observaciones, etc.",
            )


# ── Tab 3: Nomina ─────────────────────────────────────────────
with tab3:
    dc1, dc2 = st.columns(2)
    decimo_13 = dc1.toggle(
        "Incluir Decimo Tercer Sueldo",
        help="Equivale a 1 salario mensual. Se paga hasta el 24 de diciembre. "
             "Periodo: dic 1 — nov 30. (Art. 111-112, Codigo del Trabajo)",
    )
    decimo_14 = dc2.toggle(
        f"Incluir Decimo Cuarto Sueldo (${SBU_2026:.0f})",
        help=f"Equivale a 1 SBU (${SBU_2026:.0f} en 2026). "
             "Sierra/Amazonia: hasta ago 15. Costa/Galapagos: hasta mar 15. "
             "(Art. 113, Codigo del Trabajo)",
    )

    any_salary = False
    salary_collected = {}

    for name in emp_names:
        cfg = st.session_state.emp_config[name]
        salary = cfg["salario"]
        base_h = cfg["horas_base"]
        transporte_dia = cfg["transporte_dia"]

        hrs = calcular_horas_clasificadas(cls[name], base_hours=base_h)

        with st.container(border=True):
            st.markdown(f"**{name}**")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Dias", hrs["dias"])
            m2.metric("Horas", f"{hrs['horas_total']:.1f}")
            m3.metric("H. 50%", f"{hrs['horas_50']:.2f}")
            m4.metric("H. 100%", f"{hrs['horas_100']:.2f}")

            if hrs["dias_anomalia"]:
                st.caption(
                    f"⚠ {hrs['dias_anomalia']} dia(s) con datos incompletos"
                    " — las horas pueden estar subestimadas."
                )

            if salary <= 0:
                st.caption("Configura el salario en la pestana Empleados.")
                continue

            any_salary = True
            hourly = salary / 30 / base_h
            pay_50 = hrs["horas_50"] * hourly * 1.5
            pay_100 = hrs["horas_100"] * hourly * 2.0
            transporte = hrs["dias"] * transporte_dia

            bonus = st.number_input(
                "Bono / Ajuste ($)", step=1.0,
                key=f"bonus_{name}", format="%.2f",
            )

            d13 = salary if decimo_13 else 0.0
            d14 = SBU_2026 if decimo_14 else 0.0
            total = salary + pay_50 + pay_100 + transporte + bonus + d13 + d14

            t1, t2, t3, t4, t5 = st.columns(5)
            t1.metric("Salario", f"${salary:,.2f}")
            t2.metric("+50%", f"${pay_50:,.2f}",
                      f"{hrs['horas_50']:.1f}h x ${hourly*1.5:,.2f}")
            t3.metric("+100%", f"${pay_100:,.2f}",
                      f"{hrs['horas_100']:.1f}h x ${hourly*2:,.2f}")
            t4.metric("Transp.", f"${transporte:,.2f}",
                      f"{hrs['dias']}d x ${transporte_dia:,.2f}" if transporte else None)

            delta_parts = []
            if d13:
                delta_parts.append(f"13ro: ${d13:,.2f}")
            if d14:
                delta_parts.append(f"14to: ${d14:,.0f}")
            if bonus:
                delta_parts.append(f"Bono: ${bonus:,.2f}")
            t5.metric("TOTAL", f"${total:,.2f}",
                      " | ".join(delta_parts) if delta_parts else None)

            salary_collected[name] = {
                "salary": salary,
                "base_hours": base_h,
                "bonus": bonus,
                "note": "",
                "hours": hrs,
                "pay_50": pay_50,
                "pay_100": pay_100,
                "transporte": transporte,
                "decimo_13": d13,
                "decimo_14": d14,
                "total": total,
                "hourly": hourly,
            }

    if any_salary:
        st.divider()
        buf2 = io.BytesIO()
        write_excel_nomina(data, salary_collected, buf2, overrides=cls)
        out2 = uploaded.name.rsplit(".", 1)[0] + "_nomina.xlsx"
        st.download_button(
            "Descargar Nomina Completa (.xlsx)",
            data=buf2.getvalue(),
            file_name=out2,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )
        st.caption(
            "H. suplementarias (50%): extra en dias laborables, max 4h/dia. "
            "H. extraordinarias (100%): fines de semana o >12h diarias. "
            "(Art. 55, Codigo del Trabajo) · "
            f"13ro: Art. 111-112 · 14to: Art. 113 (SBU ${SBU_2026:.0f})"
        )
