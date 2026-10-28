"""Diagnostics support for Pirate Weather Mobile."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import PirateWeatherConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PirateWeatherConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "update_interval": str(coordinator.update_interval),
            "failures": coordinator.failures,
            "last_error": coordinator.last_error,
        },
        "data": None
        if data is None
        else {
            "fetched_at": data.fetched_at.isoformat(),
            "location_source": data.location_source,
            "calls_remaining": data.calls_remaining,
            "currently": data.forecast.get("currently"),
            "flags": data.forecast.get("flags"),
        },
    }
