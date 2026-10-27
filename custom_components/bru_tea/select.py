"""Auswahl für Teesorte, Temperatur, Brühzeit und Wassermenge."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import protocol as p
from .const import CUSTOM_TEA, DOMAIN
from .entity import BruEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    dev = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TeaSelect(dev),
        BruSelect(dev, "temperature", "Temperatur", p.TEMP_OPTIONS, "mdi:thermometer"),
        BruSelect(dev, "time", "Brühzeit", p.TIME_OPTIONS, "mdi:timer-outline"),
        BruSelect(dev, "water", "Wassermenge", p.WATER_OPTIONS, "mdi:cup-water"),
    ])


class BruSelect(BruEntity, RestoreEntity, SelectEntity):
    def __init__(self, dev, key, name, options, icon):
        super().__init__(dev, key, name)
        self._key = key
        self._attr_options = options
        self._attr_icon = icon

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in self._attr_options:
            self.dev.settings[self._key] = last.state

    @property
    def current_option(self):
        return self.dev.settings[self._key]

    async def async_select_option(self, option: str) -> None:
        self.dev.manual_change(self._key, option)


class TeaSelect(BruEntity, RestoreEntity, SelectEntity):
    """Teesorte wählen – setzt Temperatur, Zeit, Menge und Spülen."""

    _attr_icon = "mdi:tea-outline"

    def __init__(self, dev):
        super().__init__(dev, "tea", "Teesorte")

    @property
    def options(self) -> list[str]:
        return [CUSTOM_TEA] + [t["name"] for t in self.dev.teas]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and self.dev.get_tea(last.state) is not None:
            self.dev.settings["tea"] = last.state

    @property
    def current_option(self):
        tea = self.dev.settings.get("tea", CUSTOM_TEA)
        return tea if tea in self.options else CUSTOM_TEA

    async def async_select_option(self, option: str) -> None:
        self.dev.apply_tea(option)
