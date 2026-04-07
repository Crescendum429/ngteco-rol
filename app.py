import io
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
from storage import export_json, import_json, load_empleados, save_empleados

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

# Cargar empleados guardados en el servidor
if "emp_db" not in st.session_state:
    st.session_state.emp_db = load_empleados()


def _save():
    save_empleados(st.session_state.emp_db)


def _default_emp():
    return {
        "salario": 0.0,
        "horas_base": 8,
        "transporte_dia": 0.0,
        "region": "Sierra/Amazonia",
        "cargo": "",
        "notas": "",
    }


# ── Subir XLS (opcional) ──────────────────────────────────────
uploaded = st.file_uploader("Archivo del NGTeco (.xls)", type=["xls"])

has_xls = False
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

        # Auto-registrar empleados nuevos del XLS
        changed = False
        for emp, days, nid in st.session_state.data:
            name = emp.split("(")[0].strip()
            if nid not in st.session_state.emp_db:
                st.session_state.emp_db[nid] = _default_emp()
                st.session_state.emp_db[nid]["nombre"] = name
                st.session_state.emp_db[nid]["ngteco_id"] = nid
                changed = True
            else:
                # Actualizar nombre por si cambio en el reloj
                if st.session_state.emp_db[nid].get("nombre") != name:
                    st.session_state.emp_db[nid]["nombre"] = name
                    changed = True
        if changed:
            _save()

    has_xls = True
    data = st.session_state.data
    cls = st.session_state.cls

emp_db = st.session_state.emp_db

# Mapeo ngteco_id -> nombre para el XLS actual
xls_id_map = {}
if has_xls:
    for emp, days, nid in data:
        name = emp.split("(")[0].strip()
        xls_id_map[nid] = name

# Anomalias
anomalias = []
if has_xls:
    for emp, days, nid in data:
        name = emp.split("(")[0].strip()
        for ds, d in cls[name].items():
            for f in d["flags"]:
                if f.startswith("REVISAR:"):
                    anomalias.append({"Empleado": name, "Fecha": ds, "Obs.": f})


def _time_to_mins(t):
    if t is None or pd.isna(t):
        return None
    if isinstance(t, dt_time):
        return t.hour * 60 + t.minute
    return None


# ── Tabs ──────────────────────────────────────────────────────
if has_xls:
    tab_h, tab_e, tab_n = st.tabs(["Horas", "Empleados", "Nomina"])
else:
    tab_e = st.container()
    tab_h = tab_n = None

# ── Tab Horas ─────────────────────────────────────────────────
if has_xls and tab_h is not None:
    with tab_h:
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
            st.rerun()


# ── Tab Empleados ─────────────────────────────────────────────
with tab_e:
    if not has_xls:
        st.subheader("Empleados")

    st.caption("Los datos se guardan automaticamente en el servidor (cifrados).")

    # Backup
    ba, bb = st.columns(2)
    cfg_json = export_json(emp_db)
    ba.download_button(
        "Descargar respaldo (.json)",
        data=cfg_json,
        file_name="empleados_backup.json",
        mime="application/json",
        use_container_width=True,
    )
    backup_file = bb.file_uploader("Restaurar desde respaldo", type=["json"], key="cfg_upload")
    if backup_file:
        try:
            loaded = import_json(backup_file.read().decode())
            st.session_state.emp_db = loaded
            _save()
            st.rerun()
        except Exception:
            bb.error("Archivo JSON invalido")

    st.divider()

    # Agregar empleado manual
    with st.expander("Agregar empleado"):
        na, nb = st.columns(2)
        new_name = na.text_input("Nombre completo", key="new_emp_name")
        new_id = nb.text_input("ID del reloj (NGTeco)", key="new_emp_id",
                               help="Numero que aparece entre parentesis en el reporte del reloj")
        if st.button("Agregar") and new_name and new_id:
            if new_id in emp_db:
                st.warning(f"Ya existe un empleado con ID {new_id}")
            else:
                emp_db[new_id] = _default_emp()
                emp_db[new_id]["nombre"] = new_name.strip()
                emp_db[new_id]["ngteco_id"] = new_id.strip()
                _save()
                st.rerun()

    # Lista de empleados
    sorted_ids = sorted(emp_db.keys(), key=lambda k: emp_db[k].get("nombre", ""))

    for eid in sorted_ids:
        emp = emp_db[eid]
        nombre = emp.get("nombre", f"ID {eid}")
        en_xls = eid in xls_id_map

        with st.container(border=True):
            ca, cb, cc, cd = st.columns([3, 2, 2, 2])
            ca.markdown(f"**{nombre}** · ID: `{eid}`" +
                        (" · En este reporte" if en_xls else ""))

            emp["salario"] = cb.number_input(
                "Salario ($)", min_value=0.0, step=10.0,
                value=float(emp.get("salario", 0)),
                key=f"db_sal_{eid}", format="%.2f",
            )
            emp["horas_base"] = cc.number_input(
                "h/dia", min_value=1, max_value=12,
                value=int(emp.get("horas_base", 8)),
                key=f"db_base_{eid}",
            )
            emp["transporte_dia"] = cd.number_input(
                "Transp. ($/dia)", min_value=0.0, step=0.5,
                value=float(emp.get("transporte_dia", 0)),
                key=f"db_transp_{eid}", format="%.2f",
            )

            ea, eb, ec = st.columns([2, 3, 1])
            emp["region"] = ea.selectbox(
                "Region", ["Sierra/Amazonia", "Costa/Galapagos"],
                index=0 if emp.get("region", "Sierra/Amazonia") == "Sierra/Amazonia" else 1,
                key=f"db_reg_{eid}",
            )
            emp["cargo"] = eb.text_input(
                "Cargo", value=emp.get("cargo", ""),
                key=f"db_cargo_{eid}", placeholder="Ej: Operario, Administracion",
            )
            if ec.button("Eliminar", key=f"db_del_{eid}", type="secondary"):
                del emp_db[eid]
                _save()
                st.rerun()

    if st.button("Guardar cambios", use_container_width=True, type="primary"):
        _save()
        st.success("Datos guardados.")


# ── Tab Nomina ────────────────────────────────────────────────
if has_xls and tab_n is not None:
    with tab_n:
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

        for emp_full, days, nid in data:
            name = emp_full.split("(")[0].strip()
            cfg = emp_db.get(nid, _default_emp())
            salary = cfg.get("salario", 0)
            base_h = cfg.get("horas_base", 8)
            transporte_dia = cfg.get("transporte_dia", 0)

            hrs = calcular_horas_clasificadas(cls[name], base_hours=base_h)

            with st.container(border=True):
                cargo_str = f" · {cfg['cargo']}" if cfg.get("cargo") else ""
                st.markdown(f"**{name}**{cargo_str}")

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
                    key=f"bonus_{nid}", format="%.2f",
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
