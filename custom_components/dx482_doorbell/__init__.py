"""2easy / V-Tec DX482 video doorbell — fully local integration.

Home Assistant impersonates the doorbell's vendor cloud: a SIP registrar plus the
media proxy the doorbell dials into during calls.  Point the doorbell's
``[server]`` setting at this Home Assistant host and everything (ring, video,
unlock) works on the LAN with no internet.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady as ConfigEntryNotReadyError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_AUDIO_PORT,
    CONF_AUTO_ANSWER,
    CONF_DEVICE_ACCOUNT,
    CONF_HOST,
    CONF_IDLE_TIMEOUT,
    CONF_LOCAL_IP,
    CONF_MON_CODE,
    CONF_PHONE_ACCOUNT,
    CONF_PROXY_PORT,
    CONF_RING_POLL,
    CONF_RING_POLL_INTERVAL,
    CONF_SIP_PORT,
    CONF_VIDEO_PORT,
    DEFAULT_AUDIO_PORT,
    DEFAULT_AUTO_ANSWER,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_MON_CODE,
    DEFAULT_PROXY_PORT,
    DEFAULT_RING_POLL,
    DEFAULT_RING_POLL_INTERVAL,
    DEFAULT_SIP_PORT,
    DEFAULT_VIDEO_PORT,
    DEVICE_SIP_PORT,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    SIGNAL_DOORBELL_EVENT,
    SIGNAL_STATE,
)
from .call_poller import CallRecordPoller
from .device_config import DeviceConfig
from .session import EVENT_RING, DX482Session

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class DX482Data:
    """Runtime data stored on the config entry."""

    session: DX482Session
    state: dict[str, Any] = field(default_factory=dict)
    device_config: DeviceConfig | None = None
    notify: Any = None  # callback: push a state refresh to all entities
    call_poller: Any = None


type DX482ConfigEntry = ConfigEntry[DX482Data]


def _install_sounds(hass: HomeAssistant) -> None:
    """Copy bundled chime sounds into <config>/www/dx482 so Home Assistant serves
    them at /local/dx482/<name>.mp3.

    Google Cast devices only play media from a URL they can reach; on isolated IoT
    networks that means Home Assistant's own IP, never an external host. Serving the
    chimes locally keeps ring sounds working with no internet.
    """
    src = Path(__file__).parent / "sounds"
    if not src.is_dir():
        return
    dest = Path(hass.config.path("www", "dx482"))
    dest.mkdir(parents=True, exist_ok=True)
    for mp3 in src.glob("*.mp3"):
        target = dest / mp3.name
        try:
            if not target.exists() or target.stat().st_size != mp3.stat().st_size:
                shutil.copyfile(mp3, target)
        except OSError as err:
            _LOGGER.warning("Could not install chime %s: %s", mp3.name, err)


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry) -> bool:
    cfg = {**entry.data, **entry.options}
    await hass.async_add_executor_job(_install_sounds, hass)
    state: dict[str, Any] = {"call": "idle", "proxy": "disconnected", "video": "off", "registered": False}

    @callback
    def _fire_ring() -> None:
        state["last_ring"] = time.time()
        async_dispatcher_send(hass, f"{SIGNAL_DOORBELL_EVENT}_{entry.entry_id}", "ring")
        async_dispatcher_send(hass, f"{SIGNAL_STATE}_{entry.entry_id}")

    @callback
    def _on_event(event: str, payload: Any) -> None:
        if event == EVENT_RING:
            _fire_ring()
            return
        if event == "registered":
            state["registered"] = bool(payload)
            # The doorbell just (re)booted and registered: re-read its settings.
            rt = getattr(entry, "runtime_data", None)
            if rt is not None and rt.device_config is not None:
                hass.async_create_task(_refresh_device_config(entry))
        else:
            state[event] = payload
        async_dispatcher_send(hass, f"{SIGNAL_STATE}_{entry.entry_id}")

    session = DX482Session(
        local_ip=cfg[CONF_LOCAL_IP],
        device_ip=cfg[CONF_HOST],
        device_user=cfg[CONF_DEVICE_ACCOUNT],
        phone_user=cfg[CONF_PHONE_ACCOUNT],
        mon_code=cfg.get(CONF_MON_CODE, DEFAULT_MON_CODE),
        sip_port=cfg.get(CONF_SIP_PORT, DEFAULT_SIP_PORT),
        proxy_port=cfg.get(CONF_PROXY_PORT, DEFAULT_PROXY_PORT),
        audio_port=cfg.get(CONF_AUDIO_PORT, DEFAULT_AUDIO_PORT),
        video_port=cfg.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT),
        device_sip_port=DEVICE_SIP_PORT,
        idle_timeout=cfg.get(CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT),
        auto_answer=cfg.get(CONF_AUTO_ANSWER, DEFAULT_AUTO_ANSWER),
        on_event=_on_event,
    )
    try:
        await session.start()
    except OSError as err:
        raise ConfigEntryNotReadyError(f"cannot bind local ports: {err}") from err

    device_config = DeviceConfig(cfg[CONF_HOST])
    try:
        await device_config.async_refresh()
    except (OSError, ValueError) as err:
        _LOGGER.warning("Could not read doorbell settings over FTP (%s); settings entities will retry on reboot", err)

    @callback
    def _notify() -> None:
        async_dispatcher_send(hass, f"{SIGNAL_STATE}_{entry.entry_id}")

    entry.runtime_data = DX482Data(session=session, state=state, device_config=device_config, notify=_notify)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
    )

    if cfg.get(CONF_RING_POLL, DEFAULT_RING_POLL):
        poller = CallRecordPoller(
            hass, device_config,
            cfg.get(CONF_RING_POLL_INTERVAL, DEFAULT_RING_POLL_INTERVAL),
            _fire_ring,
        )
        poller.start()
        entry.runtime_data.call_poller = poller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _refresh_device_config(entry: DX482ConfigEntry) -> None:
    cfg = entry.runtime_data.device_config
    try:
        await cfg.async_refresh()
        cfg.reboot_required = False
    except (OSError, ValueError) as err:
        _LOGGER.debug("settings refresh failed: %s", err)
    if entry.runtime_data.notify:
        entry.runtime_data.notify()


async def async_unload_entry(hass: HomeAssistant, entry: DX482ConfigEntry) -> bool:
    if entry.runtime_data.call_poller is not None:
        await entry.runtime_data.call_poller.stop()
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.session.stop()
    return ok


async def _async_update_listener(hass: HomeAssistant, entry: DX482ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


