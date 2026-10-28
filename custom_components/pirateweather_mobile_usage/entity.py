"""Shared entity base and conversion helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_KEY_URL, ATTRIBUTION, DOMAIN
from .coordinator import PirateWeatherCoordinator

# Pirate Weather icon -> Home Assistant condition
CONDITION_MAP: dict[str, str] = {
    "clear-day": "sunny",
    "clear-night": "clear-night",
    "rain": "rainy",
    "snow": "snowy",
    "sleet": "snowy-rainy",
    "mixed": "snowy-rainy",
    "hail": "hail",
    "wind": "windy",
    "fog": "fog",
    "haze": "fog",
    "smoke": "fog",
    "cloudy": "cloudy",
    "partly-cloudy-day": "partlycloudy",
    "partly-cloudy-night": "partlycloudy",
    "thunderstorm": "lightning-rainy",
}

POURING_THRESHOLD = 7.6  # mm/h, "heavy rain" per WMO


def map_condition(block: dict[str, Any]) -> str | None:
    """Map a data point's icon to a Home Assistant condition."""
    cond = CONDITION_MAP.get(block.get("icon", ""))
    if cond == "rainy" and (block.get("precipIntensity") or 0) >= POURING_THRESHOLD:
        return "pouring"
    return cond


def percent(value: float | None) -> float | None:
    """0..1 fraction to percent."""
    return None if value is None else round(value * 100, 1)


def precipitation_mm(block: dict[str, Any]) -> float | None:
    """Liquid-equivalent precipitation of an hourly or daily block in mm.

    `precipAccumulation` is in cm and counts snow by depth, so with the
    split fields available snow is converted to water equivalent (~1:10).
    """
    liquid = block.get("liquidAccumulation")
    snow = block.get("snowAccumulation")
    ice = block.get("iceAccumulation")
    if liquid is not None or snow is not None or ice is not None:
        return round((liquid or 0) * 10 + (snow or 0) + (ice or 0) * 10, 2)
    if (total := block.get("precipAccumulation")) is not None:
        return round(total * 10, 2)
    return None


class PirateWeatherEntity(CoordinatorEntity[PirateWeatherCoordinator]):
    """Common device info and availability."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: PirateWeatherCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pirate Weather",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=API_KEY_URL,
        )

    @property
    def available(self) -> bool:
        """Available as soon as any forecast (also a cached one) exists."""
        return super().available and self.coordinator.data is not None
