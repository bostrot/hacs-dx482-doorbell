"""Binary sensors: ringing (momentary), call active, doorbell registered."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import DX482ConfigEntry
from .const import SIGNAL_DOORBELL_EVENT
from .entity import DX482Entity

RING_HOLD_SECONDS = 5


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DX482RingSensor(entry), DX482CallSensor(entry), DX482RegisteredSensor(entry)])


class DX482RingSensor(DX482Entity, BinarySensorEntity):
    _attr_translation_key = "ring"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bell-ring"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_ring"
        self._attr_is_on = False
        self._cancel = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_DOORBELL_EVENT}_{self._entry.entry_id}", self._on_ring)
        )

    @callback
    def _on_ring(self, _event: str) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        if self._cancel:
            self._cancel()

        @callback
        def _reset(_now) -> None:
            self._attr_is_on = False
            self._cancel = None
            self.async_write_ha_state()

        self._cancel = async_call_later(self.hass, RING_HOLD_SECONDS, _reset)


class DX482CallSensor(DX482Entity, BinarySensorEntity):
    _attr_translation_key = "call_active"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:phone-in-talk"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_call"

    @property
    def is_on(self) -> bool:
        return self.session.call_active


class DX482RegisteredSensor(DX482Entity, BinarySensorEntity):
    _attr_translation_key = "registered"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_registered"

    @property
    def is_on(self) -> bool:
        return self.session.registered_at is not None
