import copy
import io
import os
import tempfile
from datetime import date, time as dt_time

import altair as alt
import pandas as pd
import streamlit as st

from procesar_rol import (
    IESS_EMPLEADO,
    SBU_2026,
    calcular_horas_clasificadas,
    calcular_nomina,
    clasificar_todo,
    emp_name,
    match_empleados,
    normalize,
    parse_date,
    parse_xls,
    to_time,
    write_excel,
    write_excel_nomina,
    write_pdf_nomina,
)
from costos import (
    MERMA_DEFAULT_PCT,
    calcular_costos,
    calcular_merma_por_material,
    sumar_gastos_fijos,
    sumar_produccion_mensual,
)
from storage import (
    export_json, import_json, load_empleados, save_empleados,
    list_reportes, load_reporte, save_reporte, reporte_exists,
    delete_reporte,
    is_changelog_dismissed, dismiss_changelog,
    load_arrastre, save_arrastre, get_arrastre_anterior,
    save_extras_config, load_extras_config,
    save_nomina_resumen, load_all_nomina_resumenes,
    get_reporte_anterior,
    load_materiales, save_materiales,
    load_productos, save_productos,
    load_empaques, save_empaques,
    load_gastos_fijos, save_gastos_fijos,
    load_registro_diario, save_registro_diario, delete_registro_diario,
    list_registros_diarios,
    save_costos_snapshot, load_all_costos_snapshots,
)

APP_VERSION = "3.4"

CHANGELOG = {
    "version": APP_VERSION,
    "titulo": "Modulo de Gastos y Costos de produccion",
    "items": [
        ("Nuevo modulo Gastos",
         "Configura materias primas, productos (con su composicion), empaques "
         "y gastos fijos mensuales. Todo editable, con valores por defecto listos."),
        ("Calculo de costo por producto",
         "El sistema calcula el costo unitario real de cada producto: material, "
         "empaque, nomina y gastos indirectos. La nomina y gastos se reparten por "
         "factor de complejidad para que las jeringas no paguen igual que los vasos."),
        ("Registro diario del operario",
         "Una nueva pagina donde el operario ingresa al final del dia: material "
         "usado, desechos, molido y cajas producidas. Con esto el sistema calcula "
         "la merma real por material."),
        ("Usuarios con roles",
         "Se agrego un usuario operario con acceso exclusivo al registro diario. "
         "El administrador sigue viendo todo el ERP."),
        ("Grafico de evolucion de costos",
         "Una vez calculado el costo de un mes, queda guardado como snapshot. "
         "El grafico temporal muestra como van cambiando los costos por producto."),
    ],
}

st.set_page_config(
    page_title="SOLPLAST",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; }

