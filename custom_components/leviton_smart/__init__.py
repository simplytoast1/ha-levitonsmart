"""
Leviton Decora Smart Integration
--------------------------------

The main entry point for the Leviton Smart custom component.
This module sets up the integration by:
1. Logging into the My Leviton API.
2. Discovering the user's residence and devices.
3. Establishing a WebSocket connection for real-time updates.
4. Forwarding the setup to the appropriate platforms (light, switch, fan, etc.).
"""

import logging
import asyncio
from typing import Dict, Any, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL
from .leviton_api.client import LevitonApiClient
from .leviton_api.websocket import LevitonWebSocket

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Leviton Smart from a config entry.

    :param hass: Home Assistant instance.
    :param entry: The config entry containing user credentials.
    :return: True if setup was successful.
    """
    hass.data.setdefault(DOMAIN, {})

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    client = LevitonApiClient(session)

    try:
        # Try to restore session from stored login_response (avoids needing 2FA again)
        stored_login_response = entry.data.get("login_response")

        if stored_login_response:
            _LOGGER.debug("Restoring session from stored login response...")
            client.restore_login_response(stored_login_response)
            login_response = stored_login_response
        else:
            # Fallback: Fresh login (will fail if 2FA required without code)
            _LOGGER.debug("No stored login response, attempting fresh login...")
            code = entry.data.get("code")
            login_response = await client.login(email, password, code)

        _LOGGER.debug("Fetching residential permissions...")
        account_id = await client.get_residential_permissions()

        _LOGGER.debug("Fetching residence ID...")
        residence_id = await client.get_residence_id(account_id)

    except Exception as err:
        _LOGGER.error("Failed to connect: %s", err)
        raise ConfigEntryNotReady from err

    async def async_update_data():
        """Fetch data from API."""
        try:
            devices = await client.get_iot_switches(residence_id)
            return {str(d["id"]): d for d in devices}
        except Exception as err:
             raise UpdateFailed(f"Error communicating with API: {err}")

    # Initialize Coordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=UPDATE_INTERVAL,
    )

    # Initial fetch
    await coordinator.async_config_entry_first_refresh()

    # Callback for WebSocket updates
    def on_update(data: Dict[str, Any]) -> None:
        """
        Handle real-time updates from WebSocket.
        Updates the coordinator data directly and notifies listeners.
        """
        device_id = data.get("id")
        if device_id and device_id in coordinator.data:
            # Create a new dict for this device to ensure we don't mutate in place (safest for HA)
            current_data = coordinator.data
            device_data = dict(current_data[device_id])
            device_data.update(data)
            
            # Create a new top-level dict (shallow copy) and assign the updated device
            new_data = dict(current_data)
            new_data[device_id] = device_data
            
            # Notify entities with the new data structure
            coordinator.async_set_updated_data(new_data)

    # Initialize and start WebSocket
    ws = LevitonWebSocket(session, login_response, on_update)
    _LOGGER.info("Starting WebSocket connection...")
    
    # device_ids are keys in coordinator.data
    ws.start(list(coordinator.data.keys()))

    # Store everything in hass.data for platforms to access
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "ws": ws,
        "coordinator": coordinator, # Pass coordinator instead of raw map
    }

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry.

    :param hass: Home Assistant instance.
    :param entry: The config entry to unload.
    :return: True if unload was successful.
    """
    # Create valid unload task
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        ws: LevitonWebSocket = data["ws"]
        await ws.stop()
        _LOGGER.info("Leviton Smart integration unloaded.")

    return unload_ok
