"""Jira Cloud API client. No Home Assistant imports."""
from __future__ import annotations

import base64
from typing import Any

import aiohttp

from .const import SCOPED_API_BASE, TOKEN_TYPE_SCOPED


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
    def __init__(
        self,
        url: str,
        email: str,
        token: str,
        session: aiohttp.ClientSession,
        token_type: str = "classic",
        cloud_id: str | None = None,
    ):
        self._instance_url = url.rstrip("/")
        self._email = email
        self._token = token
        self._session = session
        self._token_type = token_type
        # For scoped tokens: use gateway base URL if cloud_id already known;
        # otherwise resolve_cloud_id() must be called before any API calls.
        if token_type == TOKEN_TYPE_SCOPED and cloud_id:
            self._base_url = f"{SCOPED_API_BASE}/{cloud_id}"
        else:
            self._base_url = self._instance_url

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

    async def get_priorities(self) -> list[str]:
        """Return priority names in server order."""
        try:
            async with self._session.get(
                f"{self._base_url}/rest/api/3/priority", headers=self._headers()
            ) as resp:
                await self._raise_for_status(resp)
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise JiraConnectionError(str(err)) from err
        return [p["name"] for p in data]

    async def get_custom_fields(self) -> dict[str, str]:
        """Return {customfield_id: display_label} for all custom fields.

        Duplicate names are disambiguated by appending the field ID in parens.
        Built-in (non-custom) fields are excluded.
        """
        try:
            async with self._session.get(
                f"{self._base_url}/rest/api/3/field", headers=self._headers()
            ) as resp:
                await self._raise_for_status(resp)
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise JiraConnectionError(str(err)) from err

        # Only custom fields
        custom = [f for f in data if f.get("custom")]

        # Count name occurrences to detect duplicates
        from collections import Counter
        name_count = Counter(f["name"] for f in custom)

        result: dict[str, str] = {}
        for field in custom:
            fid = field["id"]
            name = field["name"]
            label = f"{name} ({fid})" if name_count[name] > 1 else name
            result[fid] = label
        return result

    async def search(
        self, jql: str, fields: list[str], page_size: int = 100
    ) -> list[dict[str, Any]]:
        """Run a JQL search using the current /rest/api/3/search/jql endpoint.

        The legacy /rest/api/3/search endpoint was removed in August 2025
        (CHANGE-2046). The new endpoint uses nextPageToken-based pagination
        instead of startAt/total.
        """
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            body: dict[str, Any] = {
                "jql": jql,
                "fields": fields,
                "maxResults": page_size,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token
            try:
                async with self._session.post(
                    f"{self._base_url}/rest/api/3/search/jql",
                    headers=self._headers(),
                    json=body,
                ) as resp:
                    await self._raise_for_status(resp)
                    data = await resp.json()
            except aiohttp.ClientError as err:
                raise JiraConnectionError(str(err)) from err
            batch = data.get("issues", [])
            issues.extend(batch)
            next_page_token = data.get("nextPageToken")
            if not batch or not next_page_token:
                break
        return issues
