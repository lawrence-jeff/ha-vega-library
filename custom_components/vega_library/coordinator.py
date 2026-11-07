"""Data update coordinator for Vega Library Holds."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Hold, VegaAuthError, VegaClient, VegaError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class VegaCoordinator(DataUpdateCoordinator[list[Hold]]):
    """Fetches the patron's holds."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: VegaClient) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client

    async def _async_update_data(self) -> list[Hold]:
        try:
            return await self.client.async_get_holds()
        except VegaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VegaError as err:
            raise UpdateFailed(f"Error talking to the library: {err}") from err

    @property
    def ready_holds(self) -> list[Hold]:
        """Holds waiting for pickup."""
        return [hold for hold in self.data if hold.ready]
