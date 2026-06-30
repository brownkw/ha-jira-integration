"""Config flow for Jira Work."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JiraAuthError, JiraClient, JiraConnectionError, JiraError
from .const import (
    CONF_CLOUD_ID, CONF_EMAIL, CONF_TOKEN, CONF_TOKEN_TYPE, CONF_URL,
    DEFAULT_DUE_WITHIN_DAYS, DEFAULT_HIGH_PRIORITY_NAMES, DEFAULT_POLL_INTERVAL,
    DOMAIN, OPT_CUSTOM_FIELDS, OPT_DUE_WITHIN_DAYS, OPT_HIGH_PRIORITY_NAMES,
    OPT_POLL_INTERVAL, OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS,
    TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED,
)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_URL): str,
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_TOKEN): str,
    vol.Required(CONF_TOKEN_TYPE, default=TOKEN_TYPE_CLASSIC): vol.In(
        [TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED]
    ),
})


async def _validate(
    hass, data: dict[str, Any]
) -> tuple[dict[str, str], list[str], str | None]:
    """Validate credentials and return (custom_fields, priorities, cloud_id|None).

    For scoped tokens, resolves the cloud ID from tenant_info and stores it so
    the coordinator can reconstruct the correct gateway base URL without an
    extra network call on every HA restart.
    """
    session = async_get_clientsession(hass)
    token_type = data.get(CONF_TOKEN_TYPE, TOKEN_TYPE_CLASSIC)
    client = JiraClient(
        data[CONF_URL], data[CONF_EMAIL], data[CONF_TOKEN], session,
        token_type=token_type,
    )
    cloud_id: str | None = None
    if token_type == TOKEN_TYPE_SCOPED:
        cloud_id = await client.resolve_cloud_id()
    custom_fields = await client.get_custom_fields()
    priorities = await client.get_priorities()
    return custom_fields, priorities, cloud_id


class JiraWorkConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                custom_fields, priorities, cloud_id = await _validate(self.hass, user_input)
            except JiraAuthError:
                errors["base"] = "invalid_auth"
            except JiraConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_URL]}:{user_input[CONF_EMAIL]}"
                )
                self._abort_if_unique_id_configured()
                # Store cloud_id alongside credentials so the coordinator can
                # reconstruct the correct base URL without re-fetching tenant_info.
                entry_data = dict(user_input)
                if cloud_id is not None:
                    entry_data[CONF_CLOUD_ID] = cloud_id
                return self.async_create_entry(
                    title=user_input[CONF_URL],
                    data=entry_data,
                    options={
                        OPT_CUSTOM_FIELDS: [],
                        OPT_HIGH_PRIORITY_NAMES: list(DEFAULT_HIGH_PRIORITY_NAMES),
                        OPT_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                        OPT_DUE_WITHIN_DAYS: DEFAULT_DUE_WITHIN_DAYS,
                        OPT_ROLLING_WINDOW_HOURS: ROLLING_WINDOW_HOURS,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return JiraWorkOptionsFlow(config_entry)


class JiraWorkOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        try:
            custom_fields, priorities, _ = await _validate(self.hass, dict(self._entry.data))
        except JiraError:
            custom_fields, priorities = {}, list(DEFAULT_HIGH_PRIORITY_NAMES)

        current = self._entry.options
        schema = vol.Schema({
            vol.Optional(
                OPT_CUSTOM_FIELDS,
                default=current.get(OPT_CUSTOM_FIELDS, []),
            ): vol.All([vol.In(custom_fields)]),
            vol.Optional(
                OPT_HIGH_PRIORITY_NAMES,
                default=current.get(OPT_HIGH_PRIORITY_NAMES, DEFAULT_HIGH_PRIORITY_NAMES),
            ): vol.All([vol.In(priorities)]),
            vol.Optional(
                OPT_POLL_INTERVAL,
                default=current.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): vol.All(int, vol.Range(min=1, max=1440)),
            vol.Optional(
                OPT_DUE_WITHIN_DAYS,
                default=current.get(OPT_DUE_WITHIN_DAYS, DEFAULT_DUE_WITHIN_DAYS),
            ): vol.All(int, vol.Range(min=0, max=365)),
            vol.Optional(
                OPT_ROLLING_WINDOW_HOURS,
                default=current.get(OPT_ROLLING_WINDOW_HOURS, ROLLING_WINDOW_HOURS),
            ): vol.All(int, vol.Range(min=1, max=168)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
