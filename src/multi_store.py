"""Small, auditable storage layer for the multi-user MVP.

SQLite is intentionally used only for the single-host MVP. Session material is
Fernet-encrypted before it reaches SQLite; production should move the key to KMS
or Vault and use PostgreSQL for replicated deployments.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

import multi_config as config


def now() -> int:
    return int(time.time())


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SecretBox:
    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except Exception:
            derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
            self._fernet = Fernet(derived)

    def seal(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def open(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("encrypted value cannot be decrypted") from exc


class Store:
    def __init__(self, path: str | None = None):
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.box = SecretBox(config.SESSION_KEY)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telegram_accounts (
                    account_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL UNIQUE,
                    telegram_user_id INTEGER,
                    phone_last4 TEXT,
                    session_ciphertext TEXT,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS pending_logins (
                    login_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    phone_ciphertext TEXT NOT NULL,
                    code_hash_ciphertext TEXT NOT NULL,
                    session_ciphertext TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS connect_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_secret TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_transactions (
                    tx_hash TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_codes (
                    code_hash TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                    token_hash TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                    token_hash TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    expires_at INTEGER,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    details_json TEXT,
                    created_at INTEGER NOT NULL
                );
                """
            )

    def ensure_user(self, user_id: str, display_name: str | None = None) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO users(user_id, display_name, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET display_name=COALESCE(excluded.display_name, users.display_name)",
                (user_id, display_name, now()),
            )

    def audit(self, user_id: str | None, action: str, outcome: str, details: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO audit_events(user_id, action, outcome, details_json, created_at) VALUES(?,?,?,?,?)",
                (user_id, action, outcome, json.dumps(details or {}, ensure_ascii=False), now()),
            )

    def create_connect_token(self, user_id: str, ttl: int = 600) -> str:
        raw = secrets.token_urlsafe(32)
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM connect_tokens WHERE expires_at < ? OR used=1", (now(),))
            db.execute("INSERT INTO connect_tokens(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash(raw), user_id, now() + ttl))
        return raw

    def consume_connect_token(self, raw: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT user_id, expires_at, used FROM connect_tokens WHERE token_hash=?", (token_hash(raw),)).fetchone()
            if not row or row["used"] or row["expires_at"] < now():
                return None
            db.execute("UPDATE connect_tokens SET used=1 WHERE token_hash=?", (token_hash(raw),))
            return str(row["user_id"])

    def get_connect_user(self, raw: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT user_id, expires_at, used FROM connect_tokens WHERE token_hash=?", (token_hash(raw),)).fetchone()
            if not row or row["used"] or row["expires_at"] < now():
                return None
            return str(row["user_id"])

    def save_pending_login(self, login_id: str, user_id: str, phone: str, code_hash: str, session: str, status: str = "code_sent", ttl: int = 600) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM pending_logins WHERE user_id=?", (user_id,))
            db.execute(
                "INSERT INTO pending_logins(login_id,user_id,phone_ciphertext,code_hash_ciphertext,session_ciphertext,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (login_id, user_id, self.box.seal(phone), self.box.seal(code_hash), self.box.seal(session), status, now() + ttl, now()),
            )

    def get_pending_login(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM pending_logins WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
            if not row or row["expires_at"] < now():
                return None
            return {
                "login_id": row["login_id"],
                "user_id": row["user_id"],
                "phone": self.box.open(row["phone_ciphertext"]),
                "code_hash": self.box.open(row["code_hash_ciphertext"]),
                "session": self.box.open(row["session_ciphertext"]),
                "status": row["status"],
                "expires_at": row["expires_at"],
            }

    def set_pending_status(self, user_id: str, status: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE pending_logins SET status=? WHERE user_id=?", (status, user_id))

    def delete_pending(self, user_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM pending_logins WHERE user_id=?", (user_id,))

    def save_account(self, user_id: str, telegram_user_id: int, phone: str | None, session: str) -> str:
        account_id = secrets.token_urlsafe(18)
        stamp = now()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO telegram_accounts(account_id,user_id,telegram_user_id,phone_last4,session_ciphertext,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET telegram_user_id=excluded.telegram_user_id,phone_last4=excluded.phone_last4,session_ciphertext=excluded.session_ciphertext,status='active',updated_at=excluded.updated_at,revoked_at=NULL",
                (account_id, user_id, telegram_user_id, (phone or "")[-4:], self.box.seal(session), "active", stamp, stamp),
            )
            row = db.execute("SELECT account_id FROM telegram_accounts WHERE user_id=?", (user_id,)).fetchone()
            return str(row["account_id"])

    def get_account(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM telegram_accounts WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return None
            return {
                "account_id": row["account_id"],
                "user_id": row["user_id"],
                "telegram_user_id": row["telegram_user_id"],
                "phone_last4": row["phone_last4"],
                "session": self.box.open(row["session_ciphertext"]) if row["session_ciphertext"] else None,
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "revoked_at": row["revoked_at"],
            }

    def revoke_account(self, user_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE telegram_accounts SET status='revoked', session_ciphertext=NULL, revoked_at=?, updated_at=? WHERE user_id=?", (now(), now(), user_id))

    def save_client(self, client_id: str, client_secret: str | None, metadata: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO oauth_clients(client_id,client_secret,metadata_json,created_at) VALUES(?,?,?,?)", (client_id, client_secret, json.dumps(metadata), now()))

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
            if not row:
                return None
            return {"client_id": row["client_id"], "client_secret": row["client_secret"], "metadata": json.loads(row["metadata_json"])}

    def save_oauth_transaction(self, tx: str, payload: dict[str, Any], expires_at: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO oauth_transactions(tx_hash,payload_json,expires_at) VALUES(?,?,?)", (token_hash(tx), json.dumps(payload), expires_at))

    def load_oauth_transaction(self, tx: str, consume: bool = False) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM oauth_transactions WHERE tx_hash=?", (token_hash(tx),)).fetchone()
            if not row or row["expires_at"] < now():
                return None
            if consume:
                db.execute("DELETE FROM oauth_transactions WHERE tx_hash=?", (token_hash(tx),))
            return json.loads(row["payload_json"])

    def save_oauth_code(self, code: str, payload: dict[str, Any], expires_at: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO oauth_codes(code_hash,payload_json,expires_at,used) VALUES(?,?,?,0)", (token_hash(code), json.dumps(payload), expires_at))

    def load_oauth_code(self, code: str, consume: bool = False) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM oauth_codes WHERE code_hash=?", (token_hash(code),)).fetchone()
            if not row or row["used"] or row["expires_at"] < now():
                return None
            if consume:
                db.execute("UPDATE oauth_codes SET used=1 WHERE code_hash=?", (token_hash(code),))
            return json.loads(row["payload_json"])

    def save_access_token(self, token: str, subject: str, client_id: str, scopes: list[str], expires_at: int) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO oauth_access_tokens(token_hash,subject,client_id,scopes,expires_at) VALUES(?,?,?,?,?)", (token_hash(token), subject, client_id, " ".join(scopes), expires_at))

    def save_refresh_token(self, token: str, subject: str, client_id: str, scopes: list[str], expires_at: int | None) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO oauth_refresh_tokens(token_hash,subject,client_id,scopes,expires_at) VALUES(?,?,?,?,?)", (token_hash(token), subject, client_id, " ".join(scopes), expires_at))

    def get_refresh_token(self, token: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM oauth_refresh_tokens WHERE token_hash=?", (token_hash(token),)).fetchone()
            if not row or row["revoked"] or (row["expires_at"] is not None and row["expires_at"] < now()):
                return None
            return {"subject": row["subject"], "client_id": row["client_id"], "scopes": row["scopes"].split(), "expires_at": row["expires_at"]}

    def revoke_refresh_token(self, token: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE oauth_refresh_tokens SET revoked=1 WHERE token_hash=?", (token_hash(token),))

    def get_access_token(self, token: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM oauth_access_tokens WHERE token_hash=?", (token_hash(token),)).fetchone()
            if not row or row["revoked"] or row["expires_at"] < now():
                return None
            return {"subject": row["subject"], "client_id": row["client_id"], "scopes": row["scopes"].split(), "expires_at": row["expires_at"]}

    def revoke_access_token(self, token: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE oauth_access_tokens SET revoked=1 WHERE token_hash=?", (token_hash(token),))
