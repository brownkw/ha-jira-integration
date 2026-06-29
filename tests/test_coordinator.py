import sys
sys.path.insert(0, ".")
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
        {"key": "A-1", "fields": {
            "project": {"key": "A"}, "issuetype": {"name": "Bug"},
            "status": {"name": "To Do"}, "priority": {"name": "High"}, "duedate": None,
        }},
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
