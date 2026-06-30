#!/usr/bin/env python3
"""
Smoke test — verify live connectivity to a Jira Cloud instance.

Classic token usage:
    export JIRA_URL="https://yourinstance.atlassian.net"
    export JIRA_EMAIL="you@example.com"
    export JIRA_TOKEN="your-api-token"
    .venv/bin/python tmp_rovodev_smoke_test.py

Scoped token usage (add TOKEN_TYPE=scoped):
    export JIRA_URL="https://yourinstance.atlassian.net"
    export JIRA_EMAIL="you@example.com"
    export JIRA_TOKEN="your-scoped-token"
    export TOKEN_TYPE=scoped
    .venv/bin/python tmp_rovodev_smoke_test.py
"""

import asyncio
import os
import sys

sys.path.insert(0, ".")

import aiohttp

from custom_components.jira_work.api import JiraClient, JiraAuthError, JiraConnectionError
from custom_components.jira_work.aggregator import aggregate
from custom_components.jira_work.const import (
    JQL_OPEN_ASSIGNED,
    CORE_FIELDS,
    DEFAULT_HIGH_PRIORITY_NAMES,
    DEFAULT_DUE_WITHIN_DAYS,
    TOKEN_TYPE_CLASSIC,
    TOKEN_TYPE_SCOPED,
)


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"❌  Missing env var: {name}")
        sys.exit(1)
    return val


async def main() -> None:
    url = require_env("JIRA_URL").rstrip("/")
    email = require_env("JIRA_EMAIL")
    token = require_env("JIRA_TOKEN")
    token_type = os.environ.get("TOKEN_TYPE", TOKEN_TYPE_CLASSIC).lower()

    if token_type not in (TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED):
        print(f"❌  TOKEN_TYPE must be 'classic' or 'scoped', got: {token_type!r}")
        sys.exit(1)

    print(f"\n🔌  Connecting to {url} as {email}")
    print(f"🔑  Token type: {token_type}\n")

    cloud_id = os.environ.get("CLOUD_ID") if token_type == TOKEN_TYPE_SCOPED else None
    if token_type == TOKEN_TYPE_SCOPED and not cloud_id:
        print("❌  TOKEN_TYPE=scoped requires CLOUD_ID env var.")
        print("   Find it at: https://admin.atlassian.com → your org → select site → look at the URL")
        print("   URL format: https://admin.atlassian.com/s/<cloud-id>/...")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        client = JiraClient(url, email, token, session, token_type=token_type, cloud_id=cloud_id)

        # ── 0. Show effective base URL (scoped tokens only) ───────────────
        if token_type == TOKEN_TYPE_SCOPED:
            print(f"0️⃣  Using gateway base URL: {client._base_url}")
            print()

        # ── 1. Auth + search ──────────────────────────────────────────────
        print("1️⃣  Fetching open assigned issues...")
        try:
            issues = await client.search(JQL_OPEN_ASSIGNED, CORE_FIELDS)
        except JiraAuthError as e:
            print(f"❌  Auth failed: {e}")
            sys.exit(1)
        except JiraConnectionError as e:
            print(f"❌  Connection error: {e}")
            sys.exit(1)

        print(f"   ✅  {len(issues)} open assigned issue(s) found")
        if issues:
            sample = issues[0]
            f = sample.get("fields", {})
            print(f"   📄  Sample: [{sample['key']}] {f.get('summary', '(no summary)')[:80]}")
            print(f"       Status: {f.get('status', {}).get('name')} | "
                  f"Priority: {f.get('priority', {}).get('name')} | "
                  f"Project: {f.get('project', {}).get('key')}")

        # ── 2. Custom fields ──────────────────────────────────────────────
        print("\n2️⃣  Fetching custom fields...")
        custom_fields = await client.get_custom_fields()
        print(f"   ✅  {len(custom_fields)} custom field(s) available")
        for field_id, name in list(custom_fields.items())[:5]:
            print(f"       {field_id}: {name}")
        if len(custom_fields) > 5:
            print(f"       ... and {len(custom_fields) - 5} more")

        # ── 3. Priorities ─────────────────────────────────────────────────
        print("\n3️⃣  Fetching priority scheme...")
        priorities = await client.get_priorities()
        print(f"   ✅  Priorities: {priorities}")
        high_defaults_match = [p for p in DEFAULT_HIGH_PRIORITY_NAMES if p in priorities]
        if high_defaults_match:
            print(f"   ✅  Default high-priority names {DEFAULT_HIGH_PRIORITY_NAMES} overlap with instance")
        else:
            print(f"   ⚠️   Default high-priority names {DEFAULT_HIGH_PRIORITY_NAMES} do NOT appear in this instance")
            print(f"       You'll need to configure high-priority names in the Options Flow after setup")

        # ── 4. Aggregation dry-run ────────────────────────────────────────
        print("\n4️⃣  Running aggregator on live data...")
        result = aggregate(
            issues,
            custom_field_ids=[],
            due_within_days=DEFAULT_DUE_WITHIN_DAYS,
            high_priority_names=set(DEFAULT_HIGH_PRIORITY_NAMES),
        )
        print(f"   Total open:      {result['total']}")
        print(f"   Overdue:         {result['overdue']}")
        print(f"   Due within {DEFAULT_DUE_WITHIN_DAYS}d:  {result['due_within_x']}")
        print(f"   High priority:   {result['high_priority']}")
        print(f"   By project:      {dict(list(result['by_project'].items())[:5])}")
        print(f"   By type:         {dict(list(result['by_type'].items())[:5])}")
        print(f"   By status:       {dict(list(result['by_status'].items())[:5])}")

    print("\n✅  Smoke test complete — all systems go!\n")


if __name__ == "__main__":
    asyncio.run(main())
