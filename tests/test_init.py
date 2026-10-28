"""Behaviour tests: entities, offline handling, movement, cache."""

from __future__ import annotations

from datetime import timedelta
import logging
import re

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
    SERVICE_GET_FORECASTS,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pirateweather_mobile_usage.const import DOMAIN

from .conftest import API_KEY, LAT, LON, TRACKER, make_forecast

API_RE = re.compile(r"api\.pirateweather\.net/forecast/")
WEATHER = "weather.wohnmobil"

pytestmark = pytest.mark.usefixtures("tracker")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_weather_entity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    aioclient_mock.get(
        API_RE,
        json=forecast,
        headers={"Ratelimit-Remaining": "9876", "Ratelimit-Limit": "10000"},
    )
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get(WEATHER)
    assert state.state == "partlycloudy"
    assert state.attributes["temperature"] == 18.0
    assert state.attributes["humidity"] == 55
    assert state.attributes["forecast_latitude"] == LAT
    assert state.attributes["location_source"] == "tracker"
    assert state.attributes["offline"] is False

    url = aioclient_mock.mock_calls[0][1]
    assert url.query["units"] == "si"
    assert url.query["lang"] == "de"

    result = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {"entity_id": WEATHER, "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    hourly = result[WEATHER]["forecast"]
    # The two hours in the past are dropped, the current hour is kept.
    assert len(hourly) == 48
    assert hourly[2]["condition"] == "rainy"
    assert hourly[2]["precipitation_probability"] == 80

    result = await hass.services.async_call(
        WEATHER_DOMAIN,
        SERVICE_GET_FORECASTS,
        {"entity_id": WEATHER, "type": "daily"},
        blocking=True,
        return_response=True,
    )
    daily = result[WEATHER]["forecast"]
    assert len(daily) == 8
    assert daily[0]["temperature"] == 22.0
    assert daily[0]["templow"] == 11.0
    assert daily[0]["precipitation"] == 2.5  # 0.25 cm

    # Sensors enabled by default
    assert hass.states.get("sensor.wohnmobil_weather_alerts").state == "1"
    assert hass.states.get("sensor.wohnmobil_api_calls_remaining").state == "9876"
    assert hass.states.get("sensor.wohnmobil_last_update") is not None

    # Everything else exists but is disabled
    registry = er.async_get(hass)
    entry = registry.async_get("sensor.wohnmobil_precipitation_probability_next_3_h")
    assert entry is not None and entry.disabled


async def test_optional_sensor_values(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    registry = er.async_get(hass)
    for key in (
        "precip_probability_next_hours",
        "wind_gust_next_hours",
        "today_precipitation",
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{config_entry.entry_id}_{key}",
            config_entry=config_entry,
            suggested_object_id=key,
        )
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.precip_probability_next_hours").state == "80.0"
    # 14 m/s (pre-created registry entries skip the suggested km/h unit)
    assert hass.states.get("sensor.wind_gust_next_hours").state == "14.0"
    assert hass.states.get("sensor.today_precipitation").state == "2.5"


async def test_offline_keeps_data_and_backs_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    config_entry,
    forecast,
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.get(API_RE, exc=aiohttp.ClientConnectorError(None, OSError("down")))
    caplog.clear()
    caplog.set_level(logging.DEBUG)

    await _tick(hass, freezer, timedelta(minutes=15))
    assert coordinator.update_interval == timedelta(minutes=2)
    await _tick(hass, freezer, timedelta(minutes=2))
    assert coordinator.update_interval == timedelta(minutes=4)
    await _tick(hass, freezer, timedelta(minutes=4))
    assert coordinator.update_interval == timedelta(minutes=8)
    assert len(aioclient_mock.mock_calls) == 3

    state = hass.states.get(WEATHER)
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["offline"] is True

    warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith("custom_components")
    ]
    assert len(warnings) == 1
    assert "not reachable" in warnings[0].getMessage()
    assert API_KEY not in caplog.text

    # Movement while offline does not cause extra requests.
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT + 0.5, "longitude": LON}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(aioclient_mock.mock_calls) == 3

    # Back online: new position is used, normal interval restored.
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_RE, json=make_forecast(temperature=5.0))
    caplog.clear()
    await _tick(hass, freezer, timedelta(minutes=8))
    assert "/48.0000,9.7500" in str(aioclient_mock.mock_calls[0][1])
    assert coordinator.update_interval == timedelta(minutes=15)
    assert hass.states.get(WEATHER).attributes["temperature"] == 5.0
    assert "reachable again" in caplog.text


