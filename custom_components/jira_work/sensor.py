"""Sensor entities for Jira Work."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS


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

    def __init__(self, c, e):
        super().__init__(c, e, "overdue", "Overdue", "mdi:alert")


class JiraDueWithinSensor(_Count):
    value_key, keys_key = "due_within_x", "due_within_keys"

    def __init__(self, c, e):
        super().__init__(c, e, "due_within", "Due soon", "mdi:clock-alert")


class JiraHighPrioritySensor(_Count):
    value_key, keys_key = "high_priority", "high_priority_keys"

    def __init__(self, c, e):
        super().__init__(c, e, "high_priority", "High priority", "mdi:flag")


class JiraNewlyAssignedSensor(_Count):
    value_key, keys_key = "newly_assigned", "new_keys"

    def __init__(self, c, e):
        super().__init__(c, e, "newly_assigned", "Newly assigned", "mdi:bell-ring")


class JiraNewLastWindowSensor(_Base):
    def __init__(self, c, e):
        super().__init__(c, e, "new_last_window", "New (rolling)", "mdi:history")

    @property
    def native_value(self):
        return self._d().get("new_last_window")

    @property
    def extra_state_attributes(self):
        window = self.coordinator._entry.options.get(OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS)
        return {"window_hours": window}


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
