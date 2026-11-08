"""Data update coordinator for Vega Library Holds."""

from __future__ import annotations

from datetime import datetime, timedelta
from collections import Counter
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Hold, VegaAuthError, VegaClient, VegaError
from .const import (
    CONF_DEADLINE_DAYS,
    CONF_LIBRARY_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_DEADLINE_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STATUS_READY,
)
from .events import diff_holds

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
        self._previous: list[Hold] | None = None
        self._notified: set[tuple[str, datetime]] = set()

    async def _async_update_data(self) -> list[Hold]:
        try:
            holds = await self.client.async_get_holds()
        except VegaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VegaError as err:
            raise UpdateFailed(f"Error talking to the library: {err}") from err

        _LOGGER.debug("Fetched %d holds: %s", len(holds), Counter(h.status_name for h in holds))
        events = diff_holds(
            self._previous,
            holds,
            dt_util.utcnow(),
            self.config_entry.options.get(CONF_DEADLINE_DAYS, DEFAULT_DEADLINE_DAYS),
            self._notified,
        )
        self._previous = holds
        for event_type, hold, extra in events:
            _LOGGER.debug("Firing %s for hold %s (%s)", event_type, hold.id, extra)
            self.hass.bus.async_fire(
                event_type,
                {
                    "entry_id": self.config_entry.entry_id,
                    "library": self.config_entry.data[CONF_LIBRARY_ID],
                    "hold": hold.as_dict(),
                    **extra,
                },
            )
        return holds

    def holds_with_status(self, status: str) -> list[Hold]:
        """Holds currently in the given status."""
        return [hold for hold in self.data if hold.status_name == status]

    @property
    def ready_holds(self) -> list[Hold]:
        """Holds waiting for pickup."""
        return self.holds_with_status(STATUS_READY)
