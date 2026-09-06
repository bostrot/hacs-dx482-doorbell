"""Button platform: momentary door unlock (relay pulse)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .entity import DX482Entity
from .protocol import DX482Error

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DX482ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DX482OpenDoorButton(entry.runtime_data.coordinator)])


class DX482OpenDoorButton(DX482Entity, ButtonEntity):
    """Trigger the door relay for a momentary unlock pulse."""

    _attr_translation_key = "open_door"
    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_open_door"

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.async_trigger_door()
        except DX482Error as err:
            _LOGGER.error("Failed to trigger door: %s", err)
            raise
        # Refresh state shortly after; the latch is momentary.
        await self.coordinator.async_request_refresh()
