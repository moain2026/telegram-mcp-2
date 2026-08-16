"""Multi-user Telegram MCP MVP.

The MCP endpoint is shared, but every tool resolves the user from the verified
OAuth access token. Telegram sessions are loaded only for that user.
"""
from __future__ import annotations

import html
import os
from typing import Optional
from urllib.parse import urlencode

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings, RevocationOptions
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from telethon import utils as telethon_utils
from telethon.tl.types import Channel, Chat

import multi_config as config
from multi_auth import MultiUserOAuthProvider
from multi_store import Store
from multi_telegram import LinkError, MultiTelegram


config.validate()
store = Store()
provider = MultiUserOAuthProvider(store)
resource_url = config.PUBLIC_BASE_URL + config.MCP_PATH

mcp = FastMCP(
    "telegram-mcp-multi-user",
    instructions="Telegram tools are scoped to the authenticated service user and their linked Telegram account.",
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=config.PUBLIC_BASE_URL,
        resource_server_url=resource_url,
        required_scopes=[config.READ_SCOPE],
        client_registration_options=provider.registration_options,
        revocation_options=RevocationOptions(enabled=True),
    ),
    host=config.HOST,
    port=config.PORT,
    streamable_http_path=config.MCP_PATH,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=config.ALLOWED_HOSTS,
        allowed_origins=config.ALLOWED_ORIGINS,
    ),
)

tg = MultiTelegram(store)


def _kind(entity) -> str:
    if isinstance(entity, Channel):
        if getattr(entity, "broadcast", False):
            return "channel"
        if getattr(entity, "megagroup", False):
            return "group"
        return "channel"
    if isinstance(entity, Chat):
        return "group"
    return "user"


def _peer_id(entity) -> int:
    return int(telethon_utils.get_peer_id(entity))


def _user_id(ctx: Context) -> str:
    token = get_access_token()
    if token is None or not token.subject:
        raise LinkError("MCP authorization is required")
    return str(token.subject)


def _scopes(ctx: Context) -> set[str]:
    token = get_access_token()
    return set(token.scopes if token else [])


def _require_scope(ctx: Context, scope: str) -> str:
    user_id = _user_id(ctx)
    if scope not in _scopes(ctx):
        raise PermissionError(f"missing scope: {scope}")
    return user_id


def _coerce(value: str):
    s = str(value).strip()
    return int(s) if s.lstrip("-").isdigit() else s


def _safe_chat_item(d) -> dict:
    entity = d.entity
    return {
        "name": d.name,
        "id": d.id,
        "kind": _kind(entity),
        "is_forum": bool(getattr(entity, "forum", False)),
        "is_broadcast": bool(getattr(entity, "broadcast", False)),
        "is_megagroup": bool(getattr(entity, "megagroup", False)),
        "unread": d.unread_count,
    }


@mcp.tool()
async def tg_connection_status(ctx: Context) -> dict:
    """Return the current Telegram link state for the authenticated service user."""
    user_id = _user_id(ctx)
    return {"user_id": user_id, **tg.account_status(user_id)}


@mcp.tool()
async def tg_connect_telegram(ctx: Context) -> dict:
    """Create a short-lived private link where this user can connect their Telegram account."""
    user_id = _user_id(ctx)
    store.ensure_user(user_id, user_id)
    raw = store.create_connect_token(user_id, ttl=600)
    url = f"{config.PUBLIC_BASE_URL}/connect/telegram?{urlencode({'token': raw})}"
    store.audit(user_id, "telegram.connect_link", "ok")
    return {"ok": True, "status": "not_linked", "connect_url": url, "expires_in": 600, "instruction": "Open this URL in a browser and complete phone, code, and 2FA there. Do not paste codes into Gemini."}


@mcp.tool()
async def tg_unlink_telegram(ctx: Context, confirm: bool = False) -> dict:
    """Revoke this user's linked Telegram session; requires explicit confirmation."""
    user_id = _user_id(ctx)
    if not confirm:
        return {"ok": False, "error": "confirmation required: set confirm=true"}
    return await tg.unlink(user_id)


