# HA Jira Work Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Home Assistant custom integration that surfaces open, assigned Jira Cloud work as sensors, aggregated by project / type / status / priority, with alertable derived sensors and user-configurable custom fields.

**Architecture:** A four-layer integration. An HA-free "Jira brain" (`api.py` client + `aggregator.py` pure functions) is wrapped by an HA `DataUpdateCoordinator`, which feeds read-only sensor entities. Config and changeable custom-field selection are handled by a config flow + options flow. State for "newly assigned" sensors is persisted via HA's `Store` helper.

**Tech Stack:** Python 3.13, Home Assistant custom component, `aiohttp` (provided by HA), `pytest` + `pytest-asyncio` + `freezegun` for tests. Jira Cloud REST API v3 (`/rest/api/3/search`, `/rest/api/3/field`), HTTP Basic auth (`email:token`).

---

## File Structure

Integration package (`custom_components/jira_work/`):
- `__init__.py` — entry setup/unload, instantiate client + coordinator, forward sensor platform, register options-update + shutdown listeners.
- `const.py` — domain, defaults, config/option keys, JQL constant.
- `api.py` — `JiraClient`: auth, paginated `search`, `/field` lookup. No HA imports.
- `aggregator.py` — pure functions: `aggregate()`, custom-field normalization, date math. No HA imports.
- `coordinator.py` — `JiraDataUpdateCoordinator`: poll → aggregate → store; newly-assigned set-diff + rolling window; persistence.
- `config_flow.py` — `ConfigFlow` (setup + reauth) and `OptionsFlowHandler`.
- `sensor.py` — entity classes for the 6 sensors.
- `manifest.json`, `strings.json` — HA metadata + UI strings.

Repo root (Tier 1 HACS readiness):
- `hacs.json`, `README.md`, `LICENSE`, `requirements_test.txt`.

Tests (`tests/`):
- `conftest.py`, `fixtures/` (sample Jira JSON), `test_api.py`, `test_aggregator.py`, `test_coordinator.py`, `test_config_flow.py`.

---

## Task 1: Project scaffolding & test tooling

**Files:**
- Create: `custom_components/jira_work/__init__.py` (empty placeholder for now)
- Create: `requirements_test.txt`
- Create: `tests/__init__.py` (empty)
- Create: `pytest.ini`

- [ ] **Step 1: Create the package directory and placeholder**

Run:
```bash
mkdir -p custom_components/jira_work tests/fixtures
touch custom_components/jira_work/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements_test.txt`**

```
pytest==8.2.0
pytest-asyncio==0.23.7
freezegun==1.5.1
aioresponses==0.7.6
```

- [ ] **Step 3: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: Create and populate a virtualenv**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
```
Expected: installs without error.

- [ ] **Step 5: Verify pytest runs (no tests yet)**

Run: `.venv/bin/pytest -q`
Expected: "no tests ran" (exit code 5) — confirms tooling works.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold package and test tooling"
```

## Task 2: Constants

**Files:**
- Create: `custom_components/jira_work/const.py`

- [ ] **Step 1: Write `const.py`**

```python
"""Constants for the Jira Work integration."""

DOMAIN = "jira_work"

# Config entry keys
CONF_URL = "url"
CONF_EMAIL = "email"
CONF_TOKEN = "token"

# Options keys
OPT_CUSTOM_FIELDS = "custom_fields"      # list[str] of customfield IDs
OPT_POLL_INTERVAL = "poll_interval"      # minutes
OPT_DUE_WITHIN_DAYS = "due_within_days"
OPT_CHECKPOINT_EVERY = "checkpoint_every"  # number of polls

# Defaults
DEFAULT_POLL_INTERVAL = 5
DEFAULT_DUE_WITHIN_DAYS = 3
DEFAULT_CHECKPOINT_EVERY = 12  # 12 * 5min = hourly

# Options keys (continued)
OPT_HIGH_PRIORITY_NAMES = "high_priority_names"  # list[str] of priority names

# Defaults
DEFAULT_HIGH_PRIORITY_NAMES = ["Blocker", "Critical"]

# Core Jira fields always requested
CORE_FIELDS = ["summary", "status", "issuetype", "priority", "duedate", "project", "updated"]

# JQL for open assigned work
JQL_OPEN_ASSIGNED = "assignee = currentUser() AND statusCategory != Done ORDER BY duedate ASC"

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_state"

# Rolling window for the "new in last 24h" sensor
ROLLING_WINDOW_HOURS = 24
```

- [ ] **Step 2: Verify it imports**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from custom_components.jira_work import const; print(const.DOMAIN, const.DEFAULT_HIGH_PRIORITY_NAMES)"`
Expected: prints `jira_work ['Blocker', 'Critical']`

- [ ] **Step 3: Commit**

```bash
git add custom_components/jira_work/const.py
git commit -m "feat: add constants module"
```

## Task 3: Aggregator — pivots & core counts (pure, HA-free)

**Files:**
- Create: `custom_components/jira_work/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: Write the failing test for pivots and total**

```python
import sys
sys.path.insert(0, ".")
from custom_components.jira_work.aggregator import aggregate

def _issue(key, project, itype, status, priority=None, duedate=None, updated=None, fields=None):
    f = {
        "project": {"key": project},
        "issuetype": {"name": itype},
        "status": {"name": status},
        "priority": {"name": priority} if priority else None,
        "duedate": duedate,
        "updated": updated,
    }
    if fields:
        f.update(fields)
    return {"key": key, "fields": f}

