import io
import os
import tempfile

import streamlit as st

from procesar_rol import (
    SBU_2026,
    calcular_horas_empleado,
    classify,
    parse_xls,
    write_excel,
    write_excel_nomina,
)

st.set_page_config(page_title="Roles NGTeco", page_icon="📋", layout="wide")
st.title("Procesador de Roles")

uploaded = st.file_uploader("Archivo del NGTeco (.xls)", type=["xls"])
if not uploaded:
    st.stop()

# Procesar una sola vez por archivo
if st.session_state.get("_file") != uploaded.name:
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name
    try:
        st.session_state.data = parse_xls(tmp_path)
        st.session_state._file = uploaded.name
        buf = io.BytesIO()
        write_excel(st.session_state.data, buf)
        st.session_state.v1_bytes = buf.getvalue()
    finally:
        os.unlink(tmp_path)

data = st.session_state.data

anomalias = []
for emp, days in data:
    nombre = emp.split("(")[0].strip()
    for ds, pairs in days.items():
        _, _, _, _, flags = classify(pairs)
        for f in flags:
            anomalias.append({"Empleado": nombre, "Fecha": ds, "Observacion": f})

tab1, tab2 = st.tabs(["Horas", "Nomina"])

# ── Tab 1: Horas ──────────────────────────────────────────────
with tab1:
    c1, c2 = st.columns(2)
    c1.metric("Empleados", len(data))
    c2.metric("Anomalias", len(anomalias))

    out_name = uploaded.name.rsplit(".", 1)[0] + "_horas.xlsx"
    st.download_button(
        "Descargar Horas Corregidas (.xlsx)",
        data=st.session_state.v1_bytes,
        file_name=out_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    if anomalias:
        with st.expander(f"Ver {len(anomalias)} anomalias detectadas"):
            st.dataframe(anomalias, hide_index=True, use_container_width=True)

# ── Tab 2: Nomina ─────────────────────────────────────────────
with tab2:
    st.caption("Los salarios no se almacenan — se borran al cerrar la sesion.")

    # Decimos
    dc1, dc2 = st.columns(2)
    decimo_13 = dc1.toggle(
        "Incluir Decimo Tercer Sueldo",
        help="Equivale a 1 salario mensual. Se paga hasta el 24 de diciembre. "
             "Periodo: dic 1 — nov 30. (Art. 111-112, Codigo del Trabajo)",
    )
    decimo_14 = dc2.toggle(
        f"Incluir Decimo Cuarto Sueldo (${SBU_2026:.0f})",
        help=f"Equivale a 1 SBU (${SBU_2026:.0f} en 2026). "
             "Sierra/Amazonia: hasta ago 15 (periodo ago 1 — jul 31). "
             "Costa/Galapagos: hasta mar 15 (periodo mar 1 — feb 28). "
             "(Art. 113, Codigo del Trabajo)",
    )

    if decimo_13 or decimo_14:
        st.divider()

    any_salary = False
    salary_collected = {}

    for emp, days in data:
        name = emp.split("(")[0].strip()

        with st.container(border=True):
            r1a, r1b, r1c = st.columns([4, 2, 1])
            r1a.markdown(f"**{name}**")
            salary = r1b.number_input(
                "Salario base ($)", min_value=0.0, step=10.0,
                key=f"sal_{name}", format="%.2f",
            )
            base_h = r1c.number_input(
                "h/dia", min_value=1, max_value=12, value=8,
                key=f"base_{name}",
            )

            hrs = calcular_horas_empleado(days, base_hours=int(base_h))

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Dias", hrs['dias'])
            m2.metric("Horas", f"{hrs['horas_total']:.1f}")
            m3.metric("H. 50%", f"{hrs['horas_50']:.2f}")
            m4.metric("H. 100%", f"{hrs['horas_100']:.2f}")

            if hrs['dias_anomalia']:
                st.caption(
                    f"⚠ {hrs['dias_anomalia']} dia(s) con datos incompletos"
                    " — las horas pueden estar subestimadas."
                )

            if salary > 0:
                any_salary = True
                hourly = salary / 30 / int(base_h)
                pay_50 = hrs['horas_50'] * hourly * 1.5
                pay_100 = hrs['horas_100'] * hourly * 2.0

                ba, bb = st.columns(2)
                bonus = ba.number_input(
                    "Bono / Ajuste ($)", step=1.0,
                    key=f"bonus_{name}", format="%.2f",
                )
                note = bb.text_input(
                    "Nota del ajuste", key=f"note_{name}",
                    placeholder="Opcional",
                )

                d13 = salary if decimo_13 else 0.0
                d14 = SBU_2026 if decimo_14 else 0.0
                total = salary + pay_50 + pay_100 + bonus + d13 + d14

                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Salario", f"${salary:,.2f}")
                t2.metric("+50%", f"${pay_50:,.2f}",
                          f"{hrs['horas_50']:.1f}h x ${hourly*1.5:,.2f}")
                t3.metric("+100%", f"${pay_100:,.2f}",
                          f"{hrs['horas_100']:.1f}h x ${hourly*2:,.2f}")

                # Linea de decimos en el total
                delta_parts = []
                if d13:
                    delta_parts.append(f"13ro: ${d13:,.2f}")
                if d14:
                    delta_parts.append(f"14to: ${d14:,.0f}")
                if bonus:
                    delta_parts.append(f"Bono: ${bonus:,.2f}")
                delta_str = " | ".join(delta_parts) if delta_parts else None

                t4.metric("TOTAL", f"${total:,.2f}", delta_str)

                salary_collected[name] = {
                    'salary': salary,
                    'base_hours': int(base_h),
                    'bonus': bonus,
                    'note': note,
                    'hours': hrs,
                    'pay_50': pay_50,
                    'pay_100': pay_100,
                    'decimo_13': d13,
                    'decimo_14': d14,
                    'total': total,
                    'hourly': hourly,
                }

    if any_salary:
        st.divider()
        buf2 = io.BytesIO()
        write_excel_nomina(data, salary_collected, buf2)
        nomina_bytes = buf2.getvalue()
        out2 = uploaded.name.rsplit(".", 1)[0] + "_nomina.xlsx"
        st.download_button(
            "Descargar Nomina Completa (.xlsx)",
            data=nomina_bytes,
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
