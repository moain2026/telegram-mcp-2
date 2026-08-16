"""Minimal OAuth provider for the multi-user MCP MVP.

The authorization screen uses an invite code to establish a service user. In a
production deployment replace the invite-code screen with the organization's
OIDC/SSO provider; the MCP token and tenant/session binding remain the same.
"""
from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

import multi_config as config
from multi_store import Store, now


class MultiUserOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, store: Store):
        self.store = store
        self.allowed_scopes = config.ALL_SCOPES
        self.registration_options = ClientRegistrationOptions(
            enabled=True,
            valid_scopes=self.allowed_scopes,
            default_scopes=[config.READ_SCOPE],
            client_secret_expiry_seconds=30 * 24 * 3600,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.get_client(client_id)
        if not row:
            return None
        data = row["metadata"]
        data.update({"client_id": row["client_id"], "client_secret": row["client_secret"]})
        return OAuthClientInformationFull.model_validate(data)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id or not client_info.redirect_uris:
            raise AuthorizeError(error="invalid_request", error_description="client_id and redirect_uris are required")
        self.store.save_client(
            client_info.client_id,
            client_info.client_secret,
            client_info.model_dump(mode="json", exclude={"client_id", "client_secret"}),
        )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        requested = params.scopes or [config.READ_SCOPE]
        invalid = [scope for scope in requested if scope not in self.allowed_scopes]
        if invalid:
            raise AuthorizeError(error="invalid_scope", error_description="unsupported scopes: " + ", ".join(invalid))
        tx = secrets.token_urlsafe(32)
        self.store.save_oauth_transaction(
            tx,
            {
                "client_id": client.client_id,
                "state": params.state,
                "scopes": requested,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "resource": params.resource,
            },
            now() + 600,
        )
        return f"{config.PUBLIC_BASE_URL}/oauth/consent?{urlencode({'tx': tx})}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        payload = self.store.load_oauth_code(authorization_code)
        if not payload or payload.get("client_id") != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=payload["scopes"],
            expires_at=payload["expires_at"],
            client_id=payload["client_id"],
            code_challenge=payload["code_challenge"],
            redirect_uri=AnyUrl(payload["redirect_uri"]),
            redirect_uri_provided_explicitly=payload["redirect_uri_provided_explicitly"],
            resource=payload.get("resource"),
            subject=payload.get("subject"),
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        payload = self.store.load_oauth_code(authorization_code.code, consume=True)
        if not payload or not payload.get("subject"):
            raise TokenError(error="invalid_grant", error_description="authorization code is invalid or already used")
        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)
        access_exp = now() + 3600
        refresh_exp = now() + 30 * 24 * 3600
        self.store.save_access_token(access_token, payload["subject"], client.client_id or "", payload["scopes"], access_exp)
        self.store.save_refresh_token(refresh_token, payload["subject"], client.client_id or "", payload["scopes"], refresh_exp)
        return OAuthToken(access_token=access_token, refresh_token=refresh_token, expires_in=3600, scope=" ".join(payload["scopes"]))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        payload = self.store.get_refresh_token(refresh_token)
        if not payload or payload["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=payload["client_id"], scopes=payload["scopes"], expires_at=payload["expires_at"], subject=payload["subject"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        payload = self.store.get_refresh_token(refresh_token.token)
        if not payload or payload["client_id"] != client.client_id:
            raise TokenError(error="invalid_grant", error_description="refresh token is invalid")
        access = secrets.token_urlsafe(48)
        rotated = secrets.token_urlsafe(48)
        self.store.revoke_refresh_token(refresh_token.token)
        self.store.save_access_token(access, payload["subject"], client.client_id or "", scopes, now() + 3600)
        self.store.save_refresh_token(rotated, payload["subject"], client.client_id or "", scopes, now() + 30 * 24 * 3600)
        return OAuthToken(access_token=access, refresh_token=rotated, expires_in=3600, scope=" ".join(scopes))

    async def load_access_token(self, token: str) -> AccessToken | None:
        payload = self.store.get_access_token(token)
        if not payload:
            return None
        return AccessToken(
            token=token,
            client_id=payload["client_id"],
            scopes=payload["scopes"],
            expires_at=payload["expires_at"],
            subject=payload["subject"],
            resource=config.PUBLIC_BASE_URL + config.MCP_PATH,
            claims={"sub": payload["subject"]},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.store.revoke_access_token(token.token)
        else:
            self.store.revoke_refresh_token(token.token)

    def complete_consent(self, tx: str, invite_code: str) -> str:
        payload = self.store.load_oauth_transaction(tx, consume=True)
        if not payload:
            raise ValueError("authorization request expired")
        user_id = config.invite_codes().get(invite_code)
        if not user_id:
            raise ValueError("invalid invite code")
        self.store.ensure_user(user_id, user_id)
        code = secrets.token_urlsafe(32)
        payload["subject"] = user_id
        payload["expires_at"] = now() + 120
        self.store.save_oauth_code(code, payload, payload["expires_at"])
        params = {"code": code}
        if payload.get("state"):
            params["state"] = payload["state"]
        return construct_redirect_uri(payload["redirect_uri"], **params)
