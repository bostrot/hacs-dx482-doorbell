"""Buttons: open door (relay 1/2), light, hang up."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT
from .entity import DX482Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    relays = {**entry.data, **entry.options}.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT)
    entities: list[ButtonEntity] = [DX482UnlockButton(entry, 1)]
    if relays >= 2:
        entities.append(DX482UnlockButton(entry, 2))
    entities += [DX482LightButton(entry), DX482HangupButton(entry)]
    async_add_entities(entities)


class DX482UnlockButton(DX482Entity, ButtonEntity):
    _attr_icon = "mdi:door-open"

    def __init__(self, entry: DX482ConfigEntry, index: int) -> None:
        super().__init__(entry)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_unlock_{index}"
        self._attr_translation_key = "open_door" if index == 1 else "open_door_2"

    async def async_press(self) -> None:
        try:
            await self.session.unlock(self._index)
        except (TimeoutError, ConnectionError, OSError) as err:
            raise HomeAssistantError(f"Unlock failed: {err}") from err


class DX482LightButton(DX482Entity, ButtonEntity):
    _attr_translation_key = "light"
    _attr_icon = "mdi:lightbulb-on-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_light"

    async def async_press(self) -> None:
        try:
            await self.session.light(1)
        except (TimeoutError, ConnectionError, OSError) as err:
            raise HomeAssistantError(f"Light command failed: {err}") from err


class DX482HangupButton(DX482Entity, ButtonEntity):
    _attr_translation_key = "hangup"
    _attr_icon = "mdi:phone-hangup"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_hangup"

    async def async_press(self) -> None:
        await self.session.hangup()
