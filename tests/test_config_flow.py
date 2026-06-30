import sys
sys.path.insert(0, ".")
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.data_entry_flow import FlowResultType
from custom_components.jira_work.const import (
    CONF_CLOUD_ID, CONF_EMAIL, CONF_TOKEN, CONF_TOKEN_TYPE, CONF_URL, DOMAIN,
    TOKEN_TYPE_CLASSIC, TOKEN_TYPE_SCOPED,
)

# _validate now returns (custom_fields, priorities)
_VALIDATE_RESULT = (
    {"customfield_10020": "Story Points"},
    ["Blocker", "Critical", "Major", "Minor", "Trivial"],
)

USER_INPUT_CLASSIC = {
    CONF_URL: "https://example.atlassian.net",
    CONF_EMAIL: "me@example.com",
    CONF_TOKEN: "secret",
    CONF_TOKEN_TYPE: TOKEN_TYPE_CLASSIC,
}

# Keep a plain USER_INPUT alias so existing test names don't change
USER_INPUT = USER_INPUT_CLASSIC


async def test_user_flow_success(hass):
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=_VALIDATE_RESULT),
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
        # Classic token: no cloud_id in entry data
        assert CONF_CLOUD_ID not in result2["data"]


async def test_user_flow_scoped_token_stores_cloud_id(hass):
    """Scoped token flow stores cloud_id (supplied by user) in config entry data."""
    scoped_input = {
        CONF_URL: "https://example.atlassian.net",
        CONF_EMAIL: "me@example.com",
        CONF_TOKEN: "secret",
        CONF_TOKEN_TYPE: TOKEN_TYPE_SCOPED,
        CONF_CLOUD_ID: "abc-123-cloud-id",
    }
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=_VALIDATE_RESULT),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], scoped_input
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