/* ── Login ── */
.login-wrap {
    min-height: 88vh;
    display: flex;
    align-items: center;
    justify-content: center;
}
.login-card {
    background: linear-gradient(160deg, #0a1f18 0%, #0d2b22 60%, #0f3527 100%);
    border: 1px solid rgba(16,185,129,0.18);
    border-radius: 20px;
    padding: 52px 48px 44px;
    text-align: center;
    max-width: 360px;
    width: 100%;
    box-shadow: 0 24px 60px rgba(0,0,0,0.45), 0 0 0 1px rgba(16,185,129,0.08);
    position: relative;
    overflow: hidden;
}
.login-card::before {
    content: "";
    position: absolute;
    top: -80px; right: -80px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(16,185,129,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.login-brand {
    font-size: 2.4rem;
    font-weight: 900;
    letter-spacing: -0.06em;
    color: #ecfdf5;
    margin: 0 0 6px;
    line-height: 1;
    position: relative;
    z-index: 1;
}
.login-brand span { color: #34d399; }
.login-tagline {
    font-size: 0.8rem;
    color: #6ee7b7;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0 0 32px;
    position: relative;
    z-index: 1;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] { background: #0a1f18 !important; }
[data-testid="stSidebar"] * { color: #94a3b8 !important; }
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    border-radius: 7px !important;
    padding: 7px 14px !important;
    width: 100% !important;
    text-align: left !important;
    color: #94a3b8 !important;
    font-weight: 400 !important;
    transition: background 0.12s !important;
    margin-bottom: 1px !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #0f3527 !important;
    color: #e2e8f0 !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #134e3a !important;
    color: #6ee7b7 !important;
    font-weight: 600 !important;
}

/* ── Metrics ── */
[data-testid="stMetric"] {
    border-radius: 10px;
    padding: 14px 18px;
    border-left: 3px solid #059669;
}
[data-testid="stMetricValue"] { font-size: 1.35rem !important; }

/* ── Home hero ── */
.hero {
    background: linear-gradient(135deg, #0a1f18 0%, #065f46 55%, #047857 100%);
    border-radius: 16px;
    padding: 56px 40px 48px;
    text-align: center;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: "";
    position: absolute;
    top: -60px; right: -60px;
    width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(16,185,129,0.22) 0%, transparent 70%);
    border-radius: 50%;
}
.hero::after {
    content: "";
    position: absolute;
    bottom: -40px; left: -40px;
    width: 160px; height: 160px;
    background: radial-gradient(circle, rgba(217,119,6,0.18) 0%, transparent 70%);
    border-radius: 50%;
}
.hero-title { color: white; font-size: 3rem; font-weight: 900; letter-spacing: -0.06em; margin: 0 0 8px; line-height: 1; position: relative; z-index: 1; }
.hero-title span { color: #6ee7b7; }
.hero-sub { color: #a7f3d0; font-size: 0.95rem; margin: 0; position: relative; z-index: 1; }
.hero-badge { display: inline-block; background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.28); border-radius: 20px; padding: 4px 14px; font-size: 0.78rem; color: #6ee7b7; margin-top: 16px; letter-spacing: 0.05em; position: relative; z-index: 1; }

/* ── Module cards ── */
.mc-header { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 10px; }
.mc-title { font-size: 1rem; font-weight: 600; margin: 0 0 4px; }
.mc-desc { font-size: 0.83rem; margin: 0; line-height: 1.45; }

/* ── Page header ── */
.page-hdr { display: flex; align-items: center; gap: 14px; margin-bottom: 1.2rem; padding-bottom: 1rem; border-bottom: 1px solid #e2e8f0; }
.page-hdr-icon { flex-shrink: 0; }
.page-hdr-title { margin: 0; font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; }
.page-hdr-sub { margin: 2px 0 0; font-size: 0.85rem; color: #64748b; }

/* ── Section step badge ── */
.step-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.step-num { background: #059669; color: white; border-radius: 50%; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; font-size: 0.72rem; font-weight: 700; flex-shrink: 0; }
.step-title { font-weight: 600; font-size: 1rem; margin: 0; }
.step-cap { font-size: 0.82rem; color: #64748b; margin: 0 0 12px; }

/* ── Back nav ── */
.back-area { margin-bottom: 4px; }

@media (prefers-color-scheme: dark) {
    [data-testid="stMetric"] { background: #0f3527; }
    .mc-desc { color: #94a3b8; }
    .page-hdr { border-bottom-color: #334155; }
    .step-cap { color: #94a3b8; }
    .page-hdr-sub { color: #94a3b8; }
}
@media (prefers-color-scheme: light) {
    [data-testid="stMetric"] { background: #ecfdf5; }
    .mc-desc { color: #64748b; }
}
</style>
""", unsafe_allow_html=True)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
APP_PASSWORD_OP = os.environ.get("APP_PASSWORD_OP", "")

if APP_PASSWORD or APP_PASSWORD_OP:
    if not st.session_state.get("_auth"):
        st.markdown("""
        <style>
        [data-testid="stAppViewContainer"] > .main {
            background: linear-gradient(160deg, #071a12 0%, #0a2218 50%, #0d2b22 100%) !important;
        }
        [data-testid="stHeader"] { background: transparent !important; }
        [data-testid="stSidebar"] { display: none !important; }
        </style>
        <div style="height: 22vh"></div>
        """, unsafe_allow_html=True)
        _, _lc, _ = st.columns([1.6, 2, 1.6])
        with _lc:
            st.markdown(
                '<div style="text-align:center;margin-bottom:32px;">'
                '<div style="font-size:3rem;font-weight:900;letter-spacing:-0.07em;'
                'color:#ecfdf5;line-height:1;margin-bottom:8px;">'
                'SOL<span style="color:#34d399">PLAST</span></div>'
                '<div style="font-size:0.72rem;color:#6ee7b7;letter-spacing:0.16em;'
                'text-transform:uppercase;">Sistema de Gestion</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            pwd = st.text_input("Contrasena", type="password", label_visibility="collapsed",
                                placeholder="Contrasena")
            if pwd:
                if APP_PASSWORD and pwd == APP_PASSWORD:
                    st.session_state._auth = True
                    st.session_state._role = "admin"
                    st.rerun()
                elif APP_PASSWORD_OP and pwd == APP_PASSWORD_OP:
                    st.session_state._auth = True
                    st.session_state._role = "operario"
                    st.rerun()
                else:
                    st.error("Contrasena incorrecta")
        st.stop()
elif not st.session_state.get("_role"):
    st.session_state._role = "admin"

role = st.session_state.get("_role", "admin")

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


if role == "admin" and not st.session_state.get("_changelog_shown"):
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
        "descuento_iess": True,
        "fondos_reserva": False,
        "ocultar": False,
    }


def _time_to_mins(t):
    if t is None or pd.isna(t):
        return None
    if isinstance(t, dt_time):
        return t.hour * 60 + t.minute
    return None


def _page_header(icon_svg, title, subtitle=""):
    if st.session_state.get("_role", "admin") == "admin":
        if st.button("← Inicio", key=f"back_{st.session_state.get('pagina','_')}"):
            st.session_state.pagina = "Inicio"
            st.rerun()
    st.markdown(
        f'<div class="page-hdr">'
        f'<div class="page-hdr-icon">{icon_svg}</div>'
        f'<div><p class="page-hdr-title">{title}</p>'
        + (f'<p class="page-hdr-sub">{subtitle}</p>' if subtitle else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _step(n, title, caption=""):
    st.markdown(
        f'<div class="step-row"><div class="step-num">{n}</div>'
        f'<p class="step-title">{title}</p></div>'
        + (f'<p class="step-cap">{caption}</p>' if caption else ""),
        unsafe_allow_html=True,
    )


# ── Sidebar ───────────────────────────────────────────────────
st.sidebar.markdown(
    '<p style="font-size:1.15rem;font-weight:900;letter-spacing:-0.04em;'
    'color:#ecfdf5!important;margin:0 0 2px;">SOL<span style=\'color:#34d399!important\'>PLAST</span></p>',
    unsafe_allow_html=True,
)
st.sidebar.caption("Sistema de gestion")
st.sidebar.divider()

if role == "admin":
    MODULOS = ["Inicio", "Registro", "Gastos", "Roles", "Metricas", "Empleados"]
    DEFAULT_PAGE = "Inicio"
    GRUPOS_SIDEBAR = [
        (None, ["Inicio"]),
        ("Produccion", ["Registro", "Gastos"]),
        ("Personal", ["Roles", "Metricas"]),
        ("Configuracion", ["Empleados"]),
    ]
else:
    MODULOS = ["Registro"]
    DEFAULT_PAGE = "Registro"
    GRUPOS_SIDEBAR = [(None, ["Registro"])]

if "pagina" not in st.session_state or st.session_state.pagina not in MODULOS:
    st.session_state.pagina = DEFAULT_PAGE

for grupo_label, grupo_items in GRUPOS_SIDEBAR:
    if grupo_label:
        st.sidebar.markdown(
            f'<p style="font-size:0.65rem;letter-spacing:0.12em;text-transform:uppercase;'
            f'font-weight:700;padding:14px 4px 4px;margin:0;color:#475569!important;">'
            f'{grupo_label}</p>',
            unsafe_allow_html=True,
        )
    for mod in grupo_items:
        active = st.session_state.pagina == mod
        if st.sidebar.button(
            mod, use_container_width=True, key=f"nav_{mod}",
            type="primary" if active else "secondary",
        ):
            st.session_state.pagina = mod
            st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"v{APP_VERSION} · {role}")
pagina = st.session_state.pagina


# SVG icons (shared entre home y page headers)
_SVG = {
    "registro": (
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>'
        '<rect x="9" y="3" width="6" height="4" rx="1"/>'
        '<line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="12" y2="16"/></svg>'
    ),
    "gastos": (
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'
    ),
    "roles": (
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>'
    ),
    "metricas": (
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>'
        '<line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>'
    ),
    "empleados": (
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
    ),
}

# ── Pagina: Inicio ────────────────────────────────────────────
if pagina == "Inicio":
    st.markdown(
        f'<div class="hero">'
        f'<div class="hero-title">SOL<span>PLAST</span></div>'
        f'<div class="hero-sub">Soluciones Plasticas del Ecuador &nbsp;·&nbsp; Sistema de gestion</div>'
        f'<div class="hero-badge">v{APP_VERSION}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Quick stats
    try:
        _n_emp = len(st.session_state.emp_db)
        _reps = list_reportes()
        _resumenes = load_all_nomina_resumenes()
        _last_nom, _last_lab = 0.0, ""
        if _resumenes:
            _lk = max(_resumenes.keys())
            _last_nom = float(_resumenes[_lk].get("total_transferido", 0))
            _last_lab = _resumenes[_lk].get("periodo_label", _lk)
        _today_regs = list_registros_diarios(date.today().strftime("%Y-%m"))
        _hc1, _hc2, _hc3, _hc4 = st.columns(4)
        _hc1.metric("Empleados", _n_emp)
        _hc2.metric("Reportes cargados", len(_reps))
        _hc3.metric(
            f"Nomina ({_last_lab})" if _last_lab else "Ultima nomina",
            f"${_last_nom:,.0f}" if _last_nom else "—",
        )
        _hc4.metric("Registros este mes", len(_today_regs))
    except Exception:
        pass

    st.divider()
    st.markdown(
        '<p style="font-size:0.8rem;font-weight:600;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#94a3b8;margin-bottom:16px;">Modulos</p>',
        unsafe_allow_html=True,
    )

    _HOME_CARDS = [
        ("Registro",  "Registro Diario",
         "Cierre de jornada: material, desechos y produccion del dia.", "registro"),
        ("Gastos",    "Gastos y Costos",
         "Materiales, productos, empaques y costo unitario de produccion.", "gastos"),
        ("Roles",     "Roles y Nomina",
         "Procesamiento de horas NGTeco y calculo de sueldos.", "roles"),
        ("Metricas",  "Metricas",
         "Indicadores historicos de nomina, horas y produccion.", "metricas"),
        ("Empleados", "Empleados",
         "Configuracion de salarios, transporte y datos del personal.", "empleados"),
    ]

    _hcols = st.columns(3)
    for _hi, (_hkey, _htitle, _hdesc, _hsvgkey) in enumerate(_HOME_CARDS):
        with _hcols[_hi % 3]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="mc-header">'
                    f'<div>{_SVG[_hsvgkey]}</div>'
                    f'<div><p class="mc-title">{_htitle}</p>'
                    f'<p class="mc-desc">{_hdesc}</p></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Abrir", key=f"home_{_hkey}", use_container_width=True):
                    st.session_state.pagina = _hkey
                    st.rerun()


# ── Pagina: Empleados ─────────────────────────────────────────
if pagina == "Empleados":
    _page_header(_SVG["empleados"], "Empleados", "Salarios, transporte y configuracion del personal")
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
            emp["descuento_iess"] = ec.checkbox(
                "Descuento IESS", value=emp.get("descuento_iess", True),
                key=f"db_iess_{eid}",
                help="9.45% aporte personal al IESS",
            )
            emp["fondos_reserva"] = ed.checkbox(
                "Fondos de reserva", value=emp.get("fondos_reserva", False),
                key=f"db_fondos_{eid}",
                help="8.33% mensual, aplica despues de 1 ano de servicio",
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
    _page_header(_SVG["roles"], "Roles y Nomina", "Procesamiento de horas y calculo de sueldos")

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

        if st.session_state.get(f"_confirm_del_{sel_rid}"):
            st.warning(f"Eliminar **{sel}** de forma permanente?")
            ca, cb = st.columns(2)
            if ca.button("Si, eliminar", type="primary"):
                delete_reporte(sel_rid)
                st.session_state.pop(f"_confirm_del_{sel_rid}", None)
                st.session_state.pop("_loaded_rid", None)
                st.rerun()
            if cb.button("Cancelar"):
                st.session_state.pop(f"_confirm_del_{sel_rid}", None)
                st.rerun()
        elif sb.button("Eliminar", key=f"del_{sel_rid}"):
            st.session_state[f"_confirm_del_{sel_rid}"] = True
            st.rerun()

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
        name = emp_name(emp_full)
        if name not in cls:
            continue
        for ds, d in cls[name].items():
            for f in d["flags"]:
                if f.startswith("REVISAR:"):
                    anomalias.append({"Empleado": name, "Fecha": ds, "Obs.": f})

    st.divider()
    ba, bb = st.columns(2)
    for col, label in [(ba, "Horas"), (bb, "Sueldos")]:
        active = st.session_state.get("sub_rol", "Horas") == label
        if col.button(label, use_container_width=True,
                      type="primary" if active else "secondary",
                      key=f"sub_rol_btn_{label}"):
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
        emp_names_xls = [emp_name(e) for e, _, _ in data]
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
        rid, periodo_label = _detect_periodo(data)

        # Cargar config de decimos para este periodo
        _cfg_key = f"_extcfg_{rid}"
        if rid and not st.session_state.get(_cfg_key):
            saved = load_extras_config(rid)
            if saved:
                st.session_state[f"d13_{rid}"] = saved.get("decimo_13", False)
                st.session_state[f"d14_{rid}"] = saved.get("decimo_14", False)
            else:
                try:
                    m = int(rid.split("-")[1])
                    st.session_state[f"d13_{rid}"] = (m == 12)
                    st.session_state[f"d14_{rid}"] = (m in (3, 8))
                except Exception:
                    pass
            st.session_state[_cfg_key] = True

        _d13_key = f"d13_{rid}" if rid else "d13_tmp"
        _d14_key = f"d14_{rid}" if rid else "d14_tmp"

        dc1, dc2 = st.columns(2)
        decimo_13 = dc1.toggle(
            "Decimo Tercer Sueldo",
            key=_d13_key,
            help="1 salario mensual. Hasta dic 24. (Art. 111-112)",
        )
        decimo_14 = dc2.toggle(
            f"Decimo Cuarto Sueldo (${SBU_2026:.0f})",
            key=_d14_key,
            help=f"1 SBU (${SBU_2026:.0f}). Sierra: ago 15 / Costa: mar 15. (Art. 113)",
        )

        # Cargar horas del mes anterior para comparativa (una vez por sesion)
        prev_hrs_map = {}
        if rid:
            _prev_key = f"_prev_hrs_{rid}"
            if _prev_key not in st.session_state:
                with st.spinner("Cargando comparativa..."):
                    prev_data_r, prev_cls_r, _ = get_reporte_anterior(rid)
                if prev_data_r and prev_cls_r:
                    _tmp = {}
                    for ef, dy, ni in prev_data_r:
                        nm = emp_name(ef)
                        dk = matched.get(nm)
                        cf = emp_db.get(dk, _default_emp()) if dk else _default_emp()
                        _tmp[nm] = calcular_horas_clasificadas(
                            prev_cls_r.get(nm, {}), cf.get("horas_base", 8)
                        )
                    st.session_state[_prev_key] = _tmp
                else:
                    st.session_state[_prev_key] = {}
            prev_hrs_map = st.session_state[_prev_key]

        # Cargar arrastre del mes anterior
        arrastre_ant, prev_id = get_arrastre_anterior(rid) if rid else ({}, "")
        if arrastre_ant:
            with st.expander(f"Horas compensatorias del mes anterior ({prev_id})", expanded=True):
                st.caption("Estas horas fueron marcadas para pasar a este mes. Puedes aceptarlas o modificarlas.")
                for _emp_nm, h in arrastre_ant.items():
                    st.write(f"**{_emp_nm}**: {h:.2f}h")

        COLORS = ["#2563eb", "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626", "#6366f1", "#0d9488"]

        nomina_list = []
        any_salary = False

        for idx, (emp_full, days, nid) in enumerate(data):
            name = emp_name(emp_full)
            db_key = matched.get(name)
            cfg = emp_db.get(db_key, _default_emp()) if db_key else _default_emp()
            salario = cfg.get("salario", 0)
            color = COLORS[idx % len(COLORS)]

            # Usar arrastre del mes anterior si existe
            cfg_copy = dict(cfg)
            h_ant = arrastre_ant.get(name, 0)
            cfg_copy["horas_comp_anterior"] = st.session_state.get(f"h_ant_{nid}", h_ant)

            hrs = calcular_horas_clasificadas(cls.get(name, {}), cfg.get("horas_base", 8))

            with st.container(border=True):
                cargo = f" · {cfg.get('cargo', '')}" if cfg.get("cargo") else ""
                st.markdown(
                    f'<div style="border-left:4px solid {color}; padding-left:12px;">'
                    f'<h4 style="margin:0;">{name}<span style="font-weight:normal; '
                    f'font-size:0.85em; color:gray;">{cargo}</span></h4></div>',
                    unsafe_allow_html=True,
                )

                if salario <= 0:
                    st.caption("Configura el salario en Empleados.")
                    continue

                any_salary = True

                # Horas
                ph = prev_hrs_map.get(name)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Dias", hrs["dias"],
                          f"{hrs['dias'] - ph['dias']:+d}" if ph else None)
                m2.metric("Horas", f"{hrs['horas_total']:.1f}",
                          f"{hrs['horas_total'] - ph['horas_total']:+.1f}" if ph else None)
                m3.metric("H. 50%", f"{hrs['horas_50']:.2f}",
                          f"{hrs['horas_50'] - ph['horas_50']:+.2f}" if ph else None)
                m4.metric("H. 100%", f"{hrs['horas_100']:.2f}",
                          f"{hrs['horas_100'] - ph['horas_100']:+.2f}" if ph else None)

                if hrs["dias_anomalia"]:
                    st.caption(f"⚠ {hrs['dias_anomalia']} dia(s) con datos incompletos")

                # Ajustes del mes
                aa, ab, ac = st.columns(3)
                bonus = aa.number_input(
                    "Bono / Ajuste ($)", step=1.0,
                    key=f"bonus_{nid}", format="%.2f",
                )
                cfg_copy["horas_comp_anterior"] = ab.number_input(
                    "H. comp. mes anterior", step=0.5,
                    value=float(cfg_copy["horas_comp_anterior"]),
                    key=f"h_ant_{nid}", format="%.2f",
                    help="Horas compensatorias arrastradas del mes pasado",
                )

                # Pasar horas al siguiente mes
                pasar = False
                horas_pasar = 0.0
                if hrs['horas_50'] > 0:
                    pasar = ac.checkbox(
                        f"Pasar horas al sig. mes",
                        key=f"pasar_{nid}",
                        help="Estas horas NO se pagan este mes, se acumulan para el siguiente",
                    )
                    if pasar:
                        horas_pasar = ac.number_input(
                            "Horas a pasar", min_value=0.0,
                            max_value=float(hrs['horas_50']),
                            value=float(hrs['horas_50']),
                            step=0.5, key=f"h_pasar_{nid}", format="%.2f",
                        )

                # Advertencia de arrastre
                if cfg_copy["horas_comp_anterior"] != 0:
                    ab.caption(f"⚠ {cfg_copy['horas_comp_anterior']:.2f}h del mes anterior")

                n = calcular_nomina(hrs, cfg_copy, {
                    'decimo_13': decimo_13,
                    'decimo_14': decimo_14,
                    'bonus': bonus,
                    'horas_pasar': horas_pasar,
                })
                nomina_list.append({'name': name, 'nomina': n})

                # Ingresos
                st.markdown(
                    f'<p style="font-weight:600; color:{color}; margin-bottom:4px;">INGRESOS</p>',
                    unsafe_allow_html=True,
                )
                i1, i2, i3, i4 = st.columns(4)
                i1.metric("1ra Quincena", f"${n['quincena']:,.2f}")
                i2.metric("2da Quincena", f"${n['quincena']:,.2f}")
                extras_detail = f"50%: ${n['pay_50']:,.2f} | 100%: ${n['pay_100']:,.2f}"
                if pasar:
                    extras_detail += f" | {horas_pasar:.2f}h al sig. mes"
                i3.metric("H. Extras", f"${n['horas_extras']:,.2f}", extras_detail)
                i4.metric("Transp.", f"${n['transporte']:,.2f}",
                          f"{hrs['dias']}d x ${cfg.get('transporte_dia', 0):,.2f}")

                # Resultado
                st.markdown(
                    f'<p style="font-weight:600; color:{color}; margin-bottom:4px;">RESULTADO</p>',
                    unsafe_allow_html=True,
                )
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Total Ingresos", f"${n['total_ingresos']:,.2f}")
                if n['iess']:
                    r2.metric("IESS 9.45%", f"-${n['iess']:,.2f}")
                else:
                    r2.metric("IESS", "No aplica")
                prestamo_str = f"Prest: -${n['prestamo_iess']:,.2f}" if n['prestamo_iess'] else None
                r3.metric("Neto", f"${n['valor_recibir']:,.2f}", prestamo_str)
                r4.metric("Total Transferido", f"${n['total_transferido']:,.2f}",
                          f"F.Reserva: ${n['fondos_reserva']:,.2f}" if n['fondos_reserva'] else None)

                # PDF individual
                pdf_bytes = write_pdf_nomina({'name': name, 'nomina': n}, periodo_label or "Periodo")
                pdf_name = normalize(name).replace(" ", "_") + f"_{rid or 'nomina'}.pdf"
                st.download_button(
                    "Descargar PDF",
                    data=pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf",
                    key=f"pdf_{nid}",
                )

        # Guardar arrastre, config de decimos y resumen
        if any_salary and rid:
            arrastre_nuevo = {}
            for emp_full, days, nid in data:
                name = emp_name(emp_full)
                if st.session_state.get(f"pasar_{nid}"):
                    h = st.session_state.get(f"h_pasar_{nid}", 0)
                    if h > 0:
                        arrastre_nuevo[name] = h
            save_arrastre(rid, arrastre_nuevo)
            save_extras_config(rid, {"decimo_13": decimo_13, "decimo_14": decimo_14})
            save_nomina_resumen(rid, {
                "periodo_label": periodo_label or rid,
                "total_ingresos": round(sum(i['nomina']['total_ingresos'] for i in nomina_list), 2),
                "total_transferido": round(sum(i['nomina']['total_transferido'] for i in nomina_list), 2),
                "total_h50": round(sum(i['nomina']['hours']['horas_50'] for i in nomina_list), 2),
                "total_h100": round(sum(i['nomina']['hours']['horas_100'] for i in nomina_list), 2),
                "empleados": len(nomina_list),
            })

        if any_salary:
            st.divider()
            buf2 = io.BytesIO()
            write_excel_nomina(nomina_list, periodo_label or "Periodo", buf2)
            out2 = (periodo_label or "reporte").replace(" ", "_") + "_nomina.xlsx"
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


# ── Pagina: Metricas ──────────────────────────────────────────
if pagina == "Metricas":
    _page_header(_SVG["metricas"], "Metricas", "Indicadores historicos de nomina y produccion")

    all_reportes = list_reportes()

    if not all_reportes:
        st.info("No hay reportes guardados. Sube un archivo XLS en Roles para comenzar.")
        st.stop()

    emp_db = st.session_state.emp_db

    ha, hb = st.columns([6, 1])
    if hb.button("Actualizar", key="btn_actualizar_metricas"):
        st.session_state.pop("_metricas", None)
        st.rerun()

    if "_metricas" not in st.session_state:
        with st.spinner("Calculando metricas de todos los reportes..."):
            _metricas_tmp = {}
            for rep in all_reportes:
                rid = rep["id"]
                data_r, cls_r = load_reporte(rid)
                if not data_r or not cls_r:
                    continue
                extras_r = load_extras_config(rid) or {}
                arrastre_r = load_arrastre(rid) or {}
                matched_r, _, _ = match_empleados(data_r, emp_db)
                empleados_mes = []
                for ef, dy, ni in data_r:
                    nm = emp_name(ef)
                    dk = matched_r.get(nm)
                    cfg = emp_db.get(dk, _default_emp()) if dk else _default_emp()
                    if cfg.get("salario", 0) <= 0:
                        continue
                    hrs_r = calcular_horas_clasificadas(cls_r.get(nm, {}), cfg.get("horas_base", 8))
                    cfg_c = dict(cfg)
                    cfg_c["horas_comp_anterior"] = arrastre_r.get(nm, 0)
                    n_r = calcular_nomina(hrs_r, cfg_c, {
                        "decimo_13": extras_r.get("decimo_13", False),
                        "decimo_14": extras_r.get("decimo_14", False),
                    })
                    empleados_mes.append({
                        "nombre": nm,
                        "transferido": n_r["total_transferido"],
                        "h50": hrs_r["horas_50"],
                        "h100": hrs_r["horas_100"],
                        "dias": hrs_r["dias"],
                    })
                if empleados_mes:
                    _metricas_tmp[rid] = {
                        "label": rep["periodo"],
                        "empleados": empleados_mes,
                        "total": round(sum(e["transferido"] for e in empleados_mes), 2),
                        "h50": round(sum(e["h50"] for e in empleados_mes), 2),
                        "h100": round(sum(e["h100"] for e in empleados_mes), 2),
                    }
        st.session_state["_metricas"] = _metricas_tmp

    M = st.session_state.get("_metricas", {})

    if not M:
        st.info("Configura los salarios en Empleados para ver las metricas.")
        st.stop()

    sorted_ids = sorted(M.keys())

    # ── Resumen global ────────────────────────────────────────
    totales = [M[r]["total"] for r in sorted_ids]
    last_id = sorted_ids[-1]
    prev_id = sorted_ids[-2] if len(sorted_ids) >= 2 else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        f"Total pagado ({len(sorted_ids)} mes{'es' if len(sorted_ids) > 1 else ''})",
        f"${sum(totales):,.2f}",
    )
    c2.metric("Promedio mensual", f"${sum(totales)/len(totales):,.2f}")
    c3.metric(
        M[last_id]["label"],
        f"${M[last_id]['total']:,.2f}",
        f"${M[last_id]['total'] - M[prev_id]['total']:+,.2f}" if prev_id else None,
    )
    c4.metric("Empleados (ultimo mes)", len(M[last_id]["empleados"]))

    st.divider()

    # ── Nomina mensual ────────────────────────────────────────
    st.subheader("Nomina mensual")
    df_men = pd.DataFrame([{"Mes": M[r]["label"], "Total pagado": M[r]["total"]} for r in sorted_ids])
    _men_enc_x = alt.X("Mes:N", sort=None, axis=alt.Axis(title="", labelAngle=-20, labelLimit=110))
    _men_enc_y = alt.Y("Total pagado:Q",
                       axis=alt.Axis(title="", format="$,.0f", tickCount=4),
                       scale=alt.Scale(zero=False, padding=40))
    _men_tt = [alt.Tooltip("Mes:N", title="Periodo"),
               alt.Tooltip("Total pagado:Q", title="Total ($)", format="$,.2f")]
    _men_base = alt.Chart(df_men)
    _men_area = _men_base.mark_area(
        opacity=0.18, color="#059669", interpolate="monotone",
    ).encode(x=_men_enc_x, y=_men_enc_y)
    _men_line = _men_base.mark_line(
        color="#059669", strokeWidth=2.5, interpolate="monotone",
    ).encode(x=_men_enc_x, y=_men_enc_y, tooltip=_men_tt)
    _men_pts = _men_base.mark_circle(
        color="#059669", size=90, stroke="white", strokeWidth=2,
    ).encode(x=_men_enc_x, y=_men_enc_y, tooltip=_men_tt)
    _men_labels = _men_base.mark_text(
        dy=-16, fontSize=11, fontWeight="bold", color="#059669",
    ).encode(
        x=_men_enc_x,
        y=_men_enc_y,
        text=alt.Text("Total pagado:Q", format="$,.0f"),
    )
    nomina_chart = (
        (_men_area + _men_line + _men_pts + _men_labels)
        .properties(height=280)
        .configure_view(fill="transparent", strokeWidth=0)
        .configure_axis(grid=True, gridColor="rgba(0,0,0,0.06)", gridDash=[3, 3],
                        labelColor="#94a3b8", titleColor="#64748b",
                        domainColor="#e2e8f0", tickColor="#e2e8f0")
    )
    st.altair_chart(nomina_chart, use_container_width=True)

    # ── Detalle por empleado ──────────────────────────────────
    st.divider()
    opciones_mes = {M[r]["label"]: r for r in sorted_ids}
    mes_sel_label = st.selectbox("Ver detalle de empleados —", list(opciones_mes.keys()),
                                 index=len(opciones_mes) - 1)
    mes_sel_id = opciones_mes[mes_sel_label]

    df_emp = pd.DataFrame(M[mes_sel_id]["empleados"]) \
        .rename(columns={"nombre": "Empleado", "transferido": "Total ($)"}) \
        .sort_values("Total ($)", ascending=True)
    _emp_base = alt.Chart(df_emp)
    _emp_bars = _emp_base.mark_bar(
        cornerRadiusTopRight=4, cornerRadiusBottomRight=4,
    ).encode(
        y=alt.Y("Empleado:N", sort=None, axis=alt.Axis(title="", labelLimit=160)),
        x=alt.X("Total ($):Q", axis=alt.Axis(title="Total transferido ($)", format="$,.0f", tickCount=5)),
        color=alt.Color(
            "Total ($):Q",
            scale=alt.Scale(scheme="greens"),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("Empleado:N"),
            alt.Tooltip("Total ($):Q", format="$,.2f", title="Total ($)"),
            alt.Tooltip("dias:Q", title="Dias trabajados"),
        ],
    )
    _emp_labels = _emp_base.mark_text(align="left", dx=6, fontSize=11, fontWeight="bold").encode(
        y=alt.Y("Empleado:N", sort=None),
        x=alt.X("Total ($):Q"),
        text=alt.Text("Total ($):Q", format="$,.0f"),
        color=alt.value("#334155"),
    )
    emp_chart = (
        (_emp_bars + _emp_labels)
        .properties(height=max(180, len(df_emp) * 44))
        .configure_view(fill="transparent", strokeWidth=0)
        .configure_axis(grid=False, labelColor="#94a3b8", titleColor="#64748b",
                        domainColor="#e2e8f0", tickColor="#e2e8f0")
    )
    st.altair_chart(emp_chart, use_container_width=True)

    # ── Horas extras ─────────────────────────────────────────
    if any(M[r]["h50"] + M[r]["h100"] > 0 for r in sorted_ids):
        st.divider()
        st.subheader("Horas extras por mes")
        df_hext = pd.DataFrame([
            {"Mes": M[r]["label"], "Tipo": "50% (compensatorias)", "Horas": M[r]["h50"]}
            for r in sorted_ids
        ] + [
            {"Mes": M[r]["label"], "Tipo": "100% (fin de semana)", "Horas": M[r]["h100"]}
            for r in sorted_ids
        ])
        _hext_color = alt.Color(
            "Tipo:N",
            scale=alt.Scale(domain=["50% (compensatorias)", "100% (fin de semana)"],
                            range=["#059669", "#d97706"]),
            legend=alt.Legend(title="", orient="top", labelFontSize=12),
        )
        _hext_base = alt.Chart(df_hext)
        _hext_bars = _hext_base.mark_bar(
            cornerRadiusTopLeft=4, cornerRadiusTopRight=4,
        ).encode(
            x=alt.X("Mes:N", sort=None, axis=alt.Axis(title="", labelAngle=-20, labelLimit=110)),
            xOffset=alt.XOffset("Tipo:N"),
            y=alt.Y("Horas:Q", axis=alt.Axis(title="Horas", tickCount=5)),
            color=_hext_color,
            tooltip=[
                alt.Tooltip("Mes:N", title="Periodo"),
                alt.Tooltip("Tipo:N"),
                alt.Tooltip("Horas:Q", format=".1f"),
            ],
        )
        _hext_labels = _hext_base.mark_text(dy=-7, fontSize=10, fontWeight="bold").encode(
            x=alt.X("Mes:N", sort=None),
            xOffset=alt.XOffset("Tipo:N"),
            y=alt.Y("Horas:Q"),
            text=alt.Text("Horas:Q", format=".0f"),
            color=alt.value("#374151"),
        )
        hext_chart = (
            (_hext_bars + _hext_labels)
            .properties(height=260)
            .configure_view(fill="transparent", strokeWidth=0)
            .configure_axis(grid=True, gridColor="rgba(0,0,0,0.06)", gridDash=[3, 3],
                            labelColor="#64748b", titleColor="#64748b",
                            domainColor="#e2e8f0", tickColor="#e2e8f0")
            .configure_legend(labelColor="#374151", titleColor="#64748b")
        )
        st.altair_chart(hext_chart, use_container_width=True)

    # ── Tabla resumen ─────────────────────────────────────────
    st.divider()
    df_tabla = pd.DataFrame([
        {
            "Mes": M[r]["label"],
            "Total pagado ($)": M[r]["total"],
            "H. Extra 50%": M[r]["h50"],
            "H. Extra 100%": M[r]["h100"],
            "Empleados": len(M[r]["empleados"]),
        }
        for r in sorted_ids
    ])
    st.dataframe(
        df_tabla,
        column_config={
            "Total pagado ($)": st.column_config.NumberColumn(format="$%.2f"),
            "H. Extra 50%": st.column_config.NumberColumn(format="%.2f h"),
            "H. Extra 100%": st.column_config.NumberColumn(format="%.2f h"),
        },
        hide_index=True,
        use_container_width=True,
    )


# ── Pagina: Gastos ────────────────────────────────────────────
MESES_LARGO = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
               'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _ultimos_periodos(n=12):
    hoy = date.today()
    res = []
    for offset in range(n):
        m, y = hoy.month - offset, hoy.year
        while m <= 0:
            m += 12
            y -= 1
        res.append(f"{y}-{m:02d}")
    return res


def _periodo_label(pid):
    try:
        y, m = pid.split("-")
        return f"{MESES_LARGO[int(m) - 1]} {y}"
    except Exception:
        return pid


if pagina == "Gastos" and role == "admin":
    _page_header(_SVG["gastos"], "Gastos y Costos", "Materiales, productos, empaques y costos de produccion")

    SUB_OPTS = ["Materiales", "Productos", "Empaques", "Gastos fijos", "Costos"]

    nav_cols = st.columns(len(SUB_OPTS))
    for i, opt in enumerate(SUB_OPTS):
        active = st.session_state.get("sub_gastos", "Materiales") == opt
        if nav_cols[i].button(opt, use_container_width=True,
                              type="primary" if active else "secondary",
                              key=f"nav_gastos_{opt}"):
            st.session_state.sub_gastos = opt
            st.rerun()

    sub_g = st.session_state.get("sub_gastos", "Materiales")
    st.divider()

    # ── Materiales ──────────────────────────────────────────
    if sub_g == "Materiales":
        st.subheader("Materias primas")
        st.caption("Costo por kilogramo. Editable.")

        mats = load_materiales()
        mat_ids = list(mats.keys())

        for mid in mat_ids:
            m = mats[mid]
            with st.container(border=True):
                ca, cb, cc = st.columns([4, 3, 1])
                nombre = ca.text_input(
                    "Nombre", value=m.get("nombre", ""),
                    key=f"mat_nombre_{mid}",
                )
                costo = cb.number_input(
                    "Costo por kg ($)", min_value=0.0, step=0.05,
                    value=float(m.get("costo_kg", 0)),
                    key=f"mat_costo_{mid}", format="%.2f",
                )
                mats[mid]["nombre"] = nombre
                mats[mid]["costo_kg"] = costo
                cc.write("")
                if cc.button("Borrar", key=f"mat_del_{mid}"):
                    del mats[mid]
                    save_materiales(mats)
                    st.rerun()

        if st.button("Guardar cambios", type="primary", key="mat_save_all"):
            save_materiales(mats)
            st.toast("Materiales guardados", icon="✅")

        with st.expander("+ Agregar material nuevo"):
            nm_id = st.text_input("ID (sin espacios, ej: abs)", key="new_mat_id")
            nm_nombre = st.text_input("Nombre", key="new_mat_nombre")
            nm_costo = st.number_input("Costo por kg ($)", min_value=0.0,
                                       step=0.05, key="new_mat_costo", format="%.2f")
            if st.button("Agregar material", key="new_mat_btn"):
                if nm_id and nm_nombre:
                    mats[nm_id] = {"nombre": nm_nombre, "costo_kg": float(nm_costo)}
                    save_materiales(mats)
                    st.rerun()
                else:
                    st.error("Completa ID y nombre")

    # ── Productos ───────────────────────────────────────────
    if sub_g == "Productos":
        st.subheader("Productos")
        st.caption("Composicion de cada producto: peso, material, empaques y factor de complejidad.")

        mats = load_materiales()
        productos = load_productos()
        empaques = load_empaques()

        if not mats:
            st.warning("Primero define materiales.")
            st.stop()

        mat_ids_list = list(mats.keys())
        mat_label = {mid: mats[mid].get("nombre", mid) for mid in mat_ids_list}

        prod_keys = sorted(productos.keys(), key=lambda k: productos[k].get("nombre", k))

        for pid in prod_keys:
            p = productos[pid]
            with st.expander(f"**{p.get('nombre', pid)}**"):
                ca, cb, cc = st.columns([3, 2, 2])
                p["nombre"] = ca.text_input("Nombre", value=p.get("nombre", ""),
                                            key=f"p_nombre_{pid}")
                p["unidades_caja"] = int(cb.number_input(
                    "Unidades por caja", min_value=1, step=50,
                    value=int(p.get("unidades_caja", 1) or 1),
                    key=f"p_ucaja_{pid}",
                ))
                p["factor_complejidad"] = float(cc.number_input(
                    "Factor complejidad", min_value=0.1, step=0.1,
                    value=float(p.get("factor_complejidad", 1.0) or 1.0),
                    key=f"p_fc_{pid}", format="%.2f",
                    help="1.0 = base, 3.0 = jeringa compleja. Reparte nomina/gastos indirectos.",
                ))

                st.markdown("**Componentes**")
                comps_actuales = list(p.get("componentes", []))
                comps_finales = []

                for ci, comp in enumerate(comps_actuales):
                    with st.container(border=True):
                        cx, cy, cz, cw = st.columns([3, 2, 3, 1])
                        nom_c = cx.text_input(
                            "Nombre", value=comp.get("nombre", ""),
                            key=f"pc_{pid}_{ci}_nom",
                        )
                        peso_c = cy.number_input(
                            "Peso (g)", min_value=0.0, step=0.01,
                            value=float(comp.get("peso_g", 0) or 0),
                            key=f"pc_{pid}_{ci}_peso", format="%.3f",
                        )
                        opciones_mat = mat_ids_list + ["mezcla"]
                        mat_actual = comp.get("material", opciones_mat[0])
                        idx_m = opciones_mat.index(mat_actual) if mat_actual in opciones_mat else 0
                        mat_c = cz.selectbox(
                            "Material", opciones_mat,
                            index=idx_m,
                            format_func=lambda x: mat_label.get(x, "Mezcla"),
                            key=f"pc_{pid}_{ci}_mat",
                        )

                        eliminar = cw.button("✕", key=f"pc_{pid}_{ci}_del")

                        proporcion_nueva = None
                        if mat_c == "mezcla":
                            prop_actual = comp.get("proporcion", {}) or {}
                            st.caption("Proporcion de la mezcla")
                            prop_cols = st.columns(max(len(mat_ids_list), 1))
                            proporcion_nueva = {}
                            total = 0.0
                            for pi, mm in enumerate(mat_ids_list):
                                val = prop_cols[pi].number_input(
                                    mat_label[mm][:12],
                                    min_value=0.0, max_value=1.0, step=0.0001,
                                    value=float(prop_actual.get(mm, 0)),
                                    key=f"pc_{pid}_{ci}_prop_{mm}",
                                    format="%.4f",
                                )
                                if val > 0:
                                    proporcion_nueva[mm] = val
                                total += val
                            if abs(total - 1.0) > 0.01:
                                st.caption(f"⚠ Suma actual: {total:.4f} (deberia ser 1.0)")

                        if eliminar:
                            p["componentes"] = [
                                c for j, c in enumerate(comps_actuales) if j != ci
                            ]
                            save_productos(productos)
                            st.rerun()

                        nuevo = {"nombre": nom_c, "peso_g": peso_c, "material": mat_c}
                        if mat_c == "mezcla" and proporcion_nueva:
                            nuevo["proporcion"] = proporcion_nueva
                        comps_finales.append(nuevo)

                ac, ad = st.columns(2)
                if ac.button("+ Agregar componente", key=f"p_addcomp_{pid}"):
                    comps_finales.append({
                        "nombre": "Nuevo",
                        "peso_g": 0.0,
                        "material": mat_ids_list[0] if mat_ids_list else "mezcla",
                    })
                    p["componentes"] = comps_finales
                    save_productos(productos)
                    st.rerun()

                st.markdown("**Empaques asignados**")
                emp_actual = p.get("empaques", {}) or {}
                empaques_finales = {}
                for eid, e in empaques.items():
                    label = f"{e.get('nombre', eid)} (${float(e.get('costo', 0)):.4f}/{e.get('unidad', 'caja')})"
                    usa = st.checkbox(
                        label, value=(eid in emp_actual),
                        key=f"pe_{pid}_{eid}",
                    )
                    if usa:
                        cant = st.number_input(
                            f"Cantidad ({e.get('nombre', eid)})",
                            min_value=0.0, step=0.5,
                            value=float(emp_actual.get(eid, 1)) if isinstance(emp_actual.get(eid), (int, float)) else 1.0,
                            key=f"pe_{pid}_{eid}_qty",
                            label_visibility="collapsed",
                        )
                        empaques_finales[eid] = cant

                save_col, del_col = st.columns([3, 1])
                if save_col.button("Guardar producto", type="primary", key=f"p_save_{pid}"):
                    productos[pid] = {
                        "nombre": p["nombre"],
                        "unidades_caja": p["unidades_caja"],
                        "factor_complejidad": p["factor_complejidad"],
                        "componentes": comps_finales,
                        "empaques": empaques_finales,
                    }
                    save_productos(productos)
                    st.toast("Producto guardado", icon="✅")
                    st.rerun()

                if del_col.button("Borrar", type="secondary", key=f"p_del_{pid}"):
                    del productos[pid]
                    save_productos(productos)
                    st.rerun()

        with st.expander("+ Nuevo producto"):
            np_id = st.text_input("ID (sin espacios)", key="np_id")
            np_nombre = st.text_input("Nombre", key="np_nombre")
            np_ucaja = st.number_input("Unidades por caja", min_value=1,
                                       value=1000, step=100, key="np_ucaja")
            if st.button("Crear producto", type="primary", key="np_btn"):
                if np_id and np_nombre:
                    productos[np_id] = {
                        "nombre": np_nombre,
                        "unidades_caja": int(np_ucaja),
                        "componentes": [],
                        "empaques": {},
                        "factor_complejidad": 1.0,
                    }
                    save_productos(productos)
                    st.rerun()
                else:
                    st.error("Completa ID y nombre")

    # ── Empaques ───────────────────────────────────────────
    if sub_g == "Empaques":
        st.subheader("Empaques")
        st.caption("Costo de cada tipo de empaque. Unidad = 'caja' se prorratea entre las unidades, 'unidad' se suma directo.")

        empaques = load_empaques()
        for eid in list(empaques.keys()):
            e = empaques[eid]
            with st.container(border=True):
                ca, cb, cc, cd = st.columns([4, 2, 2, 1])
                e["nombre"] = ca.text_input("Nombre", value=e.get("nombre", ""),
                                            key=f"e_nombre_{eid}")
                e["costo"] = cb.number_input(
                    "Costo ($)", min_value=0.0, step=0.001,
                    value=float(e.get("costo", 0)),
                    key=f"e_costo_{eid}", format="%.4f",
                )
                opts_unit = ["caja", "unidad"]
                idx_u = 0 if e.get("unidad", "caja") == "caja" else 1
                e["unidad"] = cc.selectbox(
                    "Se aplica a", opts_unit, index=idx_u,
                    key=f"e_unit_{eid}",
                )
                if cd.button("Borrar", key=f"e_del_{eid}"):
                    del empaques[eid]
                    save_empaques(empaques)
                    st.rerun()

        if st.button("Guardar cambios", type="primary", key="e_save_all"):
            save_empaques(empaques)
            st.toast("Empaques guardados", icon="✅")

        with st.expander("+ Nuevo empaque"):
            ne_id = st.text_input("ID", key="ne_id")
            ne_nombre = st.text_input("Nombre", key="ne_nombre")
            ne_costo = st.number_input("Costo ($)", min_value=0.0, step=0.001,
                                       key="ne_costo", format="%.4f")
            ne_unit = st.selectbox("Se aplica a", ["caja", "unidad"], key="ne_unit")
            if st.button("Agregar", key="ne_btn"):
                if ne_id and ne_nombre:
                    empaques[ne_id] = {
                        "nombre": ne_nombre,
                        "costo": float(ne_costo),
                        "unidad": ne_unit,
                    }
                    save_empaques(empaques)
                    st.rerun()

    # ── Gastos fijos ──────────────────────────────────────
    if sub_g == "Gastos fijos":
        st.subheader("Gastos fijos mensuales")
        st.caption("Electricidad, agua, insumos indirectos. Se guardan por mes.")

        periodos = _ultimos_periodos(12)
        periodo = st.selectbox(
            "Mes", periodos,
            format_func=_periodo_label,
            key="gf_periodo",
        )

        gastos = load_gastos_fijos(periodo)

        col1, col2 = st.columns(2)
        gastos_edit = {}
        items = list(gastos.keys())
        for i, gid in enumerate(items):
            col = col1 if i % 2 == 0 else col2
            gastos_edit[gid] = col.number_input(
                gid.replace("_", " ").title(),
                min_value=0.0, step=5.0,
                value=float(gastos.get(gid, 0)),
                key=f"gf_{periodo}_{gid}", format="%.2f",
            )

        st.metric("Total gastos fijos", f"${sum(gastos_edit.values()):,.2f}")

        ba, bb = st.columns(2)
        if ba.button("Guardar", type="primary", key="gf_save"):
            save_gastos_fijos(periodo, gastos_edit)
            st.toast("Gastos fijos guardados", icon="✅")

        with bb.expander("+ Agregar gasto"):
            new_gid = st.text_input("Nombre del gasto", key="new_gf_id")
            new_gval = st.number_input("Monto mensual ($)", min_value=0.0,
                                       step=5.0, key="new_gf_val", format="%.2f")
            if st.button("Agregar gasto", key="new_gf_btn"):
                if new_gid:
                    k = new_gid.lower().replace(" ", "_")
                    gastos_edit[k] = float(new_gval)
                    save_gastos_fijos(periodo, gastos_edit)
                    st.rerun()

    # ── Costos calculados ────────────────────────────────
    if sub_g == "Costos":
        st.subheader("Costos de produccion")

        periodos = _ultimos_periodos(12)
        per_c = st.selectbox(
            "Mes a calcular", periodos,
            format_func=_periodo_label,
            key="costos_periodo",
        )

        mats = load_materiales()
        productos = load_productos()
        empaques = load_empaques()
        gastos_mes = load_gastos_fijos(per_c)
        registros_mes = list_registros_diarios(per_c)

        merma_pcts = calcular_merma_por_material(registros_mes, productos, mats) if registros_mes else {}

        cajas_prod = sumar_produccion_mensual(registros_mes)
        produccion_units = {}
        for pid, cajas in cajas_prod.items():
            u_caja = productos.get(pid, {}).get("unidades_caja", 1) or 1
            produccion_units[pid] = cajas * u_caja

        resumenes = load_all_nomina_resumenes()
        nomina_total = 0.0
        if per_c in resumenes:
            nomina_total = float(resumenes[per_c].get("total_transferido", 0))

        gastos_fijos_total = sumar_gastos_fijos(gastos_mes)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nomina del mes", f"${nomina_total:,.2f}",
                  help="Calculada en Roles > Sueldos")
        c2.metric("Gastos fijos", f"${gastos_fijos_total:,.2f}")
        c3.metric("Registros del mes", len(registros_mes))
        c4.metric("Unidades producidas", f"{int(sum(produccion_units.values())):,}")

        if not merma_pcts:
            st.info(f"Sin registros diarios este mes. Se usa merma default de {MERMA_DEFAULT_PCT}% para todos los materiales.")
        else:
            with st.expander("Merma calculada por material"):
                merma_rows = [
                    {"Material": mats.get(mid, {}).get("nombre", mid),
                     "Merma calculada": f"{pct}%"}
                    for mid, pct in merma_pcts.items()
                ]
                st.dataframe(pd.DataFrame(merma_rows), hide_index=True, use_container_width=True)

        st.divider()

        costos = calcular_costos(
            productos, mats, empaques,
            gastos_fijos_total=gastos_fijos_total,
            nomina_total=nomina_total,
            produccion_unidades=produccion_units,
            merma_pcts=merma_pcts,
        )

        save_costos_snapshot(per_c, {
            "periodo_label": _periodo_label(per_c),
            "costos": costos,
            "nomina_total": nomina_total,
            "gastos_fijos_total": gastos_fijos_total,
        })

        df_costos = pd.DataFrame([
            {
                "Producto": c["nombre"],
                "Material": c["material"],
                "Empaque": c["empaque"],
                "Nomina": c["nomina"],
                "Gastos ind.": c["gastos_ind"],
                "Costo unitario": c["total"],
                "Costo por caja": c["por_caja"],
                "Unidades mes": c["unidades"],
            }
            for c in costos.values()
        ]).sort_values("Costo unitario", ascending=False)

        st.dataframe(
            df_costos,
            column_config={
                "Material": st.column_config.NumberColumn(format="$%.4f"),
                "Empaque": st.column_config.NumberColumn(format="$%.4f"),
                "Nomina": st.column_config.NumberColumn(format="$%.4f"),
                "Gastos ind.": st.column_config.NumberColumn(format="$%.4f"),
                "Costo unitario": st.column_config.NumberColumn(format="$%.4f"),
                "Costo por caja": st.column_config.NumberColumn(format="$%.2f"),
                "Unidades mes": st.column_config.NumberColumn(format="%d"),
            },
            hide_index=True,
            use_container_width=True,
        )

        st.divider()

        st.subheader("Desglose por producto")
        breakdown_rows = []
        for c in costos.values():
            for comp_key, label in [("material", "Material"),
                                     ("empaque", "Empaque"),
                                     ("nomina", "Nomina"),
                                     ("gastos_ind", "Gastos indirectos")]:
                breakdown_rows.append({
                    "Producto": c["nombre"],
                    "Componente": label,
                    "Costo": c[comp_key],
                })

        df_bd = pd.DataFrame(breakdown_rows)
        bd_chart = (
            alt.Chart(df_bd)
            .mark_bar()
            .encode(
                y=alt.Y("Producto:N", sort="-x", axis=alt.Axis(title="")),
                x=alt.X("Costo:Q",
                        axis=alt.Axis(title="Costo unitario ($)", format="$,.3f"),
                        stack="zero"),
                color=alt.Color(
                    "Componente:N",
                    scale=alt.Scale(
                        domain=["Material", "Empaque", "Nomina", "Gastos indirectos"],
                        range=["#047857", "#059669", "#d97706", "#dc2626"],
                    ),
                    legend=alt.Legend(title="", orient="top"),
                ),
                tooltip=[
                    alt.Tooltip("Producto:N"),
                    alt.Tooltip("Componente:N"),
                    alt.Tooltip("Costo:Q", format="$.4f"),
                ],
            )
            .properties(height=max(240, len(costos) * 30))
            .configure_view(fill="transparent", strokeWidth=0)
            .configure_axis(grid=False, labelColor="#64748b", titleColor="#64748b",
                            domainColor="#e2e8f0", tickColor="#e2e8f0")
            .configure_legend(labelColor="#64748b", titleColor="#64748b")
        )
        st.altair_chart(bd_chart, use_container_width=True)

        # Evolucion temporal
        st.divider()
        st.subheader("Evolucion del costo unitario")

        snapshots = load_all_costos_snapshots()
        if len(snapshots) >= 2:
            sorted_pers = sorted(snapshots.keys())
            all_prods = set()
            for snap in snapshots.values():
                all_prods.update(snap.get("costos", {}).keys())

            prod_nombres = {pid: productos.get(pid, {}).get("nombre", pid) for pid in all_prods}

            seleccion = st.multiselect(
                "Productos a comparar",
                options=sorted(all_prods, key=lambda x: prod_nombres[x]),
                default=sorted(all_prods, key=lambda x: prod_nombres[x])[:5],
                format_func=lambda x: prod_nombres[x],
                key="costos_evo_select",
            )

            if seleccion:
                evo_rows = []
                for per in sorted_pers:
                    snap = snapshots[per]
                    lab = snap.get("periodo_label", per)
                    for pid in seleccion:
                        c_snap = snap.get("costos", {}).get(pid)
                        if c_snap:
                            evo_rows.append({
                                "Mes": lab,
                                "Producto": prod_nombres[pid],
                                "Costo unitario": c_snap.get("total", 0),
                            })

                if evo_rows:
                    df_evo = pd.DataFrame(evo_rows)
                    evo_chart = (
                        alt.Chart(df_evo)
                        .mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2)
                        .encode(
                            x=alt.X("Mes:N", sort=None,
                                    axis=alt.Axis(title="", labelAngle=-20)),
                            y=alt.Y("Costo unitario:Q",
                                    axis=alt.Axis(title="Costo unitario ($)", format="$,.4f")),
                            color=alt.Color("Producto:N",
                                            legend=alt.Legend(orient="right", title="")),
                            tooltip=[
                                alt.Tooltip("Producto:N"),
                                alt.Tooltip("Mes:N"),
                                alt.Tooltip("Costo unitario:Q", format="$.4f"),
                            ],
                        )
                        .properties(height=300)
                        .configure_view(fill="transparent", strokeWidth=0)
                        .configure_axis(grid=False, labelColor="#64748b", titleColor="#64748b",
                                        domainColor="#e2e8f0", tickColor="#e2e8f0")
                        .configure_legend(labelColor="#64748b", titleColor="#64748b")
                    )
                    st.altair_chart(evo_chart, use_container_width=True)
        else:
            st.caption("Calcula costos en al menos 2 meses distintos para ver la evolucion temporal.")


# ── Pagina: Registro Diario ──────────────────────────────────
if pagina == "Registro":
    _page_header(_SVG["registro"], "Registro diario", "Cierre de jornada — datos de merma, produccion y material")

    rca, rcb = st.columns([3, 1])
    fecha_sel = rca.date_input("Fecha", value=date.today(),
                               format="DD/MM/YYYY", key="reg_fecha")
    fecha_str = fecha_sel.strftime("%Y-%m-%d")

    mats_r = load_materiales()
    productos_r = load_productos()

    registro = load_registro_diario(fecha_str)
    if registro:
        rca.info(f"Registro existente para {fecha_sel.strftime('%d/%m/%Y')} — editando.")

    st.divider()

    # 1. Material usado
    _step(1, "Material virgen usado (kg)", "Kilos de cada materia prima que entraron a las maquinas hoy.")

    mat_usado_reg = {}
    n_mats = max(len(mats_r), 1)
    mat_cols = st.columns(min(n_mats, 3))
    for i, (mid, m) in enumerate(mats_r.items()):
        col = mat_cols[i % len(mat_cols)]
        v = registro.get("material_usado", {}).get(mid, 0.0)
        mat_usado_reg[mid] = col.number_input(
            m.get("nombre", mid), min_value=0.0, step=0.5,
            value=float(v),
            key=f"reg_mat_{fecha_str}_{mid}", format="%.2f",
        )

    coment_material = st.text_area(
        "Comentarios sobre el material virgen (opcional)",
        value=registro.get("coment_material", ""),
        key=f"reg_cmat_{fecha_str}", height=70,
        placeholder="Ej: PP clarificado con color amarillento, lote nuevo",
    )

    st.divider()

    # 2. Molido usado como insumo
    _step(2, "Material molido usado (kg)", "Molido reciclado ingresado a las maquinas hoy, agrupado por denominacion.")

    DENOMINACIONES_MOLIDO = [
        ("vaso",     "Molido de vaso"),
        ("cuchara",  "Molido de cuchara"),
        ("canula",   "Molido de canula"),
        ("acordeon", "Molido de acordeon"),
        ("tapon",    "Molido de tapon"),
        ("piston",   "Molido de piston"),
        ("gotero",   "Molido de gotero"),
    ]

    molido_usado_reg = {}
    mu_cols = st.columns(3)
    for i, (den_id, den_label) in enumerate(DENOMINACIONES_MOLIDO):
        col = mu_cols[i % 3]
        v = registro.get("molido_usado", {}).get(den_id, 0.0)
        nv = col.number_input(
            den_label, min_value=0.0, step=0.5,
            value=float(v),
            key=f"reg_molu_{fecha_str}_{den_id}", format="%.2f",
        )
        if nv > 0:
            molido_usado_reg[den_id] = nv

    coment_molido_usado = st.text_area(
        "Comentarios sobre el molido usado (opcional)",
        value=registro.get("coment_molido_usado", ""),
        key=f"reg_cmolu_{fecha_str}", height=70,
        placeholder="Ej: mezcla 30% molido de vaso con virgen",
    )

    st.divider()

    # 3. Desechos
    _step(3, "Desechos no recuperables (kg)", "Material que no se puede moler ni reusar.")

    prod_keys = sorted(productos_r.keys(), key=lambda k: productos_r[k].get("nombre", k))
    desechos_reg = {}
    d_cols = st.columns(3)
    for i, pid in enumerate(prod_keys):
        col = d_cols[i % 3]
        v = registro.get("desechos_por_producto", {}).get(pid, 0.0)
        nv = col.number_input(
            productos_r[pid].get("nombre", pid),
            min_value=0.0, step=0.05,
            value=float(v),
            key=f"reg_des_{fecha_str}_{pid}", format="%.3f",
        )
        if nv > 0:
            desechos_reg[pid] = nv

    SUBPRODUCTOS = [
        ("canula",   "Canula"),
        ("piston",   "Piston"),
        ("acordeon", "Acordeon"),
        ("tapon",    "Tapon"),
        ("capuchon", "Capuchon"),
    ]

    st.markdown("**Desechos de subproductos (partes)**")
    desechos_sub_reg = {}
    sd_cols = st.columns(3)
    for i, (sid, sname) in enumerate(SUBPRODUCTOS):
        col = sd_cols[i % 3]
        v = registro.get("desechos_subproductos", {}).get(sid, 0.0)
        nv = col.number_input(
            sname, min_value=0.0, step=0.05,
            value=float(v),
            key=f"reg_dsub_{fecha_str}_{sid}", format="%.3f",
        )
        if nv > 0:
            desechos_sub_reg[sid] = nv

    st.markdown("**Desechos de areas generales (opcional)**")
    otros_reg = {}
    oa, ob, oc = st.columns(3)
    prev_o = registro.get("desechos_otros", {}) or {}
    otros_reg["empacadora"] = oa.number_input(
        "Empacadora", min_value=0.0, step=0.05,
        value=float(prev_o.get("empacadora", 0)),
        key=f"reg_desemp_{fecha_str}", format="%.3f",
    )
    otros_reg["mazarota"] = ob.number_input(
        "Mazarota", min_value=0.0, step=0.05,
        value=float(prev_o.get("mazarota", 0)),
        key=f"reg_desmaz_{fecha_str}", format="%.3f",
    )
    otros_reg["otros"] = oc.number_input(
        "Otros", min_value=0.0, step=0.05,
        value=float(prev_o.get("otros", 0)),
        key=f"reg_desotr_{fecha_str}", format="%.3f",
    )

    coment_desechos = st.text_area(
        "Comentarios sobre los desechos (opcional)",
        value=registro.get("coment_desechos", ""),
        key=f"reg_cdes_{fecha_str}", height=70,
        placeholder="Ej: maquina 3 con mas desecho que lo normal, arranque lento",
    )

    st.divider()

    # 4. Molido generado
    _step(4, "Molido generado hoy (kg)", "Material procesado en la molida. Disponible para reusar proximos dias.")

    molido_reg = {}
    m_cols = st.columns(3)
    for i, pid in enumerate(prod_keys):
        col = m_cols[i % 3]
        v = registro.get("molido", {}).get(pid, 0.0)
        nv = col.number_input(
            productos_r[pid].get("nombre", pid),
            min_value=0.0, step=0.5,
            value=float(v),
            key=f"reg_mol_{fecha_str}_{pid}", format="%.2f",
        )
        if nv > 0:
            molido_reg[pid] = nv

    coment_molido = st.text_area(
        "Comentarios sobre el molido (opcional)",
        value=registro.get("coment_molido", ""),
        key=f"reg_cmol_{fecha_str}", height=70,
        placeholder="Ej: molido de vasos con restos de etiqueta",
    )

    st.divider()

    # 5. Produccion
    _step(5, "Produccion del dia", "Productos terminados y subproductos (partes para jeringas y goteros).")

    def _leer_prod_prev(prev_val, unidad_default):
        if isinstance(prev_val, (int, float)):
            return int(prev_val), unidad_default
        if isinstance(prev_val, dict):
            return int(prev_val.get("cant", 0) or 0), prev_val.get("uni", unidad_default)
        return 0, unidad_default

    st.markdown("**Productos completos**")
    produccion_reg = {}
    p_cols = st.columns(2)
    for i, pid in enumerate(prod_keys):
        col = p_cols[i % 2]
        with col:
            u_caja = productos_r[pid].get("unidades_caja", 1)
            prev_cant, prev_uni = _leer_prod_prev(
                registro.get("produccion", {}).get(pid), "caja"
            )
            st.markdown(f"**{productos_r[pid].get('nombre', pid)}**")
            ic, tc = st.columns([2, 3])
            cant = ic.number_input(
                "Cantidad",
                min_value=0, step=1, value=prev_cant,
                key=f"reg_prod_{fecha_str}_{pid}",
                label_visibility="collapsed",
                help=f"{u_caja} unidades por caja",
            )
            uni = tc.segmented_control(
                "Unidad",
                options=["caja", "funda"],
                default=prev_uni if prev_uni in ("caja", "funda") else "caja",
                key=f"reg_prod_uni_{fecha_str}_{pid}",
                label_visibility="collapsed",
            )
            if cant > 0:
                produccion_reg[pid] = {"cant": cant, "uni": uni or "caja"}

    st.markdown("**Subproductos (partes)**")
    st.caption("Piezas sueltas listas para ensamblar. Se cuentan en fundas o tachos.")

    subproductos_reg = {}
    s_cols = st.columns(2)
    for i, (sid, sname) in enumerate(SUBPRODUCTOS):
        col = s_cols[i % 2]
        with col:
            prev_cant, prev_uni = _leer_prod_prev(
                registro.get("subproductos", {}).get(sid), "funda"
            )
            st.markdown(f"**{sname}**")
            ic, tc = st.columns([2, 3])
            cant = ic.number_input(
                "Cantidad",
                min_value=0, step=1, value=prev_cant,
                key=f"reg_sub_{fecha_str}_{sid}",
                label_visibility="collapsed",
            )
            uni = tc.segmented_control(
                "Unidad",
                options=["funda", "tacho"],
                default=prev_uni if prev_uni in ("funda", "tacho") else "funda",
                key=f"reg_sub_uni_{fecha_str}_{sid}",
                label_visibility="collapsed",
            )
            if cant > 0:
                subproductos_reg[sid] = {"cant": cant, "uni": uni or "funda"}

    coment_produccion = st.text_area(
        "Comentarios sobre la produccion (opcional)",
        value=registro.get("coment_produccion", ""),
        key=f"reg_cprod_{fecha_str}", height=70,
        placeholder="Ej: se paro 1h por cambio de molde en la maquina 2",
    )

    st.divider()

    obs = st.text_area(
        "Observaciones generales del dia (opcional)",
        value=registro.get("observaciones", ""),
        key=f"reg_obs_{fecha_str}", height=80,
        placeholder="Cualquier otra nota importante",
    )

    ba, bb = st.columns(2)
    if ba.button("Guardar registro", type="primary", use_container_width=True,
                 key="reg_save"):
        datos = {
            "material_usado": {k: v for k, v in mat_usado_reg.items() if v > 0},
            "coment_material": coment_material,
            "molido_usado": molido_usado_reg,
            "coment_molido_usado": coment_molido_usado,
            "desechos_por_producto": desechos_reg,
            "desechos_subproductos": desechos_sub_reg,
            "desechos_otros": {k: v for k, v in otros_reg.items() if v > 0},
            "coment_desechos": coment_desechos,
            "molido": molido_reg,
            "coment_molido": coment_molido,
            "produccion": produccion_reg,
            "subproductos": subproductos_reg,
            "coment_produccion": coment_produccion,
            "observaciones": obs,
        }
        save_registro_diario(fecha_str, datos)
        st.success(f"Registro guardado para {fecha_sel.strftime('%d/%m/%Y')}")
        st.balloons()

    if role == "admin" and registro:
        if bb.button("Eliminar registro", type="secondary",
                     use_container_width=True, key="reg_del"):
            delete_registro_diario(fecha_str)
            st.success("Registro eliminado")
            st.rerun()

    st.divider()
    st.subheader("Ultimos registros")

    todos_reg = list_registros_diarios()
    if todos_reg:
        recientes = sorted(todos_reg.keys(), reverse=True)[:10]
        rows_recientes = []
        for f in recientes:
            r = todos_reg[f]
            tm = sum(float(v or 0) for v in (r.get("material_usado") or {}).values())
            tp = sum(float(v or 0) for v in (r.get("produccion") or {}).values())
            rows_recientes.append({
                "Fecha": f,
                "Material usado (kg)": round(tm, 2),
                "Cajas": int(tp),
                "Obs.": (r.get("observaciones", "") or "")[:50],
            })
        st.dataframe(pd.DataFrame(rows_recientes), hide_index=True, use_container_width=True)
    else:
        st.caption("Sin registros aun.")
