"""Sensor platform: door state and Wi-Fi signal."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import DATA_DOOR_STATE, DATA_RSSI
from .entity import DX482Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DX482ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            DX482DoorStateSensor(coordinator),
            DX482RssiSensor(coordinator),
        ]
    )


class DX482DoorStateSensor(DX482Entity, SensorEntity):
    _attr_translation_key = "door_state"
    _attr_icon = "mdi:door"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_door_state"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get(DATA_DOOR_STATE)


class DX482RssiSensor(DX482Entity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_rssi"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get(DATA_RSSI)
