import sys
sys.path.insert(0, ".")
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.data_entry_flow import FlowResultType
from custom_components.jira_work.const import (
    CONF_CLOUD_ID, CONF_EMAIL, CONF_TOKEN, CONF_TOKEN_TYPE, CONF_URL, DOMAIN,
    TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED,
)

# _validate now returns (custom_fields, priorities, cloud_id|None)
_VALIDATE_CLASSIC = (
    {"customfield_10020": "Story Points"},
    ["Blocker", "Critical", "Major", "Minor", "Trivial"],
    None,  # no cloud_id for classic tokens
)
_VALIDATE_SCOPED = (
    {"customfield_10020": "Story Points"},
    ["Blocker", "Critical", "Major", "Minor", "Trivial"],
    "abc-123-cloud-id",
)

USER_INPUT_CLASSIC = {
    CONF_URL: "https://example.atlassian.net",
    CONF_EMAIL: "me@example.com",
    CONF_TOKEN: "secret",
    CONF_TOKEN_TYPE: TOKEN_TYPE_CLASSIC,
}

USER_INPUT_SCOPED = {
    CONF_URL: "https://example.atlassian.net",
    CONF_EMAIL: "me@example.com",
    CONF_TOKEN: "secret",
    CONF_TOKEN_TYPE: TOKEN_TYPE_SCOPED,
}

# Keep a plain USER_INPUT alias so existing test names don't change
USER_INPUT = USER_INPUT_CLASSIC


async def test_user_flow_success(hass):
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=_VALIDATE_CLASSIC),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_EMAIL] == "me@example.com"
        # Classic token: no cloud_id stored
        assert CONF_CLOUD_ID not in result2["data"]


async def test_user_flow_scoped_token_stores_cloud_id(hass):
    """Scoped token flow must store cloud_id in config entry data."""
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=_VALIDATE_SCOPED),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT_SCOPED
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_CLOUD_ID] == "abc-123-cloud-id"
        assert result2["data"][CONF_TOKEN_TYPE] == TOKEN_TYPE_SCOPED


async def test_user_flow_bad_auth(hass):
    from custom_components.jira_work.api import JiraAuthError
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(side_effect=JiraAuthError("nope")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"
