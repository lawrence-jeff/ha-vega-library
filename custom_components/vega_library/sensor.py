"""Sensors for Vega Library Holds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import VegaConfigEntry
from .coordinator import VegaCoordinator
from .const import STATUS_IN_TRANSIT, STATUS_WAITING
from .entity import device_info


@dataclass(frozen=True, kw_only=True)
class VegaSensorDescription(SensorEntityDescription):
    """Sensor description with a value function."""

    value_fn: Callable[[VegaCoordinator], int | datetime | None]
    attrs_fn: Callable[[VegaCoordinator], dict[str, Any]] | None = None


def _earliest_deadline(coordinator: VegaCoordinator) -> datetime | None:
    deadlines = [h.expires for h in coordinator.ready_holds if h.expires]
    return min(deadlines) if deadlines else None


def _status_count(status: str) -> Callable[[VegaCoordinator], int]:
    return lambda c: len(c.holds_with_status(status))


SENSORS: tuple[VegaSensorDescription, ...] = (
    VegaSensorDescription(
        key="holds_total",
        translation_key="holds_total",
        icon="mdi:book-clock-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: len(c.data),
        attrs_fn=lambda c: {"holds": [h.as_dict() for h in c.data]},
    ),
    VegaSensorDescription(
        key="holds_ready",
        translation_key="holds_ready",
        icon="mdi:book-check-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: len(c.ready_holds),
        attrs_fn=lambda c: {
            "titles": [h.title for h in c.ready_holds],
            "holds": [h.as_dict() for h in c.ready_holds],
        },
    ),
    VegaSensorDescription(
        key="holds_in_transit",
        translation_key="holds_in_transit",
        icon="mdi:truck-delivery-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_status_count(STATUS_IN_TRANSIT),
        attrs_fn=lambda c: {"holds": [h.as_dict() for h in c.holds_with_status(STATUS_IN_TRANSIT)]},
    ),
    VegaSensorDescription(
        key="holds_waiting",
        translation_key="holds_waiting",
        icon="mdi:book-clock-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_status_count(STATUS_WAITING),
        attrs_fn=lambda c: {"holds": [h.as_dict() for h in c.holds_with_status(STATUS_WAITING)]},
    ),
    VegaSensorDescription(
        key="next_pickup_deadline",
        translation_key="next_pickup_deadline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_earliest_deadline,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(VegaSensor(coordinator, entry, desc) for desc in SENSORS)


class VegaSensor(CoordinatorEntity[VegaCoordinator], SensorEntity):
    """A hold-related sensor."""

    entity_description: VegaSensorDescription
    _attr_has_entity_name = True
    # Hold lists can be several KB and change often; keep them out of the history database.
    _unrecorded_attributes = frozenset({"holds", "titles"})

    def __init__(
        self,
        coordinator: VegaCoordinator,
        entry: VegaConfigEntry,
        description: VegaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> int | datetime | None:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator)
        return None
