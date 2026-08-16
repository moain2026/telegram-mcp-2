"""Per-user Telegram session lifecycle for the multi-user MCP MVP."""
from __future__ import annotations

import asyncio
import secrets
from collections import defaultdict
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

import multi_config as config
from multi_store import Store


class LinkError(RuntimeError):
    pass


class MultiTelegram:
    def __init__(self, store: Store):
        self.store = store
        self._clients: dict[str, TelegramClient] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _new_client(self, session: str = "") -> TelegramClient:
        client = TelegramClient(StringSession(session), config.API_ID, config.API_HASH)
        await client.connect()
        return client

    async def start_link(self, user_id: str, phone: str) -> dict[str, Any]:
        phone = phone.strip()
        if not phone.startswith("+") or len(phone) < 8:
            raise LinkError("phone must use international format, for example +967...")
        async with self._locks[user_id]:
            client = await self._new_client()
            try:
                sent = await client.send_code_request(phone)
                session = client.session.save()
                login_id = secrets.token_urlsafe(18)
                self.store.save_pending_login(login_id, user_id, phone, sent.phone_code_hash, session)
                self.store.audit(user_id, "telegram.send_code", "ok")
                return {"ok": True, "status": "code_sent", "login_id": login_id, "expires_in": 600}
            except PhoneNumberInvalidError as exc:
                self.store.audit(user_id, "telegram.send_code", "phone_invalid")
                raise LinkError("Telegram rejected the phone number") from exc
            finally:
                await client.disconnect()

    async def finish_code(self, user_id: str, code: str) -> dict[str, Any]:
        pending = self.store.get_pending_login(user_id)
        if not pending:
            raise LinkError("no active login; request a new code")
        async with self._locks[user_id]:
            client = await self._new_client(pending["session"])
            try:
                await client.sign_in(phone=pending["phone"], code=code.strip(), phone_code_hash=pending["code_hash"])
                return await self._activate(user_id, client, pending["phone"])
            except SessionPasswordNeededError:
                self.store.set_pending_status(user_id, "2fa_required")
                self.store.audit(user_id, "telegram.code", "2fa_required")
                return {"ok": True, "status": "2fa_required"}
            except PhoneCodeExpiredError as exc:
                self.store.delete_pending(user_id)
                self.store.audit(user_id, "telegram.code", "expired")
                raise LinkError("Telegram code expired; request a new code") from exc
            except PhoneCodeInvalidError as exc:
                self.store.audit(user_id, "telegram.code", "invalid")
                raise LinkError("Telegram code is invalid") from exc
            finally:
                if client.is_connected():
                    await client.disconnect()

    async def finish_2fa(self, user_id: str, password: str) -> dict[str, Any]:
        pending = self.store.get_pending_login(user_id)
        if not pending or pending["status"] != "2fa_required":
            raise LinkError("2FA is not currently required; request a new code")
        if not password:
            raise LinkError("2FA password is required")
        async with self._locks[user_id]:
            client = await self._new_client(pending["session"])
            try:
                await client.sign_in(password=password)
                return await self._activate(user_id, client, pending["phone"])
            except PasswordHashInvalidError as exc:
                self.store.audit(user_id, "telegram.2fa", "invalid")
                raise LinkError("Telegram 2FA password is invalid") from exc
            finally:
                if client.is_connected():
                    await client.disconnect()

    async def _activate(self, user_id: str, client: TelegramClient, phone: str | None) -> dict[str, Any]:
        if not await client.is_user_authorized():
            raise LinkError("Telegram did not authorize the session")
        me = await client.get_me()
        account_id = self.store.save_account(user_id, me.id, phone or me.phone, client.session.save())
        self.store.delete_pending(user_id)
        self.store.audit(user_id, "telegram.link", "ok", {"telegram_user_id": me.id})
        return {"ok": True, "status": "active", "account_id": account_id, "telegram_user_id": me.id, "username": me.username}

    def account_status(self, user_id: str) -> dict[str, Any]:
        account = self.store.get_account(user_id)
        pending = self.store.get_pending_login(user_id)
        if account and account["status"] == "active":
            return {"status": "active", "account_id": account["account_id"], "telegram_user_id": account["telegram_user_id"], "phone_last4": account["phone_last4"]}
        if pending:
            return {"status": pending["status"], "expires_at": pending["expires_at"]}
        return {"status": "not_linked"}

    async def client(self, user_id: str) -> TelegramClient:
        cached = self._clients.get(user_id)
        if cached is not None and cached.is_connected():
            return cached
        account = self.store.get_account(user_id)
        if not account or account["status"] != "active" or not account["session"]:
            raise LinkError("Telegram account is not linked; call tg_connect_telegram first")
        async with self._locks[user_id]:
            cached = self._clients.get(user_id)
            if cached is not None and cached.is_connected():
                return cached
            client = await self._new_client(account["session"])
            if not await client.is_user_authorized():
                self.store.revoke_account(user_id)
                await client.disconnect()
                raise LinkError("Telegram session is no longer authorized; link the account again")
            self._clients[user_id] = client
            return client

    async def unlink(self, user_id: str) -> dict[str, Any]:
        async with self._locks[user_id]:
            client = self._clients.pop(user_id, None)
            if client is not None and client.is_connected():
                await client.disconnect()
            self.store.revoke_account(user_id)
            self.store.delete_pending(user_id)
            self.store.audit(user_id, "telegram.unlink", "ok")
            return {"ok": True, "status": "revoked"}

    async def close(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            if client.is_connected():
                await client.disconnect()
