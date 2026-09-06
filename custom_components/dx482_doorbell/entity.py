"""Shared base entity for the DX482 doorbell."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import DX482Coordinator


class DX482Entity(CoordinatorEntity[DX482Coordinator]):
    """Base entity that shares the coordinator and device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DX482Coordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
            configuration_url=f"http://{coordinator.client.host}",
        )

    @property
    def _entry_id(self) -> str:
        return self.coordinator.entry.entry_id