@mcp.tool()
async def tg_status(ctx: Context) -> dict:
    """Return the linked Telegram account status for the authenticated user."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    status = tg.account_status(user_id)
    if status["status"] != "active":
        return {"ok": True, "user_id": user_id, **status}
    client = await tg.client(user_id)
    me = await client.get_me()
    return {"ok": True, "user_id": user_id, "id": me.id, "first_name": me.first_name, "username": me.username, "phone_last4": (me.phone or "")[-4:], "status": "active"}


@mcp.tool()
async def tg_account_overview(ctx: Context, limit: int = 200) -> dict:
    """Return one read-only summary of this user's Telegram account and dialogs."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    me = await client.get_me()
    groups, channels, users = [], [], []
    async for d in client.iter_dialogs(limit=max(1, min(limit, 500))):
        item = _safe_chat_item(d)
        if item["kind"] == "group":
            groups.append(item)
        elif item["kind"] == "channel":
            channels.append(item)
        else:
            users.append(item)
    return {"user_id": user_id, "account": {"id": me.id, "username": me.username, "phone_last4": (me.phone or "")[-4:]}, "counts": {"groups": len(groups), "channels": len(channels), "users": len(users), "total": len(groups) + len(channels) + len(users)}, "groups": groups, "channels": channels, "users": users}


@mcp.tool()
async def tg_list_dialogs(ctx: Context, limit: int = 100) -> dict:
    """List dialogs for this user's linked Telegram account in explicit arrays."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    dialogs = []
    async for d in client.iter_dialogs(limit=max(1, min(limit, 500))):
        dialogs.append(_safe_chat_item(d))
    return {"user_id": user_id, "count": len(dialogs), "dialogs": dialogs}


@mcp.tool()
async def tg_get_dialog_details(ctx: Context, chat: str) -> dict:
    """Return metadata for a chat visible to this user's Telegram account."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(chat))
    return {"user_id": user_id, "id": _peer_id(entity), "title": getattr(entity, "title", None), "name": getattr(entity, "first_name", None), "username": getattr(entity, "username", None), "kind": _kind(entity), "is_forum": bool(getattr(entity, "forum", False)), "is_broadcast": bool(getattr(entity, "broadcast", False)), "is_megagroup": bool(getattr(entity, "megagroup", False)), "participants_count": getattr(entity, "participants_count", None)}


@mcp.tool()
async def tg_read_messages(ctx: Context, chat: str, limit: int = 20) -> list[dict]:
    """Read recent messages from a chat visible to this user's account."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(chat))
    out = []
    async for message in client.iter_messages(entity, limit=max(1, min(limit, 100))):
        out.append({"id": message.id, "date": message.date.isoformat() if message.date else None, "sender_id": message.sender_id, "text": message.message, "has_media": message.media is not None})
    return out


@mcp.tool()
async def tg_search_messages(ctx: Context, query: str, chat: Optional[str] = None, limit: int = 20) -> dict:
    """Search messages for this user's account globally or in one chat."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(chat)) if chat else None
    out = []
    async for message in client.iter_messages(entity, search=query, limit=max(1, min(limit, 100))):
        out.append({"id": message.id, "date": message.date.isoformat() if message.date else None, "text": message.message, "has_media": message.media is not None})
    return {"user_id": user_id, "count": len(out), "messages": out}


@mcp.tool()
async def tg_resolve(ctx: Context, target: str) -> dict:
    """Resolve a username, link, or numeric ID using this user's account."""
    user_id = _require_scope(ctx, config.READ_SCOPE)
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(target))
    return {"user_id": user_id, "id": _peer_id(entity), "title": getattr(entity, "title", None), "username": getattr(entity, "username", None), "type": type(entity).__name__, "kind": _kind(entity)}


@mcp.tool()
async def tg_send_message(ctx: Context, chat: str, text: str, confirm: bool = False) -> dict:
    """Send a message from this user's linked account; requires send scope and confirm=true."""
    user_id = _require_scope(ctx, config.SEND_SCOPE)
    if not confirm:
        return {"ok": False, "error": "confirmation required: set confirm=true"}
    if len(text) > 4000:
        return {"ok": False, "error": "text exceeds 4000 characters"}
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(chat))
    message = await client.send_message(entity, text)
    store.audit(user_id, "telegram.send_message", "ok", {"chat": str(chat), "message_id": message.id})
    return {"ok": True, "message_id": message.id, "chat": chat}


@mcp.tool()
async def tg_download_media(ctx: Context, chat: str, message_id: int) -> dict:
    """Download media into a per-user directory."""
    user_id = _require_scope(ctx, config.MEDIA_SCOPE)
    client = await tg.client(user_id)
    entity = await client.get_entity(_coerce(chat))
    message = await client.get_messages(entity, ids=message_id)
    if message is None or message.media is None:
        return {"ok": False, "error": "no media on that message"}
    out_dir = os.path.join(config.DOWNLOAD_ROOT, user_id)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    path = await client.download_media(message, file=out_dir)
    return {"ok": True, "path": path, "user_id": user_id}


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "service": "telegram-mcp-multi-user"})