def test_total_and_pivots():
    issues = [
        _issue("NOVA-1", "NOVA", "Bug", "To Do", "High"),
        _issue("NOVA-2", "NOVA", "Story", "In Progress", "Medium"),
        _issue("ISOS-1", "ISOS", "Migration", "To Do", "Medium"),
    ]
    result = aggregate(issues, custom_field_ids=[], due_within_days=3, now=None)
    assert result["total"] == 3
    assert result["by_project"] == {"NOVA": 2, "ISOS": 1}
    assert result["by_type"] == {"Bug": 1, "Story": 1, "Migration": 1}
    assert result["by_status"] == {"To Do": 2, "In Progress": 1}
    assert result["by_priority"] == {"High": 1, "Medium": 2}

def test_missing_priority_buckets_as_unprioritized():
    issues = [_issue("NOVA-1", "NOVA", "Bug", "To Do", priority=None)]
    result = aggregate(issues, custom_field_ids=[], due_within_days=3, now=None)
    assert result["by_priority"] == {"Unprioritized": 1}

def test_empty_list():
    result = aggregate([], custom_field_ids=[], due_within_days=3, now=None)
    assert result["total"] == 0
    assert result["by_project"] == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_aggregator.py -v`
Expected: FAIL with ModuleNotFoundError / cannot import `aggregate`.

- [ ] **Step 3: Write the minimal aggregator implementation**

```python
"""Pure aggregation logic for Jira Work. No Home Assistant imports."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


def _bucket(items: Iterable[str]) -> dict[str, int]:
    return dict(Counter(items))


def aggregate(
    issues: list[dict[str, Any]],
    custom_field_ids: list[str],
    due_within_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Turn a raw Jira issue list into counts and pivots."""
    projects: list[str] = []
    types: list[str] = []
    statuses: list[str] = []
    priorities: list[str] = []

    for issue in issues:
        f = issue.get("fields", {})
        projects.append((f.get("project") or {}).get("key", "Unknown"))
        types.append((f.get("issuetype") or {}).get("name", "Unknown"))
        statuses.append((f.get("status") or {}).get("name", "Unknown"))
        prio = f.get("priority")
        priorities.append(prio.get("name") if prio else "Unprioritized")

    return {
        "total": len(issues),
        "by_project": _bucket(projects),
        "by_type": _bucket(types),
        "by_status": _bucket(statuses),
        "by_priority": _bucket(priorities),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_aggregator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/aggregator.py tests/test_aggregator.py
git commit -m "feat: aggregator pivots and core counts"
```

## Task 4: Aggregator — alertable counts (overdue, due-within-X, high priority)

**Files:**
- Modify: `custom_components/jira_work/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: Write the failing tests (frozen time)**

Append to `tests/test_aggregator.py`:
```python
from datetime import datetime, timezone

def _now():
    return datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)

def test_overdue_and_due_within():
    issues = [
        _issue("A-1", "A", "Bug", "To Do", "Low", duedate="2026-06-20"),  # overdue
        _issue("A-2", "A", "Bug", "To Do", "Low", duedate="2026-06-30"),  # within 3 days
        _issue("A-3", "A", "Bug", "To Do", "Low", duedate="2026-07-15"),  # far future
        _issue("A-4", "A", "Bug", "To Do", "Low", duedate=None),          # no due date
    ]
    r = aggregate(issues, custom_field_ids=[], due_within_days=3, high_priority_names=set(), now=_now())
    assert r["overdue"] == 1
    assert sorted(r["overdue_keys"]) == ["A-1"]
    assert r["due_within_x"] == 1
    assert sorted(r["due_within_keys"]) == ["A-2"]

def test_high_priority_count():
    issues = [
        _issue("A-1", "A", "Bug", "To Do", "Blocker"),
        _issue("A-2", "A", "Bug", "To Do", "Critical"),
        _issue("A-3", "A", "Bug", "To Do", "Major"),
    ]
    r = aggregate(issues, custom_field_ids=[], due_within_days=3, high_priority_names={"Blocker", "Critical"}, now=_now())
    assert r["high_priority"] == 2
    assert sorted(r["high_priority_keys"]) == ["A-1", "A-2"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_aggregator.py -k "overdue or high_priority" -v`
Expected: FAIL with KeyError on `overdue` / `high_priority`.

- [ ] **Step 3: Extend the aggregator**

Update the `aggregate` function signature to accept `high_priority_names`:
```python
def aggregate(
    issues: list[dict[str, Any]],
    custom_field_ids: list[str],
    due_within_days: int,
    high_priority_names: set[str],
    now: datetime | None = None,
) -> dict[str, Any]:
```
Inside `aggregate`, before the `return`, add:
```python
    if now is None:
        now = datetime.now(timezone.utc)
    today = now.date()

    overdue_keys: list[str] = []
    due_within_keys: list[str] = []
    high_priority_keys: list[str] = []

    for issue in issues:
        f = issue.get("fields", {})
        key = issue.get("key")
        due = f.get("duedate")
        if due:
            due_date = datetime.fromisoformat(due).date()
            if due_date < today:
                overdue_keys.append(key)
            elif 0 <= (due_date - today).days <= due_within_days:
                due_within_keys.append(key)
        prio = f.get("priority")
        if prio and prio.get("name") in high_priority_names:
            high_priority_keys.append(key)
```
Then add these to the returned dict:
```python
        "overdue": len(overdue_keys),
        "overdue_keys": overdue_keys,
        "due_within_x": len(due_within_keys),
        "due_within_keys": due_within_keys,
        "high_priority": len(high_priority_keys),
        "high_priority_keys": high_priority_keys,
```

- [ ] **Step 4: Run all aggregator tests**

Run: `.venv/bin/pytest tests/test_aggregator.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/aggregator.py tests/test_aggregator.py
git commit -m "feat: aggregator alertable counts"
```

## Task 5: Aggregator — custom-field normalization & numeric summing

**Files:**
- Modify: `custom_components/jira_work/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_aggregator.py`:
```python
def test_custom_field_normalization():
    issues = [
        _issue("A-1", "A", "Bug", "To Do", "Low", fields={
            "customfield_10020": 5,                       # numeric (e.g. story points)
            "customfield_10031": {"value": "Platform"},   # option object
            "customfield_10040": [{"value": "x"}, {"value": "y"}],  # array of options
            "customfield_10050": None,                    # null
        }),
        _issue("A-2", "A", "Bug", "To Do", "Low", fields={
            "customfield_10020": 8,
            "customfield_10031": {"value": "Mobile"},
        }),
    ]
    r = aggregate(
        issues,
        custom_field_ids=["customfield_10020", "customfield_10031", "customfield_10040", "customfield_10050"],
        due_within_days=3,
        now=_now(),
    )
    cf = r["custom_fields"]
    # numeric field gets a sum
    assert cf["customfield_10020"]["sum"] == 13
    # option object normalized to its value, per-issue
    assert cf["customfield_10031"]["values"] == {"A-1": "Platform", "A-2": "Mobile"}
    # array normalized to joined string
    assert cf["customfield_10040"]["values"] == {"A-1": "x, y"}
    # null/missing produces no per-issue entry
    assert cf["customfield_10050"]["values"] == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_aggregator.py -k custom_field -v`
Expected: FAIL with KeyError on `custom_fields`.

- [ ] **Step 3: Add normalization to the aggregator**

Add this helper function to `aggregator.py` (module level):
```python
def _normalize_value(value: Any) -> Any:
    """Reduce a Jira custom-field value to a display-friendly form."""
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, dict):
        for k in ("value", "name", "displayName"):
            if k in value:
                return value[k]
        return str(value)
    if isinstance(value, list):
        parts = [_normalize_value(v) for v in value]
        parts = [str(p) for p in parts if p is not None]
        return ", ".join(parts) if parts else None
    return str(value)
```
Inside `aggregate`, before the `return`, add:
```python
    custom_fields: dict[str, dict[str, Any]] = {}
    for fid in custom_field_ids:
        values: dict[str, Any] = {}
        numeric_total = 0.0
        has_numeric = False
        for issue in issues:
            raw = issue.get("fields", {}).get(fid)
            norm = _normalize_value(raw)
            if norm is None:
                continue
            values[issue["key"]] = norm
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                numeric_total += raw
                has_numeric = True
        entry: dict[str, Any] = {"values": values}
        if has_numeric:
            entry["sum"] = numeric_total
        custom_fields[fid] = entry
```
Add to the returned dict:
```python
        "custom_fields": custom_fields,
```

- [ ] **Step 4: Run all aggregator tests**

Run: `.venv/bin/pytest tests/test_aggregator.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/aggregator.py tests/test_aggregator.py
git commit -m "feat: custom-field normalization and numeric summing"
```

## Task 6: JiraClient — auth, paginated search, error mapping

**Files:**
- Create: `custom_components/jira_work/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL with ImportError (no `api` module).

- [ ] **Step 3: Write `api.py`**

```python
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

    async def search(self, jql: str, fields: list[str], page_size: int = 100) -> list[dict[str, Any]]:
        """Run a JQL search, following pagination."""
        issues: list[dict[str, Any]] = []
        start_at = 0
        while True:
            body = {"jql": jql, "fields": fields, "startAt": start_at, "maxResults": page_size}
            try:
                async with self._session.post(
                    f"{self._url}/rest/api/3/search", headers=self._headers(), json=body
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
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/api.py tests/test_api.py
git commit -m "feat: JiraClient auth, paginated search, error mapping"
```

## Task 7: JiraClient — field lookup with duplicate-name disambiguation

**Files:**
- Modify: `custom_components/jira_work/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:
```python
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

async def test_get_custom_fields_friendly_names():
    fields = [
        {"id": "summary", "name": "Summary", "custom": False},
        {"id": "customfield_10020", "name": "Story Points", "custom": True},
        {"id": "customfield_10031", "name": "Team", "custom": True},
    ]
    with aioresponses() as m:
        m.get(f"{BASE}/rest/api/3/field", payload=fields)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            result = await c.get_custom_fields()
    # only custom fields, mapped id -> label
    assert result == {
        "customfield_10020": "Story Points",
        "customfield_10031": "Team",
    }

async def test_get_custom_fields_disambiguates_duplicates():
    fields = [
        {"id": "customfield_10031", "name": "Team", "custom": True},
        {"id": "customfield_10044", "name": "Team", "custom": True},
        {"id": "customfield_10020", "name": "Story Points", "custom": True},
    ]
    with aioresponses() as m:
        m.get(f"{BASE}/rest/api/3/field", payload=fields)
        async with aiohttp.ClientSession() as s:
            c = _client(s)
            result = await c.get_custom_fields()
    assert result["customfield_10031"] == "Team (customfield_10031)"
    assert result["customfield_10044"] == "Team (customfield_10044)"
    assert result["customfield_10020"] == "Story Points"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_api.py -k custom_fields -v`
Expected: FAIL — no `get_custom_fields` method.

- [ ] **Step 3: Add `get_priorities` and `get_custom_fields` to `JiraClient`**

Add `get_priorities` method to the `JiraClient` class:
```python
    async def get_priorities(self) -> list[str]:
        """Return priority names in server order."""
        try:
            async with self._session.get(
                f"{self._url}/rest/api/3/priority", headers=self._headers()
            ) as resp:
                await self._raise_for_status(resp)
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise JiraConnectionError(str(err)) from err
        return [p["name"] for p in data]
```

Add `get_custom_fields` method to the `JiraClient` class:
```python
    async def get_custom_fields(self) -> dict[str, str]:
        """Return {customfield_id: friendly_label}, disambiguating duplicate names."""
        try:
            async with self._session.get(
                f"{self._url}/rest/api/3/field", headers=self._headers()
            ) as resp:
                await self._raise_for_status(resp)
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise JiraConnectionError(str(err)) from err

        customs = [f for f in data if f.get("custom")]
        name_counts: dict[str, int] = {}
        for f in customs:
            name_counts[f["name"]] = name_counts.get(f["name"], 0) + 1

        result: dict[str, str] = {}
        for f in customs:
            label = f["name"]
            if name_counts[label] > 1:
                label = f"{label} ({f['id']})"
            result[f["id"]] = label
        return result
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/api.py tests/test_api.py
git commit -m "feat: field lookup with duplicate-name disambiguation"
```

## Task 8: Newly-assigned state logic (set-diff + rolling window)

This logic is stateful but HA-free, so it lives in its own module and is unit-tested directly. The coordinator will own an instance.

**Files:**
- Create: `custom_components/jira_work/newly_assigned.py`
- Test: `tests/test_newly_assigned.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
sys.path.insert(0, ".")
from datetime import datetime, timezone, timedelta
from custom_components.jira_work.newly_assigned import NewlyAssignedTracker

def _now():
    return datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)

def test_first_poll_reports_zero():
    t = NewlyAssignedTracker(window_hours=24)
    res = t.update({"A-1", "A-2"}, now=_now())
    assert res["newly_assigned"] == 0
    assert res["new_keys"] == []
    assert res["new_last_window"] == 0

def test_detects_new_key_then_resets():
    t = NewlyAssignedTracker(window_hours=24)
    t.update({"A-1"}, now=_now())
    res = t.update({"A-1", "A-2"}, now=_now())
    assert res["newly_assigned"] == 1
    assert res["new_keys"] == ["A-2"]
    # transient resets next poll (A-2 now known)
    res2 = t.update({"A-1", "A-2"}, now=_now())
    assert res2["newly_assigned"] == 0

def test_rolling_window_counts_then_prunes():
    t = NewlyAssignedTracker(window_hours=24)
    t.update({"A-1"}, now=_now())
    t.update({"A-1", "A-2"}, now=_now())          # A-2 new now
    res = t.update({"A-1", "A-2"}, now=_now())     # still within window
    assert res["new_last_window"] == 1
    later = _now() + timedelta(hours=25)
    res2 = t.update({"A-1", "A-2"}, now=later)      # A-2 aged out
    assert res2["new_last_window"] == 0

def test_serialize_roundtrip():
    t = NewlyAssignedTracker(window_hours=24)
    t.update({"A-1"}, now=_now())
    t.update({"A-1", "A-2"}, now=_now())
    blob = t.serialize()
    t2 = NewlyAssignedTracker.deserialize(blob, window_hours=24)
    res = t2.update({"A-1", "A-2"}, now=_now())
    assert res["newly_assigned"] == 0          # A-2 already known after restore
    assert res["new_last_window"] == 1         # rolling entry restored
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_newly_assigned.py -v`
Expected: FAIL — no module.

- [ ] **Step 3: Write `newly_assigned.py`**

```python
"""Stateful newly-assigned tracking. No Home Assistant imports."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any


class NewlyAssignedTracker:
    def __init__(self, window_hours: int):
        self._window = timedelta(hours=window_hours)
        self._known: set[str] | None = None          # None => no prior poll yet
        self._recent: dict[str, str] = {}            # key -> first_seen ISO ts

    def update(self, current: set[str], now: datetime | None = None) -> dict[str, Any]:
        if now is None:
            now = datetime.now(timezone.utc)

        if self._known is None:
            new_keys: list[str] = []
        else:
            new_keys = sorted(current - self._known)

        for k in new_keys:
            self._recent[k] = now.isoformat()

        self._known = set(current)
        self._prune(now)

        return {
            "newly_assigned": len(new_keys),
            "new_keys": new_keys,
            "new_last_window": len(self._recent),
        }

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._window
        self._recent = {
            k: ts for k, ts in self._recent.items()
            if datetime.fromisoformat(ts) >= cutoff
        }

    def serialize(self) -> dict[str, Any]:
        return {
            "known": sorted(self._known) if self._known is not None else None,
            "recent": self._recent,
        }

    @classmethod
    def deserialize(cls, blob: dict[str, Any], window_hours: int) -> "NewlyAssignedTracker":
        t = cls(window_hours)
        known = blob.get("known")
        t._known = set(known) if known is not None else None
        t._recent = dict(blob.get("recent", {}))
        return t
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_newly_assigned.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/newly_assigned.py tests/test_newly_assigned.py
git commit -m "feat: newly-assigned set-diff and rolling window tracker"
```

## Task 9: Coordinator (poll, aggregate, tracker, persistence)

**Files:**
- Create: `custom_components/jira_work/coordinator.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Write the failing test (mocked client + store)**

```python
import sys
sys.path.insert(0, ".")
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
from custom_components.jira_work.coordinator import JiraDataUpdateCoordinator
from custom_components.jira_work.api import JiraConnectionError
from homeassistant.helpers.update_coordinator import UpdateFailed


def _entry(options=None):
    e = MagicMock()
    e.options = options or {}
    e.entry_id = "test"
    return e


async def test_poll_populates_data(hass):
    client = MagicMock()
    client.search = AsyncMock(return_value=[
        {"key": "A-1", "fields": {"project": {"key": "A"}, "issuetype": {"name": "Bug"},
         "status": {"name": "To Do"}, "priority": {"name": "High"}, "duedate": None}},
    ])
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    coord = JiraDataUpdateCoordinator(hass, client, _entry(), store)
    await coord.async_load_state()
    data = await coord._async_update_data()
    assert data["total"] == 1
    assert data["by_type"] == {"Bug": 1}
    assert "newly_assigned" in data


async def test_poll_error_raises_updatefailed(hass):
    client = MagicMock()
    client.search = AsyncMock(side_effect=JiraConnectionError("boom"))
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    coord = JiraDataUpdateCoordinator(hass, client, _entry(), store)
    await coord.async_load_state()
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
```

- [ ] **Step 2: Add the `hass` fixture to `tests/conftest.py`**

Create `tests/conftest.py`:
```python
import sys
sys.path.insert(0, ".")
import pytest
from homeassistant.core import HomeAssistant

@pytest.fixture
async def hass(event_loop):
    hass = HomeAssistant("/tmp/ha-test-config")
    await hass.async_start()
    yield hass
    await hass.async_stop()
```
Add `homeassistant==2024.6.0` to `requirements_test.txt` and run `.venv/bin/pip install -r requirements_test.txt`.

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_coordinator.py -v`
Expected: FAIL — no `coordinator` module.

- [ ] **Step 4: Write `coordinator.py`**

```python
"""Data update coordinator for Jira Work."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aggregator import aggregate
from .api import JiraClient, JiraError
from .const import (
    CORE_FIELDS, DEFAULT_CHECKPOINT_EVERY, DEFAULT_DUE_WITHIN_DAYS,
    DEFAULT_HIGH_PRIORITY_NAMES, DEFAULT_POLL_INTERVAL, DOMAIN,
    JQL_OPEN_ASSIGNED, OPT_CHECKPOINT_EVERY, OPT_CUSTOM_FIELDS,
    OPT_DUE_WITHIN_DAYS, OPT_HIGH_PRIORITY_NAMES, OPT_POLL_INTERVAL,
    ROLLING_WINDOW_HOURS,
)
from .newly_assigned import NewlyAssignedTracker

_LOGGER = logging.getLogger(__name__)


class JiraDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: JiraClient, entry: ConfigEntry, store: Store):
        self._client = client
        self._entry = entry
        self._store = store
        self._tracker = NewlyAssignedTracker(ROLLING_WINDOW_HOURS)
        self._poll_count = 0
        interval = entry.options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    @property
    def custom_field_ids(self) -> list[str]:
        return self._entry.options.get(OPT_CUSTOM_FIELDS, [])

    async def async_load_state(self) -> None:
        blob = await self._store.async_load()
        if blob:
            self._tracker = NewlyAssignedTracker.deserialize(blob, ROLLING_WINDOW_HOURS)

    async def async_save_state(self) -> None:
        await self._store.async_save(self._tracker.serialize())

    async def _async_update_data(self) -> dict[str, Any]:
        fields = CORE_FIELDS + self.custom_field_ids
        try:
            issues = await self._client.search(JQL_OPEN_ASSIGNED, fields)
        except JiraError as err:
            raise UpdateFailed(str(err)) from err

        now = datetime.now(timezone.utc)
        due_within = self._entry.options.get(OPT_DUE_WITHIN_DAYS, DEFAULT_DUE_WITHIN_DAYS)
        high_priority_names = set(self._entry.options.get(OPT_HIGH_PRIORITY_NAMES, DEFAULT_HIGH_PRIORITY_NAMES))
        result = aggregate(issues, self.custom_field_ids, due_within, high_priority_names, now=now)

        current_keys = {i["key"] for i in issues}
        result.update(self._tracker.update(current_keys, now=now))

        self._poll_count += 1
        checkpoint = self._entry.options.get(OPT_CHECKPOINT_EVERY, DEFAULT_CHECKPOINT_EVERY)
        if checkpoint and self._poll_count % checkpoint == 0:
            await self.async_save_state()

        return result
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_coordinator.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/jira_work/coordinator.py tests/test_coordinator.py tests/conftest.py requirements_test.txt
git commit -m "feat: data update coordinator with aggregation, tracker, checkpointing"
```

## Task 10: Sensor entities (6 sensors, Shape 1+)

**Files:**
- Create: `custom_components/jira_work/sensor.py`
- Test: `tests/test_sensor.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
sys.path.insert(0, ".")
from unittest.mock import MagicMock
from custom_components.jira_work.sensor import (
    JiraTotalSensor, JiraOverdueSensor, JiraDueWithinSensor,
    JiraHighPrioritySensor, JiraNewlyAssignedSensor, JiraNewLastWindowSensor,
)

def _coord(data):
    c = MagicMock()
    c.data = data
    c.last_update_success = True
    return c

DATA = {
    "total": 3,
    "by_project": {"A": 2, "B": 1}, "by_type": {"Bug": 3},
    "by_status": {"To Do": 3}, "by_priority": {"High": 3},
    "custom_fields": {"customfield_10020": {"values": {"A-1": 5}, "sum": 5}},
    "overdue": 1, "overdue_keys": ["A-1"],
    "due_within_x": 1, "due_within_keys": ["A-2"],
    "high_priority": 3, "high_priority_keys": ["A-1", "A-2", "A-3"],
    "newly_assigned": 1, "new_keys": ["A-3"],
    "new_last_window": 2,
}

def test_total_sensor_state_and_attributes():
    s = JiraTotalSensor(_coord(DATA), "entry1")
    assert s.native_value == 3
    attrs = s.extra_state_attributes
    assert attrs["by_project"] == {"A": 2, "B": 1}
    assert attrs["by_type"] == {"Bug": 3}
    assert attrs["custom_fields"]["customfield_10020"]["sum"] == 5

def test_alertable_sensors():
    assert JiraOverdueSensor(_coord(DATA), "e").native_value == 1
    assert JiraOverdueSensor(_coord(DATA), "e").extra_state_attributes["keys"] == ["A-1"]
    assert JiraDueWithinSensor(_coord(DATA), "e").native_value == 1
    assert JiraHighPrioritySensor(_coord(DATA), "e").native_value == 3
    assert JiraNewlyAssignedSensor(_coord(DATA), "e").native_value == 1
    assert JiraNewLastWindowSensor(_coord(DATA), "e").native_value == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_sensor.py -v`
Expected: FAIL — no `sensor` module.

- [ ] **Step 3: Write `sensor.py`**

```python
"""Sensor entities for Jira Work."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class _Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry_id: str, key: str, name: str, icon: str):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Jira Work",
            manufacturer="Atlassian",
        )

    def _d(self) -> dict[str, Any]:
        return self.coordinator.data or {}


class JiraTotalSensor(_Base):
    def __init__(self, coordinator, entry_id: str):
        super().__init__(coordinator, entry_id, "open_assigned", "Open assigned", "mdi:jira")

    @property
    def native_value(self):
        return self._d().get("total")

    @property
    def extra_state_attributes(self):
        d = self._d()
        return {
            "by_project": d.get("by_project", {}),
            "by_type": d.get("by_type", {}),
            "by_status": d.get("by_status", {}),
            "by_priority": d.get("by_priority", {}),
            "custom_fields": d.get("custom_fields", {}),
        }


class _Count(_Base):
    value_key = ""
    keys_key = ""

    @property
    def native_value(self):
        return self._d().get(self.value_key)

    @property
    def extra_state_attributes(self):
        return {"keys": self._d().get(self.keys_key, [])}


class JiraOverdueSensor(_Count):
    value_key, keys_key = "overdue", "overdue_keys"
    def __init__(self, c, e): super().__init__(c, e, "overdue", "Overdue", "mdi:alert")


class JiraDueWithinSensor(_Count):
    value_key, keys_key = "due_within_x", "due_within_keys"
    def __init__(self, c, e): super().__init__(c, e, "due_within", "Due soon", "mdi:clock-alert")


class JiraHighPrioritySensor(_Count):
    value_key, keys_key = "high_priority", "high_priority_keys"
    def __init__(self, c, e): super().__init__(c, e, "high_priority", "High priority", "mdi:flag")


class JiraNewlyAssignedSensor(_Count):
    value_key, keys_key = "newly_assigned", "new_keys"
    def __init__(self, c, e): super().__init__(c, e, "newly_assigned", "Newly assigned", "mdi:bell-ring")


class JiraNewLastWindowSensor(_Base):
    def __init__(self, c, e):
        super().__init__(c, e, "new_last_window", "New (rolling)", "mdi:history")

    @property
    def native_value(self):
        return self._d().get("new_last_window")

    @property
    def extra_state_attributes(self):
        return {"window_hours": 24}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        JiraTotalSensor(coordinator, entry.entry_id),
        JiraOverdueSensor(coordinator, entry.entry_id),
        JiraDueWithinSensor(coordinator, entry.entry_id),
        JiraHighPrioritySensor(coordinator, entry.entry_id),
        JiraNewlyAssignedSensor(coordinator, entry.entry_id),
        JiraNewLastWindowSensor(coordinator, entry.entry_id),
    ])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_sensor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/sensor.py tests/test_sensor.py
git commit -m "feat: six sensor entities (Shape 1+)"
```

## Task 11: Config flow + options flow

**Files:**
- Create: `custom_components/jira_work/config_flow.py`
- Test: `tests/test_config_flow.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
sys.path.insert(0, ".")
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.data_entry_flow import FlowResultType
from custom_components.jira_work.const import (
    DOMAIN, CONF_URL, CONF_EMAIL, CONF_TOKEN, OPT_CUSTOM_FIELDS,
)

USER_INPUT = {
    CONF_URL: "https://example.atlassian.net",
    CONF_EMAIL: "me@example.com",
    CONF_TOKEN: "tok123",
}

async def test_user_flow_success(hass):
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=({"customfield_10020": "Story Points"}, ["Blocker", "Critical", "Major", "Minor", "Trivial"])),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_EMAIL] == "me@example.com"

async def test_user_flow_bad_auth(hass):
    from custom_components.jira_work.api import JiraAuthError
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(side_effect=JiraAuthError("nope")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_config_flow.py -v`
Expected: FAIL — no `config_flow` module.

- [ ] **Step 3: Write `config_flow.py`**

```python
"""Config and options flow for Jira Work."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry, ConfigFlow, OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JiraAuthError, JiraClient, JiraConnectionError, JiraError
from .const import (
    CONF_EMAIL, CONF_TOKEN, CONF_URL, DEFAULT_DUE_WITHIN_DAYS,
    DEFAULT_HIGH_PRIORITY_NAMES, DEFAULT_POLL_INTERVAL, DOMAIN,
    OPT_CUSTOM_FIELDS, OPT_DUE_WITHIN_DAYS, OPT_HIGH_PRIORITY_NAMES,
    OPT_POLL_INTERVAL,
)

USER_SCHEMA = vol.Schema({
    vol.Required(CONF_URL): str,
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_TOKEN): str,
})


async def _validate(hass, data: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Return (custom_fields map, priority names list), or raise."""
    session = async_get_clientsession(hass)
    client = JiraClient(data[CONF_URL], data[CONF_EMAIL], data[CONF_TOKEN], session)
    custom_fields = await client.get_custom_fields()
    priorities = await client.get_priorities()
    return custom_fields, priorities


class JiraWorkConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate(self.hass, user_input)
            except JiraAuthError:
                errors["base"] = "invalid_auth"
            except (JiraConnectionError, JiraError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_URL]}::{user_input[CONF_EMAIL]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_EMAIL], data=user_input)
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "JiraWorkOptionsFlow":
        return JiraWorkOptionsFlow(entry)


class JiraWorkOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        try:
            custom_fields, priorities = await _validate(self.hass, dict(self._entry.data))
        except JiraError:
            custom_fields, priorities = {}, list(DEFAULT_HIGH_PRIORITY_NAMES)

        current = self._entry.options
        schema = vol.Schema({
            vol.Optional(
                OPT_CUSTOM_FIELDS,
                default=current.get(OPT_CUSTOM_FIELDS, []),
            ): vol.All([vol.In(custom_fields)]),
            vol.Optional(
                OPT_HIGH_PRIORITY_NAMES,
                default=current.get(OPT_HIGH_PRIORITY_NAMES, DEFAULT_HIGH_PRIORITY_NAMES),
            ): vol.All([vol.In(priorities)]),
            vol.Optional(
                OPT_POLL_INTERVAL,
                default=current.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): vol.All(int, vol.Range(min=1, max=1440)),
            vol.Optional(
                OPT_DUE_WITHIN_DAYS,
                default=current.get(OPT_DUE_WITHIN_DAYS, DEFAULT_DUE_WITHIN_DAYS),
            ): vol.All(int, vol.Range(min=0, max=365)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
```

Notes:
- `vol.In(custom_fields)` accepts a dict and uses its keys (customfield IDs) as valid values; HA renders the dict's values as labels — friendly-name dropdown, stores IDs.
- `vol.In(priorities)` is a list, so HA renders a multi-select of priority name strings.
- If `_validate` fails (e.g. Jira unreachable when options open), falls back to the default priority list so the form still renders.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_config_flow.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/jira_work/config_flow.py tests/test_config_flow.py
git commit -m "feat: config flow and options flow"
```

## Task 12: Integration entry wiring (`__init__.py`)

**Files:**
- Modify: `custom_components/jira_work/__init__.py`

- [ ] **Step 1: Replace the placeholder `__init__.py`**

```python
"""The Jira Work integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import JiraClient
from .const import (
    CONF_EMAIL, CONF_TOKEN, CONF_URL, DOMAIN, STORAGE_KEY, STORAGE_VERSION,
)
from .coordinator import JiraDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = JiraClient(
        entry.data[CONF_URL], entry.data[CONF_EMAIL], entry.data[CONF_TOKEN], session
    )
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
    coordinator = JiraDataUpdateCoordinator(hass, client, entry, store)
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Persist on graceful shutdown.
    async def _on_stop(event: Event) -> None:
        await coordinator.async_save_state()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    )
    # Reload when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_save_state()
    return unloaded
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import custom_components.jira_work"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add custom_components/jira_work/__init__.py
git commit -m "feat: integration entry setup/unload with persistence and reload"
```

## Task 13: Manifest, strings & Tier 1 packaging files

**Files:**
- Create: `custom_components/jira_work/manifest.json`
- Create: `custom_components/jira_work/strings.json`
- Create: `hacs.json`
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Write `manifest.json`**

```json
{
  "domain": "jira_work",
  "name": "Jira Work",
  "version": "0.1.0",
  "config_flow": true,
  "documentation": "https://github.com/wbrown/ha-jira-work",
  "issue_tracker": "https://github.com/wbrown/ha-jira-work/issues",
  "codeowners": ["@wbrown"],
  "requirements": [],
  "iot_class": "cloud_polling",
  "integration_type": "service"
}
```

- [ ] **Step 2: Write `strings.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "data": {
          "url": "Jira URL (https://your-site.atlassian.net)",
          "email": "Account email",
          "token": "API token"
        }
      }
    },
    "error": {
      "invalid_auth": "Authentication failed. Check your email and API token.",
      "cannot_connect": "Could not connect to Jira. Check the URL."
    },
    "abort": {
      "already_configured": "This Jira account is already configured."
    }
  },
  "options": {
    "step": {
      "init": {
        "data": {
          "custom_fields": "Custom fields to track",
          "high_priority_names": "High-priority levels (for the high-priority sensor)",
          "poll_interval": "Poll interval (minutes)",
          "due_within_days": "Due-soon window (days)"
        }
      }
    }
  }
}
```

- [ ] **Step 3: Write `hacs.json`**

```json
{
  "name": "Jira Work",
  "render_readme": true,
  "homeassistant": "2024.6.0"
}
```

- [ ] **Step 4: Write `README.md`**

```markdown
# Jira Work — Home Assistant Integration

Surface your open, assigned Jira Cloud work as Home Assistant sensors,
aggregated by project, type, status, and priority, with alertable sensors
for overdue, due-soon, high-priority, and newly-assigned items.

## Install (HACS custom repository)

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/wbrown/ha-jira-work`, category "Integration".
3. Install "Jira Work", restart Home Assistant.
4. Settings → Devices & Services → Add Integration → "Jira Work".

## Configure

- **URL**: `https://your-site.atlassian.net`
- **Email**: your Atlassian account email
- **API token**: create at https://id.atlassian.com/manage-profile/security/api-tokens

Use **Configure** (Options) to pick custom fields, poll interval, and the
due-soon window.

## Sensors

`open_assigned` (total + pivots in attributes), `overdue`, `due_within`,
`high_priority`, `newly_assigned` (transient), `new_last_window` (rolling 24h).
```

- [ ] **Step 5: Write `LICENSE` (MIT)**

Run:
```bash
curl -s https://raw.githubusercontent.com/licenses/license-templates/master/templates/mit.txt -o LICENSE || true
```
If offline, paste a standard MIT license text with year 2026 and author "Wayne Brown".

- [ ] **Step 6: Commit**

```bash
git add custom_components/jira_work/manifest.json custom_components/jira_work/strings.json hacs.json README.md LICENSE
git commit -m "feat: manifest, strings, and Tier 1 HACS packaging files"
```

## Task 14: Full verification & release tag

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS across `test_aggregator.py`, `test_api.py`, `test_newly_assigned.py`, `test_coordinator.py`, `test_sensor.py`, `test_config_flow.py`.

- [ ] **Step 2: Validate JSON files parse**

Run:
```bash
.venv/bin/python -c "import json; [json.load(open(p)) for p in ['custom_components/jira_work/manifest.json','custom_components/jira_work/strings.json','hacs.json']]; print('json ok')"
```
Expected: prints `json ok`.

- [ ] **Step 3: Confirm no HA imports leaked into the pure layer**

Run:
```bash
! grep -rn "import homeassistant\|from homeassistant" custom_components/jira_work/api.py custom_components/jira_work/aggregator.py custom_components/jira_work/newly_assigned.py && echo "pure layer clean"
```
Expected: prints `pure layer clean`.

- [ ] **Step 4: Tag the release**

Run:
```bash
git tag v0.1.0
git log --oneline | head -20
```
Expected: tag created; clean commit history.

---

## Spec Coverage Notes

- Auth (API token, Basic) → Task 6, Task 11.
- Single paginated JQL query, explicit fields → Task 6, Task 9.
- `/field` resolution, cached off hot path, duplicate-name disambiguation → Task 7, used in Task 11 (setup + options only).
- `/priority` resolution, fetched at setup alongside `/field` → Task 7, Task 11.
- High-priority names user-configurable via Options Flow, defaulting to `["Blocker", "Critical"]` → Tasks 2, 4, 7, 9, 11.
- Pivots (project/type/status/priority) → Task 3.
- Alertable counts (overdue/due-within/high-priority) → Task 4.
- Custom-field normalization + numeric summing → Task 5.
- Newly-assigned (transient + rolling) + serialize → Task 8; wired in Task 9.
- Persistence option 2 (load + shutdown + hourly checkpoint) → Task 9 (checkpoint), Task 12 (load + shutdown).
- 6 sensors, Shape 1+, `keys` attributes, device grouping, measurement state_class → Task 10.
- Options flow (changeable custom fields, interval, due-within) + reload → Task 11, Task 12.
- Custom work item types via `by_type` (dynamic) → covered by Task 3 (no hardcoded list; test includes "Migration").
- Error handling (auth/connect/429/UpdateFailed/resilient nulls) → Tasks 4, 6, 9.
- Tier 1 HACS packaging → Task 13.
- Testing strategy (pure-layer pytest, mocked HTTP, frozen time) → Tasks 3-11, 14.
