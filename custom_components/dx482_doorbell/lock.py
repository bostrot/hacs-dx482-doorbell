"""Lock platform: front-door latch control via dispatcher 0x08."""

from __future__ import annotations

import logging

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import DATA_DOOR_OPEN, DATA_DOOR_STATE, DATA_DOOR_STATE_RAW
from .entity import DX482Entity
from .protocol import DX482Error

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DX482ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DX482Lock(entry.runtime_data.coordinator)])


class DX482Lock(DX482Entity, LockEntity):
    """Represents the door latch.

    The DX482 reports a coarse door-state byte.  Because the latch is often
    momentary, this entity is optimistic: it reflects the command it issued and
    reconciles with the polled state when a reliable reading is available.
    """

    _attr_translation_key = "door_lock"
    _attr_icon = "mdi:door"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._entry_id}_lock"
        self._optimistic_locked: bool | None = None

    @property
    def is_locked(self) -> bool | None:
        door_open = self.coordinator.data.get(DATA_DOOR_OPEN)
        if door_open is not None:
            return not door_open
        return self._optimistic_locked

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.coordinator.data
        return {
            "door_state": data.get(DATA_DOOR_STATE),
            "door_state_raw": data.get(DATA_DOOR_STATE_RAW),
        }

    async def async_lock(self, **kwargs) -> None:
        try:
            await self.coordinator.client.async_set_lock(unlock=False)
        except DX482Error as err:
            _LOGGER.error("Lock command failed: %s", err)
            raise
        self._optimistic_locked = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs) -> None:
        try:
            await self.coordinator.client.async_set_lock(unlock=True)
        except DX482Error as err:
            _LOGGER.error("Unlock command failed: %s", err)
            raise
        self._optimistic_locked = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        # A reliable poll reading supersedes the optimistic value.
        if self.coordinator.data.get(DATA_DOOR_OPEN) is not None:
            self._optimistic_locked = None
        super()._handle_coordinator_update()
