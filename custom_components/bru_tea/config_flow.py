"""Config-Flow: BRU-Maschine finden und direkt in der Oberfläche koppeln."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .pairing import BruPairing, PairingError
from .protocol import NAME_PREFIX, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


def _is_bru(info: BluetoothServiceInfoBleak) -> bool:
    return (info.name or "").startswith(NAME_PREFIX) or SERVICE_UUID in [
        u.lower() for u in info.service_uuids]


class BruConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str = "BRU"
        self._devices: dict[str, str] = {}
        self._pairing: BruPairing | None = None

    # ---- Gerät finden --------------------------------------------------------
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or "BRU"
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_pair()

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._name = self._devices.get(self._address, "BRU").split(" (")[0]
            return await self.async_step_pair()

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in current and _is_bru(info):
                self._devices[info.address] = f"{info.name or 'BRU'} ({info.address})"
        if not self._devices:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._devices)}))

    # ---- Koppeln ---------------------------------------------------------------
    async def async_step_pair(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"name": self._name, "error": ""}
        if user_input is not None:
            if user_input.get("skip"):
                return self._finish()
            await self._close_pairing()
            self._pairing = BruPairing(self._address)
            try:
                if await self._pairing.start():
                    await self._close_pairing()
                    return self._finish()                      # schon gekoppelt
                if await self._pairing.wait_for_request(30) == "done":
                    await self._close_pairing()
                    return self._finish()                      # ohne Code gekoppelt
                return await self.async_step_code()
            except PairingError as err:
                _LOGGER.warning("BRU-Pairing: %s", err)
                await self._close_pairing()
                errors["base"] = "pair_failed"
                placeholders["error"] = str(err)

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Optional("skip", default=False): bool}),
            errors=errors, description_placeholders=placeholders)

    async def async_step_code(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None and self._pairing is not None:
            code = str(user_input["code"]).strip()
            if not code.isdigit():
                errors["code"] = "invalid_code"
            else:
                self._pairing.submit_code(code)
                try:
                    await self._pairing.wait_done(40)
                    await self._close_pairing()
                    return self._finish()
                except PairingError as err:
                    _LOGGER.warning("BRU-Pairing: %s", err)
                    await self._close_pairing()
                    errors["base"] = "pair_failed"
                    placeholders["error"] = str(err)
                    return self.async_show_form(
                        step_id="pair",
                        data_schema=vol.Schema({vol.Optional("skip", default=False): bool}),
                        errors=errors,
                        description_placeholders={"name": self._name, **placeholders})

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors, description_placeholders=placeholders)

    # ---- Hilfen ------------------------------------------------------------------
    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._name,
                                       data={CONF_ADDRESS: self._address})

    async def _close_pairing(self) -> None:
        if self._pairing is not None:
            await self._pairing.close()
            self._pairing = None

    def async_remove(self) -> None:
        if self._pairing is not None:
            self.hass.async_create_task(self._close_pairing())
