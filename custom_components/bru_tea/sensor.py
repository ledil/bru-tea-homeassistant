"""Status-Sensoren."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BruEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    dev = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StatusSensor(dev), SubStatusSensor(dev), ResultSensor(dev)])


class StatusSensor(BruEntity, SensorEntity):
    _attr_icon = "mdi:tea"

    def __init__(self, dev):
        super().__init__(dev, "status", "Status")

    @property
    def native_value(self):
        return self.dev.status_text

    @property
    def extra_state_attributes(self):
        return {"status_code": self.dev.status, "status_raw": self.dev.status_name,
                "phase": self.dev.phase_text, "substatus": self.dev.substatus_name,
                "substatus_code": self.dev.substatus, "source": self.dev.status_source,
                "connected": self.dev.connected, "rssi": self.dev.rssi,
                "firmware": self.dev.firmware}

    @property
    def available(self) -> bool:
        return self.dev.available or self.dev.connected


class SubStatusSensor(BruEntity, SensorEntity):
    _attr_icon = "mdi:progress-clock"

    def __init__(self, dev):
        super().__init__(dev, "substatus", "Phase")

    @property
    def available(self) -> bool:
        return self.dev.available or self.dev.connected

    @property
    def native_value(self):
        return self.dev.phase_text

    @property
    def extra_state_attributes(self):
        return {"substatus_code": self.dev.substatus, "substatus_raw": self.dev.substatus_name}


class ResultSensor(BruEntity, SensorEntity):
    _attr_icon = "mdi:message-alert-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, dev):
        super().__init__(dev, "last_result", "Letztes Brüh-Ergebnis")

    @property
    def native_value(self):
        return self.dev.last_result