async def test_offline_uses_hourly_forecast_as_current(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    config_entry,
) -> None:
    freezer.move_to("2030-07-01T12:30:00+00:00")
    aioclient_mock.get(API_RE, json=make_forecast())
    await _setup(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_RE, exc=aiohttp.ClientConnectionError())

    await _tick(hass, freezer, timedelta(hours=3))
    # 15:30 lies in the hourly entry starting 15:00, temperature 18 + 3
    assert hass.states.get(WEATHER).attributes["temperature"] == 21.0


async def test_stale_data_becomes_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    config_entry,
    forecast,
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_RE, exc=aiohttp.ClientConnectionError())

    for _ in range(14):
        await _tick(hass, freezer, timedelta(hours=1))
    assert hass.states.get(WEATHER).state == STATE_UNAVAILABLE


async def test_movement_triggers_refresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    config_entry,
    forecast,
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    assert len(aioclient_mock.mock_calls) == 1

    # ~1 km: below the 2 km threshold
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT + 0.009, "longitude": LON}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(aioclient_mock.mock_calls) == 1

    # ~3.3 km
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT + 0.03, "longitude": LON}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(aioclient_mock.mock_calls) == 2
    assert "/47.5300,9.7500" in str(aioclient_mock.mock_calls[1][1])

    # Further movement within the cooldown is coalesced into one request.
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT + 0.06, "longitude": LON}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT + 0.09, "longitude": LON}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(aioclient_mock.mock_calls) == 2
    await _tick(hass, freezer, timedelta(minutes=5, seconds=1))
    assert len(aioclient_mock.mock_calls) == 3
    assert "/47.5900,9.7500" in str(aioclient_mock.mock_calls[2][1])


async def test_tracker_without_gps_uses_last_position(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    config_entry,
    forecast,
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    hass.states.async_set(TRACKER, "unavailable", {})
    await _tick(hass, freezer, timedelta(minutes=15))
    assert "/47.5000,9.7500" in str(aioclient_mock.mock_calls[-1][1])
    assert hass.states.get(WEATHER).attributes["location_source"] == "last_known"


async def test_cache_survives_restart_offline(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage,
    config_entry,
    forecast,
) -> None:
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{config_entry.entry_id}",
        "data": {
            "forecast": forecast,
            "latitude": LAT,
            "longitude": LON,
            "location_source": "tracker",
            "fetched_at": (dt_util.utcnow() - timedelta(minutes=30)).isoformat(),
        },
    }
    aioclient_mock.get(API_RE, exc=aiohttp.ClientConnectionError())
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get(WEATHER)
    assert state.state == "partlycloudy"
    assert state.attributes["offline"] is True


async def test_offline_at_first_start_without_cache(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry
) -> None:
    aioclient_mock.get(API_RE, exc=aiohttp.ClientConnectionError())
    await _setup(hass, config_entry)
    # Setup succeeds anyway (no "not ready" retry loop); entities wait for data.
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(WEATHER).state == STATE_UNAVAILABLE


async def test_rejected_key_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry
) -> None:
    aioclient_mock.get(API_RE, status=401)
    await _setup(hass, config_entry)
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == SOURCE_REAUTH for f in flows)


async def test_unload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redact_api_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry, forecast
) -> None:
    from custom_components.pirateweather_mobile_usage.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    aioclient_mock.get(API_RE, json=forecast)
    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert API_KEY not in str(diag)
    assert diag["data"]["location_source"] == "tracker"
