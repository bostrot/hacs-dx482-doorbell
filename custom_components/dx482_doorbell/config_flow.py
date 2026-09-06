"""Config flow for the DX482 doorbell."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CONTROL_PORT,
    CONF_HOST,
    CONF_RTSP_CHANNEL,
    CONF_RTSP_PASSWORD,
    CONF_RTSP_PORT,
    CONF_RTSP_USERNAME,
    CONF_RING_ENABLED,
    CONF_RING_POLL_MS,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONTROL_PORT,
    DEFAULT_NAME,
    DEFAULT_RING_ENABLED,
    DEFAULT_RING_POLL_MS,
    DEFAULT_RTSP_CHANNEL,
    DEFAULT_RTSP_PASSWORD,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .protocol import DX482Client, DX482Error


def _data_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_CONTROL_PORT, default=d.get(CONF_CONTROL_PORT, DEFAULT_CONTROL_PORT)
            ): cv.port,
            vol.Required(
                CONF_RTSP_PORT, default=d.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)
            ): cv.port,
            vol.Required(
                CONF_RTSP_USERNAME,
                default=d.get(CONF_RTSP_USERNAME, DEFAULT_RTSP_USERNAME),
            ): str,
            vol.Required(
                CONF_RTSP_PASSWORD,
                default=d.get(CONF_RTSP_PASSWORD, DEFAULT_RTSP_PASSWORD),
            ): str,
            vol.Required(
                CONF_RTSP_CHANNEL,
                default=d.get(CONF_RTSP_CHANNEL, DEFAULT_RTSP_CHANNEL),
            ): vol.In(["101", "102"]),
        }
    )


class DX482ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the DX482 doorbell."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            await self.async_set_unique_id(f"{host}:{user_input[CONF_CONTROL_PORT]}")
            self._abort_if_unique_id_configured()

            client = DX482Client(host, user_input[CONF_CONTROL_PORT])
            try:
                reachable = await client.async_ping()
            except DX482Error:
                reachable = False
            if not reachable:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_HOST, DEFAULT_NAME),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DX482OptionsFlow()


class DX482OptionsFlow(OptionsFlow):
    """Handle options (poll interval, RTSP channel)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
                vol.Required(
                    CONF_RTSP_CHANNEL,
                    default=current.get(CONF_RTSP_CHANNEL, DEFAULT_RTSP_CHANNEL),
                ): vol.In(["101", "102"]),
                vol.Required(
                    CONF_RING_ENABLED,
                    default=current.get(CONF_RING_ENABLED, DEFAULT_RING_ENABLED),
                ): bool,
                vol.Required(
                    CONF_RING_POLL_MS,
                    default=current.get(CONF_RING_POLL_MS, DEFAULT_RING_POLL_MS),
                ): vol.All(vol.Coerce(int), vol.Range(min=50, max=10000)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
