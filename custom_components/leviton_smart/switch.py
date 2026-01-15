"""
Leviton Switch Platform
-----------------------

This platform controls Relay Switches, Outlets, and GFCI devices.
It supports simple On/Off control.
"""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODELS_SWITCH, MODELS_OUTLET, MODELS_GFCI
from .entity import LevitonEntity

_LOGGER = logging.getLogger(__name__)

# All models that should be exposed as switches (on/off only)
SWITCH_MODELS = MODELS_SWITCH + MODELS_OUTLET + MODELS_GFCI


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Leviton Switch platform."""
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    for device_id, device_data in coordinator.data.items():
        model = device_data.get("model", "")
        # Create switch entities for switches, outlets, and GFCI devices
        if model in SWITCH_MODELS:
            entities.append(LevitonSwitch(client, coordinator, device_id, config_entry.entry_id))

    async_add_entities(entities)


class LevitonSwitch(LevitonEntity, SwitchEntity):
    """Representation of a Leviton Switch/Outlet."""

    _attr_icon = "mdi:light-switch"

    def __init__(self, client, coordinator, device_id, entry_id):
        """Initialize the switch."""
        super().__init__(client, coordinator, device_id, entry_id)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._data.get("power") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        attributes = {"power": "ON"}
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn on %s: %s", self.name, err)
            
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        attributes = {"power": "OFF"}
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn off %s: %s", self.name, err)

        await self.coordinator.async_request_refresh()
