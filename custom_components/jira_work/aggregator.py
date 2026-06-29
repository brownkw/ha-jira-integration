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
    high_priority_names: set[str] = frozenset(),
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

    return {
        "total": len(issues),
        "by_project": _bucket(projects),
        "by_type": _bucket(types),
        "by_status": _bucket(statuses),
        "by_priority": _bucket(priorities),
        "overdue": len(overdue_keys),
        "overdue_keys": overdue_keys,
        "due_within_x": len(due_within_keys),
        "due_within_keys": due_within_keys,
        "high_priority": len(high_priority_keys),
        "high_priority_keys": high_priority_keys,
    }
