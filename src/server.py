"""telegram-mcp — MCP tools for a Telegram user account.

The server exposes read, media, group/forum, and carefully gated moderation tools.
"""
from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP
from telethon import functions, utils as telethon_utils
from telethon.tl.types import Channel, Chat

from client import tg
import config

mcp = FastMCP("telegram-mcp")


def _kind(entity) -> str:
    """Return a user-facing kind instead of Telethon's shared Channel type."""
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


@mcp.tool()
async def tg_status() -> dict:
    """Return the connected account and session status."""
    c = await tg.client()
    me = await c.get_me()
    return {"ok": True, "id": me.id, "first_name": me.first_name, "username": me.username, "phone": me.phone}


@mcp.tool()
async def tg_list_dialogs(limit: int = 100) -> dict:
    """List dialogs in a named array with an explicit count for reliable client parsing."""
    c = await tg.client()
    dialogs = []
    async for d in c.iter_dialogs(limit=limit):
        entity = d.entity
        dialogs.append({
            "name": d.name,
            "id": d.id,
            "kind": _kind(entity),
            "is_forum": bool(getattr(entity, "forum", False)),
            "is_broadcast": bool(getattr(entity, "broadcast", False)),
            "is_megagroup": bool(getattr(entity, "megagroup", False)),
            "unread": d.unread_count,
        })
    return {"count": len(dialogs), "dialogs": dialogs}


@mcp.tool()
async def tg_account_overview(limit: int = 200) -> dict:
    """Return one read-only account summary with counts and grouped dialogs."""
    c = await tg.client()
    me = await c.get_me()
    groups, channels, users = [], [], []
    async for d in c.iter_dialogs(limit=limit):
        entity = d.entity
        item = {
            "name": d.name,
            "id": d.id,
            "kind": _kind(entity),
            "is_forum": bool(getattr(entity, "forum", False)),
            "is_broadcast": bool(getattr(entity, "broadcast", False)),
            "is_megagroup": bool(getattr(entity, "megagroup", False)),
            "unread": d.unread_count,
        }
        if item["kind"] == "group":
            groups.append(item)
        elif item["kind"] == "channel":
            channels.append(item)
        else:
            users.append(item)
    return {
        "account": {"id": me.id, "username": me.username, "phone": me.phone},
        "counts": {"groups": len(groups), "channels": len(channels), "users": len(users), "total": len(groups) + len(channels) + len(users)},
        "groups": groups,
        "channels": channels,
        "users": users,
    }


@mcp.tool()
async def tg_get_dialog_details(chat: str) -> dict:
    """Return detailed metadata for a user, group, supergroup, or channel."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    return {
        "id": _peer_id(entity),
        "title": getattr(entity, "title", None),
        "name": getattr(entity, "first_name", None),
        "username": getattr(entity, "username", None),
        "kind": _kind(entity),
        "is_forum": bool(getattr(entity, "forum", False)),
        "is_broadcast": bool(getattr(entity, "broadcast", False)),
        "is_megagroup": bool(getattr(entity, "megagroup", False)),
        "participants_count": getattr(entity, "participants_count", None),
    }


@mcp.tool()
async def tg_read_messages(chat: str, limit: int = 20) -> list[dict]:
    """Read recent messages from a chat."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    out = []
    async for m in c.iter_messages(entity, limit=limit):
        out.append({"id": m.id, "date": m.date.isoformat() if m.date else None, "sender_id": m.sender_id, "text": m.message, "has_media": m.media is not None})
    return out


