"""The Vega Library Holds integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import VegaClient
from .const import CONF_AUTH_URL, CONF_HOST, CONF_LIBRARY_ID, CONF_SITE_HOST, DOMAIN, STORAGE_VERSION
from .coordinator import VegaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.IMAGE]

type VegaConfigEntry = ConfigEntry[VegaCoordinator]


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    # The refresh token rotates on every use, so it lives in a Store rather than
    # the config entry (updating the entry would trigger a reload each time).
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


@callback
def _migrate_unique_id(entry: ConfigEntry):
    """Renamed sensor key: holds_total -> holds_all (keeps history and entity settings)."""

    def migrate(reg_entry: er.RegistryEntry) -> dict[str, str] | None:
        old = f"{entry.entry_id}_holds_total"
        if reg_entry.unique_id == old:
            return {"new_unique_id": f"{entry.entry_id}_holds_all"}
        return None

    return migrate


async def async_setup_entry(hass: HomeAssistant, entry: VegaConfigEntry) -> bool:
    """Set up from a config entry."""
    await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id(entry))
    store = _store(hass, entry)
    stored = await store.async_load() or {}
    _LOGGER.debug(
        "Setting up %s (stored refresh token: %s)", entry.title, bool(stored.get("refresh_token"))
    )

    def save_token(token: str) -> None:
        store.async_delay_save(lambda: {"refresh_token": token}, 1)

    client = VegaClient(
        async_get_clientsession(hass),
        entry.data[CONF_LIBRARY_ID],
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        auth_url=entry.data.get(CONF_AUTH_URL),
        site_host=entry.data.get(CONF_SITE_HOST),
        refresh_token=stored.get("refresh_token"),
        token_callback=save_token,
    )
    coordinator = VegaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: VegaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VegaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: VegaConfigEntry) -> None:
    """Delete stored tokens when the entry is removed."""
    await _store(hass, entry).async_remove()
