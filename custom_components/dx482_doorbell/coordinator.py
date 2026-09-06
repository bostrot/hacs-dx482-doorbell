"""DataUpdateCoordinator for the DX482 doorbell."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DATA_AVAILABLE,
    DATA_DOOR_OPEN,
    DATA_DOOR_STATE,
    DATA_DOOR_STATE_RAW,
    DATA_RSSI,
    DOMAIN,
)
from .protocol import OPEN_STATE_BYTES, DX482Client, DX482Error

_LOGGER = logging.getLogger(__name__)


class DX482Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the doorbell gently and shares state with all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DX482Client,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{client.host}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            DATA_AVAILABLE: False,
            DATA_DOOR_STATE: None,
            DATA_DOOR_STATE_RAW: None,
            DATA_DOOR_OPEN: None,
            DATA_RSSI: None,
        }
        try:
            label, raw = await self.client.async_door_state()
        except DX482Error as err:
            raise UpdateFailed(f"door state query failed: {err}") from err

        data[DATA_AVAILABLE] = True
        data[DATA_DOOR_STATE] = label
        data[DATA_DOOR_STATE_RAW] = raw
        if raw is not None:
            data[DATA_DOOR_OPEN] = raw in OPEN_STATE_BYTES

        # RSSI is a nice-to-have; never fail the whole update over it.
        try:
            data[DATA_RSSI] = await self.client.async_wifi_rssi()
        except DX482Error:
            _LOGGER.debug("RSSI query failed", exc_info=True)

        return data
