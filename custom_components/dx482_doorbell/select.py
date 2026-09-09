"""Select entities for the doorbell's menu-mode settings (e.g. call/divert mode)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .device_config import SELECT_PARAMS, SelectParam
from .entity import DX482Entity


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.runtime_data.device_config is None:
        return
    async_add_entities(DX482SelectParam(entry, p) for p in SELECT_PARAMS.values())


class DX482SelectParam(DX482Entity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:phone-forward"

    def __init__(self, entry: DX482ConfigEntry, param: SelectParam) -> None:
        super().__init__(entry)
        self._param = param
        self._values_by_label = {v: k for k, v in param.options.items()}
        self._attr_unique_id = f"{entry.entry_id}_select_{param.key}"
        self._attr_translation_key = param.key
        self._attr_options = list(param.options.values())

    @property
    def current_option(self) -> str | None:
        cfg = self._entry.runtime_data.device_config
        if cfg is None:
            return None
        raw = cfg.get_str(self._param.para_id, self._param.default)
        return self._param.options.get(raw)

    async def async_select_option(self, option: str) -> None:
        cfg = self._entry.runtime_data.device_config
        value = self._values_by_label.get(option)
        if cfg is None or value is None:
            raise HomeAssistantError(f"Unknown option {option!r}")
        try:
            await cfg.async_set_raw(self._param.para_id, value, reboot_required=not self._param.live)
        except OSError as err:
            raise HomeAssistantError(f"Could not write setting to the doorbell: {err}") from err
        self._entry.runtime_data.notify()
