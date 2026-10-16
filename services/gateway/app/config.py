import json
import os


def need(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise RuntimeError(f"Missing required env {key}")
    return v


PORT = int(os.environ.get("PORT", "8080"))
DATABASE_URL = need("DATABASE_URL")
SESSION_SECRET = need("SESSION_SECRET")
ENCRYPTION_KEY = need("ENCRYPTION_KEY")
ADMIN_EMAIL = need("ADMIN_EMAIL")
ADMIN_PASSWORD = need("ADMIN_PASSWORD")
UPSTREAM_TOKEN = os.environ.get("UPSTREAM_TOKEN", "")
SEED_SERVERS = json.loads(os.environ.get("SEED_SERVERS") or "[]")
CALL_TIMEOUT = float(os.environ.get("CALL_TIMEOUT_MS", "20000")) / 1000
LIST_TIMEOUT = float(os.environ.get("LIST_TIMEOUT_MS", "5000")) / 1000
HEALTH_INTERVAL = float(os.environ.get("HEALTH_INTERVAL_MS", "15000")) / 1000
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "") == "true"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
