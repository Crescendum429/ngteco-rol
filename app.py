import io
import os
import tempfile

import streamlit as st

from procesar_rol import (
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
        # Pre-generar v1 para no recalcular en cada interaccion
        buf = io.BytesIO()
        write_excel(st.session_state.data, buf)
        st.session_state.v1_bytes = buf.getvalue()
    finally:
        os.unlink(tmp_path)

data = st.session_state.data

# Anomalias (para ambos tabs)
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

    any_salary = False
    salary_collected = {}

    for emp, days in data:
        name = emp.split("(")[0].strip()

        with st.container(border=True):
            # Fila 1: nombre + inputs
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

            # Fila 2: metricas de horas
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

            # Fila 3: calculo de pago (solo si hay salario)
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

                total = salary + pay_50 + pay_100 + bonus

                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Salario", f"${salary:,.2f}")
                t2.metric("+50%", f"${pay_50:,.2f}",
                          f"{hrs['horas_50']:.1f}h x ${hourly*1.5:,.2f}")
                t3.metric("+100%", f"${pay_100:,.2f}",
                          f"{hrs['horas_100']:.1f}h x ${hourly*2:,.2f}")
                t4.metric("TOTAL", f"${total:,.2f}",
                          f"Bono: ${bonus:,.2f}" if bonus else None)

                salary_collected[name] = {
                    'salary': salary,
                    'base_hours': int(base_h),
                    'bonus': bonus,
                    'note': note,
                    'hours': hrs,
                    'pay_50': pay_50,
                    'pay_100': pay_100,
                    'total': total,
                    'hourly': hourly,
                }

    # Boton de descarga nomina
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
            "Horas suplementarias (50%): horas extra en dias laborables, "
            "max 4h/dia. Horas extraordinarias (100%): fines de semana "
            "o exceso de 12h diarias. (Art. 55, Codigo del Trabajo Ecuador)"
        )
