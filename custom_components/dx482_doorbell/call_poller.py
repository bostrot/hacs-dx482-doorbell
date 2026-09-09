"""Cloud-free ring detection by polling the doorbell's call-record table over FTP.

Works regardless of the doorbell's SIP-divert setting: every door-station button
press is logged to ``call_record_table.csv``, so a new door-call row means a ring.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .device_config import DeviceConfig

_LOGGER = logging.getLogger(__name__)


class CallRecordPoller:
    def __init__(self, hass, device_config: DeviceConfig, interval: float, on_ring: Callable[[], None]) -> None:
        self._hass = hass
        self._cfg = device_config
        self._interval = max(2.0, float(interval))
        self._on_ring = on_ring
        self._task: asyncio.Task | None = None
        self._baseline: str | None = None
        self._fails = 0

    def start(self) -> None:
        if self._task is None:
            self._task = self._hass.loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        _LOGGER.debug("call-record ring poller started (%.0fs)", self._interval)
        while True:
            try:
                marker = await self._cfg.async_call_marker()
                self._fails = 0
                if marker is not None:
                    key = marker[0]
                    if self._baseline is None:
                        self._baseline = key
                    elif key > self._baseline:
                        self._baseline = key
                        _LOGGER.info("ring detected from call log at %s", marker[1])
                        self._on_ring()
            except (OSError, ValueError) as err:
                self._fails += 1
                if self._fails in (1, 5, 20):
                    _LOGGER.warning("call-record poll failed (%s)", err)
            # Back off when the device is unreachable so we don't hammer it.
            delay = self._interval if self._fails == 0 else min(self._interval * (1 + self._fails), 60.0)
            await asyncio.sleep(delay)
