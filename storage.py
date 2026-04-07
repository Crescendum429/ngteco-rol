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


def export_json(empleados):
    return json.dumps(empleados, ensure_ascii=False, indent=2)


def import_json(raw):
    return json.loads(raw)
