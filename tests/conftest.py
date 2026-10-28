"""Fixtures for Pirate Weather Mobile tests."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pirateweather_mobile_usage.const import CONF_TRACKER, DOMAIN

API_KEY = "SECRET-TEST-KEY-123"
TRACKER = "device_tracker.wohnmobil"
LAT, LON = 47.5000, 9.7500


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the integration from custom_components."""


def make_forecast(
    temperature: float = 18.0, icon: str = "partly-cloudy-day"
) -> dict[str, Any]:
    """A trimmed API response anchored at the current (frozen) time."""
    now = int(dt_util.utcnow().timestamp())
    hour0 = now - now % 3600
    day0 = now - now % 86400
    hourly = [
        {
            "time": hour0 + i * 3600,
            "icon": "rain" if i == 2 else icon,
            "temperature": temperature + i,
            "apparentTemperature": temperature + i - 1,
            "dewPoint": 9.0,
            "humidity": 0.62,
            "pressure": 1014.2,
            "windSpeed": 3.5,
            "windGust": 14.0 if i == 2 else 6.0,
            "windBearing": 240,
            "cloudCover": 0.4,
            "uvIndex": 3,
            "precipIntensity": 1.2 if i == 2 else 0.0,
            "precipProbability": 0.8 if i == 2 else 0.1,
            "precipType": "rain" if i == 2 else "none",
        }
        for i in range(-2, 48)
    ]
    daily = [
        {
            "time": day0 + i * 86400,
            "icon": "rain" if i == 1 else "clear-day",
            "summary": "Sonnig." if i == 0 else "Regen.",
            "temperatureMax": 22.0 + i,
            "temperatureMin": 11.0 + i,
            "precipProbability": 0.3,
            "liquidAccumulation": 0.25,
            "snowAccumulation": 0.0,
            "iceAccumulation": 0.0,
            "precipAccumulation": 0.25,
            "windSpeed": 4.0,
            "windGust": 9.0,
            "windBearing": 200,
            "humidity": 0.6,
            "cloudCover": 0.3,
            "uvIndex": 5,
            "pressure": 1013.0,
        }
        for i in range(-1, 8)
    ]
    return {
        "latitude": LAT,
        "longitude": LON,
        "currently": {
            "time": now,
            "icon": icon,
            "summary": "Teilweise bewölkt",
            "temperature": temperature,
            "apparentTemperature": temperature - 1,
            "dewPoint": 8.5,
            "humidity": 0.55,
            "pressure": 1015.0,
            "windSpeed": 3.0,
            "windGust": 7.5,
            "windBearing": 250,
            "cloudCover": 0.45,
            "uvIndex": 2,
            "visibility": 16.1,
            "precipIntensity": 0.0,
            "precipProbability": 0.05,
            "precipType": "none",
            "nearestStormDistance": 42.0,
            "nearestStormBearing": 180,
        },
        "hourly": {"summary": "Am Nachmittag Regen.", "data": hourly},
        "daily": {"summary": "Wechselhaft.", "data": daily},
        "alerts": [
            {
                "title": "Sturmböen",
                "severity": "Moderate",
                "regions": ["Bodensee"],
                "time": now - 3600,
                "expires": now + 7200,
                "description": "Es treten Sturmböen auf.",
                "uri": "https://example.invalid/alert",
            },
            {
                "title": "Abgelaufen",
                "severity": "Minor",
                "regions": [],
                "time": now - 7200,
                "expires": now - 60,
                "description": "",
                "uri": "",
            },
        ],
        "flags": {"units": "si", "version": "V2.test"},
    }


@pytest.fixture
def forecast() -> dict[str, Any]:
    return make_forecast()


@pytest.fixture
def tracker(hass: HomeAssistant) -> None:
    hass.states.async_set(
        TRACKER, "not_home", {"latitude": LAT, "longitude": LON, "gps_accuracy": 10}
    )


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnmobil",
        unique_id=TRACKER,
        data={CONF_API_KEY: API_KEY, CONF_TRACKER: TRACKER},
    )
    entry.add_to_hass(hass)
    return entry
