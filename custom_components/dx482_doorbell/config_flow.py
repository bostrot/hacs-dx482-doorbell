"""Config flow for the DX482 doorbell (local cloud stand-in)."""

from __future__ import annotations

import socket
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_RING_POLL,
    CONF_RING_POLL_INTERVAL,
    DEFAULT_RING_POLL,
    DEFAULT_RING_POLL_INTERVAL,
    CONF_AUDIO_PORT,
    CONF_AUTO_ANSWER,
    CONF_DEVICE_ACCOUNT,
    CONF_HOST,
    CONF_IDLE_TIMEOUT,
    CONF_LOCAL_IP,
    CONF_MON_CODE,
    CONF_PHONE_ACCOUNT,
    CONF_PROXY_PORT,
    CONF_RELAY_COUNT,
    CONF_SIP_PORT,
    CONF_VIDEO_PORT,
    DEFAULT_AUDIO_PORT,
    DEFAULT_AUTO_ANSWER,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_MON_CODE,
    DEFAULT_PROXY_PORT,
    DEFAULT_RELAY_COUNT,
    DEFAULT_SIP_PORT,
    DEFAULT_VIDEO_PORT,
    DOMAIN,
)


def _guess_local_ip(target: str) -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target or "8.8.8.8", 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def _user_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
            vol.Required(CONF_LOCAL_IP, default=d.get(CONF_LOCAL_IP, _guess_local_ip(d.get(CONF_HOST, "")))): str,
            vol.Required(CONF_DEVICE_ACCOUNT, default=d.get(CONF_DEVICE_ACCOUNT, "")): str,
            vol.Required(CONF_PHONE_ACCOUNT, default=d.get(CONF_PHONE_ACCOUNT, "")): str,
            vol.Required(CONF_MON_CODE, default=d.get(CONF_MON_CODE, DEFAULT_MON_CODE)): str,
        }
    )


class DX482ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ACCOUNT].strip().lower())
            self._abort_if_unique_id_configured()
            for key in (CONF_DEVICE_ACCOUNT, CONF_PHONE_ACCOUNT, CONF_MON_CODE):
                user_input[key] = user_input[key].strip()
            # Make sure the ports we will impersonate the cloud on are free.
            for port, kind in ((DEFAULT_SIP_PORT, socket.SOCK_DGRAM), (DEFAULT_PROXY_PORT, socket.SOCK_STREAM)):
                try:
                    s = socket.socket(socket.AF_INET, kind)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((user_input[CONF_LOCAL_IP], port))
                    s.close()
                except OSError:
                    errors["base"] = "port_in_use"
                    break
            if not errors:
                return self.async_create_entry(title=f"DX482 {user_input[CONF_HOST]}", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_user_schema(user_input or {}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DX482OptionsFlow()


class DX482OptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_MON_CODE, default=cur.get(CONF_MON_CODE, DEFAULT_MON_CODE)): str,
                vol.Required(CONF_IDLE_TIMEOUT, default=cur.get(CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT)): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
                vol.Required(CONF_AUTO_ANSWER, default=cur.get(CONF_AUTO_ANSWER, DEFAULT_AUTO_ANSWER)): bool,
                vol.Required(CONF_RING_POLL, default=cur.get(CONF_RING_POLL, DEFAULT_RING_POLL)): bool,
                vol.Required(CONF_RING_POLL_INTERVAL, default=cur.get(CONF_RING_POLL_INTERVAL, DEFAULT_RING_POLL_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=2, max=60)),
                vol.Required(CONF_RELAY_COUNT, default=cur.get(CONF_RELAY_COUNT, DEFAULT_RELAY_COUNT)): vol.In([1, 2]),
                vol.Required(CONF_SIP_PORT, default=cur.get(CONF_SIP_PORT, DEFAULT_SIP_PORT)): cv.port,
                vol.Required(CONF_PROXY_PORT, default=cur.get(CONF_PROXY_PORT, DEFAULT_PROXY_PORT)): cv.port,
                vol.Required(CONF_AUDIO_PORT, default=cur.get(CONF_AUDIO_PORT, DEFAULT_AUDIO_PORT)): cv.port,
                vol.Required(CONF_VIDEO_PORT, default=cur.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)): cv.port,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
