"""Shared base entity for the DX482 doorbell."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL, SIGNAL_STATE
from .session import DX482Session


class DX482Entity(Entity):
    """Base entity: device info, session access, state-change signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
        )

    @property
    def session(self) -> DX482Session:
        return self._entry.runtime_data.session

    @property
    def state_map(self) -> dict[str, Any]:
        return self._entry.runtime_data.state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_STATE}_{self._entry.entry_id}", self._on_state)
        )

    @callback
    def _on_state(self) -> None:
        self.async_write_ha_state()
