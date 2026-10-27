"""Schalter: nach dem Brühen spülen."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import BruEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([RinseSwitch(hass.data[DOMAIN][entry.entry_id])])


class RinseSwitch(BruEntity, RestoreEntity, SwitchEntity):
    _attr_icon = "mdi:water-sync"

    def __init__(self, dev):
        super().__init__(dev, "rinse", "Spülen nach dem Brühen")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last:
            self.dev.settings["rinse"] = last.state == "on"

    @property
    def is_on(self):
        return self.dev.settings["rinse"]

    async def async_turn_on(self, **kwargs) -> None:
        self.dev.manual_change("rinse", True)

    async def async_turn_off(self, **kwargs) -> None:
        self.dev.manual_change("rinse", False)
