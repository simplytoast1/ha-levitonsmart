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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL
from .leviton_api.client import LevitonApiClient, LevitonAuthError
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

    # Populated once the WebSocket exists, so a mid-session token refresh can
    # reach it. The REST client is built before the WebSocket.
    ws_holder: Dict[str, LevitonWebSocket] = {}

    @callback
    def _persist_login_response(login_response: Dict[str, Any]) -> None:
        """
        Store a silently refreshed session back onto the config entry.

        Without this the entry would keep the expired token forever, every restart
        would burn another login round trip, and the WebSocket would keep
        reconnecting with a token the cloud no longer accepts.
        """
        _LOGGER.debug("Persisting refreshed Leviton session to the config entry.")
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "login_response": login_response}
        )

        ws = ws_holder.get("ws")
        if ws is not None:
            ws.update_login_response(login_response)
            hass.async_create_task(ws.reconnect())

    client = LevitonApiClient(session, on_token_refresh=_persist_login_response)

    # The client needs the credentials, not just the token, so it can recover on
    # its own when the stored token expires.
    client.set_credentials(email, password)

    try:
        # Try to restore session from stored login_response (avoids needing 2FA again)
        stored_login_response = entry.data.get("login_response")

        if stored_login_response:
            _LOGGER.debug("Restoring session from stored login response...")
            client.restore_login_response(stored_login_response)
        else:
            # Fallback: Fresh login (will fail if 2FA required without code)
            _LOGGER.debug("No stored login response, attempting fresh login...")
            code = entry.data.get("code")
            await client.login(email, password, code)

        _LOGGER.debug("Fetching residential permissions...")
        account_id = await client.get_residential_permissions()

        _LOGGER.debug("Fetching residence ID...")
        residence_id = await client.get_residence_id(account_id)

    except LevitonAuthError as err:
        # Only the user can fix this, so ask them to re-authenticate instead of
        # retrying forever behind a "will retry" message.
        _LOGGER.error("Leviton authentication failed: %s", err)
        raise ConfigEntryAuthFailed(str(err)) from err

    except Exception as err:
        _LOGGER.error("Failed to connect: %s", err)
        raise ConfigEntryNotReady from err

    # The calls above may have refreshed the session, so take the current one.
    login_response = client.login_response

    async def async_update_data():
        """Fetch data from API."""
        try:
            devices = await client.get_iot_switches(residence_id)
            return {str(d["id"]): d for d in devices}
        except LevitonAuthError as err:
            # Surfaces as a re-authentication prompt rather than a silent failure.
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
             raise UpdateFailed(f"Error communicating with API: {err}")

    # Initialize Coordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=UPDATE_INTERVAL,
    )

    # Initial fetch
    await coordinator.async_config_entry_first_refresh()

    # Track which device IDs the WebSocket has subscribed to.
    known_ws_ids: set[str] = set()

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
    ws_holder["ws"] = ws
    _LOGGER.info("Starting WebSocket connection...")

    # device_ids are keys in coordinator.data
    initial_ids = [str(k) for k in coordinator.data.keys()]
    known_ws_ids.update(initial_ids)
    ws.start(initial_ids)

    # Subscribe to any new devices that appear on subsequent coordinator refreshes.
    @callback
    def _subscribe_new_devices() -> None:
        new_ids = [str(d) for d in coordinator.data.keys() if str(d) not in known_ws_ids]
        for device_id in new_ids:
            known_ws_ids.add(device_id)
            hass.async_create_task(ws.add_device(device_id))
        if new_ids:
            _LOGGER.info("Discovered %d new Leviton device(s): %s", len(new_ids), new_ids)

    entry.async_on_unload(coordinator.async_add_listener(_subscribe_new_devices))

    # Store everything in hass.data for platforms to access
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "ws": ws,
        "coordinator": coordinator, # Pass coordinator instead of raw map
    }

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """
    Allow a device to be manually removed from the device registry.

    HA calls this when the user clicks 'Delete' on a device. We permit deletion
    only if the device is no longer present in the latest coordinator data,
    i.e. it has been removed from the Leviton cloud and is now orphaned.
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    device_id = next(
        (identifier[1] for identifier in device_entry.identifiers if identifier[0] == DOMAIN),
        None,
    )

    # Allow deletion if the device is not (or no longer) in coordinator data
    return device_id is None or device_id not in coordinator.data


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
