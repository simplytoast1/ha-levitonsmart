"""
Leviton Binary Sensor Platform
------------------------------

This platform exposes binary sensors for Leviton devices, primarily Motion Sensors.
For example, the D2MSD Motion Dimmer exposes 'motion' state.
"""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODELS_MOTION_SENSOR
from .entity import LevitonEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Leviton Binary Sensor platform."""
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    for device_id, device_data in coordinator.data.items():
        model = device_data.get("model", "")
        # Create motion sensor entities for motion-capable models
        if model in MODELS_MOTION_SENSOR:
            entities.append(LevitonMotionSensor(client, coordinator, device_id, config_entry.entry_id))

    async_add_entities(entities)


class LevitonMotionSensor(LevitonEntity, BinarySensorEntity):
    """Representation of a Leviton Motion Sensor."""
    
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, client, coordinator, device_id, entry_id):
        """Initialize the motion sensor."""
        super().__init__(client, coordinator, device_id, entry_id)
        # Append _motion to unique_id so it doesn't conflict with the Light entity
        self._attr_unique_id = f"{self.device_id}_motion"
        # With _attr_has_entity_name=True, HA combines device name + entity name
        self._attr_name = "Motion"

    @property
    def is_on(self) -> bool:
        """
        Return true if motion is detected.
        
        The API typically returns specific motion status or occupancy.
        We check the 'motion' field from the WebSocket/API data.
        """
        return bool(self._data.get("motion"))
