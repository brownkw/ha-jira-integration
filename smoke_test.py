#!/usr/bin/env python3
"""
Smoke test for the jira_work Home Assistant integration.

Tests live connectivity to a Jira Cloud instance using the JiraClient
from the integration. Validates auth, search, custom fields, priorities,
and the aggregator — all against real data.

Usage
-----
Classic (unscoped) token:
    export JIRA_URL="https://your-site.atlassian.net"
    export JIRA_EMAIL="you@example.com"
    export JIRA_TOKEN="your-classic-token"
    python smoke_test.py

Scoped token:
    export JIRA_URL="https://your-site.atlassian.net"
    export JIRA_EMAIL="you@example.com"
    export JIRA_TOKEN="your-scoped-token"
    export TOKEN_TYPE=scoped
    export CLOUD_ID="your-cloud-id"   # from https://your-site.atlassian.net/_edge/tenant_info
    python smoke_test.py

Notes
-----
- Scoped tokens require: read:jira-work, read:jira-user
- Scoped tokens use the API gateway: https://api.atlassian.com/ex/jira/{cloudId}
- The legacy /rest/api/3/search endpoint was removed in Aug 2025 (CHANGE-2046)
  This integration uses /rest/api/3/search/jql with nextPageToken pagination
"""

import asyncio
import os
import sys

import aiohttp

# Allow running from repo root
sys.path.insert(0, ".")

from custom_components.jira_work.aggregator import aggregate
from custom_components.jira_work.api import JiraClient, JiraConnectionError
from custom_components.jira_work.const import (
    TOKEN_TYPE_CLASSIC,
    TOKEN_TYPE_SCOPED,
)

DEFAULT_HIGH_PRIORITY_NAMES = ["Blocker", "Critical"]


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"❌  Missing required env var: {name}")
        sys.exit(1)
    return val


