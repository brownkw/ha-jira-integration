import sys
sys.path.insert(0, ".")
from datetime import datetime, timezone
from freezegun import freeze_time
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


# ── Task 4: alertable counts ──────────────────────────────────────────────────

def _now():
    return datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


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
    assert r["high_priority"] == 0


def test_high_priority_count():
    issues = [
        _issue("A-1", "A", "Bug", "To Do", "Blocker"),
        _issue("A-2", "A", "Bug", "To Do", "Critical"),
        _issue("A-3", "A", "Bug", "To Do", "Major"),
    ]
    r = aggregate(issues, custom_field_ids=[], due_within_days=3, high_priority_names={"Blocker", "Critical"}, now=_now())
    assert r["high_priority"] == 2
    assert sorted(r["high_priority_keys"]) == ["A-1", "A-2"]


def test_due_today_is_within_window():
    """Items due today (days=0 delta) should appear in due_within, not overdue."""
    issues = [_issue("A-1", "A", "Bug", "To Do", duedate="2026-06-28")]
    r = aggregate(issues, custom_field_ids=[], due_within_days=3, now=_now())
    assert r["overdue"] == 0
    assert r["due_within_x"] == 1