@mcp.custom_route("/connect/telegram", methods=["GET"], include_in_schema=False)
async def connect_page(request: Request) -> Response:
    token = request.query_params.get("token", "")
    if not store.get_connect_user(token):
        return HTMLResponse("<h1>Link expired</h1><p>Request a new link from Gemini.</p>", status_code=410)
    return HTMLResponse(_page("Connect Telegram", f"""
        <p>This private link belongs to one MCP user. It expires soon.</p>
        <form method='post' action='/connect/telegram/start'>
          <input type='hidden' name='token' value='{html.escape(token)}'>
          <label>Phone number in international format</label>
          <input name='phone' placeholder='+967...' required>
          <button>Send Telegram code</button>
        </form>
    """))


@mcp.custom_route("/connect/telegram/start", methods=["POST"], include_in_schema=False)
async def connect_start(request: Request) -> Response:
    form = await request.form()
    token = str(form.get("token", ""))
    phone = str(form.get("phone", ""))
    user_id = store.get_connect_user(token)
    if not user_id:
        return HTMLResponse("<h1>Link expired</h1>", status_code=410)
    try:
        result = await tg.start_link(user_id, phone)
    except LinkError as exc:
        return HTMLResponse(_page("Telegram link error", f"<p>{html.escape(str(exc))}</p><a href='/connect/telegram?token={html.escape(token)}'>Try again</a>"), status_code=400)
    return HTMLResponse(_page("Enter Telegram code", f"""
        <p>A Telegram code was requested. Enter it here. Do not share it with anyone.</p>
        <form method='post' action='/connect/telegram/code'>
          <input type='hidden' name='token' value='{html.escape(token)}'>
          <input name='code' inputmode='numeric' autocomplete='one-time-code' required>
          <button>Verify code</button>
        </form>
    """))


@mcp.custom_route("/connect/telegram/code", methods=["POST"], include_in_schema=False)
async def connect_code(request: Request) -> Response:
    form = await request.form()
    token = str(form.get("token", ""))
    code = str(form.get("code", ""))
    user_id = store.get_connect_user(token)
    if not user_id:
        return HTMLResponse("<h1>Link expired</h1>", status_code=410)
    try:
        result = await tg.finish_code(user_id, code)
    except LinkError as exc:
        return HTMLResponse(_page("Code error", f"<p>{html.escape(str(exc))}</p><a href='/connect/telegram?token={html.escape(token)}'>Request another code</a>"), status_code=400)
    if result["status"] == "2fa_required":
        return HTMLResponse(_page("Enter Telegram 2FA", f"""
            <p>Telegram requires your two-step verification password. It is submitted only to this service and never returned to Gemini.</p>
            <form method='post' action='/connect/telegram/2fa'>
              <input type='hidden' name='token' value='{html.escape(token)}'>
              <input name='password' type='password' autocomplete='current-password' required>
              <button>Complete link</button>
            </form>
        """))
    return HTMLResponse(_page("Telegram connected", "<p>Your Telegram account is linked. You may close this tab and return to Gemini.</p>"))


@mcp.custom_route("/connect/telegram/2fa", methods=["POST"], include_in_schema=False)
async def connect_2fa(request: Request) -> Response:
    form = await request.form()
    token = str(form.get("token", ""))
    password = str(form.get("password", ""))
    user_id = store.get_connect_user(token)
    if not user_id:
        return HTMLResponse("<h1>Link expired</h1>", status_code=410)
    try:
        await tg.finish_2fa(user_id, password)
    except LinkError as exc:
        return HTMLResponse(_page("2FA error", f"<p>{html.escape(str(exc))}</p>"), status_code=400)
    return HTMLResponse(_page("Telegram connected", "<p>Your Telegram account is linked. You may close this tab and return to Gemini.</p>"))


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>body{{font:16px system-ui;max-width:560px;margin:4rem auto;padding:0 1rem;background:#f7f7f8;color:#161616}}main{{background:white;border:1px solid #ddd;border-radius:16px;padding:2rem;box-shadow:0 8px 30px #0001}}input{{display:block;width:100%;padding:.8rem;margin:.5rem 0 1rem;box-sizing:border-box;border:1px solid #aaa;border-radius:8px}}button{{padding:.8rem 1.2rem;border:0;border-radius:8px;background:#2463eb;color:white;font-weight:600}}</style></head><body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>"""


# Protected resource metadata is mounted by FastMCP automatically when auth is set.
