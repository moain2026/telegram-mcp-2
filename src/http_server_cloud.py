import os
from server import mcp
from mcp.server.fastmcp.server import TransportSecuritySettings

public_host = os.getenv("MCP_PUBLIC_HOST", "surface-purse-jvc-sage.trycloudflare.com")
mcp.settings.host = os.getenv("MCP_HOST", "127.0.0.1")
mcp.settings.port = int(os.getenv("MCP_PORT", "8080"))
mcp.settings.streamable_http_path = "/mcp"
mcp.settings.stateless_http = True
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[public_host],
    allowed_origins=[f"https://{public_host}"],
)

if __name__ == "__main__":
    mcp.run("streamable-http")
