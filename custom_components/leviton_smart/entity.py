"""
Leviton Base Entity
-------------------

This module defines the base class for all Leviton Smart entities.
It encapsulates common logic such as:
1. Identifying the device.
2. Handling real-time updates from the WebSocket.
3. Managing the 'available' state.
4. Providing common device info for the Home Assistant Device Registry.
"""

from typing import Dict, Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.core import callback

from .const import DOMAIN
from .leviton_api.client import LevitonApiClient

class LevitonEntity(CoordinatorEntity):
    """Base class for Leviton devices."""

    def __init__(self, client: LevitonApiClient, coordinator, device_id: str, entry_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.client = client
        self.device_id = str(device_id) # Ensure string
        self.entry_id = entry_id
        self._attr_unique_id = str(device_id) # Ensure string
        self._attr_has_entity_name = True
        self._attr_name = None  # Use device name only, no entity suffix

    @property
    def _data(self) -> Dict[str, Any]:
        """
        Helper to get the latest data for this device from the coordinator.
        """
        return self.coordinator.data.get(self.device_id, {})

    @property
    def _device_name(self) -> str:
        """Get a clean device name without room info."""
        name = self._data.get("name") or "Leviton Device"

        # Remove trailing "None" (room name when unassigned)
        if name.endswith(" None"):
            name = name[:-5].strip()

        # If there's a roomName field that got prepended, try to use just the device name part
        # Some API responses include room name in the name field
        room_name = self._data.get("roomName") or self._data.get("room")
        if room_name and name.startswith(f"{room_name} "):
            name = name[len(room_name):].strip()

        return name or "Leviton Device"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self._device_name,
            manufacturer="Leviton",
            model=self._data.get("model", "Unknown Model"),
            sw_version=self._data.get("version"),
        )

    # Auto-remove entities when their device disappears from the coordinator.
    # Intentionally disabled: a temporary cloud communication failure would cause
    # all devices to vanish and trigger mass entity deletion. Manual deletion via
    # async_remove_config_entry_device (in __init__.py) is preferred instead.
    #
    # @callback
    # def _handle_coordinator_update(self) -> None:
    #     if self.device_id not in self.coordinator.data:
    #         self.hass.async_create_task(self.async_remove(force_remove=True))
    #         return
    #     super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check coordinator availability and specific device status
        return (
            self.coordinator.last_update_success 
            and self.device_id in self.coordinator.data
            and self._data.get("status") != "offline"
        )
