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
