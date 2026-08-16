"""Configuration for the multi-user Telegram MCP MVP.

Secrets are read from the process environment or .env.multi. Never commit the
values from that file. Production should load these values from a secret manager.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _load_env_file(path: str = ".env.multi") -> None:
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
PUBLIC_BASE_URL = os.environ.get("MCP_PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8080"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")
DB_PATH = os.environ.get("MCP_DB_PATH", "./data/multitenant.sqlite3")
SESSION_KEY = os.environ.get("MCP_SESSION_ENCRYPTION_KEY", "")
INVITE_CODES_JSON = os.environ.get("MCP_INVITE_CODES", "{}")
DOWNLOAD_ROOT = os.environ.get("MCP_DOWNLOAD_ROOT", "./data/downloads")
ALLOWED_HOSTS = [x.strip() for x in os.environ.get("MCP_ALLOWED_HOSTS", "localhost:8080,127.0.0.1:8080").split(",") if x.strip()]
ALLOWED_ORIGINS = [x.strip() for x in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if x.strip()]

READ_SCOPE = "telegram:read"
MEDIA_SCOPE = "telegram:media"
SEND_SCOPE = "telegram:send"
MANAGE_SCOPE = "telegram:manage"
ADMIN_SCOPE = "telegram:admin"
ALL_SCOPES = [READ_SCOPE, MEDIA_SCOPE, SEND_SCOPE, MANAGE_SCOPE, ADMIN_SCOPE]


def invite_codes() -> dict[str, str]:
    try:
        value = json.loads(INVITE_CODES_JSON)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MCP_INVITE_CODES must be a JSON object") from exc
    if not isinstance(value, dict):
        raise RuntimeError("MCP_INVITE_CODES must be a JSON object")
    return {str(code): str(user_id) for code, user_id in value.items()}


def validate() -> None:
    missing = []
    if not API_ID:
        missing.append("TELEGRAM_API_ID")
    if not API_HASH:
        missing.append("TELEGRAM_API_HASH")
    if not SESSION_KEY:
        missing.append("MCP_SESSION_ENCRYPTION_KEY")
    if missing:
        raise RuntimeError("Missing required multi-user config: " + ", ".join(missing))
    if not PUBLIC_BASE_URL.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise RuntimeError("MCP_PUBLIC_BASE_URL must use HTTPS outside localhost")
    if not invite_codes():
        raise RuntimeError("MCP_INVITE_CODES must contain at least one user-specific invite code")
