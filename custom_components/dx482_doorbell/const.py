"""Constants for the DX482 doorbell integration."""

from __future__ import annotations

DOMAIN = "dx482_doorbell"

# Config entry keys
CONF_HOST = "host"                  # doorbell IP
CONF_LOCAL_IP = "local_ip"          # this HA host's LAN IP (what the doorbell's [server] points to)
CONF_DEVICE_ACCOUNT = "device_account"   # doorbell SIP account, e.g. 64000002db48
CONF_PHONE_ACCOUNT = "phone_account"     # "divert"/phone SIP account, e.g. 6e000002db48
CONF_MON_CODE = "mon_code"          # monitor code sent to start video, e.g. 0x34
CONF_SIP_PORT = "sip_port"
CONF_PROXY_PORT = "proxy_port"
CONF_AUDIO_PORT = "audio_port"
CONF_VIDEO_PORT = "video_port"
CONF_IDLE_TIMEOUT = "idle_timeout"
CONF_AUTO_ANSWER = "auto_answer"
CONF_RELAY_COUNT = "relay_count"
CONF_RING_POLL = "ring_poll"
CONF_RING_POLL_INTERVAL = "ring_poll_interval"

# Defaults
DEFAULT_NAME = "DX482 Doorbell"
DEFAULT_MON_CODE = "0x34"
DEFAULT_SIP_PORT = 5068
DEFAULT_PROXY_PORT = 8850
DEFAULT_AUDIO_PORT = 30000
DEFAULT_VIDEO_PORT = 30002
DEFAULT_IDLE_TIMEOUT = 30
DEFAULT_AUTO_ANSWER = False
DEFAULT_RELAY_COUNT = 1
DEFAULT_RING_POLL = False
DEFAULT_RING_POLL_INTERVAL = 3
DEVICE_SIP_PORT = 5069

MANUFACTURER = "2easy / V-Tec"
MODEL = "DX482"

# Events / signals
EVENT_RING = "ring"
SIGNAL_DOORBELL_EVENT = f"{DOMAIN}_event"
SIGNAL_STATE = f"{DOMAIN}_state"
