"""
Leviton WebSocket Client
------------------------

This module handles the persistent WebSocket connection to the My Leviton cloud.
It is responsible for:
1. Maintaining the connection (reconnecting on failure).
2. Authenticating via the specific 'challenge' mechanism.
3. Subscribing to device updates.
4. Parsing incoming 'notification' messages and dispatching them to registered callbacks.
"""

import asyncio
import json
import logging
import aiohttp
from typing import Optional, Dict, List, Callable, Any

_LOGGER = logging.getLogger(__name__)

# The WebSocket endpoint for My Leviton cloud
WS_URL = "wss://socket.cloud.leviton.com/"


class LevitonWebSocket:
    """
    Manages the WebSocket connection to My Leviton.
    """

    def __init__(
        self, 
        session: aiohttp.ClientSession, 
        login_response: Dict[str, Any], 
        on_update: Callable[[Dict[str, Any]], None]
    ) -> None:
        """
        Initialize the WebSocket manager.

        :param session: The aiohttp ClientSession.
        :param login_response: The FULL JSON response received from the login API. 
                               This is required for the auth challenge.
        :param on_update: A callback function `func(data)` that will be called when a device update arrives.
        """
        self._session = session
        self._login_response = login_response
        self._on_update = on_update
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self._device_ids: List[str] = []
        self._reconnect_task: Optional[asyncio.Task] = None

    def start(self, device_ids: List[str]) -> None:
        """
        Start the WebSocket connection task.

        :param device_ids: List of device IDs (strings) to subscribe to.
        """
        self._device_ids = device_ids
        self._running = True
        self._reconnect_task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        """
        Stop the WebSocket connection and cleanup tasks.
        """
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        _LOGGER.info("WebSocket client stopped.")

    async def _connect_loop(self) -> None:
        """
        The main loop that maintains the connection. 
        It attempts to connect and automatically reconnects on failure with a backoff delay.
        """
        retry_delay = 1
        
        while self._running:
            try:
                await self._connect()
                # If we return normally from _connect, it means remote closed connection cleanly-ish
                # or we were disconnected. Reset retry delay on successful connection duration?
                # For now, just reset if we had a successful run.
                retry_delay = 1 
            except Exception as err:
                _LOGGER.error("WebSocket connection error: %s. Reconnecting in %s seconds...", err, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Exponential backoff capped at 60s

    async def _connect(self) -> None:
        """
        Establish the WebSocket connection and handle the message loop.
        """
        # Include authorization token in headers
        token = self._login_response.get("id", "") if self._login_response else ""

        headers = {
            "Origin": "https://myapp.leviton.com",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
            "Authorization": token,
        }

        _LOGGER.debug("Connecting to WebSocket at %s (token present: %s)", WS_URL, bool(token))
        
        async with self._session.ws_connect(
            WS_URL,
            headers=headers,
            heartbeat=30
        ) as ws:
            self._ws = ws
            _LOGGER.info("WebSocket connected.")

            # Send authentication token immediately after connecting
            # Format: {"token": <full_login_response>} - no "type" field
            auth_payload = {"token": self._login_response}
            _LOGGER.info("Sending auth token immediately after connect...")
            await ws.send_json(auth_payload)

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket connection received error: %s", ws.exception())
                    break
        
        self._ws = None
        _LOGGER.info("WebSocket disconnected.")

    async def _handle_message(self, message_str: str) -> None:
        """
        Parse and route incoming WebSocket messages.

        :param message_str: The raw JSON string received.
        """
        # Strip null bytes (protocol terminator) and whitespace
        message_str = message_str.strip('\x00').strip()

        if not message_str:
            return

        _LOGGER.debug("Raw WebSocket message: %s", message_str[:200])

        try:
            data = json.loads(message_str)
        except ValueError:
            _LOGGER.error("Received invalid JSON: %s", message_str[:200])
            return

        msg_type = data.get("type")

        if msg_type == "challenge":
            # Server is asking for authentication.
            # CRITICAL: We must send the ENTIRE login response object as 'token'.
            _LOGGER.info("Received WebSocket challenge, sending auth response...")
            response = {
                "type": "authenticate",
                "token": self._login_response,
            }
            _LOGGER.debug("Auth payload keys: %s", list(self._login_response.keys()) if self._login_response else "None")
            await self._ws.send_json(response)

        elif msg_type == "status":
            status = data.get("status")
            connection_id = data.get("connectionId", "")
            _LOGGER.info("WebSocket status: %s (connectionId: %s)", status, connection_id)
            if status == "ready":
                # Auth successful, server is ready for subscriptions
                _LOGGER.info("WebSocket authenticated! Subscribing to %d devices...", len(self._device_ids))
                await self._subscribe_all()

        elif msg_type == "notification":
            # This is a device update.
            _LOGGER.debug("Received notification: %s", data)
            self._process_notification(data)

        else:
            _LOGGER.debug("Received unhandled WebSocket message: type=%s, data=%s", msg_type, data)

    async def _subscribe_all(self) -> None:
        """
        Send subscription requests for all registered device IDs.
        """
        if not self._ws:
            return

        for device_id in self._device_ids:
            # modelId must be an integer in the subscription
            try:
                model_id = int(device_id)
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid device ID format: %s", device_id)
                continue

            payload = {
                "type": "subscribe",
                "subscription": {
                    "modelName": "IotSwitch",
                    "modelId": model_id,
                }
            }
            _LOGGER.debug("Subscribing to device %d", model_id)
            await self._ws.send_json(payload)

        _LOGGER.info("Subscribed to %d devices.", len(self._device_ids))

    def _process_notification(self, data: Dict[str, Any]) -> None:
        """
        Extract meaningful data from a notification and trigger the update callback.

        :param data: The raw notification dictionary.
        """
        notification = data.get("notification", {})
        model_id = notification.get("modelId")
        event_data = notification.get("data", {})

        if not model_id:
            _LOGGER.warning("Notification missing modelId: %s", data)
            return

        if not event_data:
            _LOGGER.debug("Notification has no data: %s", data)
            return

        # Check if this device is one we're tracking
        device_id_str = str(model_id)
        if device_id_str not in self._device_ids and str(model_id) not in [str(d) for d in self._device_ids]:
            _LOGGER.debug("Notification for untracked device %s (tracking: %s)", model_id, self._device_ids)

        # Build update payload with device ID as string (matches coordinator.data keys)
        update_payload = {
            "id": device_id_str,
        }

        # Copy all relevant state fields from the notification data
        state_fields = ["power", "brightness", "fanSpeed", "occupancy", "motion", "connected"]
        for key in state_fields:
            if key in event_data:
                update_payload[key] = event_data[key]

        _LOGGER.info(
            "Device %s update: power=%s, brightness=%s",
            model_id,
            event_data.get("power"),
            event_data.get("brightness"),
        )
        _LOGGER.debug("Full notification data: %s", event_data)

        self._on_update(update_payload)
