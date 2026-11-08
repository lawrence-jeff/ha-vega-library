"""Diagnostics for Vega Library Holds (credentials and reading history redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import VegaConfigEntry
from .summary import summarize_holds

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "refresh_token", "access_token", "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VegaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
        },
        "holds": summarize_holds(coordinator.data or []),
    }
