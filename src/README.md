# telegram-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes a **Telegram user
account** (via [Telethon](https://docs.telethon.dev) / MTProto) as a clean set of
tools any MCP-capable agent can call.

Built for the Al-Abbasi environment. Uses a **user account** (not a bot), so it
bypasses the 20 MB bot upload limit and can read/send as the account itself.

## Tools

| Tool | Description |
|------|-------------|
| `tg_status` | Connected account + session health |
| `tg_list_dialogs` | Recent chats / groups / channels |
| `tg_read_messages` | Read recent messages from a chat |
| `tg_send_message` | Send a text message (safety-gated) |
| `tg_download_media` | Download media from a message (handles >20 MB) |
| `tg_resolve` | Resolve a username / link / id to an entity |

**Safety:** destructive account operations (delete account, change/reset
password) are hard-blocked in `client.py` and can never be invoked.

## Setup

```bash
git clone https://github.com/moain2026/telegram-mcp.git
cd telegram-mcp
pip install -r requirements.txt
cp .env.example .env        # then fill in your values
```

### Get a session string

You need `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` from
https://my.telegram.org. Then:

```bash
python login.py             # enter phone code (+ 2FA if set)
# copy the printed TELEGRAM_STRING_SESSION into .env
```

The string session keeps you logged in without fragile `.session` files.

## Run

```bash
python server.py            # stdio MCP server
```

### Register with an MCP client (example)

```json
{
  "mcpServers": {
    "telegram": {
      "command": "python",
      "args": ["/path/to/telegram-mcp/server.py"]
    }
  }
}
```

## Security notes

- `.env`, `*.session`, `*.vault`, and the session string are git-ignored — **never** commit them.
- The session string grants full account access. Treat it like a password.
- Rate-limit your sends to avoid Telegram flood bans.

## License

Proprietary — Al-Abbasi Soft.
