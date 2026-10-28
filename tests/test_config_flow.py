"""Config flow tests."""

from __future__ import annotations

import re

import aiohttp
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pirateweather_mobile_usage.const import (
    CONF_LANGUAGE,
    CONF_MAX_STALE,
    CONF_MIN_DISTANCE,
    CONF_TRACKER,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

from .conftest import API_KEY, TRACKER

API_RE = re.compile(r"api\.pirateweather\.net/forecast/")

USER_INPUT = {CONF_NAME: "Wohnmobil", CONF_API_KEY: API_KEY, CONF_TRACKER: TRACKER}


@pytest.mark.usefixtures("tracker")
async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, forecast
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wohnmobil"
    assert result["data"] == {CONF_API_KEY: API_KEY, CONF_TRACKER: TRACKER}
    # The validation request used the tracker's position.
    assert "/47.5000,9.7500" in str(aioclient_mock.mock_calls[0][1])


@pytest.mark.usefixtures("tracker")
@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401}, "invalid_auth"),
        ({"status": 429}, "quota_exceeded"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"status": 418}, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs,
    error,
    forecast,
) -> None:
    aioclient_mock.get(API_RE, **mock_kwargs)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    # Recovers once the problem is gone.
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_RE, json=forecast)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unknown_tracker(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {CONF_TRACKER: "tracker_not_found"}


@pytest.mark.usefixtures("tracker", "config_entry")
async def test_user_flow_duplicate(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("tracker")
async def test_reauth_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "NEW-KEY"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "NEW-KEY"
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.usefixtures("tracker")
async def test_options_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    options = {
        CONF_UPDATE_INTERVAL: 30,
        CONF_MIN_DISTANCE: 5,
        CONF_MAX_STALE: 24,
        CONF_LANGUAGE: "en",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == options
