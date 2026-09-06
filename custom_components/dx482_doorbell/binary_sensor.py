"""Binary sensor platform: reachability and momentary ring indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import DX482ConfigEntry
from .const import DATA_DOOR_OPEN, EVENT_RING, SIGNAL_DOORBELL_EVENT
from .entity import DX482Entity

RING_HOLD_SECONDS = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DX482ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            DX482DoorOpenSensor(coordinator),
            DX482RingSensor(coordinator, entry),
        ]
    )


class DX482DoorOpenSensor(DX482Entity, BinarySensorEntity):
    _attr_translation_key = "door_open"
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_door_open"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get(DATA_DOOR_OPEN)


class DX482RingSensor(DX482Entity, BinarySensorEntity):
    """Turns on briefly when a ring event arrives via the webhook."""

    _attr_translation_key = "ring"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator, entry: DX482ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{self._entry_id}_ring"
        self._attr_is_on = False
        self._cancel_reset = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DOORBELL_EVENT}_{self._entry_id}",
                self._on_event,
            )
        )

    @callback
    def _on_event(self, event: str) -> None:
        if event != EVENT_RING:
            return
        self._attr_is_on = True
        self.async_write_ha_state()
        if self._cancel_reset:
            self._cancel_reset()

        @callback
        def _reset(_now) -> None:
            self._attr_is_on = False
            self._cancel_reset = None
            self.async_write_ha_state()

        self._cancel_reset = async_call_later(self.hass, RING_HOLD_SECONDS, _reset)
