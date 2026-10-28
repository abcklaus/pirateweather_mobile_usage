"""Data coordinator: follows the tracker, fetches forecasts, survives outages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api import (
    PirateWeatherAuthError,
    PirateWeatherClient,
    PirateWeatherError,
    PirateWeatherQuotaError,
)
from .const import (
    BACKOFF_INITIAL,
    BACKOFF_MAX,
    CONF_MAX_STALE,
    CONF_MIN_DISTANCE,
    CONF_TRACKER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_STALE,
    DEFAULT_MIN_DISTANCE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOCATION_REFRESH_COOLDOWN,
)

_LOGGER = logging.getLogger(__package__)

STORAGE_VERSION = 1
CACHE_SAVE_DELAY = 60  # seconds; keeps SD-card writes low

SOURCE_TRACKER = "tracker"
SOURCE_LAST_KNOWN = "last_known"
SOURCE_HOME = "home"

type PirateWeatherConfigEntry = ConfigEntry[PirateWeatherCoordinator]


@dataclass(slots=True)
class WeatherData:
    """A forecast together with where and when it was fetched."""

    forecast: dict[str, Any]
    latitude: float
    longitude: float
    location_source: str
    fetched_at: datetime
    calls_remaining: int | None = None
    calls_limit: int | None = None

    @property
    def age(self) -> timedelta:
        """Time since the forecast was fetched."""
        return dt_util.utcnow() - self.fetched_at

    @property
    def current(self) -> dict[str, Any]:
        """Current conditions.

        While the data is fresh this is the API's `currently` block. Once it
        is older than an hour (no network), the hourly forecast entry for the
        present hour is a better estimate, so that one is used instead.
        """
        currently = self.forecast.get("currently") or {}
        if self.age < timedelta(hours=1):
            return currently
        now_ts = dt_util.utcnow().timestamp()
        for hour in self.forecast.get("hourly", {}).get("data", []):
            start = hour.get("time", 0)
            if start <= now_ts < start + 3600:
                return hour
        return currently

    @property
    def today(self) -> dict[str, Any]:
        """Daily block for the current local day at the forecast location."""
        now_ts = dt_util.utcnow().timestamp()
        days = self.forecast.get("daily", {}).get("data", [])
        for day in days:
            start = day.get("time", 0)
            if start <= now_ts < start + 86400:
                return day
        return days[0] if days else {}

    def as_cache(self) -> dict[str, Any]:
        """Serialize for the persistent cache."""
        return {
            "forecast": self.forecast,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "location_source": self.location_source,
            "fetched_at": self.fetched_at.isoformat(),
        }

    @classmethod
    def from_cache(cls, raw: dict[str, Any]) -> WeatherData | None:
        """Restore from the persistent cache, None if unusable."""
        try:
            fetched_at = dt_util.parse_datetime(raw["fetched_at"])
            if fetched_at is None:
                return None
            return cls(
                forecast=raw["forecast"],
                latitude=float(raw["latitude"]),
                longitude=float(raw["longitude"]),
                location_source=raw["location_source"],
                fetched_at=fetched_at,
            )
        except (KeyError, TypeError, ValueError):
            return None


class PirateWeatherCoordinator(DataUpdateCoordinator[WeatherData]):
    """Fetches the forecast for the current tracker position.

    Failures that are expected on the road (no network, timeouts, server
    errors, exhausted quota) do not make the entities unavailable. The last
    forecast is kept, one warning is logged when the connection is lost and
    one info message when it is back, and retries back off up to an hour.
    """

    config_entry: PirateWeatherConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PirateWeatherConfigEntry,
        client: PirateWeatherClient,
    ) -> None:
        options = entry.options
        self._normal_interval = timedelta(
            minutes=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._normal_interval,
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=LOCATION_REFRESH_COOLDOWN.total_seconds(),
                immediate=True,
            ),
        )
        self._client = client
        self._tracker: str = entry.data[CONF_TRACKER]
        self._min_distance_km: float = options.get(
            CONF_MIN_DISTANCE, DEFAULT_MIN_DISTANCE
        )
        self._max_stale = timedelta(
            hours=options.get(CONF_MAX_STALE, DEFAULT_MAX_STALE)
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.failures = 0
        self.last_error: str | None = None

    @property
    def is_offline(self) -> bool:
        """True while the most recent fetch attempt failed."""
        return self.failures > 0

    async def async_load_cache(self) -> None:
        """Seed the coordinator with the forecast saved before the last restart."""
        raw = await self._store.async_load()
        if not raw:
            return
        cached = WeatherData.from_cache(raw)
        if cached is None or cached.age > self._max_stale:
            return
        self.data = cached
        _LOGGER.debug("Restored forecast from %s", cached.fetched_at)

    @callback
    def async_start_tracking(self) -> None:
        """Refresh early when the vehicle has moved far enough."""
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [self._tracker], self._async_tracker_changed
            )
        )

    @callback
    def _async_tracker_changed(self, event: Event[EventStateChangedData]) -> None:
        position = self._tracker_position()
        if position is None or self.data is None:
            return
        if self.is_offline:
            # The backoff timer retries anyway and will use the new position.
            return
        moved_km = (
            distance(self.data.latitude, self.data.longitude, *position) or 0
        ) / 1000
        if moved_km >= self._min_distance_km:
            _LOGGER.debug("Moved %.1f km, refreshing forecast", moved_km)
            self.hass.async_create_task(self.async_request_refresh())

    def _tracker_position(self) -> tuple[float, float] | None:
        state = self.hass.states.get(self._tracker)
        if state is None:
            return None
        try:
            lat = float(state.attributes[ATTR_LATITUDE])
            lon = float(state.attributes[ATTR_LONGITUDE])
        except (KeyError, TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon

    def _resolve_position(self) -> tuple[float, float, str]:
        if (position := self._tracker_position()) is not None:
            return (*position, SOURCE_TRACKER)
        if self.data is not None:
            return self.data.latitude, self.data.longitude, SOURCE_LAST_KNOWN
        return self.hass.config.latitude, self.hass.config.longitude, SOURCE_HOME

    async def _async_update_data(self) -> WeatherData:
        lat, lon, source = self._resolve_position()
        try:
            response = await self._client.async_get_forecast(lat, lon)
        except PirateWeatherAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PirateWeatherQuotaError as err:
            return self._handle_failure(err, BACKOFF_MAX)
        except PirateWeatherError as err:
            backoff = min(BACKOFF_INITIAL * 2**self.failures, BACKOFF_MAX)
            return self._handle_failure(err, backoff)

        if self.failures:
            _LOGGER.info(
                "Pirate Weather reachable again after %d failed attempt(s)",
                self.failures,
            )
        self.failures = 0
        self.last_error = None
        self.update_interval = self._normal_interval

        data = WeatherData(
            forecast=response.data,
            latitude=lat,
            longitude=lon,
            location_source=source,
            fetched_at=dt_util.utcnow(),
            calls_remaining=response.calls_remaining,
            calls_limit=response.calls_limit,
        )
        self._store.async_delay_save(data.as_cache, CACHE_SAVE_DELAY)
        return data

    def _handle_failure(
        self, err: PirateWeatherError, retry_in: timedelta
    ) -> WeatherData:
        self.failures += 1
        self.last_error = str(err)
        self.update_interval = retry_in

        if self.data is None:
            # Nothing to fall back to yet; the base class logs this only once.
            raise UpdateFailed(f"{err}; retrying in {retry_in}")
        if self.data.age > self._max_stale:
            raise UpdateFailed(
                f"{err}; last forecast is older than {self._max_stale}, retrying in {retry_in}"
            )

        if self.failures == 1:
            _LOGGER.warning(
                "Pirate Weather not reachable (%s). Keeping forecast from %s, "
                "retrying with increasing delay",
                err,
                dt_util.as_local(self.data.fetched_at).strftime("%Y-%m-%d %H:%M"),
            )
        else:
            _LOGGER.debug(
                "Attempt %d failed (%s), next in %s", self.failures, err, retry_in
            )
        return self.data
