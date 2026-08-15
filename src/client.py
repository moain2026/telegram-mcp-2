"""Thin async wrapper around Telethon with a hard safety gate.

The safety gate blocks destructive account-level operations (delete account,
change/reset password) regardless of caller. This mirrors the original
telegram-toolkit policy.
"""
from __future__ import annotations

import os
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

import config

# Telethon request classes that must never be executed.
_BLOCKED = {
    "DeleteAccountRequest",
    "UpdatePasswordSettingsRequest",
    "ResetPasswordRequest",
}


class SafetyError(RuntimeError):
    pass


def _guard(request: Any) -> None:
    name = type(request).__name__
    if name in _BLOCKED:
        raise SafetyError(f"blocked destructive operation: {name}")


class Telegram:
    """Lazy singleton-style client holder."""

    def __init__(self) -> None:
        config.validate()
        self._client: TelegramClient | None = None

    async def client(self) -> TelegramClient:
        if self._client is None:
            c = TelegramClient(
                StringSession(config.STRING_SESSION),
                config.API_ID,
                config.API_HASH,
            )
            await c.connect()
            if not await c.is_user_authorized():
                raise SafetyError(
                    "session not authorized — regenerate TELEGRAM_STRING_SESSION via login"
                )
            self._client = c
        return self._client

    async def call(self, request: Any):
        """Invoke a raw Telethon request through the safety gate."""
        _guard(request)
        c = await self.client()
        return await c(request)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


tg = Telegram()
