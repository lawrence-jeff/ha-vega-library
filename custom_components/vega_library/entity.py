"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONF_LIBRARY_ID, DOMAIN


def mask_card(card: str) -> str:
    """Show only the last 4 digits so card numbers do not leak into names and entity IDs."""
    return f"…{card[-4:]}" if len(card) > 4 else card


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One service device per library account."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Library {entry.data[CONF_LIBRARY_ID]} {mask_card(entry.data[CONF_USERNAME])}",
        manufacturer="Innovative (Vega Discover)",
        entry_type=DeviceEntryType.SERVICE,
    )
