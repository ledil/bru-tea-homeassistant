"""Buttons: Brühen, Abbrechen, Status aktualisieren."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BruEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    dev = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrewButton(dev), CancelButton(dev), RefreshButton(dev)])


class BrewButton(BruEntity, ButtonEntity):
    _attr_icon = "mdi:kettle-steam"

    def __init__(self, dev):
        super().__init__(dev, "brew", "Tee zubereiten")

    async def async_press(self) -> None:
        await self.dev.async_brew()


class CancelButton(BruEntity, ButtonEntity):
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, dev):
        super().__init__(dev, "cancel", "Abbrechen")

    async def async_press(self) -> None:
        await self.dev.async_cancel()


class RefreshButton(BruEntity, ButtonEntity):
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, dev):
        super().__init__(dev, "refresh", "Status aktualisieren")

    async def async_press(self) -> None:
        await self.dev.async_refresh()
