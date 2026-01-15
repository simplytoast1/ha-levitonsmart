"""
Config Flow for Leviton Decora Smart
------------------------------------

This module handles the configuration UI in Home Assistant. 
It prompts the user for their My Leviton email and password, verifies them
by attempting a real login, and if successful, creates the integration entry.
Supports Two-Factor Authentication (2FA).
"""

import logging
import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .leviton_api.client import LevitonApiClient, TwoFactorRequired
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class LevitonSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for Leviton Decora Smart.
    """

    VERSION = 1
    
    def __init__(self):
        """Initialize."""
        self.auth_info: Optional[Dict[str, Any]] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle the initial step where the user enters their credentials.
        """
        errors: Dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonApiClient(session)

            try:
                # Attempt credential verification
                _LOGGER.debug("Verifying credentials for %s", email)
                login_response = await client.login(email, password)
                
                # Success - create entry
                return await self._create_entry(email, password, login_response)

            except TwoFactorRequired:
                # 2FA needed - store creds and move to next step
                _LOGGER.info("2FA required for %s", email)
                self.auth_info = user_input
                return await self.async_step_2fa()

            except Exception as err:
                _LOGGER.error("Failed to authenticate: %s", err)
                errors["base"] = "invalid_auth"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user", 
            data_schema=data_schema, 
            errors=errors
        )

    async def async_step_2fa(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle the 2FA step.
        """
        errors: Dict[str, str] = {}
        
        if user_input is not None:
            code = user_input["code"]
            email = self.auth_info[CONF_EMAIL]
            password = self.auth_info[CONF_PASSWORD]
            
            session = async_get_clientsession(self.hass)
            client = LevitonApiClient(session)
            
            try:
                _LOGGER.debug("Verifying 2FA code for %s", email)
                login_response = await client.login(email, password, code=code)
                
                return await self._create_entry(email, password, login_response)
                
            except Exception as err:
                _LOGGER.error("Failed to verify 2FA: %s", err)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="2fa",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"email": self.auth_info[CONF_EMAIL]},
        )

    async def _create_entry(self, email, password, login_response):
        """Helper to create the config entry."""
        await self.async_set_unique_id(email.lower())
        self._abort_if_unique_id_configured()

        _LOGGER.info("Credentials verified. Creating entry.")
        return self.async_create_entry(
            title=email,
            data={
                CONF_EMAIL: email,
                CONF_PASSWORD: password,
                "login_response": login_response,  # Store full response
            },
        )

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle re-authentication when token expires."""
        self.auth_info = {
            CONF_EMAIL: entry_data.get(CONF_EMAIL),
            CONF_PASSWORD: entry_data.get(CONF_PASSWORD),
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle re-authentication confirmation."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            email = self.auth_info[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonApiClient(session)

            try:
                login_response = await client.login(email, password)
                return await self._update_entry(email, password, login_response)
            except TwoFactorRequired:
                self.auth_info[CONF_PASSWORD] = password
                return await self.async_step_reauth_2fa()
            except Exception as err:
                _LOGGER.error("Re-authentication failed: %s", err)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self.auth_info[CONF_EMAIL]},
        )

    async def async_step_reauth_2fa(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle 2FA during re-authentication."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            code = user_input["code"]
            email = self.auth_info[CONF_EMAIL]
            password = self.auth_info[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonApiClient(session)

            try:
                login_response = await client.login(email, password, code=code)
                return await self._update_entry(email, password, login_response)
            except Exception as err:
                _LOGGER.error("Re-auth 2FA failed: %s", err)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_2fa",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )

    async def _update_entry(self, email, password, login_response):
        """Update the existing config entry with new credentials."""
        existing_entry = await self.async_set_unique_id(email.lower())
        if existing_entry:
            self.hass.config_entries.async_update_entry(
                existing_entry,
                data={
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                    "login_response": login_response,
                },
            )
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        return self.async_abort(reason="unknown")
