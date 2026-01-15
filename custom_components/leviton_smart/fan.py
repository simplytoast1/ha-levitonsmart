"""
Leviton Fan Platform
--------------------

This platform controls Fan Speed Controllers (e.g., DW4SF, D24SF).
It maps Leviton's 4-speed levels to Home Assistant percentages.
"""

import logging
import math
from typing import Any, Optional

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import DOMAIN, MODELS_FAN
from .entity import LevitonEntity

_LOGGER = logging.getLogger(__name__)

# Leviton standard fan speeds (brightness values)
SPEED_LOW = 25
SPEED_MEDIUM = 50
SPEED_HIGH = 75
SPEED_MAX = 100

LEVITON_SPEEDS = [SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH, SPEED_MAX]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Leviton Fan platform."""
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    for device_id, device_data in coordinator.data.items():
        model = device_data.get("model", "")
        if model in MODELS_FAN:
            entities.append(LevitonFan(client, coordinator, device_id, config_entry.entry_id))

    async_add_entities(entities)


class LevitonFan(LevitonEntity, FanEntity):
    """Representation of a Leviton Fan Controller."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_OFF | FanEntityFeature.TURN_ON
    _attr_speed_count = len(LEVITON_SPEEDS)
    _attr_icon = "mdi:fan"

    def __init__(self, client, coordinator, device_id, entry_id):
        """Initialize the fan."""
        super().__init__(client, coordinator, device_id, entry_id)

    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        return self._data.get("power") == "ON"

    @property
    def percentage(self) -> Optional[int]:
        """
        Return the current speed percentage.
        We map the Leviton specific brightness (fan speed) to a standard HA percentage.
        """
        if not self.is_on:
            return 0
            
        brightness = self._data.get("brightness", 0)
        
        # Find nearest standard speed or exact match
        # If it's 0 (off) but power is ON, treat as low? Or just return 0.
        if brightness == 0:
            return 0
            
        return ordered_list_item_to_percentage(LEVITON_SPEEDS, brightness)

    async def async_turn_on(
        self, 
        percentage: Optional[int] = None, 
        preset_mode: Optional[str] = None, 
        **kwargs: Any
    ) -> None:
        """
        Turn the fan on.
        
        :param percentage: Optional percentage to set.
        """
        req_brightness = None

        if percentage is not None:
             req_brightness = percentage_to_ordered_list_item(LEVITON_SPEEDS, percentage)
        elif not self.is_on:
            # If turning on without specific speed, default to last known or just ON
            pass

        attributes = {"power": "ON"}
        
        if req_brightness is not None:
            attributes["brightness"] = req_brightness
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn on %s: %s", self.name, err)

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        attributes = {"power": "OFF"}
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn off %s: %s", self.name, err)

        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """
        Set the speed percentage of the fan.
        """
        if percentage == 0:
            await self.async_turn_off()
            return
            
        req_brightness = percentage_to_ordered_list_item(LEVITON_SPEEDS, percentage)
        
        attributes = {"power": "ON", "brightness": req_brightness}
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to set fan speed for %s: %s", self.name, err)

        await self.coordinator.async_request_refresh()
