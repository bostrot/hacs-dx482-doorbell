"""Constants for the DX482 doorbell integration."""

from __future__ import annotations

DOMAIN = "dx482_doorbell"

# Config entry keys
CONF_HOST = "host"
CONF_CONTROL_PORT = "control_port"
CONF_RTSP_PORT = "rtsp_port"
CONF_RTSP_USERNAME = "rtsp_username"
CONF_RTSP_PASSWORD = "rtsp_password"
CONF_RTSP_CHANNEL = "rtsp_channel"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_LOCK = "enable_lock"
CONF_RING_ENABLED = "ring_enabled"
CONF_RING_POLL_MS = "ring_poll_ms"

# Defaults
DEFAULT_NAME = "DX482 Doorbell"
DEFAULT_CONTROL_PORT = 8765
DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_USERNAME = "admin"
DEFAULT_RTSP_PASSWORD = "1234abcd"
DEFAULT_RTSP_CHANNEL = "101"  # 101 = main/high-res, 102 = sub/low-res
DEFAULT_SCAN_INTERVAL = 60  # seconds; device is fragile, poll gently
DEFAULT_RING_ENABLED = True
DEFAULT_RING_POLL_MS = 200  # call-log poll interval on a persistent connection

MANUFACTURER = "2easy"
MODEL = "DX482"

# Webhook / event
EVENT_RING = "ring"
EVENT_MOTION = "motion"
SIGNAL_DOORBELL_EVENT = f"{DOMAIN}_event"

# Coordinator data keys
DATA_AVAILABLE = "available"
DATA_DOOR_STATE = "door_state"
DATA_DOOR_STATE_RAW = "door_state_raw"
DATA_DOOR_OPEN = "door_open"
DATA_RSSI = "rssi"
