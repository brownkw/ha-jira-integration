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
    # Optional — only required when token_type == scoped; validated manually below.
    vol.Optional(CONF_CLOUD_ID, default=""): str,
})


async def _validate(
    hass, data: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Validate credentials and return (custom_fields, priorities).

    For scoped tokens, the cloud_id must already be present in data — it is
    supplied by the user in the config flow and passed through to JiraClient
    directly. No network call is needed to resolve it.
    """
    session = async_get_clientsession(hass)
    token_type = data.get(CONF_TOKEN_TYPE, TOKEN_TYPE_CLASSIC)
    cloud_id = data.get(CONF_CLOUD_ID)
    client = JiraClient(
        data[CONF_URL], data[CONF_EMAIL], data[CONF_TOKEN], session,
        token_type=token_type,
        cloud_id=cloud_id,
    )
    # Fetch issues first so we can filter custom fields to only those
    # that are actually populated on the user's assigned tickets.
    import asyncio
    from .const import JQL_OPEN_ASSIGNED
    # Run all three calls concurrently — field list and priorities don't depend
    # on the issue sample, so we fan them out and let them race.
    issues, all_fields, priorities = await asyncio.gather(
        client.search(jql=JQL_OPEN_ASSIGNED, fields=["*all"], page_size=10),
        client.get_custom_fields(),
        client.get_priorities(),
    )
    # Now filter the full field list down to only those populated on our issues
    if issues:
        populated: set[str] = set()
        for issue in issues:
            for key, val in issue.get("fields", {}).items():
                if key.startswith("customfield_") and val is not None:
                    populated.add(key)
        custom_fields = {k: v for k, v in all_fields.items() if k in populated}
    else:
        custom_fields = all_fields
    return custom_fields, priorities


class JiraWorkConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Manual validation: cloud_id required for scoped tokens
            if (
                user_input.get(CONF_TOKEN_TYPE) == TOKEN_TYPE_SCOPED
                and not user_input.get(CONF_CLOUD_ID, "").strip()
            ):
                errors[CONF_CLOUD_ID] = "cloud_id_required"
            else:
                try:
                    custom_fields, priorities = await _validate(self.hass, user_input)
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
                    # Strip empty cloud_id for classic tokens
                    entry_data = {k: v for k, v in user_input.items() if v != ""}
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
            custom_fields, priorities = await _validate(self.hass, dict(self._entry.data))
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
