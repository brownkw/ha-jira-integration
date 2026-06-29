import sys
sys.path.insert(0, ".")
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.data_entry_flow import FlowResultType
from custom_components.jira_work.const import CONF_EMAIL, CONF_TOKEN, CONF_URL, DOMAIN

USER_INPUT = {
    CONF_URL: "https://example.atlassian.net",
    CONF_EMAIL: "me@example.com",
    CONF_TOKEN: "secret",
}


async def test_user_flow_success(hass):
    with patch(
        "custom_components.jira_work.config_flow._validate",
        new=AsyncMock(return_value=(
            {"customfield_10020": "Story Points"},
            ["Blocker", "Critical", "Major", "Minor", "Trivial"],
        )),
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