async def main() -> None:
    url = _require_env("JIRA_URL").rstrip("/")
    email = _require_env("JIRA_EMAIL")
    token = _require_env("JIRA_TOKEN")
    token_type = os.environ.get("TOKEN_TYPE", TOKEN_TYPE_CLASSIC).strip()
    cloud_id = os.environ.get("CLOUD_ID", "").strip()

    if token_type == TOKEN_TYPE_SCOPED and not cloud_id:
        print("❌  TOKEN_TYPE=scoped requires CLOUD_ID to be set.")
        print("    Find it at: https://your-site.atlassian.net/_edge/tenant_info")
        sys.exit(1)

    print(f"\n🔌  Connecting to {url} as {email}")
    print(f"🔑  Token type: {token_type}")

    async with aiohttp.ClientSession() as session:
        client = JiraClient(
            session=session,
            url=url,
            email=email,
            token=token,
            token_type=token_type,
            cloud_id=cloud_id or None,
        )

        if token_type == TOKEN_TYPE_SCOPED:
            print(f"\n0️⃣  Using gateway base URL: {client._base_url}")

        import time

        JQL = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
        parallel = "--parallel" in sys.argv
        mode_label = "PARALLEL" if parallel else "SEQUENTIAL"
        print(f"\n⚙️   Mode: {mode_label}")
        total_t0 = time.monotonic()

        if parallel:
            # ── Parallel: fan out all three fetches concurrently ───────────
            print("\n1️⃣ 2️⃣ 3️⃣  Fetching issues (core), issues (sample *all), fields & priorities in parallel...")
            t0 = time.monotonic()
            try:
                (issues, sample_issues, all_fields, priorities) = await asyncio.gather(
                    client.search(jql=JQL, fields=["summary", "status", "priority",
                                                    "issuetype", "project", "duedate", "assignee"]),
                    client.search(jql=JQL, fields=["*all"], page_size=10),
                    client.get_custom_fields(),
                    client.get_priorities(),
                )
            except JiraConnectionError as err:
                print(f"   ❌  Connection error: {err}")
                sys.exit(1)

            # Filter fields to populated ones
            populated: set[str] = set()
            for issue in sample_issues:
                for key, val in issue.get("fields", {}).items():
                    if key.startswith("customfield_") and val is not None:
                        populated.add(key)
            fields = {k: v for k, v in all_fields.items() if k in populated} if sample_issues else all_fields
            elapsed = time.monotonic() - t0
            print(f"   ✅  {len(issues)} issues | {len(fields)} custom fields | {len(priorities)} priorities  ⏱ {elapsed:.2f}s total")

        else:
            # ── Sequential: one call at a time ─────────────────────────────

            # ── 1. Search ──────────────────────────────────────────────────
            print("\n1️⃣  Fetching open assigned issues...")
            t0 = time.monotonic()
            try:
                issues = await client.search(
                    jql=JQL,
                    fields=["summary", "status", "priority", "issuetype", "project",
                            "duedate", "assignee"],
                )
            except JiraConnectionError as err:
                print(f"   ❌  Connection error: {err}")
                sys.exit(1)
            print(f"   ✅  {len(issues)} open assigned issue(s) found  ⏱ {time.monotonic()-t0:.2f}s")
            t0 = time.monotonic()

            # ── 2. Custom fields ───────────────────────────────────────────
            print("\n2️⃣  Fetching custom fields...")
            try:
                sample_issues = await client.search(jql=JQL, fields=["*all"], page_size=10)
                fields = await client.get_custom_fields(issues=sample_issues)
            except JiraConnectionError as err:
                print(f"   ❌  Connection error: {err}")
                sys.exit(1)
            print(f"   ✅  {len(fields)} custom field(s) available  ⏱ {time.monotonic()-t0:.2f}s")
            t0 = time.monotonic()

            # ── 3. Priority scheme ─────────────────────────────────────────
            print("\n3️⃣  Fetching priority scheme...")
            try:
                priorities = await client.get_priorities()
            except JiraConnectionError as err:
                print(f"   ❌  Connection error: {err}")
                sys.exit(1)
            print(f"   ✅  {len(priorities)} priorities  ⏱ {time.monotonic()-t0:.2f}s")
            t0 = time.monotonic()

        # ── Shared: sample issue display ───────────────────────────────────
        if issues:
            s = issues[0]
            key = s.get("key", "?")
            summary = s["fields"].get("summary", "?")[:50]
            status = s["fields"].get("status", {}).get("name", "?")
            priority = (s["fields"].get("priority") or {}).get("name", "?")
            project = s["fields"].get("project", {}).get("key", "?")
            print(f"\n   📄  Sample: [{key}] {summary}")
            print(f"       Status: {status} | Priority: {priority} | Project: {project}")

        print(f"\n   🏁  Steps 1-3 total wall time: {time.monotonic()-total_t0:.2f}s")

        if not parallel:
            for fid, fname in list(fields.items())[:5]:
                print(f"       {fid}: {fname}")
            if len(fields) > 5:
                print(f"       ... and {len(fields) - 5} more")
            priorities_preview = priorities[:5]
            print(f"   ✅  Priorities (first 5): {priorities_preview}")

        t0 = time.monotonic()
        overlap = set(DEFAULT_HIGH_PRIORITY_NAMES) & set(priorities)
        if overlap:
            print(f"   ✅  Default high-priority names {DEFAULT_HIGH_PRIORITY_NAMES} overlap with instance")
        else:
            print(f"   ⚠️   Default high-priority names {DEFAULT_HIGH_PRIORITY_NAMES} NOT found in instance priorities")
            print(f"       Consider updating CONF_PRIORITIES in HA Options to match your instance")

        # ── 4. Aggregator dry-run ──────────────────────────────────────────
        print("\n4️⃣  Running aggregator on live data...")
        result = aggregate(
            issues,
            custom_field_ids=[],
            due_within_days=3,
            high_priority_names=set(DEFAULT_HIGH_PRIORITY_NAMES),
        )

        print(f"   Total open:      {result['total']}")
        print(f"   Overdue:         {result['overdue']}")
        print(f"   Due within 3d:  {result['due_within_x']}")
        print(f"   High priority:   {result['high_priority']}")
        print(f"   By project:      {dict(result['by_project'])}")
        print(f"   By type:         {dict(result['by_type'])}")
        print(f"   By status:       {dict(result['by_status'])}")

    print("\n✅  Smoke test complete — all systems go!\n")


if __name__ == "__main__":
    asyncio.run(main())
