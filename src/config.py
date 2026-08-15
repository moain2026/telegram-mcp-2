"""Configuration loader for telegram-mcp.

Loads secrets from environment / a local .env file (never committed).
Required:
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_STRING_SESSION
Optional:
  TELEGRAM_DOWNLOAD_DIR (default ./downloads)
"""
import os


def _load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env_file()

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
STRING_SESSION = os.environ.get("TELEGRAM_STRING_SESSION", "")
DOWNLOAD_DIR = os.environ.get("TELEGRAM_DOWNLOAD_DIR", "./downloads")


def validate() -> None:
    missing = [k for k, v in {
        "TELEGRAM_API_ID": API_ID,
        "TELEGRAM_API_HASH": API_HASH,
        "TELEGRAM_STRING_SESSION": STRING_SESSION,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            "Missing required config: " + ", ".join(missing) +
            " (set them in .env or environment)"
        )
