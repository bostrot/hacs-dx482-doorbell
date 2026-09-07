"""Camera: on-demand live view (MJPEG via ffmpeg) and stills from the doorbell's H.264 RTP."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from haffmpeg.camera import CameraMjpeg
from haffmpeg.tools import IMAGE_JPEG, ImageFrame
from homeassistant.components.camera import Camera
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_aiohttp_proxy_stream
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .entity import DX482Entity

_LOGGER = logging.getLogger(__name__)
FFMPEG_INPUT_ARGS = "-protocol_whitelist file,udp,rtp -fflags nobuffer -flags low_delay"


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DX482Camera(entry)])


class DX482Camera(DX482Entity, Camera):
    _attr_translation_key = "camera"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        DX482Entity.__init__(self, entry)
        Camera.__init__(self)
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._last_image: bytes | None = None

    @property
    def is_streaming(self) -> bool:
        return self.session.video_active

    async def _ensure_video(self) -> None:
        if not self.session.video_active:
            await self.session.start_video()

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        try:
            await self._ensure_video()
            port, sdp = self.session.add_consumer()
        except (TimeoutError, ConnectionError, OSError) as err:
            _LOGGER.warning("Snapshot failed: %s", err)
            return self._last_image
        try:
            frame = ImageFrame(get_ffmpeg_manager(self.hass).binary)
            image = await asyncio.wait_for(
                frame.get_image(sdp, output_format=IMAGE_JPEG, extra_cmd=FFMPEG_INPUT_ARGS), timeout=15
            )
        except (asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("ffmpeg still failed: %s", err)
            image = None
        finally:
            self.session.remove_consumer(port)
        if image:
            self._last_image = image
        return image or self._last_image

    async def handle_async_mjpeg_stream(self, request: web.Request) -> web.StreamResponse | None:
        try:
            await self._ensure_video()
            port, sdp = self.session.add_consumer()
        except (TimeoutError, ConnectionError, OSError) as err:
            _LOGGER.warning("Live view failed: %s", err)
            return None
        stream = CameraMjpeg(get_ffmpeg_manager(self.hass).binary)
        await stream.open_camera(sdp, extra_cmd=FFMPEG_INPUT_ARGS + " -q:v 4")
        try:
            reader = await stream.get_reader()
            return await async_aiohttp_proxy_stream(self.hass, request, reader, get_ffmpeg_manager(self.hass).ffmpeg_stream_content_type)
        finally:
            await stream.close()
            self.session.remove_consumer(port)
