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
    OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS,
)
from .newly_assigned import NewlyAssignedTracker

_LOGGER = logging.getLogger(__name__)


class JiraDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        client: JiraClient,
        entry: ConfigEntry,
        store: Store,
    ):
        self._client = client
        self._entry = entry
        self._store = store
        window = entry.options.get(OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS)
        self._tracker = NewlyAssignedTracker(window)
        self._poll_count = 0
        interval = entry.options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    @property
    def custom_field_ids(self) -> list[str]:
        return self._entry.options.get(OPT_CUSTOM_FIELDS, [])

    async def async_load_state(self) -> None:
        blob = await self._store.async_load()
        if blob:
            self._tracker = NewlyAssignedTracker.deserialize(
                blob,
                self._entry.options.get(OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS),
            )

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
        high_priority_names = set(
            self._entry.options.get(OPT_HIGH_PRIORITY_NAMES, DEFAULT_HIGH_PRIORITY_NAMES)
        )
        result = aggregate(
            issues, self.custom_field_ids, due_within, high_priority_names, now=now
        )

        current_keys = {i["key"] for i in issues}
        result.update(self._tracker.update(current_keys, now=now))

        self._poll_count += 1
        checkpoint = self._entry.options.get(OPT_CHECKPOINT_EVERY, DEFAULT_CHECKPOINT_EVERY)
        if checkpoint and self._poll_count % checkpoint == 0:
            await self.async_save_state()

        return result
