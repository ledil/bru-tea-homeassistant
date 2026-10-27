"""Basisklasse für BRU-Entitäten."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .device import BruDevice


class BruEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, dev: BruDevice, key: str, name: str) -> None:
        self.dev = dev
        self._attr_unique_id = f"{dev.address}_{key}"
        self._attr_name = name
        self._attr_device_info = dev.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.dev.add_listener(self.async_write_ha_state))
