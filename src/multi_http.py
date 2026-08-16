"""Run the multi-user Telegram MCP over Streamable HTTP."""
from __future__ import annotations

import multi_server


if __name__ == "__main__":
    multi_server.mcp.run(transport="streamable-http")
