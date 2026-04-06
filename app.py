import io
import os
import tempfile

import streamlit as st

from procesar_rol import classify, parse_xls, write_excel

st.set_page_config(page_title="Roles NGTeco", page_icon="📋", layout="centered")

st.title("Procesador de Roles")
st.caption("Carga el reporte XLS del reloj NGTeco y descarga el rol listo para revisar.")

uploaded = st.file_uploader("Archivo del NGTeco (.xls)", type=["xls"])

if uploaded:
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        data = parse_xls(tmp_path)

        anomalias = []
        for emp, days in data:
            nombre = emp.split("(")[0].strip()
            for ds, pairs in days.items():
                _, _, _, _, flags = classify(pairs)
                for f in flags:
                    anomalias.append({"Empleado": nombre, "Fecha": ds, "Observacion": f})

        col1, col2 = st.columns(2)
        col1.metric("Empleados", len(data))
        col2.metric("Dias con anomalia", len(anomalias))

        buf = io.BytesIO()
        write_excel(data, buf)
        buf.seek(0)

        nombre_salida = uploaded.name.rsplit(".", 1)[0] + "_procesado.xlsx"
        st.download_button(
            label="Descargar Rol Procesado (.xlsx)",
            data=buf,
            file_name=nombre_salida,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if anomalias:
            st.divider()
            st.subheader(f"Dias que requieren revision manual ({len(anomalias)})")
            st.dataframe(anomalias, use_container_width=True, hide_index=True)

    finally:
        os.unlink(tmp_path)
