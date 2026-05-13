import json
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

_client = None


def _supabase():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def load_empleados():
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", "empleados").execute()
            if res.data:
                return res.data[0]["value"]
        except Exception:
            pass
        return {}

    # Fallback: archivo local (para desarrollo)
    path = os.environ.get("DATA_FILE", "empleados.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_empleados(empleados):
    if USE_SUPABASE:
        _supabase().table("config").upsert({
            "key": "empleados",
            "value": empleados,
        }).execute()
        return

    path = os.environ.get("DATA_FILE", "empleados.json")
    with open(path, "w") as f:
        json.dump(empleados, f, ensure_ascii=False, indent=2)


def is_changelog_dismissed(version):
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", "changelog").execute()
            if res.data:
                return version in res.data[0]["value"].get("dismissed", [])
        except Exception:
            pass
    return False


def dismiss_changelog(version):
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", "changelog").execute()
            current = res.data[0]["value"] if res.data else {"dismissed": []}
        except Exception:
            current = {"dismissed": []}
        if version not in current["dismissed"]:
            current["dismissed"].append(version)
        _supabase().table("config").upsert({"key": "changelog", "value": current}).execute()


def export_json(empleados):
    return json.dumps(empleados, ensure_ascii=False, indent=2)


def import_json(raw):
    return json.loads(raw)


# ── Reportes mensuales ────────────────────────────────────────

def _serialize_data(data):
    """Convierte data de parse_xls a formato JSON-safe."""
    result = []
    for emp, days, nid in data:
        days_ser = {}
        for ds, pairs in days.items():
            days_ser[ds] = pairs
        result.append({"emp": emp, "days": days_ser, "nid": nid})
    return result


def _deserialize_data(raw):
    """Reconstruye data desde JSON."""
    result = []
    for item in raw:
        days = {}
        for ds, pairs in item["days"].items():
            days[ds] = [tuple(p) for p in pairs]
        result.append((item["emp"], days, item["nid"]))
    return result


def list_reportes():
    if USE_SUPABASE:
        try:
            res = (_supabase().table("reportes")
                   .select("id, periodo, uploaded_at")
                   .order("id", desc=True)
                   .execute())
            return res.data or []
        except Exception:
            return []
    return []


def load_reporte(reporte_id):
    if USE_SUPABASE:
        try:
            res = (_supabase().table("reportes")
                   .select("data, cls")
                   .eq("id", reporte_id)
                   .execute())
            if res.data:
                row = res.data[0]
                return _deserialize_data(row["data"]), row["cls"]
        except Exception:
            pass
    return None, None


def save_reporte(reporte_id, periodo, data, cls):
    if USE_SUPABASE:
        _supabase().table("reportes").upsert({
            "id": reporte_id,
            "periodo": periodo,
            "data": _serialize_data(data),
            "cls": cls,
        }).execute()


def load_arrastre(reporte_id):
    """Carga horas de arrastre guardadas para un reporte."""
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", f"arrastre_{reporte_id}").execute()
            if res.data:
                return res.data[0]["value"]
        except Exception:
            pass
    return {}


def save_arrastre(reporte_id, arrastre):
    """Guarda horas de arrastre para un reporte. arrastre: {emp_name: hours}"""
    if USE_SUPABASE:
        _supabase().table("config").upsert({
            "key": f"arrastre_{reporte_id}",
            "value": arrastre,
        }).execute()


def get_arrastre_anterior(reporte_id):
    """Busca arrastre del mes anterior."""
    try:
        y, m = reporte_id.split("-")
        y, m = int(y), int(m)
        if m == 1:
            prev = f"{y-1}-12"
        else:
            prev = f"{y}-{m-1:02d}"
        return load_arrastre(prev), prev
    except Exception:
        return {}, ""


def reporte_exists(reporte_id):
    if USE_SUPABASE:
        try:
            res = (_supabase().table("reportes")
                   .select("id")
                   .eq("id", reporte_id)
                   .execute())
            return bool(res.data)
        except Exception:
            return False
    return False


def delete_reporte(reporte_id):
    if USE_SUPABASE:
        _supabase().table("reportes").delete().eq("id", reporte_id).execute()
        for suffix in ["arrastre", "extras", "nomina_resumen"]:
            try:
                _supabase().table("config").delete().eq("key", f"{suffix}_{reporte_id}").execute()
            except Exception:
                pass


def save_extras_config(reporte_id, config):
    if USE_SUPABASE:
        _supabase().table("config").upsert({
            "key": f"extras_{reporte_id}",
            "value": config,
        }).execute()


def load_extras_config(reporte_id):
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", f"extras_{reporte_id}").execute()
            if res.data:
                return res.data[0]["value"]
        except Exception:
            pass
    return {}


def get_extras_config_anterior(reporte_id):
    try:
        y, m = reporte_id.split("-")
        y, m = int(y), int(m)
        prev = f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"
        return load_extras_config(prev), prev
    except Exception:
        return {}, ""


def save_nomina_resumen(reporte_id, resumen):
    if USE_SUPABASE:
        _supabase().table("config").upsert({
            "key": f"nomina_resumen_{reporte_id}",
            "value": resumen,
        }).execute()


def load_all_nomina_resumenes():
    if USE_SUPABASE:
        try:
            res = (_supabase().table("config")
                   .select("key, value")
                   .like("key", "nomina_resumen_%")
                   .execute())
            result = {}
            for row in (res.data or []):
                rid = row["key"].replace("nomina_resumen_", "")
                result[rid] = row["value"]
            return result
        except Exception:
            pass
    return {}


def get_reporte_anterior(reporte_id):
    try:
        y, m = reporte_id.split("-")
        y, m = int(y), int(m)
        prev = f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"
        data, cls = load_reporte(prev)
        return data, cls, prev
    except Exception:
        return None, None, ""


# ── Modulo Gastos: configuraciones y registros ───────────────

def _cfg_get(key, default=None):
    if USE_SUPABASE:
        try:
            res = _supabase().table("config").select("value").eq("key", key).execute()
            if res.data:
                return res.data[0]["value"]
        except Exception:
            pass
    return default


def _cfg_set(key, value):
    if USE_SUPABASE:
        _supabase().table("config").upsert({"key": key, "value": value}).execute()


def _cfg_delete(key):
    if USE_SUPABASE:
        try:
            _supabase().table("config").delete().eq("key", key).execute()
        except Exception:
            pass


def _cfg_list(prefix):
    if USE_SUPABASE:
        try:
            res = (_supabase().table("config")
                   .select("key, value")
                   .like("key", f"{prefix}%")
                   .execute())
            return {row["key"]: row["value"] for row in (res.data or [])}
        except Exception:
            pass
    return {}


_OLD_CAJA_IDS = {"caja_vasos_std", "caja_vasos_grande", "caja_cuchara",
                 "caja_jeringa", "caja_gotero"}


def load_materiales():
    from costos import MATERIALES_DEFAULT
    return _cfg_get("gastos:materiales", {k: dict(v) for k, v in MATERIALES_DEFAULT.items()})


def save_materiales(data):
    _cfg_set("gastos:materiales", data)


def load_productos():
    from costos import PRODUCTOS_DEFAULT
    import copy
    data = _cfg_get("gastos:productos", copy.deepcopy(PRODUCTOS_DEFAULT))
    # Migracion: reemplazar referencias a cajas viejas por 'caja' unica
    cambiado = False
    for pid, prod in data.items():
        emp = prod.get("empaques") or {}
        nuevos = {}
        for eid, qty in emp.items():
            if eid in _OLD_CAJA_IDS:
                nuevos["caja"] = qty
                cambiado = True
            else:
                nuevos[eid] = qty
        if nuevos != emp:
            data[pid]["empaques"] = nuevos
    if cambiado:
        _cfg_set("gastos:productos", data)
    return data


def save_productos(data):
    _cfg_set("gastos:productos", data)


def load_empaques():
    from costos import EMPAQUES_DEFAULT
    data = _cfg_get("gastos:empaques", {k: dict(v) for k, v in EMPAQUES_DEFAULT.items()})
    # Migracion: consolidar cajas viejas en una sola 'caja'
    if any(old in data for old in _OLD_CAJA_IDS):
        if "caja" not in data:
            data["caja"] = {"nombre": "Caja", "costo": 1.00, "unidad": "caja"}
        for old in list(_OLD_CAJA_IDS):
            data.pop(old, None)
        _cfg_set("gastos:empaques", data)
    return data


def save_empaques(data):
    _cfg_set("gastos:empaques", data)


def load_gastos_fijos(periodo_id):
    from costos import GASTOS_FIJOS_DEFAULT
    return _cfg_get(f"gastos:fijos:{periodo_id}", dict(GASTOS_FIJOS_DEFAULT))


def save_gastos_fijos(periodo_id, data):
    _cfg_set(f"gastos:fijos:{periodo_id}", data)


def load_nomina_overrides(periodo_id):
    """Overrides por periodo: {emp_id: {prestamo_iess, transporte_dia, descuento_iess, fondos_reserva}}"""
    return _cfg_get(f"nomina:overrides:{periodo_id}", {})


def save_nomina_overrides(periodo_id, data):
    _cfg_set(f"nomina:overrides:{periodo_id}", data)


# ═══ Beneficios recurrentes (nomina) — list of rules per empleado ═══

def load_beneficios_recurrentes():
    return _cfg_get("nomina:beneficios_recurrentes", [])


def save_beneficios_recurrentes(rules):
    _cfg_set("nomina:beneficios_recurrentes", rules)


# ═══ CRM / Comercial — entidades con None=usar mock ═══

def _load_or_none(key):
    """Retorna los datos guardados o None si nunca se guardaron."""
    return _cfg_get(key, None)


def load_clientes():
    return _load_or_none("crm:clientes")


def save_clientes(data):
    _cfg_set("crm:clientes", data)


def load_cotizaciones():
    return _load_or_none("crm:cotizaciones")


def save_cotizaciones(data):
    _cfg_set("crm:cotizaciones", data)


def load_ordenes_compra():
    return _load_or_none("crm:ordenes_compra")


def save_ordenes_compra(data):
    _cfg_set("crm:ordenes_compra", data)


def load_facturas():
    return _load_or_none("crm:facturas")


def save_facturas(data):
    _cfg_set("crm:facturas", data)


def load_guias():
    return _load_or_none("crm:guias")


def save_guias(data):
    _cfg_set("crm:guias", data)


def load_certificados():
    return _load_or_none("crm:certificados")


def save_certificados(data):
    _cfg_set("crm:certificados", data)


def load_emisor():
    return _load_or_none("crm:emisor")


def save_emisor(data):
    _cfg_set("crm:emisor", data)


# ═══ Inventario ═══

def load_inventario_mp():
    return _load_or_none("inv:mp")


def save_inventario_mp(data):
    _cfg_set("inv:mp", data)


def load_inventario_pt():
    return _load_or_none("inv:pt")


def save_inventario_pt(data):
    _cfg_set("inv:pt", data)


def load_movimientos_inventario():
    return _load_or_none("inv:movimientos")


def save_movimientos_inventario(data):
    _cfg_set("inv:movimientos", data)


# ═══ Esquema de inventario nuevo (alineado con operación real) ═══

def load_inv_piezas():
    """Stock de piezas sueltas. Estructura: [{id, pieza, estado, cliente_id?, unidades, minimo, ultima_actualizacion}]
    pieza ∈ {canula, piston, tapon, acordeon_nuevo, acordeon_antiguo, gotero_base, capuchon}
    estado ∈ {cruda, impresa}
    cliente_id opcional cuando estado=impresa."""
    return _load_or_none("inv:piezas") or []


def save_inv_piezas(data):
    _cfg_set("inv:piezas", data)


def load_inv_molido():
    """Stock de molido segregado. Estructura: {tipo: kg}.
    tipo ∈ {canula, vaso, piston, tapon, acordeon, alta, baja, mazarota}"""
    return _load_or_none("inv:molido") or {}


def save_inv_molido(data):
    _cfg_set("inv:molido", data)


def load_inv_auxiliar():
    """Stock de material auxiliar. Estructura: lista de
    [{id, nombre, categoria, unidad, stock, minimo, costo_unit, desactivado}].
    Migracion: si encuentra dict antiguo {item_id: {...}}, lo convierte a lista."""
    raw = _load_or_none("inv:auxiliar")
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        items = []
        for k, v in raw.items():
            if isinstance(v, dict):
                items.append({
                    "id": k,
                    "nombre": v.get("nombre", k),
                    "categoria": v.get("categoria", "empacadora"),
                    "unidad": v.get("unidad", "unidades"),
                    "stock": float(v.get("actual", v.get("stock", 0))),
                    "minimo": float(v.get("minimo", 0)),
                    "costo_unit": float(v.get("costo_unit", 0)),
                    "desactivado": bool(v.get("desactivado", False)),
                })
        return items
    return []


def save_inv_auxiliar(data):
    _cfg_set("inv:auxiliar", data)


def load_inv_aux_consumo():
    """Historico de consumo aux. Lista [{aux_id, fecha, usado, stock_tras}]."""
    return _load_or_none("inv:aux_consumo") or []


def save_inv_aux_consumo(data):
    _cfg_set("inv:aux_consumo", data)


def append_aux_consumo(entries):
    """Agrega entradas al historico. entries = lista de dicts."""
    existing = load_inv_aux_consumo()
    existing.extend(entries)
    save_inv_aux_consumo(existing)


def load_qc_templates():
    """Plantillas QC por producto. {prod_id: {parametros: [{id, nombre, unidad, minimo, maximo, metodo}]}}."""
    return _load_or_none("qc:templates") or {}


def save_qc_templates(data):
    _cfg_set("qc:templates", data)


def load_alertas_persistentes():
    """Alertas creadas manualmente (ej. OC sugeridas del chat). Lista persistente.
    Estructura: [{id, tipo, titulo, descripcion, fecha_creacion, ref, meta}]"""
    return _load_or_none("alertas:persistentes") or []


def save_alertas_persistentes(data):
    _cfg_set("alertas:persistentes", data)


def load_alertas_descartadas():
    """Set de IDs de alertas que el usuario descarto. Las descartadas no se muestran."""
    return _load_or_none("alertas:descartadas") or []


def save_alertas_descartadas(data):
    _cfg_set("alertas:descartadas", list(data))


# ─── Stock dinamico calculado desde movimientos ───
# El stock real NUNCA se persiste como tal: se deriva del log de movimientos
# (entradas - consumos) y de los lotes (PT). Asi nunca hay desincronizacion.

def compute_stock_mp():
    """Stock de materia prima por material, calculado desde movimientos.
    Retorna lista [{id, stock_kg, minimo_kg, costo_prom_kg, ultima_entrada}]."""
    movs = load_movimientos_inventario() or []
    materiales = load_materiales() or {}
    if not isinstance(materiales, dict):
        materiales = {}
    by_id = {}
    for mat_id, mat in materiales.items():
        by_id[mat_id] = {
            "id": mat_id,
            "stock_kg": 0.0,
            "minimo_kg": float(mat.get("minimo_kg") or 0),
            "costo_prom_kg": float(mat.get("costo_kg") or 0),
            "ultima_entrada": "",
        }
    for m in movs:
        if not isinstance(m, dict) or m.get("clase") != "mp":
            continue
        item = m.get("item_id")
        if not item:
            continue
        if item not in by_id:
            by_id[item] = {"id": item, "stock_kg": 0.0, "minimo_kg": 0, "costo_prom_kg": 0, "ultima_entrada": ""}
        cant = float(m.get("cantidad") or 0)
        tipo = m.get("tipo")
        if tipo in ("entrada", "produccion"):
            by_id[item]["stock_kg"] += cant
            fecha = m.get("fecha") or ""
            if fecha > by_id[item]["ultima_entrada"]:
                by_id[item]["ultima_entrada"] = fecha
        elif tipo in ("consumo", "salida"):
            by_id[item]["stock_kg"] -= cant
        elif tipo == "ajuste":
            by_id[item]["stock_kg"] += cant  # ajuste positivo por default
    # Redondear y filtrar inactivos (sin stock ni minimo)
    for v in by_id.values():
        v["stock_kg"] = round(v["stock_kg"], 2)
    return [v for v in by_id.values() if v["stock_kg"] != 0 or v["minimo_kg"] > 0]


def compute_stock_pt():
    """Stock de producto terminado por producto, desde lotes en stock.
    Retorna lista [{prod_id, stock_cajas, reservado, minimo_cajas}]."""
    lotes = load_inv_lotes() or []
    productos = load_productos() or {}
    if not isinstance(productos, dict):
        productos = {}
    by_id = {pid: {"prod_id": pid, "stock_cajas": 0, "reservado": 0, "minimo_cajas": int(p.get("minimo_cajas") or 0)} for pid, p in productos.items()}
    for l in lotes:
        if not isinstance(l, dict):
            continue
        if l.get("despachado"):
            continue
        pid = l.get("producto_id")
        if not pid:
            continue
        if pid not in by_id:
            by_id[pid] = {"prod_id": pid, "stock_cajas": 0, "reservado": 0, "minimo_cajas": 0}
        by_id[pid]["stock_cajas"] += int(l.get("cantidad_cajas") or 0)
    return [v for v in by_id.values() if v["stock_cajas"] != 0 or v["minimo_cajas"] > 0]


def compute_stock_aux():
    """Stock de material auxiliar. Para mantener coherencia: stock_inicial del
    item + entradas - consumos. El item ya guarda 'stock' actualizado por el
    endpoint registrar-dia, asi que lo retornamos directo."""
    aux = load_inv_auxiliar() or []
    if not isinstance(aux, list):
        return []
    return [a for a in aux if isinstance(a, dict)]


def load_inv_lotes():
    """Lotes de producto terminado. Estructura: [{id, producto_id, cliente_id?, fecha_elaboracion, fecha_caducidad, cantidad_cajas, unidades_caja, peso_neto, peso_total, responsable, despachado, despachado_en}]"""
    return _load_or_none("inv:lotes") or []


def save_inv_lotes(data):
    _cfg_set("inv:lotes", data)


def load_bom():
    """Bill of materials por producto. Estructura: {producto_id: {pieza: cantidad_por_caja, ...}}"""
    return _load_or_none("catalogo:bom") or {}


def save_bom(data):
    _cfg_set("catalogo:bom", data)


def load_cambios_molde():
    """Historial de cambios de molde. Estructura: [{fecha, maquina, de_producto, a_producto, responsable}]"""
    return _load_or_none("inv:cambios_molde") or []


def save_cambios_molde(data):
    _cfg_set("inv:cambios_molde", data)


# ═══ Audit log — cambios sensibles a entidades financieras ═══

def append_audit(entry):
    """Append-only log de cambios a entidades sensibles. NO se borra ni edita.
    Cada entry: {ts, user, entity, action, entity_id, before, after, ip}
    """
    log = _load_or_none("audit:log") or []
    log.append(entry)
    # Mantener solo ultimos 10000 para evitar crecer indefinidamente
    if len(log) > 10000:
        log = log[-10000:]
    _cfg_set("audit:log", log)


def load_audit_log(limit=200, entity_type=None, entity_id=None):
    log = _load_or_none("audit:log") or []
    if entity_type:
        log = [e for e in log if e.get("entity") == entity_type]
    if entity_id:
        log = [e for e in log if e.get("entity_id") == entity_id]
    # Mas reciente primero
    return list(reversed(log))[:limit]


def load_registro_diario(fecha_str):
    return _cfg_get(f"gastos:diario:{fecha_str}", {})


def save_registro_diario(fecha_str, data):
    _cfg_set(f"gastos:diario:{fecha_str}", data)


def delete_registro_diario(fecha_str):
    _cfg_delete(f"gastos:diario:{fecha_str}")


def list_registros_diarios(year_month=None):
    prefix = "gastos:diario:"
    if year_month:
        prefix = f"gastos:diario:{year_month}"
    raw = _cfg_list(prefix)
    result = {}
    for key, val in raw.items():
        fecha = key.replace("gastos:diario:", "")
        result[fecha] = val
    return result


def save_costos_snapshot(periodo_id, snapshot):
    _cfg_set(f"gastos:snapshot:{periodo_id}", snapshot)


def load_costos_snapshot(periodo_id):
    return _cfg_get(f"gastos:snapshot:{periodo_id}", {})


def load_all_costos_snapshots():
    raw = _cfg_list("gastos:snapshot:")
    return {key.replace("gastos:snapshot:", ""): val for key, val in raw.items()}
