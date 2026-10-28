"""Constants for the Pirate Weather Mobile integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "pirateweather_mobile_usage"

API_KEY_URL: Final = "https://pirate-weather.apiable.io/"

CONF_TRACKER: Final = "tracker_entity_id"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_MIN_DISTANCE: Final = "min_distance"
CONF_MAX_STALE: Final = "max_stale_hours"
CONF_LANGUAGE: Final = "language"

DEFAULT_NAME: Final = "Pirate Weather Mobil"
DEFAULT_UPDATE_INTERVAL: Final = 15  # minutes
DEFAULT_MIN_DISTANCE: Final = 2.0  # km
DEFAULT_MAX_STALE: Final = 12  # hours
DEFAULT_LANGUAGE: Final = "de"

MIN_UPDATE_INTERVAL: Final = 5
MAX_UPDATE_INTERVAL: Final = 180

# Backoff while the API cannot be reached (network down, server errors).
BACKOFF_INITIAL: Final = timedelta(minutes=2)
BACKOFF_MAX: Final = timedelta(minutes=60)

# Location-triggered refreshes are not issued more often than this.
LOCATION_REFRESH_COOLDOWN: Final = timedelta(minutes=5)

API_URL: Final = "https://api.pirateweather.net/forecast/{api_key}/{lat},{lon}"
API_TIMEOUT: Final = 20  # seconds

ATTRIBUTION: Final = "Powered by Pirate Weather"

LANGUAGES: Final = [
    "de",
    "en",
    "fr",
    "it",
    "nl",
    "es",
    "pl",
    "da",
    "sv",
    "no",
    "cs",
    "hr",
    "sl",
    "hu",
    "pt",
]
