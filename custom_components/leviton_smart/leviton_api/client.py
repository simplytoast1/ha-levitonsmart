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
from typing import Callable, Optional, Dict, List, Any

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


class LevitonAuthError(Exception):
    """
    Base class for authentication problems that only the user can resolve.

    Callers should map this to ConfigEntryAuthFailed so Home Assistant starts a
    re-authentication flow instead of silently retrying forever.
    """
    pass


class TwoFactorRequired(LevitonAuthError):
    """Raised when the API returns a 2FA challenge."""
    pass


class InvalidCredentials(LevitonAuthError):
    """Raised when the API rejects the supplied email/password (or 2FA code)."""
    pass


class AuthenticationExpired(LevitonAuthError):
    """Raised when the token has expired and re-authentication is needed."""
    pass


class LevitonApiClient:
    """
    Async Client for the My Leviton API.

    This class manages the session, authentication, and specific API endpoints
    required to interact with Leviton Decora Smart devices.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        on_token_refresh: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Initialize the API client.

        :param session: The aiohttp ClientSession to use for making requests.
        :param on_token_refresh: Optional callback invoked with the new login response
                                 whenever the client silently re-authenticates, so the
                                 caller can persist the refreshed session.
        """
        self._session = session
        self._token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._email: Optional[str] = None
        self._password: Optional[str] = None
        self._code: Optional[str] = None
        self._login_response: Optional[Dict[str, Any]] = None
        self._on_token_refresh = on_token_refresh

    def set_credentials(self, email: str, password: str) -> None:
        """
        Provide the credentials used to silently re-authenticate on a 401.

        This must be called when a session is restored instead of logged in, since
        restore_login_response() only carries the token and never sees the password.

        :param email: User's email address.
        :param password: User's password.
        """
        self._email = email
        self._password = password

    def restore_session(self, token: str, user_id: str) -> None:
        """Restore a previously saved session."""
        self._token = token
        self._user_id = user_id

    def restore_login_response(self, login_response: Dict[str, Any]) -> None:
        """
        Restore the full login response from stored config entry data.
        This avoids needing to re-authenticate (and re-do 2FA) on every restart.

        Note this only restores the token. Pair it with set_credentials() so the
        client can recover on its own once that token expires.

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
        :raises InvalidCredentials: If the server rejects the email/password/code.
        :raises Exception: If the request fails for any other reason.
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
                
                # Other auth failure - do not recurse here, just fail on initial login
                _LOGGER.error("Login failed. Status: %s. Response: %s", response.status, text)
                raise InvalidCredentials(f"Login failed: {text}")

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

        On 401 (token expired), tries to re-login WITHOUT a 2FA code first.
        Anything the user has to resolve (2FA challenge, changed password, or no
        credentials available at all) surfaces as a LevitonAuthError so Home
        Assistant can start a re-authentication flow.
        """
        if not self._token:
            raise AuthenticationExpired("Not authenticated.")

        headers = {**DEFAULT_HEADERS, **kwargs.pop("headers", {})}
        headers["Authorization"] = self._token

        # First attempt
        response = await self._session.request(method, url, headers=headers, **kwargs)

        if response.status != 401:
            return response

        # Discard the rejected response before retrying.
        response.close()
        _LOGGER.warning("Token expired (401). Attempting re-authentication...")

        if not (self._email and self._password):
            _LOGGER.error("Cannot re-authenticate: missing credentials.")
            raise AuthenticationExpired("Token expired and no credentials stored.")

        try:
            # Try to re-login WITHOUT 2FA code (may work if remembered)
            login_response = await self.login(self._email, self._password)
        except TwoFactorRequired as err:
            # 2FA required - user needs to re-authenticate manually
            _LOGGER.error("Token expired and 2FA required. User must re-authenticate.")
            raise AuthenticationExpired(
                "Token expired and a new two-factor code is required."
            ) from err

        # Hand the refreshed session back so it can be persisted and reused
        # (the WebSocket authenticates with the same login response).
        if self._on_token_refresh:
            self._on_token_refresh(login_response)

        headers["Authorization"] = self._token
        response = await self._session.request(method, url, headers=headers, **kwargs)

        if response.status == 401:
            response.close()
            raise AuthenticationExpired(
                "Re-authentication succeeded but the API still rejected the token."
            )

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
            raise AuthenticationExpired("Not authenticated. Please login first.")

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
            raise AuthenticationExpired("Not authenticated.")
            
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
            raise AuthenticationExpired("Not authenticated.")

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
            raise AuthenticationExpired("Not authenticated.")

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
            raise AuthenticationExpired("Not authenticated.")
            
        url = f"{BASE_URL}/IotSwitches/{device_id}"
        
        _LOGGER.debug("Setting attributes for device %s: %s", device_id, attributes)
        
        response = await self._make_request("PUT", url, json=attributes)
        if response.status != 200:
            text = await response.text()
            _LOGGER.error("Failed to update device %s. Status: %s. Response: %s", device_id, response.status, text)
            raise Exception(f"Device update failed: {text}")
            
        # We don't necessarily need the response body if it was a success standard 200 OK
        _LOGGER.debug("Successfully updated device %s", device_id)
