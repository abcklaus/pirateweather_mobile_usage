"""Config flow for Pirate Weather Mobile."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    PirateWeatherAuthError,
    PirateWeatherClient,
    PirateWeatherConnectionError,
    PirateWeatherError,
    PirateWeatherQuotaError,
)
from .const import (
    CONF_LANGUAGE,
    CONF_MAX_STALE,
    CONF_MIN_DISTANCE,
    CONF_TRACKER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_STALE,
    DEFAULT_MIN_DISTANCE,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LANGUAGES,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
TRACKER_SELECTOR = EntitySelector(EntitySelectorConfig(domain="device_tracker"))


async def _async_validate(
    hass: HomeAssistant, api_key: str, tracker: str
) -> dict[str, str]:
    """Try one request, at the tracker's position if it has one."""
    lat, lon = hass.config.latitude, hass.config.longitude
    if (state := hass.states.get(tracker)) is not None:
        try:
            lat = float(state.attributes[ATTR_LATITUDE])
            lon = float(state.attributes[ATTR_LONGITUDE])
        except (KeyError, TypeError, ValueError):
            pass

    client = PirateWeatherClient(
        async_get_clientsession(hass), api_key, DEFAULT_LANGUAGE
    )
    try:
        await client.async_get_forecast(lat, lon)
    except PirateWeatherAuthError:
        return {"base": "invalid_auth"}
    except PirateWeatherQuotaError:
        return {"base": "quota_exceeded"}
    except PirateWeatherConnectionError:
        return {"base": "cannot_connect"}
    except PirateWeatherError:
        _LOGGER.exception("Unexpected response while validating the API key")
        return {"base": "unknown"}
    return {}


class PirateWeatherMobileConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return PirateWeatherMobileOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for API key and tracker."""
        errors: dict[str, str] = {}
        if user_input is not None:
            tracker = user_input[CONF_TRACKER]
            await self.async_set_unique_id(tracker)
            self._abort_if_unique_id_configured()
            if self.hass.states.get(tracker) is None:
                errors[CONF_TRACKER] = "tracker_not_found"
            else:
                errors = await _async_validate(
                    self.hass, user_input[CONF_API_KEY], tracker
                )
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_TRACKER: tracker,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
                vol.Required(CONF_TRACKER): TRACKER_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the API key was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate(
                self.hass, user_input[CONF_API_KEY], entry.data[CONF_TRACKER]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change API key or tracker."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            tracker = user_input[CONF_TRACKER]
            await self.async_set_unique_id(tracker)
            if tracker != entry.unique_id:
                self._abort_if_unique_id_configured()
            if self.hass.states.get(tracker) is None:
                errors[CONF_TRACKER] = "tracker_not_found"
            else:
                errors = await _async_validate(
                    self.hass, user_input[CONF_API_KEY], tracker
                )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, unique_id=tracker, data_updates=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
                vol.Required(CONF_TRACKER): TRACKER_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or dict(entry.data)
            ),
            errors=errors,
        )


class PirateWeatherMobileOptionsFlow(OptionsFlow):
    """Polling, movement and language options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL,
                        max=MAX_UPDATE_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_DISTANCE,
                    default=options.get(CONF_MIN_DISTANCE, DEFAULT_MIN_DISTANCE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.5,
                        max=50,
                        step=0.5,
                        unit_of_measurement="km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAX_STALE,
                    default=options.get(CONF_MAX_STALE, DEFAULT_MAX_STALE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=72,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_LANGUAGE,
                    default=options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=LANGUAGES, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
