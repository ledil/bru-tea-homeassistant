"""Config-Flow: BRU-Maschine finden und direkt in der Oberfläche koppeln."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from . import protocol as p
from .const import CONF_TEAS, CUSTOM_TEA, DEFAULT_TEAS, DOMAIN
from .pairing import BruPairing, PairingError
from .protocol import NAME_PREFIX, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


def _is_bru(info: BluetoothServiceInfoBleak) -> bool:
    return (info.name or "").startswith(NAME_PREFIX) or SERVICE_UUID in [
        u.lower() for u in info.service_uuids]


class BruConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BruOptionsFlow()

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


# ---- Teesorten verwalten ("Konfigurieren") ------------------------------------
def _dropdown(options: list[str]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options,
                                               mode=SelectSelectorMode.DROPDOWN))


def _tea_schema(tea: dict | None = None) -> vol.Schema:
    tea = tea or {"name": "", "temperature": "80 °C", "time": "3:00",
                  "water": "200 ml", "rinse": False}
    return vol.Schema({
        vol.Required("name", default=tea["name"]): str,
        vol.Required("temperature", default=tea["temperature"]): _dropdown(p.TEMP_OPTIONS),
        vol.Required("time", default=tea["time"]): _dropdown(p.TIME_OPTIONS),
        vol.Required("water", default=tea["water"]): _dropdown(p.WATER_OPTIONS),
        vol.Required("rinse", default=bool(tea.get("rinse", False))): bool,
    })


class BruOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._teas: list[dict] | None = None
        self._edit_id: str | None = None

    @property
    def teas(self) -> list[dict]:
        if self._teas is None:
            self._teas = [dict(t) for t in
                          self.config_entry.options.get(CONF_TEAS, DEFAULT_TEAS)]
        return self._teas

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options,
                                             CONF_TEAS: self.teas})

    def _validate(self, data: dict, own_id: str | None) -> dict[str, str]:
        name = data["name"].strip()
        if not name or name == CUSTOM_TEA:
            return {"name": "invalid_name"}
        if any(t["name"].lower() == name.lower() and t["id"] != own_id for t in self.teas):
            return {"name": "duplicate_name"}
        return {}

    def _new_id(self, name: str) -> str:
        base = slugify(name) or "tee"
        ids = {t["id"] for t in self.teas}
        new, i = base, 2
        while new in ids:
            new, i = f"{base}_{i}", i + 1
        return new

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        menu = ["add"]
        if self.teas:
            menu += ["edit", "delete"]
        return self.async_show_menu(
            step_id="init", menu_options=menu,
            description_placeholders={"teas": "\n".join(
                f"- {t['name']}: {t['temperature']}, {t['time']} min, {t['water']}"
                + (", spülen" if t.get("rinse") else "") for t in self.teas) or "–"})

    async def async_step_add(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = self._validate(user_input, None)
            if not errors:
                name = user_input["name"].strip()
                self.teas.append({"id": self._new_id(name), **user_input, "name": name})
                return self._save()
        return self.async_show_form(step_id="add",
                                    data_schema=_tea_schema(user_input), errors=errors)

    async def async_step_edit(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_id = user_input["tea"]
            return await self.async_step_edit_tea()
        return self.async_show_form(step_id="edit", data_schema=vol.Schema({
            vol.Required("tea"): vol.In({t["id"]: t["name"] for t in self.teas})}))

    async def async_step_edit_tea(self, user_input=None) -> ConfigFlowResult:
        tea = next(t for t in self.teas if t["id"] == self._edit_id)
        errors = {}
        if user_input is not None:
            errors = self._validate(user_input, tea["id"])
            if not errors:
                tea.update(user_input, name=user_input["name"].strip())
                return self._save()
        return self.async_show_form(step_id="edit_tea",
                                    data_schema=_tea_schema(user_input or tea),
                                    errors=errors)

    async def async_step_delete(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            remove = set(user_input.get("teas", []))
            self._teas = [t for t in self.teas if t["id"] not in remove]
            return self._save()
        return self.async_show_form(step_id="delete", data_schema=vol.Schema({
            vol.Optional("teas", default=[]): SelectSelector(SelectSelectorConfig(
                options=[{"value": t["id"], "label": t["name"]} for t in self.teas],
                multiple=True, mode=SelectSelectorMode.LIST))}))
