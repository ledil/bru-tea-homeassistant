"""BRU Tea Maker – Home-Assistant-Integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PLATFORMS
from .device import BruDevice

BREW_SCHEMA = vol.Schema({
    vol.Optional("address"): cv.string,
    vol.Optional("temperature"): cv.string,
    vol.Optional("time"): cv.string,
    vol.Optional("water"): vol.Coerce(int),
    vol.Optional("rinse"): cv.boolean,
    vol.Optional("buzzer", default=True): cv.boolean,
})
SIMPLE_SCHEMA = vol.Schema({vol.Optional("address"): cv.string})


def _get_device(hass: HomeAssistant, call: ServiceCall) -> BruDevice:
    devices: dict[str, BruDevice] = hass.data.get(DOMAIN, {})
    if not devices:
        raise HomeAssistantError("Keine BRU-Maschine eingerichtet")
    addr = call.data.get("address")
    if addr:
        for dev in devices.values():
            if dev.address.lower() == addr.lower():
                return dev
        raise HomeAssistantError(f"Keine BRU-Maschine mit Adresse {addr}")
    return next(iter(devices.values()))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    dev = BruDevice(hass, entry.data[CONF_ADDRESS], entry.title)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = dev
    dev.async_start()

    if not hass.services.has_service(DOMAIN, "brew"):
        async def brew(call: ServiceCall) -> None:
            await _get_device(hass, call).async_brew(
                temperature=call.data.get("temperature"), brew_time=call.data.get("time"),
                water=call.data.get("water"), rinse=call.data.get("rinse"),
                buzzer=call.data["buzzer"])

        async def cancel(call: ServiceCall) -> None:
            await _get_device(hass, call).async_cancel()

        async def refresh(call: ServiceCall) -> None:
            await _get_device(hass, call).async_refresh()

        hass.services.async_register(DOMAIN, "brew", brew, BREW_SCHEMA)
        hass.services.async_register(DOMAIN, "cancel", cancel, SIMPLE_SCHEMA)
        hass.services.async_register(DOMAIN, "refresh", refresh, SIMPLE_SCHEMA)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        dev: BruDevice = hass.data[DOMAIN].pop(entry.entry_id)
        await dev.async_shutdown()
        if not hass.data[DOMAIN]:
            for svc in ("brew", "cancel", "refresh"):
                hass.services.async_remove(DOMAIN, svc)
    return ok
