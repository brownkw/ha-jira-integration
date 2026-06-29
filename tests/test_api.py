import sys
sys.path.insert(0, ".")
import base64
import pytest
import aiohttp
from aioresponses import aioresponses
from custom_components.jira_work.api import (
    JiraClient, JiraAuthError, JiraConnectionError, JiraRateLimitError,
)

BASE = "https://example.atlassian.net"


def _client(session):
    return JiraClient(BASE, "me@example.com", "tok123", session)


async def test_auth_header_is_basic():
    async with aiohttp.ClientSession() as s:
        c = _client(s)
        expected = "Basic " + base64.b64encode(b"me@example.com:tok123").decode()
        assert c._auth_header() == expected


async def test_search_paginates():
    page1 = {"startAt": 0, "maxResults": 2, "total": 3,
              "issues": [{"key": "A-1", "fields": {}}, {"key": "A-2", "fields": {}}]}
    page2 = {"startAt": 2, "maxResults": 2, "total": 3,
              "issues": [{"key": "A-3", "fields": {}}]}
    with aioresponses() as m:
        m.post(f"{BASE}/rest/api/3/search", payload=page1)
        m.post(f"{BASE}/rest/api/3/search", payload=page2)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            issues = await c.search("jql", ["summary"])
            assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3"]


async def test_search_401_raises_auth_error():
    with aioresponses() as m:
        m.post(f"{BASE}/rest/api/3/search", status=401)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            with pytest.raises(JiraAuthError):
                await c.search("jql", ["summary"])


async def test_search_429_raises_rate_limit():
    with aioresponses() as m:
        m.post(f"{BASE}/rest/api/3/search", status=429, headers={"Retry-After": "30"})
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            with pytest.raises(JiraRateLimitError) as exc:
                await c.search("jql", ["summary"])
            assert exc.value.retry_after == 30


# ── Task 7: field lookup ──────────────────────────────────────────────────────

async def test_get_priorities():
    priorities = [
        {"id": "1", "name": "Blocker"},
        {"id": "2", "name": "Critical"},
        {"id": "3", "name": "Major"},
        {"id": "4", "name": "Minor"},
        {"id": "5", "name": "Trivial"},
    ]
    with aioresponses() as m:
        m.get(f"{BASE}/rest/api/3/priority", payload=priorities)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            result = await c.get_priorities()
    assert result == ["Blocker", "Critical", "Major", "Minor", "Trivial"]


async def test_get_custom_fields_deduplicates_names():
    fields = [
        {"id": "customfield_10020", "name": "Story Points", "custom": True},
        {"id": "customfield_10031", "name": "Team", "custom": True},
        {"id": "customfield_10099", "name": "Team", "custom": True},   # duplicate name
        {"id": "summary", "name": "Summary", "custom": False},         # built-in, excluded
    ]
    with aioresponses() as m:
        m.get(f"{BASE}/rest/api/3/field", payload=fields)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            result = await c.get_custom_fields()
    assert result["customfield_10020"] == "Story Points"
    assert result["customfield_10031"] == "Team (customfield_10031)"
    assert result["customfield_10099"] == "Team (customfield_10099)"
    assert "summary" not in result
