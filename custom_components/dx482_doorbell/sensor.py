"""Sensors: session state and last ring time."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .entity import DX482Entity


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DX482StateSensor(entry), DX482LastRingSensor(entry)])


class DX482StateSensor(DX482Entity, SensorEntity):
    _attr_translation_key = "session_state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:doorbell-video"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_state"

    @property
    def native_value(self) -> str:
        s = self.session
        if s.video_active:
            return "streaming"
        if s.call_active:
            return "in_call"
        if s.registered_at:
            return "idle"
        return "waiting_for_doorbell"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        s = self.session
        return {
            "proxy_logged_in": s.proxy_logged_in,
            "rtp_video_packets": s.rtp_video_packets,
            "video_resolution": f"{s.video_resolution[0]}x{s.video_resolution[1]}" if s.video_resolution else None,
            "registered_at": datetime.fromtimestamp(s.registered_at, tz=timezone.utc).isoformat() if s.registered_at else None,
        }


class DX482LastRingSensor(DX482Entity, SensorEntity):
    _attr_translation_key = "last_ring"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bell"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_last_ring"

    @property
    def native_value(self) -> datetime | None:
        ts = self.session.last_ring_at
        return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
