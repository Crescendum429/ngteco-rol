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
    return default if default is not None else {}


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