@mcp.tool()
async def tg_search_messages(query: str, chat: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Search messages by text globally or inside one chat."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat)) if chat else None
    out = []
    async for m in c.iter_messages(entity, search=query, limit=limit):
        out.append({"id": m.id, "chat_id": getattr(m, "peer_id", None).channel_id if getattr(getattr(m, "peer_id", None), "channel_id", None) else None, "date": m.date.isoformat() if m.date else None, "text": m.message, "has_media": m.media is not None})
    return {"count": len(out), "messages": out}


@mcp.tool()
async def tg_send_message(chat: str, text: str) -> dict:
    """Send a text message to a chat. This performs an external action."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    msg = await c.send_message(entity, text)
    return {"ok": True, "message_id": msg.id, "chat": chat}


@mcp.tool()
async def tg_send_file(chat: str, file_path: str, caption: Optional[str] = None, reply_to: Optional[int] = None) -> dict:
    """Upload a local file to a chat. This performs an external action."""
    if not os.path.isfile(file_path):
        return {"ok": False, "error": "file not found", "path": file_path}
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    msg = await c.send_file(entity, file_path, caption=caption, reply_to=reply_to)
    return {"ok": True, "message_id": msg.id, "chat": chat, "path": file_path}


@mcp.tool()
async def tg_download_media(chat: str, message_id: int, out_dir: Optional[str] = None) -> dict:
    """Download media from a message, including large files."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    msg = await c.get_messages(entity, ids=message_id)
    if msg is None or msg.media is None:
        return {"ok": False, "error": "no media on that message"}
    target = out_dir or config.DOWNLOAD_DIR
    os.makedirs(target, exist_ok=True)
    path = await c.download_media(msg, file=target)
    size = os.path.getsize(path) if path and os.path.exists(path) else 0
    return {"ok": True, "path": path, "bytes": size}


@mcp.tool()
async def tg_resolve(target: str) -> dict:
    """Resolve a username, link, or numeric id to entity metadata."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(target))
    return {"id": _peer_id(entity), "title": getattr(entity, "title", None), "username": getattr(entity, "username", None), "type": type(entity).__name__, "kind": _kind(entity)}


@mcp.tool()
async def tg_create_group(title: str, about: str = "", forum: bool = False) -> dict:
    """Create a Telegram supergroup; optionally enable forum topics."""
    c = await tg.client()
    result = await c(functions.channels.CreateChannelRequest(title=title, about=about, megagroup=True, forum=forum))
    entity = next((x for x in getattr(result, "chats", []) if isinstance(x, Channel)), None)
    if entity is None:
        return {"ok": False, "error": "Telegram did not return the created group"}
    return {"ok": True, "id": _peer_id(entity), "title": getattr(entity, "title", title), "kind": "group", "is_forum": bool(getattr(entity, "forum", forum))}


@mcp.tool()
async def tg_create_forum_topic(chat: str, title: str, icon_color: Optional[int] = None, icon_emoji_id: Optional[int] = None) -> dict:
    """Create a topic in a forum supergroup."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    if not getattr(entity, "megagroup", False) or not getattr(entity, "forum", False):
        return {"ok": False, "error": "chat is not a forum supergroup"}
    peer = await c.get_input_entity(entity)
    await c(functions.messages.CreateForumTopicRequest(peer=peer, title=title, icon_color=icon_color, icon_emoji_id=icon_emoji_id))
    return {"ok": True, "chat": _peer_id(entity), "title": title}


@mcp.tool()
async def tg_list_members(chat: str, limit: int = 100) -> list[dict]:
    """List members of a group or channel up to the requested limit."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    out = []
    async for user in c.iter_participants(entity, limit=limit):
        out.append({"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "username": user.username, "bot": bool(user.bot)})
    return out


@mcp.tool()
async def tg_edit_message(chat: str, message_id: int, text: str) -> dict:
    """Edit a message sent by the connected account."""
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    msg = await c.edit_message(entity, message_id, text)
    return {"ok": bool(msg), "message_id": message_id, "chat": chat}


@mcp.tool()
async def tg_pin_message(chat: str, message_id: int, notify: bool = False, confirm: bool = False) -> dict:
    """Pin a message. Requires confirm=true because it changes chat state."""
    if not confirm:
        return {"ok": False, "error": "confirmation required: set confirm=true"}
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    await c.pin_message(entity, message_id, notify=notify)
    return {"ok": True, "chat": chat, "message_id": message_id}


@mcp.tool()
async def tg_delete_message(chat: str, message_id: int, revoke: bool = True, confirm: bool = False) -> dict:
    """Delete a message. Requires confirm=true because deletion is destructive."""
    if not confirm:
        return {"ok": False, "error": "confirmation required: set confirm=true"}
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    await c.delete_messages(entity, [message_id], revoke=revoke)
    return {"ok": True, "chat": chat, "message_id": message_id}


@mcp.tool()
async def tg_add_member(chat: str, user: str, confirm: bool = False) -> dict:
    """Add one member to a group or channel. Requires explicit confirmation."""
    if not confirm:
        return {"ok": False, "error": "confirmation required: set confirm=true"}
    c = await tg.client()
    entity = await c.get_entity(_coerce(chat))
    member = await c.get_input_entity(_coerce(user))
    if isinstance(entity, Channel):
        await c(functions.channels.InviteToChannelRequest(channel=entity, users=[member]))
    elif isinstance(entity, Chat):
        await c(functions.messages.AddChatUserRequest(chat_id=entity.id, user_id=member, fwd_limit=0))
    else:
        return {"ok": False, "error": "target is not a group or channel"}
    return {"ok": True, "chat": chat, "user": user}


def _coerce(chat: str):
    s = str(chat).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    return s


if __name__ == "__main__":
    mcp.run()
