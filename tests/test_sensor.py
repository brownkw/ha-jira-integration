import sys
sys.path.insert(0, ".")
from unittest.mock import MagicMock
from custom_components.jira_work.sensor import (
    JiraTotalSensor, JiraOverdueSensor, JiraDueWithinSensor,
    JiraHighPrioritySensor, JiraNewlyAssignedSensor, JiraNewLastWindowSensor,
)

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


def _coord(data):
    c = MagicMock()
    c.data = data
    c.last_update_success = True
    c._entry = MagicMock()
    c._entry.options = {}
    return c


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


def test_new_last_window_reflects_configured_hours():
    coord = _coord(DATA)
    coord._entry.options = {"rolling_window_hours": 48}
    s = JiraNewLastWindowSensor(coord, "e")
    assert s.extra_state_attributes["window_hours"] == 48


def test_new_last_window_defaults_to_24():
    coord = _coord(DATA)
    coord._entry.options = {}
    s = JiraNewLastWindowSensor(coord, "e")
    assert s.extra_state_attributes["window_hours"] == 24
