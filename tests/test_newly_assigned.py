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
    res2 = t.update({"A-1", "A-2"}, now=later)     # A-2 aged out
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
