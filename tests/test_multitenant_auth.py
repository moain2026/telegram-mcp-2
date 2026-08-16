from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


def _setup(tmp_path: Path):
    os.environ["TELEGRAM_API_ID"] = "123456"
    os.environ["TELEGRAM_API_HASH"] = "hash"
    os.environ["MCP_SESSION_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["MCP_INVITE_CODES"] = json.dumps({"invite-a": "user-a"})
    os.environ["MCP_DB_PATH"] = str(tmp_path / "db.sqlite3")
    os.environ["MCP_PUBLIC_BASE_URL"] = "http://localhost:8080"
    import multi_config
    importlib.reload(multi_config)
    from multi_store import Store
    from multi_auth import MultiUserOAuthProvider
    return Store(), MultiUserOAuthProvider(Store())


def test_oauth_pkce_subject_binding(tmp_path: Path):
    store, provider = _setup(tmp_path)
    client = OAuthClientInformationFull(
        client_id="client-1",
        client_secret=None,
        redirect_uris=["https://client.example/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="telegram:read",
        client_name="test-client",
    )
    import asyncio
    asyncio.run(provider.register_client(client))
    verifier = "test-verifier-123"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = AuthorizationParams(
        state="state-1",
        scopes=["telegram:read"],
        code_challenge=challenge,
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=True,
        resource="http://localhost:8080/mcp",
    )
    url = asyncio.run(provider.authorize(client, params))
    tx = parse_qs(urlparse(url).query)["tx"][0]
    redirect = provider.complete_consent(tx, "invite-a")
    code = parse_qs(urlparse(redirect).query)["code"][0]
    auth_code = asyncio.run(provider.load_authorization_code(client, code))
    assert auth_code is not None
    assert auth_code.subject == "user-a"
    token = asyncio.run(provider.exchange_authorization_code(client, auth_code))
    access = asyncio.run(provider.load_access_token(token.access_token))
    assert access is not None
    assert access.subject == "user-a"
    assert access.scopes == ["telegram:read"]


def test_multi_server_exposes_scoped_tools(tmp_path: Path):
    _setup(tmp_path)
    import asyncio
    import importlib
    import multi_server
    importlib.reload(multi_server)
    tools = asyncio.run(multi_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {"tg_connect_telegram", "tg_connection_status", "tg_account_overview", "tg_list_dialogs"}.issubset(names)
