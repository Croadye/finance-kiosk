"""Dropbox API helpers for OAuth, file discovery, downloads, and webhook validation."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable

import httpx

DROPBOX_API = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT = "https://content.dropboxapi.com/2"


@dataclass(slots=True)
class DropboxSettings:
    """Minimal configuration required to talk to Dropbox."""

    app_key: str
    app_secret: str
    redirect_uri: str | None = None
    refresh_token: str | None = None
    access_token: str | None = None

    @classmethod
    def from_env(cls) -> "DropboxSettings | None":
        key = os.getenv("DROPBOX_APP_KEY")
        secret = os.getenv("DROPBOX_APP_SECRET")
        if not key or not secret:
            return None
        return cls(
            app_key=key,
            app_secret=secret,
            redirect_uri=os.getenv("DROPBOX_REDIRECT_URI"),
            refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN"),
            access_token=os.getenv("DROPBOX_ACCESS_TOKEN"),
        )


class DropboxError(RuntimeError):
    pass


class DropboxClient:
    """Lightweight async Dropbox API client."""

    def __init__(self, settings: DropboxSettings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                       json: Any | None = None, data: Any | None = None) -> httpx.Response:
        token = self.settings.access_token
        if not token:
            raise DropboxError(
                "Dropbox access token missing. Provide DROPBOX_ACCESS_TOKEN.")
        auth_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            auth_headers.update(headers)
        resp = await self._client.request(method, url, headers=auth_headers, json=json, data=data)
        if resp.status_code >= 400:
            raise DropboxError(
                f"Dropbox API error {resp.status_code}: {resp.text}")
        return resp

    async def exchange_code(self, code: str) -> dict[str, Any]:
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": self.settings.app_key,
            "client_secret": self.settings.app_secret,
        }
        if self.settings.redirect_uri:
            data["redirect_uri"] = self.settings.redirect_uri
        resp = await self._client.post("https://api.dropboxapi.com/oauth2/token", data=data)
        if resp.status_code >= 400:
            raise DropboxError(f"OAuth exchange failed: {resp.text}")
        payload = resp.json()
        self.settings.access_token = payload.get(
            "access_token", self.settings.access_token)
        self.settings.refresh_token = payload.get(
            "refresh_token", self.settings.refresh_token)
        return payload

    async def refresh_access_token(self) -> dict[str, Any]:
        if not self.settings.refresh_token:
            raise DropboxError("Cannot refresh without refresh token")
        data = {
            "refresh_token": self.settings.refresh_token,
            "grant_type": "refresh_token",
            "client_id": self.settings.app_key,
            "client_secret": self.settings.app_secret,
        }
        resp = await self._client.post("https://api.dropboxapi.com/oauth2/token", data=data)
        if resp.status_code >= 400:
            raise DropboxError(f"OAuth refresh failed: {resp.text}")
        payload = resp.json()
        self.settings.access_token = payload.get(
            "access_token", self.settings.access_token)
        return payload

    def authorize_url(self, state: str | None = None) -> str:
        params = {
            "client_id": self.settings.app_key,
            "response_type": "code",
        }
        if self.settings.redirect_uri:
            params["redirect_uri"] = self.settings.redirect_uri
        if state:
            params["state"] = state
        query = str(httpx.QueryParams(params))
        return f"https://www.dropbox.com/oauth2/authorize?{query}"

    async def list_folder(self, path: str, *, cursor: str | None = None,
                          recursive: bool = False) -> tuple[list[dict[str, Any]], str | None]:
        """Return (entries, cursor)."""
        entries: list[dict[str, Any]] = []
        if cursor:
            url = f"{DROPBOX_API}/files/list_folder/continue"
            payload: dict[str, Any] = {"cursor": cursor}
        else:
            url = f"{DROPBOX_API}/files/list_folder"
            payload = {"path": path, "recursive": recursive}
        while True:
            resp = await self._request("POST", url, json=payload)
            data = resp.json()
            entries.extend(data.get("entries", []))
            if data.get("has_more"):
                payload = {"cursor": data["cursor"]}
                url = f"{DROPBOX_API}/files/list_folder/continue"
                continue
            return entries, data.get("cursor")

    async def download_file(self, path: str) -> tuple[bytes, dict[str, Any]]:
        headers = {"Dropbox-API-Arg": json.dumps({"path": path})}
        resp = await self._request("POST", f"{DROPBOX_CONTENT}/files/download", headers=headers)
        metadata_header = resp.headers.get("Dropbox-Api-Result")
        metadata: dict[str, Any] = {}
        if metadata_header:
            metadata = json.loads(metadata_header)
        return resp.content, metadata

    async def download_and_iterate(self, entries: Iterable[dict[str, Any]]) -> AsyncIterator[tuple[dict[str, Any], bytes]]:
        for entry in entries:
            if entry.get(".tag") != "file":
                continue
            content, _ = await self.download_file(entry["path_lower"])
            yield entry, content


def verify_webhook_signature(body: bytes, signature: str | None, *, app_secret: str) -> bool:
    if not signature:
        return False
    calc = hmac.new(app_secret.encode("utf-8"),
                    body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)


@asynccontextmanager
async def dropbox_client_from_env() -> AsyncIterator[DropboxClient]:
    settings = DropboxSettings.from_env()
    if not settings:
        raise DropboxError("Dropbox environment variables missing")
    client = DropboxClient(settings)
    try:
        yield client
    finally:
        await client.close()
