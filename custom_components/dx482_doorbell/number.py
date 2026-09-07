"""Number entities for the doorbell's own settings (written over FTP, applied on reboot)."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .device_config import PARAMS, Param
from .entity import DX482Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.runtime_data.device_config is None:
        return
    async_add_entities(DX482ParamNumber(entry, p) for p in PARAMS.values())


class DX482ParamNumber(DX482Entity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: DX482ConfigEntry, param: Param) -> None:
        super().__init__(entry)
        self._param = param
        self._attr_unique_id = f"{entry.entry_id}_param_{param.key}"
        self._attr_translation_key = param.key
        self._attr_native_min_value = param.min
        self._attr_native_max_value = param.max
        self._attr_native_step = param.step
        self._attr_native_unit_of_measurement = param.unit
        self._attr_icon = "mdi:tune"

    @property
    def native_value(self) -> float | None:
        cfg = self._entry.runtime_data.device_config
        return cfg.get(self._param.key) if cfg else None

    async def async_set_native_value(self, value: float) -> None:
        cfg = self._entry.runtime_data.device_config
        try:
            await cfg.async_set(self._param.key, int(value))
        except OSError as err:
            raise HomeAssistantError(f"Could not write setting to the doorbell: {err}") from err
        self._entry.runtime_data.notify()
