import sys
sys.path.insert(0, ".")
import base64
import pytest
import aiohttp
from aioresponses import aioresponses
from custom_components.jira_work.api import (
    JiraClient, JiraAuthError, JiraConnectionError, JiraRateLimitError,
)
from custom_components.jira_work.const import (
    SCOPED_API_BASE, TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED,
)

BASE = "https://example.atlassian.net"
CLOUD_ID = "test-cloud-id-abc"
SCOPED_BASE = f"{SCOPED_API_BASE}/{CLOUD_ID}"


def _client(session):
    return JiraClient(BASE, "me@example.com", "tok123", session)


def _scoped_client(session, cloud_id=None):
    return JiraClient(
        BASE, "me@example.com", "tok123", session,
        token_type=TOKEN_TYPE_SCOPED,
        cloud_id=cloud_id,
    )


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


async def test_scoped_client_uses_gateway_url_when_cloud_id_known():
    """When cloud_id is passed at construction, _base_url uses the gateway immediately."""
    async with aiohttp.ClientSession() as s:
        c = _scoped_client(s, cloud_id=CLOUD_ID)
        assert c._base_url == SCOPED_BASE
        assert c._instance_url == BASE


async def test_scoped_client_without_cloud_id_falls_back_to_instance_url():
    """Without a cloud_id, scoped client starts at instance URL until resolve_cloud_id() is called."""
    async with aiohttp.ClientSession() as s:
        c = _scoped_client(s, cloud_id=None)
        assert c._base_url == BASE


async def test_resolve_cloud_id_sets_base_url():
    """resolve_cloud_id() fetches tenant_info and updates _base_url to the gateway URL."""
    tenant_info = {"cloudId": CLOUD_ID, "displayName": "Test Site"}
    with aioresponses() as m:
        m.get(f"{BASE}/_edge/tenant_info", payload=tenant_info)
        async with aiohttp.ClientSession() as s:
            c = _scoped_client(s, cloud_id=None)
            returned_id = await c.resolve_cloud_id()
    assert returned_id == CLOUD_ID
    assert c._base_url == SCOPED_BASE


async def test_resolve_cloud_id_raises_on_http_error():
    """resolve_cloud_id() raises JiraConnectionError if tenant_info returns non-200."""
    with aioresponses() as m:
        m.get(f"{BASE}/_edge/tenant_info", status=404)
        async with aiohttp.ClientSession() as s:
            c = _scoped_client(s, cloud_id=None)
            with pytest.raises(JiraConnectionError):
                await c.resolve_cloud_id()


async def test_scoped_client_search_uses_gateway_url():
    """After cloud_id is known, search() POSTs to the gateway URL, not the instance URL."""
    page = {"startAt": 0, "maxResults": 50, "total": 1,
            "issues": [{"key": "A-1", "fields": {}}]}
    with aioresponses() as m:
        m.post(f"{SCOPED_BASE}/rest/api/3/search", payload=page)
        async with aiohttp.ClientSession() as s:
            c = _scoped_client(s, cloud_id=CLOUD_ID)
            issues = await c.search("jql", ["summary"])
    assert len(issues) == 1


async def test_classic_client_search_uses_instance_url():
    """Classic client continues to use the instance URL unchanged."""
    page = {"startAt": 0, "maxResults": 50, "total": 1,
            "issues": [{"key": "B-1", "fields": {}}]}
    with aioresponses() as m:
        m.post(f"{BASE}/rest/api/3/search", payload=page)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            issues = await c.search("jql", ["summary"])
    assert len(issues) == 1


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
