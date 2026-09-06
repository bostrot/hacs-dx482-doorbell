"""Camera platform: RTSP live view + binary-protocol JPEG snapshot fallback."""

from __future__ import annotations

import logging
from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import (
    CONF_RTSP_CHANNEL,
    CONF_RTSP_PASSWORD,
    CONF_RTSP_PORT,
    CONF_RTSP_USERNAME,
    DEFAULT_RTSP_CHANNEL,
    DEFAULT_RTSP_PASSWORD,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_USERNAME,
)
from .entity import DX482Entity
from .protocol import DX482Error

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DX482ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DX482Camera(entry.runtime_data.coordinator, entry)])


class DX482Camera(DX482Entity, Camera):
    """Live H.264 view over RTSP, with a JPEG snapshot fallback."""

    _attr_translation_key = "camera"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator, entry: DX482ConfigEntry) -> None:
        DX482Entity.__init__(self, coordinator)
        Camera.__init__(self)
        self._entry = entry
        self._attr_unique_id = f"{self._entry_id}_camera"

    def _rtsp_url(self) -> str:
        data = {**self._entry.data, **self._entry.options}
        host = self.coordinator.client.host
        port = data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)
        user = quote(data.get(CONF_RTSP_USERNAME, DEFAULT_RTSP_USERNAME), safe="")
        pwd = quote(data.get(CONF_RTSP_PASSWORD, DEFAULT_RTSP_PASSWORD), safe="")
        channel = data.get(CONF_RTSP_CHANNEL, DEFAULT_RTSP_CHANNEL)
        return (
            f"rtsp://{user}:{pwd}@{host}:{port}"
            f"/Streaming/Channels/{channel}"
        )

    async def stream_source(self) -> str | None:
        return self._rtsp_url()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image.

        Prefer a frame grabbed from the RTSP stream via ffmpeg; fall back to the
        device's binary-protocol JPEG capture when ffmpeg/stream is unavailable.
        """
        try:
            from haffmpeg.tools import IMAGE_JPEG, ImageFrame
            from homeassistant.components.ffmpeg import get_ffmpeg_manager

            manager = get_ffmpeg_manager(self.hass)
            image_frame = ImageFrame(manager.binary)
            image = await image_frame.get_image(
                self._rtsp_url(),
                output_format=IMAGE_JPEG,
                extra_cmd="-rtsp_transport tcp",
            )
            if image:
                return image
        except Exception as err:  # noqa: BLE001 - ffmpeg optional, fall back
            _LOGGER.debug("ffmpeg still capture failed, using device JPEG: %s", err)

        try:
            return await self.coordinator.client.async_snapshot()
        except DX482Error as err:
            _LOGGER.debug("JPEG snapshot fallback failed: %s", err)
            return None
