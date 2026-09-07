"""Buttons: open door (relay 1/2), light, hang up."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DX482ConfigEntry
from .const import CONF_LOCAL_IP, CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT
from .entity import DX482Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    relays = {**entry.data, **entry.options}.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT)
    entities: list[ButtonEntity] = [DX482UnlockButton(entry, 1)]
    if relays >= 2:
        entities.append(DX482UnlockButton(entry, 2))
    entities += [DX482LightButton(entry), DX482HangupButton(entry),
                 DX482RebootButton(entry), DX482PointToHAButton(entry), DX482RestoreCloudButton(entry)]
    async_add_entities(entities)


class DX482UnlockButton(DX482Entity, ButtonEntity):
    _attr_icon = "mdi:door-open"

    def __init__(self, entry: DX482ConfigEntry, index: int) -> None:
        super().__init__(entry)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_unlock_{index}"
        self._attr_translation_key = "open_door" if index == 1 else "open_door_2"

    async def async_press(self) -> None:
        try:
            await self.session.unlock(self._index)
        except (TimeoutError, ConnectionError, OSError) as err:
            raise HomeAssistantError(f"Unlock failed: {err}") from err


class DX482LightButton(DX482Entity, ButtonEntity):
    _attr_translation_key = "light"
    _attr_icon = "mdi:lightbulb-on-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_light"

    async def async_press(self) -> None:
        try:
            await self.session.light(1)
        except (TimeoutError, ConnectionError, OSError) as err:
            raise HomeAssistantError(f"Light command failed: {err}") from err


class DX482HangupButton(DX482Entity, ButtonEntity):
    _attr_translation_key = "hangup"
    _attr_icon = "mdi:phone-hangup"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_hangup"

    async def async_press(self) -> None:
        await self.session.hangup()


class _DeviceConfigButton(DX482Entity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    async def _run(self, coro) -> None:
        try:
            await coro
        except OSError as err:
            raise HomeAssistantError(f"Doorbell FTP/telnet failed: {err}") from err
        self._entry.runtime_data.notify()


class DX482RebootButton(_DeviceConfigButton):
    _attr_translation_key = "reboot"
    _attr_icon = "mdi:restart"

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_reboot"

    async def async_press(self) -> None:
        await self._run(self._entry.runtime_data.device_config.async_reboot())


class DX482PointToHAButton(_DeviceConfigButton):
    """Write this HA host into the doorbell's [server] (backs up the original). Reboot afterwards."""

    _attr_translation_key = "point_to_ha"
    _attr_icon = "mdi:home-assistant"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_point_to_ha"

    async def async_press(self) -> None:
        local_ip = {**self._entry.data, **self._entry.options}[CONF_LOCAL_IP]
        await self._run(self._entry.runtime_data.device_config.async_point_sip_server(local_ip))


class DX482RestoreCloudButton(_DeviceConfigButton):
    """Restore the vendor cloud server in the doorbell (re-enables the phone app). Reboot afterwards."""

    _attr_translation_key = "restore_cloud"
    _attr_icon = "mdi:cloud-upload-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DX482ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_restore_cloud"

    async def async_press(self) -> None:
        await self._run(self._entry.runtime_data.device_config.async_restore_vendor_cloud())
