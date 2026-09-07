"""Event entity: doorbell ring."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import EVENT_RING, SIGNAL_DOORBELL_EVENT
from .entity import DX482Entity


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DX482DoorbellEvent(entry)])


class DX482DoorbellEvent(DX482Entity, EventEntity):
    _attr_translation_key = "doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [EVENT_RING]

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_doorbell_event"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_DOORBELL_EVENT}_{self._entry.entry_id}", self._on_event)
        )

    @callback
    def _on_event(self, event: str) -> None:
        if event in self._attr_event_types:
            self._trigger_event(event)
            self.async_write_ha_state()
