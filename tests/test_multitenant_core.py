from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


def _setup(tmp_path: Path):
    os.environ["TELEGRAM_API_ID"] = "123456"
    os.environ["TELEGRAM_API_HASH"] = "hash"
    os.environ["MCP_SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["MCP_INVITE_CODES"] = json.dumps({"invite-a": "user-a", "invite-b": "user-b"})
    os.environ["MCP_DB_PATH"] = str(tmp_path / "db.sqlite3")
    import importlib
    import multi_config
    importlib.reload(multi_config)
    from multi_store import Store
    from multi_auth import MultiUserOAuthProvider
    return Store(), MultiUserOAuthProvider(Store())


def test_session_ciphertext_and_user_isolation(tmp_path: Path):
    store, _ = _setup(tmp_path)
    store.ensure_user("user-a")
    store.ensure_user("user-b")
    store.save_account("user-a", 111, "+9670000111", "session-a")
    store.save_account("user-b", 222, "+9670000222", "session-b")
    assert store.get_account("user-a")["session"] == "session-a"
    assert store.get_account("user-b")["session"] == "session-b"
    raw = (tmp_path / "db.sqlite3").read_bytes()
    assert b"session-a" not in raw
    assert b"session-b" not in raw


def test_oauth_access_tokens_are_scoped_to_subject(tmp_path: Path):
    store, _ = _setup(tmp_path)
    store.save_access_token("token-a", "user-a", "client", ["telegram:read"], 4102444800)
    store.save_access_token("token-b", "user-b", "client", ["telegram:read"], 4102444800)
    assert store.get_access_token("token-a")["subject"] == "user-a"
    assert store.get_access_token("token-b")["subject"] == "user-b"
    assert store.get_access_token("token-a")["subject"] != store.get_access_token("token-b")["subject"]


def test_connect_tokens_expire_and_are_single_use(tmp_path: Path):
    store, _ = _setup(tmp_path)
    store.ensure_user("user-a")
    token = store.create_connect_token("user-a", ttl=600)
    assert store.get_connect_user(token) == "user-a"
    assert store.consume_connect_token(token) == "user-a"
    assert store.get_connect_user(token) is None
