"""The 2easy DX482 Video Doorbell integration (direct-LAN, no cloud)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_CONTROL_PORT,
    CONF_HOST,
    CONF_RING_ENABLED,
    CONF_RING_POLL_MS,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONTROL_PORT,
    DEFAULT_RING_ENABLED,
    DEFAULT_RING_POLL_MS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_MOTION,
    EVENT_RING,
    MANUFACTURER,
    MODEL,
    SIGNAL_DOORBELL_EVENT,
)
from .coordinator import DX482Coordinator
from .protocol import DX482Client
from .ring_poller import RingPoller

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SENSOR,
]


@dataclass
class DX482Data:
    """Runtime data stored on the config entry."""

    client: DX482Client
    coordinator: DX482Coordinator
    ring_poller: RingPoller | None = None


type DX482ConfigEntry = ConfigEntry[DX482Data]


async def async_setup_entry(hass: HomeAssistant, entry: DX482ConfigEntry) -> bool:
    """Set up DX482 doorbell from a config entry."""
    host = entry.data[CONF_HOST]
    control_port = entry.data.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT)
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    client = DX482Client(host, control_port)
    coordinator = DX482Coordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = DX482Data(client=client, coordinator=coordinator)

    # Register the device up front so entities attach cleanly.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
        configuration_url=f"http://{host}",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_webhook(hass, entry)

    # Built-in local ring detection: poll the call log on a persistent socket.
    opts = {**entry.data, **entry.options}
    if opts.get(CONF_RING_ENABLED, DEFAULT_RING_ENABLED):
        poller = RingPoller(
            hass,
            entry.entry_id,
            client,
            opts.get(CONF_RING_POLL_MS, DEFAULT_RING_POLL_MS),
        )
        poller.start()
        entry.runtime_data.ring_poller = poller

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DX482ConfigEntry) -> bool:
    """Unload a config entry."""
    _unregister_webhook(hass, entry)
    if entry.runtime_data.ring_poller is not None:
        await entry.runtime_data.ring_poller.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: DX482ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# --- Webhook for ring / motion events -------------------------------------
#
# The doorbell's own ring signalling is SIP (cloud) and not observable on the
# LAN without packet capture.  Rather than depend on the cloud, this
# integration exposes a local webhook that an external notifier (a router-side
# tcpdump/SIP script, Frigate motion, an ONVIF event bridge, etc.) can POST to
# in order to raise a ring or motion event inside Home Assistant.
#
#   POST /api/webhook/<webhook_id>            -> ring
#   POST /api/webhook/<webhook_id>  {"event":"motion"}  -> motion


def _webhook_id(entry: DX482ConfigEntry) -> str:
    return f"{DOMAIN}_{entry.entry_id}"


@callback
def _register_webhook(hass: HomeAssistant, entry: DX482ConfigEntry) -> None:
    from homeassistant.components import webhook

    webhook_id = _webhook_id(entry)

    async def _handle(hass: HomeAssistant, webhook_id: str, request):
        event = EVENT_RING
        try:
            if request.can_read_body:
                body = await request.json()
                if isinstance(body, dict):
                    event = body.get("event", EVENT_RING)
        except (ValueError, TypeError):
            event = EVENT_RING
        if event not in (EVENT_RING, EVENT_MOTION):
            event = EVENT_RING
        _LOGGER.debug("Doorbell webhook fired: %s", event)
        async_dispatcher_send(hass, f"{SIGNAL_DOORBELL_EVENT}_{entry.entry_id}", event)

    try:
        webhook.async_register(
            hass, DOMAIN, entry.title, webhook_id, _handle, local_only=True
        )
    except ValueError:
        # Already registered (e.g. after a reload race) — safe to ignore.
        _LOGGER.debug("Webhook %s already registered", webhook_id)


@callback
def _unregister_webhook(hass: HomeAssistant, entry: DX482ConfigEntry) -> None:
    from homeassistant.components import webhook

    try:
        webhook.async_unregister(hass, _webhook_id(entry))
    except (ValueError, KeyError):
        pass
