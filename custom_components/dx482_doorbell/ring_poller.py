"""Local ring detection by rapidly polling the doorbell's call log.

The doorbell signals a ring over SIP through the vendor cloud, which is not
observable on the LAN.  Instead we poll the call-log dispatcher (0x11) on a
single persistent TCP connection every few hundred milliseconds and raise a
ring event whenever the reply changes.  No cloud, no external script.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import EVENT_RING, SIGNAL_DOORBELL_EVENT
from .protocol import (
    DISP_CALL_LOG,
    DX482Client,
    DX482Error,
    DX482PersistentConnection,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_BACKOFF_S = 2.0
RECONNECT_BACKOFF_MAX_S = 30.0
# Ignore repeated changes inside this window so one ring => one event.
RING_DEBOUNCE_S = 3.0


class RingPoller:
    """Background task that watches the call log for new entries."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: DX482Client,
        interval_ms: int,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._conn = DX482PersistentConnection(client)
        self._interval = max(interval_ms, 50) / 1000.0
        self._task: asyncio.Task | None = None
        self._last_payload: bytes | None = None
        self._last_ring = 0.0

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
        await self._conn.close()

    async def _run(self) -> None:
        backoff = RECONNECT_BACKOFF_S
        while True:
            try:
                resp = await self._conn.query(DISP_CALL_LOG)
            except DX482Error as err:
                _LOGGER.debug("ring poll failed (%s); retry in %.0fs", err, backoff)
                # Re-baseline after a reconnect so a stale diff isn't a ring.
                self._last_payload = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX_S)
                continue

            backoff = RECONNECT_BACKOFF_S
            self._check(resp.payload or resp.raw)
            await asyncio.sleep(self._interval)

    def _check(self, payload: bytes) -> None:
        if self._last_payload is None:
            # First sample after (re)connect is the baseline, never an event.
            self._last_payload = payload
            return
        if payload == self._last_payload:
            return
        self._last_payload = payload
        now = self._hass.loop.time()
        if now - self._last_ring < RING_DEBOUNCE_S:
            return
        self._last_ring = now
        _LOGGER.debug("call log changed -> ring event")
        async_dispatcher_send(
            self._hass, f"{SIGNAL_DOORBELL_EVENT}_{self._entry_id}", EVENT_RING
        )
