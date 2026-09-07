"""Switch entities for the doorbell's boolean settings (written over FTP, applied on reboot)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .device_config import BOOL_PARAMS, Param
from .entity import DX482Entity


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.runtime_data.device_config is None:
        return
    async_add_entities(DX482ParamSwitch(entry, p) for p in BOOL_PARAMS.values())


class DX482ParamSwitch(DX482Entity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, entry: DX482ConfigEntry, param: Param) -> None:
        super().__init__(entry)
        self._param = param
        self._attr_unique_id = f"{entry.entry_id}_param_{param.key}"
        self._attr_translation_key = param.key

    @property
    def is_on(self) -> bool | None:
        cfg = self._entry.runtime_data.device_config
        return bool(cfg.get(self._param.key)) if cfg else None

    async def _set(self, value: int) -> None:
        try:
            await self._entry.runtime_data.device_config.async_set(self._param.key, value)
        except OSError as err:
            raise HomeAssistantError(f"Could not write setting to the doorbell: {err}") from err
        self._entry.runtime_data.notify()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(1)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(0)
