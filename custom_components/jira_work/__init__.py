"""The Jira Work integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import JiraClient
from .const import (
    CONF_CLOUD_ID, CONF_EMAIL, CONF_TOKEN, CONF_TOKEN_TYPE, CONF_URL,
    DOMAIN, STORAGE_KEY, STORAGE_VERSION, TOKEN_TYPE_CLASSIC,
)
from .coordinator import JiraDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = JiraClient(
        entry.data[CONF_URL],
        entry.data[CONF_EMAIL],
        entry.data[CONF_TOKEN],
        session,
        token_type=entry.data.get(CONF_TOKEN_TYPE, TOKEN_TYPE_CLASSIC),
        cloud_id=entry.data.get(CONF_CLOUD_ID),
    )
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
    coordinator = JiraDataUpdateCoordinator(hass, client, entry, store)
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    async def _on_stop(event: Event) -> None:
        await coordinator.async_save_state()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_save_state()
    return unloaded
