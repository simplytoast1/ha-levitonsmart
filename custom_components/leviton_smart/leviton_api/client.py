"""
Leviton API Client
------------------

This module provides the HTTP client for communicating with the My Leviton cloud API.
It handles user authentication (login), retrieving account information, discovering devices,
and controlling device states (power, brightness, etc.).

It translates the logic found in the original Homebridge plugin to an async Python implementation
suitable for Home Assistant.
"""

import logging
import json
import aiohttp
from typing import Optional, Dict, List, Any

# Logger for this module
_LOGGER = logging.getLogger(__name__)

# Base URL for the My Leviton API
BASE_URL = "https://my.leviton.com/api"

# Default headers matching the official Leviton app
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://myapp.leviton.com",
    "Referer": "https://myapp.leviton.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Accept-Language": "en-US,en;q=0.9",
}


class TwoFactorRequired(Exception):
    """Raised when the API returns a 2FA challenge."""
    pass


class AuthenticationExpired(Exception):
    """Raised when the token has expired and re-authentication is needed."""
    pass


class LevitonApiClient:
    """
    Async Client for the My Leviton API.

    This class manages the session, authentication, and specific API endpoints
    required to interact with Leviton Decora Smart devices.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """
        Initialize the API client.

        :param session: The aiohttp ClientSession to use for making requests.
        """
        self._session = session
        self._token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._email: Optional[str] = None
        self._password: Optional[str] = None
        self._code: Optional[str] = None
        self._login_response: Optional[Dict[str, Any]] = None

    def restore_session(self, token: str, user_id: str) -> None:
        """Restore a previously saved session."""
        self._token = token
        self._user_id = user_id

    def restore_login_response(self, login_response: Dict[str, Any]) -> None:
        """
        Restore the full login response from stored config entry data.
        This avoids needing to re-authenticate (and re-do 2FA) on every restart.

        :param login_response: The full login response dict stored during initial setup.
        """
        self._login_response = login_response
        self._token = login_response.get("id")
        self._user_id = login_response.get("userId")

    @property
    def login_response(self) -> Optional[Dict[str, Any]]:
        """Return the full login response (needed for WebSocket authentication)."""
        return self._login_response

    @property
    def session(self) -> aiohttp.ClientSession:
        """Return the aiohttp session."""
        return self._session

    async def login(self, email: str, password: str, code: Optional[str] = None) -> Dict[str, Any]:
        """
        Authenticate with the My Leviton service using email and password.
        Stores credentials for auto-refresh.
        
        This method sends a POST request to the /Person/login endpoint.
        The response contains the authentication token and user ID which are stored internally
        for subsequent requests.
        
        If 2FA is enabled and no code is provided, this will raise TwoFactorRequired.
        If a code is provided, it is included in the login payload.

        :param email: User's email address.
        :param password: User's password.
        :param code: Optional 2FA code if required.
        :return: The full JSON login response dictionary.
        :raises TwoFactorRequired: If the server asks for a 2FA code.
        :raises Exception: If authentication fails or response is invalid.
        """
        url = f"{BASE_URL}/Person/login?include=user"
        _LOGGER.debug("Attempting to login with email: %s", email)

        headers = {**DEFAULT_HEADERS}
        payload = {"email": email, "password": password}
        
        if code:
            payload["code"] = code

        async with self._session.post(url, json=payload, headers=headers) as response:
            text = await response.text()
            
            # Check for 2FA requirement
            if response.status in (401, 406):
                if "InsufficientData:Personusestwofactorauthentication.Requirescode." in text:
                    _LOGGER.info("2FA Code Required")
                    raise TwoFactorRequired("2FA Code Required")
                
                # Other auth failure - do not recursion here, just fail on initial login
                _LOGGER.error("Login failed. Status: %s. Response: %s", response.status, text)
                raise Exception(f"Login failed: {text}")

            if response.status != 200:
                _LOGGER.error("Login failed. Status: %s. Response: %s", response.status, text)
                raise Exception(f"Login failed with status {response.status}")

            data = json.loads(text)
            
            # Validate response contains necessary auth data
            if "id" not in data or "userId" not in data:
                _LOGGER.error("Invalid login response: missing id or userId")
                raise Exception("Invalid login response")

            self._token = data["id"]
            self._user_id = data["userId"]
            self._login_response = data  # Store full response for WebSocket auth

            # Store credentials for auto-refresh
            self._email = email
            self._password = password
            self._code = code

            _LOGGER.info("Login successful. Token obtained.")
            return data

    async def _make_request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """
        Helper to make authenticated requests with auto-retry on 401.

        On 401 (token expired), tries to re-login WITHOUT 2FA code first.
        If 2FA is required, raises AuthenticationExpired so HA can trigger re-auth.
        """
        if not self._token:
            raise Exception("Not authenticated.")

        headers = {**DEFAULT_HEADERS, **kwargs.pop("headers", {})}
        headers["Authorization"] = self._token

        # First attempt
        response = await self._session.request(method, url, headers=headers, **kwargs)

        if response.status == 401:
            _LOGGER.warning("Token expired (401). Attempting re-authentication...")

            if self._email and self._password:
                try:
                    # Try to re-login WITHOUT 2FA code (may work if remembered)
                    await self.login(self._email, self._password)
                    headers["Authorization"] = self._token
                    response = await self._session.request(method, url, headers=headers, **kwargs)
                except TwoFactorRequired:
                    # 2FA required - user needs to re-authenticate manually
                    _LOGGER.error("Token expired and 2FA required. User must re-authenticate.")
                    raise AuthenticationExpired("Token expired. Please re-authenticate in Home Assistant.")
            else:
                _LOGGER.error("Cannot re-authenticate: missing credentials.")
                raise AuthenticationExpired("Token expired and no credentials stored.")

        return response




    async def get_residential_permissions(self) -> str:
        """
        Retrieve the primary Residential Account ID for the logged-in user.

        This involves:
        1. Getting the list of 'residentialPermissions' for the user.
        2. Extracting the 'residentialAccountId' from the first permission found.

        :return: The residentialAccountId string.
        :raises Exception: If no permissions or accounts are found.
        """
        if not self._token or not self._user_id:
            raise Exception("Not authenticated. Please login first.")

        url = f"{BASE_URL}/Person/{self._user_id}/residentialPermissions"
        _LOGGER.debug("Fetching residential permissions...")
        
        
        response = await self._make_request("GET", url)
        if response.status != 200:
            raise Exception(f"Failed to get permissions: {await response.text()}")
        
        permissions = await response.json()

        if not permissions or not isinstance(permissions, list):
            raise Exception("No residential permissions found (empty list).")
        
        # Typically taking the first permission is sufficient for most users
        first_perm = permissions[0]
        account_id = first_perm.get("residentialAccountId")
        
        if not account_id:
            raise Exception("Permission entry did not contain a residentialAccountId.")
            
        return account_id

    async def get_residence_id(self, account_id: str) -> str:
        """
        Retrieve the primary Residence ID associated with a Residential Account.

        :param account_id: The residential account ID retrieved from permissions.
        :return: The primaryResidenceId string.
        :raises Exception: If the account details are invalid.
        """
        if not self._token:
            raise Exception("Not authenticated.")
            
        url = f"{BASE_URL}/ResidentialAccounts/{account_id}"
        _LOGGER.debug("Fetching residential account details for ID: %s", account_id)
        
        
        response = await self._make_request("GET", url)
        if response.status != 200:
            raise Exception(f"Failed to get account details: {await response.text()}")
        
        account = await response.json()
        residence_id = account.get("primaryResidenceId")
        
        if not residence_id:
            # Fallback: Try fetching residences list if primaryResidenceId is missing
            _LOGGER.warning("primaryResidenceId missing, attempting to list residences...")
            return await self._get_first_residence(account_id)
            
        return residence_id

    async def _get_first_residence(self, residence_object_id: str) -> str:
        """
        Fallback method to get the first available residence if the primary one is not set.

        :param residence_object_id: The ID used to query residences (often same as account object ID).
        :return: The id of the first found residence.
        """
        url = f"{BASE_URL}/ResidentialAccounts/{residence_object_id}/residences"
        
        response = await self._make_request("GET", url)
        if response.status != 200:
             raise Exception("Failed to list residences.")
        
        residences = await response.json()
        if not residences:
            raise Exception("No residences found for this account.")
        
        return residences[0]["id"]

    async def get_iot_switches(self, residence_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all IoT Switches (devices) for a specific residence.

        :param residence_id: The residence ID to query.
        :return: A list of device dictionaries containing status and config.
        """
        if not self._token:
            raise Exception("Not authenticated.")

        url = f"{BASE_URL}/Residences/{residence_id}/iotSwitches"
        _LOGGER.debug("Discovering devices for residence: %s", residence_id)

        # Include iotButtons related data for full device info
        headers = {"filter": json.dumps({"include": ["iotButtons"]})}

        response = await self._make_request("GET", url, headers=headers)
        if response.status != 200:
            raise Exception(f"Failed to get devices: {await response.text()}")

        devices = await response.json()
        _LOGGER.info("Discovered %d iotSwitches.", len(devices))
        return devices

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """
        Retrieve the current state of a single device.

        :param device_id: The device ID to query.
        :return: Device dictionary with current state.
        """
        if not self._token:
            raise Exception("Not authenticated.")

        url = f"{BASE_URL}/IotSwitches/{device_id}"
        _LOGGER.debug("Fetching state for device: %s", device_id)

        response = await self._make_request("GET", url)
        if response.status != 200:
            raise Exception(f"Failed to get device state: {await response.text()}")

        return await response.json()

    async def set_device_attribute(self, device_id: str, attributes: Dict[str, Any]) -> None:
        """
        Update one or more attributes of a specific device (e.g., power, brightness).
        
        This sends a PUT request to the /IotSwitches/{deviceId} endpoint.

        :param device_id: The ID of the device to control.
        :param attributes: Dictionary of attributes to update (e.g., {'power': 'ON'}).
        """
        if not self._token:
            raise Exception("Not authenticated.")
            
        url = f"{BASE_URL}/IotSwitches/{device_id}"
        
        _LOGGER.debug("Setting attributes for device %s: %s", device_id, attributes)
        
        response = await self._make_request("PUT", url, json=attributes)
        if response.status != 200:
            text = await response.text()
            _LOGGER.error("Failed to update device %s. Status: %s. Response: %s", device_id, response.status, text)
            raise Exception(f"Device update failed: {text}")
            
        # We don't necessarily need the response body if it was a success standard 200 OK
        _LOGGER.debug("Successfully updated device %s", device_id)
