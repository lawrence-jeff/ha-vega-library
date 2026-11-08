"""Image entity showing the covers of books ready for pickup."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import VegaConfigEntry
from .const import (
    COVER_GAP,
    CONF_COLUMNS,
    CONF_COVER_HEIGHT,
    CONF_MAX_COVERS,
    DEFAULT_COLUMNS,
    DEFAULT_COVER_HEIGHT,
    DEFAULT_MAX_COVERS,
)
from .coordinator import VegaCoordinator
from .entity import device_info
from .montage import build_montage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the image entity."""
    async_add_entities([ReadyHoldsImage(hass, entry.runtime_data, entry)])


class ReadyHoldsImage(CoordinatorEntity[VegaCoordinator], ImageEntity):
    """One image with every ready book's cover side by side."""

    _attr_has_entity_name = True
    _attr_translation_key = "ready_holds"
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, coordinator: VegaCoordinator, entry: VegaConfigEntry) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ready_holds_image"
        self._attr_device_info = device_info(entry)
        self._image: bytes | None = None
        self._key: tuple[str | None, ...] | None = None
        self._lock = asyncio.Lock()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rebuild the image in the background when the ready list changes."""
        self.hass.async_create_task(self._async_refresh_image())
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_image()

    async def _async_refresh_image(self) -> None:
        ready = self.coordinator.ready_holds
        key = tuple(h.cover_url for h in ready)
        async with self._lock:
            if key == self._key and self._image is not None:
                return
            covers = await asyncio.gather(
                *(
                    self.coordinator.client.async_fetch_cover(h.cover_url) if h.cover_url else _none()
                    for h in ready
                )
            )
            wanted = sum(1 for h in ready if h.cover_url)
            got = sum(1 for c in covers if c)
            if got < wanted:
                _LOGGER.warning(
                    "Could not download %d of %d covers for the ready-holds image "
                    "(run with debug logging to see which)",
                    wanted - got,
                    wanted,
                )
            else:
                _LOGGER.debug("Downloaded %d covers for the ready-holds image", got)
            options = self._entry.options
            self._image = await self.hass.async_add_executor_job(
                build_montage,
                list(covers),
                options.get(CONF_COVER_HEIGHT, DEFAULT_COVER_HEIGHT),
                COVER_GAP,
                options.get(CONF_COLUMNS, DEFAULT_COLUMNS),
                options.get(CONF_MAX_COVERS, DEFAULT_MAX_COVERS),
            )
            self._key = key
            self._attr_image_last_updated = dt_util.utcnow()
            self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        if self._image is None:
            await self._async_refresh_image()
        return self._image


async def _none() -> None:
    return None
