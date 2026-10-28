"""Pirate Weather forecasts that follow a moving device tracker."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PirateWeatherClient
from .const import CONF_LANGUAGE, DEFAULT_LANGUAGE
from .coordinator import PirateWeatherConfigEntry, PirateWeatherCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.WEATHER]


async def async_setup_entry(
    hass: HomeAssistant, entry: PirateWeatherConfigEntry
) -> bool:
    """Set up Pirate Weather Mobile from a config entry."""
    client = PirateWeatherClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
    )
    coordinator = PirateWeatherCoordinator(hass, entry, client)
    await coordinator.async_load_cache()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # No async_config_entry_first_refresh(): without network at startup the
    # entities should come up with the cached forecast (or unavailable)
    # instead of the entry being retried as "not ready", and a hanging
    # request must not delay Home Assistant's startup.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{entry.entry_id}_first_refresh"
    )
    coordinator.async_start_tracking()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PirateWeatherConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: PirateWeatherConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
