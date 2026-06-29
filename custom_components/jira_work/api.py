"""Jira Cloud API client. No Home Assistant imports."""
from __future__ import annotations

import base64
from typing import Any

import aiohttp


class JiraError(Exception):
    """Base error."""


class JiraAuthError(JiraError):
    """401/403 from Jira."""


class JiraConnectionError(JiraError):
    """Network/5xx error."""


class JiraRateLimitError(JiraError):
    """429 with optional Retry-After."""

    def __init__(self, retry_after: int | None = None):
        super().__init__("rate limited")
        self.retry_after = retry_after


class JiraClient:
    def __init__(self, url: str, email: str, token: str, session: aiohttp.ClientSession):
        self._url = url.rstrip("/")
        self._email = email
        self._token = token
        self._session = session

    def _auth_header(self) -> str:
        raw = f"{self._email}:{self._token}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _raise_for_status(self, resp: aiohttp.ClientResponse) -> None:
        if resp.status in (401, 403):
            raise JiraAuthError(f"auth failed: {resp.status}")
        if resp.status == 429:
            ra = resp.headers.get("Retry-After")
            raise JiraRateLimitError(int(ra) if ra and ra.isdigit() else None)
        if resp.status >= 400:
            raise JiraConnectionError(f"HTTP {resp.status}")

    async def search(
        self, jql: str, fields: list[str], page_size: int = 100
    ) -> list[dict[str, Any]]:
        """Run a JQL search, following pagination."""
        issues: list[dict[str, Any]] = []
        start_at = 0
        while True:
            body = {
                "jql": jql,
                "fields": fields,
                "startAt": start_at,
                "maxResults": page_size,
            }
            try:
                async with self._session.post(
                    f"{self._url}/rest/api/3/search",
                    headers=self._headers(),
                    json=body,
                ) as resp:
                    await self._raise_for_status(resp)
                    data = await resp.json()
            except aiohttp.ClientError as err:
                raise JiraConnectionError(str(err)) from err
            batch = data.get("issues", [])
            issues.extend(batch)
            total = data.get("total", len(issues))
            start_at += len(batch)
            if not batch or start_at >= total:
                break
        return issues
