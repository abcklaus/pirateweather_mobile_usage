"""Minimal async client for the Pirate Weather forecast API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import API_TIMEOUT, API_URL


class PirateWeatherError(Exception):
    """Base error. Messages never contain the API key."""


class PirateWeatherConnectionError(PirateWeatherError):
    """The API could not be reached (no network, DNS, timeout, 5xx)."""


class PirateWeatherAuthError(PirateWeatherError):
    """The API key was rejected."""


class PirateWeatherQuotaError(PirateWeatherError):
    """The monthly quota of the API key is used up."""


@dataclass(slots=True)
class ForecastResponse:
    """Parsed forecast plus the quota headers of the response."""

    data: dict[str, Any]
    calls_remaining: int | None
    calls_limit: int | None


def _int_header(headers: Any, name: str) -> int | None:
    try:
        return int(headers[name])
    except (KeyError, TypeError, ValueError):
        return None


class PirateWeatherClient:
    """Fetches forecasts for arbitrary coordinates."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, language: str
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._language = language

    async def async_get_forecast(self, lat: float, lon: float) -> ForecastResponse:
        """Fetch the forecast for the given position in SI units."""
        url = API_URL.format(api_key=self._api_key, lat=f"{lat:.4f}", lon=f"{lon:.4f}")
        params = {
            "units": "si",
            "extend": "hourly",
            "version": "2",
            "exclude": "minutely",
            "lang": self._language,
        }
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
            ) as resp:
                if resp.status in (401, 403):
                    raise PirateWeatherAuthError(
                        f"API key rejected (HTTP {resp.status})"
                    )
                if resp.status == 429:
                    raise PirateWeatherQuotaError(
                        "Monthly API quota exhausted (HTTP 429)"
                    )
                if resp.status >= 500:
                    raise PirateWeatherConnectionError(
                        f"Server error (HTTP {resp.status})"
                    )
                if resp.status != 200:
                    raise PirateWeatherError(
                        f"Unexpected response (HTTP {resp.status})"
                    )
                data = await resp.json(content_type=None)
                headers = resp.headers
        except PirateWeatherError:
            raise
        except TimeoutError:
            raise PirateWeatherConnectionError("Request timed out") from None
        except aiohttp.ClientError as err:
            # aiohttp messages can contain the full URL including the key,
            # so only the exception type is passed on.
            raise PirateWeatherConnectionError(
                f"Connection failed ({type(err).__name__})"
            ) from None
        except ValueError:
            raise PirateWeatherError("Invalid JSON in response") from None

        if not isinstance(data, dict) or "currently" not in data:
            raise PirateWeatherError("Response contains no current conditions")

        return ForecastResponse(
            data=data,
            calls_remaining=_int_header(headers, "Ratelimit-Remaining"),
            calls_limit=_int_header(headers, "Ratelimit-Limit"),
        )
