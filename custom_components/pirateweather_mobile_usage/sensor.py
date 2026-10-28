"""Individual sensors for automations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UV_INDEX,
    EntityCategory,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import PirateWeatherConfigEntry, PirateWeatherCoordinator, WeatherData
from .entity import PirateWeatherEntity, percent, precipitation_mm

PRECIP_TYPES = ["none", "rain", "snow", "sleet", "ice", "mixed"]
LOOKAHEAD_HOURS = 3


def _next_hours(
    data: WeatherData, hours: int = LOOKAHEAD_HOURS
) -> list[dict[str, Any]]:
    """Hourly blocks overlapping the next few hours."""
    now_ts = dt_util.utcnow().timestamp()
    end_ts = now_ts + hours * 3600
    return [
        hour
        for hour in data.forecast.get("hourly", {}).get("data", [])
        if hour.get("time", 0) + 3600 > now_ts and hour.get("time", 0) < end_ts
    ]


def _max_next_hours(data: WeatherData, key: str) -> float | None:
    values = [v for hour in _next_hours(data) if (v := hour.get(key)) is not None]
    return max(values) if values else None


def _active_alerts(data: WeatherData) -> list[dict[str, Any]]:
    now_ts = dt_util.utcnow().timestamp()
    return [
        alert
        for alert in data.forecast.get("alerts") or []
        if (expires := alert.get("expires", -999)) == -999 or expires > now_ts
    ]


def _alert_attributes(data: WeatherData) -> dict[str, Any]:
    return {
        "alerts": [
            {
                "title": alert.get("title"),
                "severity": alert.get("severity"),
                "regions": alert.get("regions"),
                "issued": dt_util.utc_from_timestamp(alert["time"]).isoformat()
                if alert.get("time")
                else None,
                "expires": dt_util.utc_from_timestamp(alert["expires"]).isoformat()
                if alert.get("expires", -999) > 0
                else None,
                "description": alert.get("description"),
                "uri": alert.get("uri"),
            }
            for alert in _active_alerts(data)
        ]
    }


def _text(value: Any) -> str | None:
    """Clip free text to the 255 characters a state may hold."""
    return None if value is None else str(value)[:255]


@dataclass(frozen=True, kw_only=True)
class PirateWeatherSensorDescription(SensorEntityDescription):
    """Sensor description with value extraction."""

    value_fn: Callable[[WeatherData], StateType | datetime]
    attr_fn: Callable[[WeatherData], dict[str, Any]] | None = None
    # Most sensors are opt-in; enable the ones your automations need.
    entity_registry_enabled_default: bool = False


def _current(key: str, convert: Callable[[Any], Any] | None = None):
    def value(data: WeatherData) -> Any:
        raw = data.current.get(key)
        return convert(raw) if convert and raw is not None else raw

    return value


SENSORS: tuple[PirateWeatherSensorDescription, ...] = (
    # Current conditions
    PirateWeatherSensorDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("temperature"),
    ),
    PirateWeatherSensorDescription(
        key="apparent_temperature",
        translation_key="apparent_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("apparentTemperature"),
    ),
    PirateWeatherSensorDescription(
        key="dew_point",
        translation_key="dew_point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("dewPoint"),
    ),
    PirateWeatherSensorDescription(
        key="humidity",
        translation_key="humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("humidity", percent),
    ),
    PirateWeatherSensorDescription(
        key="pressure",
        translation_key="pressure",
        native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("pressure"),
    ),
    PirateWeatherSensorDescription(
        key="wind_speed",
        translation_key="wind_speed",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("windSpeed"),
    ),
    PirateWeatherSensorDescription(
        key="wind_gust",
        translation_key="wind_gust",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("windGust"),
    ),
    PirateWeatherSensorDescription(
        key="wind_bearing",
        translation_key="wind_bearing",
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        value_fn=_current("windBearing"),
    ),
    PirateWeatherSensorDescription(
        key="cloud_cover",
        translation_key="cloud_cover",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("cloudCover", percent),
    ),
    PirateWeatherSensorDescription(
        key="visibility",
        translation_key="visibility",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("visibility"),
    ),
    PirateWeatherSensorDescription(
        key="uv_index",
        translation_key="uv_index",
        native_unit_of_measurement=UV_INDEX,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("uvIndex"),
    ),
    PirateWeatherSensorDescription(
        key="precip_intensity",
        translation_key="precip_intensity",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("precipIntensity"),
    ),
    PirateWeatherSensorDescription(
        key="precip_probability",
        translation_key="precip_probability",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("precipProbability", percent),
    ),
    PirateWeatherSensorDescription(
        key="precip_type",
        translation_key="precip_type",
        device_class=SensorDeviceClass.ENUM,
        options=PRECIP_TYPES,
        value_fn=lambda data: (
            t if (t := data.current.get("precipType")) in PRECIP_TYPES else "none"
        ),
    ),
    PirateWeatherSensorDescription(
        key="nearest_storm_distance",
        translation_key="nearest_storm_distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current("nearestStormDistance"),
    ),
    PirateWeatherSensorDescription(
        key="nearest_storm_bearing",
        translation_key="nearest_storm_bearing",
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        value_fn=_current("nearestStormBearing"),
    ),
    PirateWeatherSensorDescription(
        key="summary",
        translation_key="summary",
        value_fn=lambda data: _text(data.current.get("summary")),
    ),
    # Next hours: made for "retract the awning" style automations
    PirateWeatherSensorDescription(
        key="precip_probability_next_hours",
        translation_key="precip_probability_next_hours",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: percent(_max_next_hours(data, "precipProbability")),
    ),
    PirateWeatherSensorDescription(
        key="wind_gust_next_hours",
        translation_key="wind_gust_next_hours",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _max_next_hours(data, "windGust"),
    ),
    PirateWeatherSensorDescription(
        key="hourly_summary",
        translation_key="hourly_summary",
        value_fn=lambda data: _text(data.forecast.get("hourly", {}).get("summary")),
    ),
    # Today
    PirateWeatherSensorDescription(
        key="today_temperature_max",
        translation_key="today_temperature_max",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda data: data.today.get("temperatureMax"),
    ),
    PirateWeatherSensorDescription(
        key="today_temperature_min",
        translation_key="today_temperature_min",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda data: data.today.get("temperatureMin"),
    ),
    PirateWeatherSensorDescription(
        key="today_precip_probability",
        translation_key="today_precip_probability",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: percent(data.today.get("precipProbability")),
    ),
    PirateWeatherSensorDescription(
        key="today_precipitation",
        translation_key="today_precipitation",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        value_fn=lambda data: precipitation_mm(data.today),
    ),
    PirateWeatherSensorDescription(
        key="today_summary",
        translation_key="today_summary",
        value_fn=lambda data: _text(data.today.get("summary")),
    ),
    # Enabled by default
    PirateWeatherSensorDescription(
        key="alerts",
        translation_key="alerts",
        value_fn=lambda data: len(_active_alerts(data)),
        attr_fn=_alert_attributes,
        entity_registry_enabled_default=True,
    ),
    PirateWeatherSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.fetched_at,
        entity_registry_enabled_default=True,
    ),
    PirateWeatherSensorDescription(
        key="api_calls_remaining",
        translation_key="api_calls_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.calls_remaining,
        attr_fn=lambda data: {"monthly_limit": data.calls_limit},
        entity_registry_enabled_default=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PirateWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        PirateWeatherSensor(coordinator, description) for description in SENSORS
    )


class PirateWeatherSensor(PirateWeatherEntity, SensorEntity):
    """A single value from the forecast."""

    entity_description: PirateWeatherSensorDescription

    def __init__(
        self,
        coordinator: PirateWeatherCoordinator,
        description: PirateWeatherSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data)
