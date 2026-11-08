"""Config flow for Vega Library Holds."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    async_discover,
    VegaAuthError,
    VegaClient,
    VegaConnectionError,
    VegaError,
    VegaUnknownLibraryError,
)
from .entity import mask_card
from .const import (
    CONF_AUTH_URL,
    CONF_COLUMNS,
    CONF_COVER_HEIGHT,
    CONF_DEADLINE_DAYS,
    CONF_HOST,
    CONF_LIBRARY_ID,
    CONF_MAX_COVERS,
    CONF_SCAN_INTERVAL,
    CONF_SITE_HOST,
    CONF_SITE_URL,
    DEFAULT_COLUMNS,
    DEFAULT_COVER_HEIGHT,
    DEFAULT_DEADLINE_DAYS,
    DEFAULT_MAX_COVERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _validate(hass, data: Mapping[str, Any]) -> str | None:
    """Try to log in and fetch holds. Returns an error key, or None on success."""
    client = VegaClient(
        async_get_clientsession(hass),
        data[CONF_LIBRARY_ID],
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        auth_url=data.get(CONF_AUTH_URL),
        site_host=data.get(CONF_SITE_HOST),
    )
    try:
        await client.async_login()
        await client.async_get_holds()
    except VegaUnknownLibraryError as err:
        _LOGGER.warning("Vega setup check: library not found (%s)", err)
        return "unknown_library"
    except VegaAuthError as err:
        _LOGGER.warning("Vega setup check: sign-in rejected (%s)", err)
        return "invalid_auth"
    except VegaConnectionError as err:
        _LOGGER.warning("Vega setup check: could not connect (%s)", err)
        return "cannot_connect"
    except VegaError as err:
        _LOGGER.warning("Vega setup check: unexpected error (%r)", err)
        return "unknown"
    return None


class VegaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            data: dict[str, Any] | None = None
            try:
                found = await async_discover(
                    async_get_clientsession(self.hass), user_input[CONF_SITE_URL]
                )
            except VegaUnknownLibraryError:
                errors["base"] = "unknown_library"
            except VegaConnectionError:
                errors["base"] = "cannot_connect"
            else:
                data = {
                    CONF_LIBRARY_ID: found.site_code,
                    CONF_HOST: found.host,
                    CONF_AUTH_URL: found.auth_url,
                    CONF_SITE_HOST: found.site_host,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                await self.async_set_unique_id(f"{found.host}/{found.site_code}/{username}")
                self._abort_if_unique_id_configured()
                if error := await _validate(self.hass, data):
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=f"{found.site_code} ({mask_card(username)})", data=data
                    )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_URL, default=defaults.get(CONF_SITE_URL, "")): str,
                    vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            if error := await _validate(self.hass, data):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VegaOptionsFlow()


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": 1,
        "mode": NumberSelectorMode.BOX,
    }
    if unit:  # the selector schema rejects unit_of_measurement=None
        config["unit_of_measurement"] = unit
    return NumberSelector(NumberSelectorConfig(**config))


class VegaOptionsFlow(OptionsFlow):
    """Polling interval and cover-image layout."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ): _number(15, 1440, "min"),
                    vol.Required(CONF_COLUMNS, default=o.get(CONF_COLUMNS, DEFAULT_COLUMNS)): _number(1, 10),
                    vol.Required(
                        CONF_MAX_COVERS, default=o.get(CONF_MAX_COVERS, DEFAULT_MAX_COVERS)
                    ): _number(2, 30),
                    vol.Required(
                        CONF_COVER_HEIGHT, default=o.get(CONF_COVER_HEIGHT, DEFAULT_COVER_HEIGHT)
                    ): _number(60, 400, "px"),
                    vol.Required(
                        CONF_DEADLINE_DAYS, default=o.get(CONF_DEADLINE_DAYS, DEFAULT_DEADLINE_DAYS)
                    ): _number(0, 14, "days"),
                }
            ),
        )
