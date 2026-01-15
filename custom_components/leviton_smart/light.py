"""
Leviton Light Platform
----------------------

This platform controls Dimmers that support brightness control.
It supports:
1. On/Off control.
2. Brightness control (1-100%).
3. Reading state from the shared device data.
"""

import logging
from typing import Any, Dict

from homeassistant.components.light import (
    LightEntity,
    ColorMode,
    ATTR_BRIGHTNESS,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODELS_LIGHT, MODELS_FAN
from .entity import LevitonEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Leviton Light platform."""
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    for device_id, device_data in coordinator.data.items():
        model = device_data.get("model", "")
        # Only create light entities for dimmer models (not fans, not switches)
        if model in MODELS_LIGHT and model not in MODELS_FAN:
            entities.append(LevitonDimmer(client, coordinator, device_id, config_entry.entry_id))

    async_add_entities(entities)


class LevitonDimmer(LevitonEntity, LightEntity):
    """Representation of a Leviton Dimmer."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_icon = "mdi:lightbulb-on"

    def __init__(self, client, coordinator, device_id, entry_id):
        """Initialize the dimmer."""
        super().__init__(client, coordinator, device_id, entry_id)

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._data.get("power") == "ON"

    @property
    def brightness(self) -> int:
        """
        Return the brightness of this light between 0..255.
        Leviton uses 0-100 scale.
        """
        leviton_level = self._data.get("brightness", 0)
        return int(leviton_level * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """
        Turn the light on.
        
        :param kwargs: May contain ATTR_BRIGHTNESS.
        """
        req_power = True
        req_brightness = None

        if ATTR_BRIGHTNESS in kwargs:
            # Convert 0-255 to 0-100
            ha_brightness = kwargs[ATTR_BRIGHTNESS]
            req_brightness = int(ha_brightness * 100 / 255)
            # Ensure it's at least 1 if on
            req_brightness = max(1, req_brightness)
        
        attributes = {"power": "ON"}
        if req_brightness is not None:
            attributes["brightness"] = req_brightness
        
        # Optimistic state update
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn on %s: %s", self.name, err)
            # Revert state on failure (next update will fix it anyway, but good practice)
            # Ideally we would revert, but real-time update will likely correct it soon.
            
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        
        attributes = {"power": "OFF"}
        
        self._data.update(attributes)
        self.async_write_ha_state()

        try:
            await self.client.set_device_attribute(self.device_id, attributes)
        except Exception as err:
            _LOGGER.error("Failed to turn off %s: %s", self.name, err)
            
        await self.coordinator.async_request_refresh()
