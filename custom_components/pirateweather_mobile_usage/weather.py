"""Weather entity for Pirate Weather Mobile."""

from __future__ import annotations

from typing import Any

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import PirateWeatherConfigEntry, PirateWeatherCoordinator
from .entity import PirateWeatherEntity, map_condition, percent, precipitation_mm


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PirateWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the weather entity."""
    async_add_entities([PirateWeatherMobileWeather(entry.runtime_data)])


def _iso(ts: float) -> str:
    return dt_util.utc_from_timestamp(ts).isoformat()


class PirateWeatherMobileWeather(
    PirateWeatherEntity, SingleCoordinatorWeatherEntity[PirateWeatherCoordinator]
):
    """Current conditions and forecast at the tracker's position."""

    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: PirateWeatherCoordinator) -> None:
        # The MRO runs SingleCoordinatorWeatherEntity.__init__ via super().
        super().__init__(coordinator, "weather")

    @property
    def _current(self) -> dict[str, Any]:
        return self.coordinator.data.current

    @property
    def condition(self) -> str | None:
        return map_condition(self._current)

    @property
    def native_temperature(self) -> float | None:
        return self._current.get("temperature")

    @property
    def native_apparent_temperature(self) -> float | None:
        return self._current.get("apparentTemperature")

    @property
    def native_dew_point(self) -> float | None:
        return self._current.get("dewPoint")

    @property
    def humidity(self) -> float | None:
        return percent(self._current.get("humidity"))

    @property
    def cloud_coverage(self) -> float | None:
        return percent(self._current.get("cloudCover"))

    @property
    def native_pressure(self) -> float | None:
        return self._current.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        return self._current.get("windSpeed")

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._current.get("windGust")

    @property
    def wind_bearing(self) -> float | None:
        return self._current.get("windBearing")

    @property
    def native_visibility(self) -> float | None:
        return self._current.get("visibility")

    @property
    def uv_index(self) -> float | None:
        return self._current.get("uvIndex")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "forecast_latitude": data.latitude,
            "forecast_longitude": data.longitude,
            "location_source": data.location_source,
            "last_update": dt_util.as_local(data.fetched_at).isoformat(),
            "offline": self.coordinator.is_offline,
            "summary": data.forecast.get("hourly", {}).get("summary"),
        }

    def _blocks(self, name: str, period: int) -> list[dict[str, Any]]:
        """Forecast entries whose period has not ended yet.

        Matters when the forecast is hours old because the network is down.
        """
        now_ts = dt_util.utcnow().timestamp()
        return [
            block
            for block in self.coordinator.data.forecast.get(name, {}).get("data", [])
            if block.get("time", 0) + period > now_ts
        ]

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        return [
            Forecast(
                datetime=_iso(hour["time"]),
                condition=map_condition(hour),
                native_temperature=hour.get("temperature"),
                native_apparent_temperature=hour.get("apparentTemperature"),
                native_dew_point=hour.get("dewPoint"),
                native_precipitation=round(hour.get("precipIntensity") or 0, 2),
                precipitation_probability=percent(hour.get("precipProbability")),
                humidity=percent(hour.get("humidity")),
                cloud_coverage=percent(hour.get("cloudCover")),
                native_pressure=hour.get("pressure"),
                native_wind_speed=hour.get("windSpeed"),
                native_wind_gust_speed=hour.get("windGust"),
                wind_bearing=hour.get("windBearing"),
                uv_index=hour.get("uvIndex"),
            )
            for hour in self._blocks("hourly", 3600)
        ]

    @callback
    def _async_forecast_daily(self) -> list[Forecast] | None:
        return [
            Forecast(
                datetime=_iso(day["time"]),
                condition=map_condition(day),
                native_temperature=day.get("temperatureMax"),
                native_templow=day.get("temperatureMin"),
                native_precipitation=precipitation_mm(day),
                precipitation_probability=percent(day.get("precipProbability")),
                humidity=percent(day.get("humidity")),
                cloud_coverage=percent(day.get("cloudCover")),
                native_pressure=day.get("pressure"),
                native_wind_speed=day.get("windSpeed"),
                native_wind_gust_speed=day.get("windGust"),
                wind_bearing=day.get("windBearing"),
                uv_index=day.get("uvIndex"),
            )
            for day in self._blocks("daily", 86400)
        ]
