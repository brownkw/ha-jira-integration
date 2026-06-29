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
