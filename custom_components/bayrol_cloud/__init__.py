"""The Bayrol Pool Controller integration."""
from __future__ import annotations

import logging
import aiohttp
import async_timeout
import voluptuous as vol
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client.bayrol_api import BayrolPoolAPI
from .client.device_parser import parse_device_status
from .const import DEFAULT_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)

DOMAIN = "bayrol_cloud"
CONF_CID = "cid"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR, Platform.SELECT]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_CID): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Bayrol Pool component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bayrol Pool from a config entry."""
    _LOGGER.debug("Setting up Bayrol Pool integration")
    
    # Create API instance
    session = async_get_clientsession(hass)
    api = BayrolPoolAPI(session)

    # Initial login to establish session
    try:
        _LOGGER.debug("Performing initial login after setup/restart...")
        login_success = False
        retry_count = 0
        max_retries = 3

        while not login_success and retry_count < max_retries:
            try:
                if await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]):
                    login_success = True
                    _LOGGER.debug("Initial login successful")
                    break
                else:
                    _LOGGER.warning("Login attempt %d failed, retrying...", retry_count + 1)
            except Exception as err:
                _LOGGER.warning("Login attempt %d failed with error: %s", retry_count + 1, err)
            retry_count += 1

        if not login_success:
            _LOGGER.error("Failed to perform initial login after %d attempts", max_retries)
            return False

        # Verify we can get data
        _LOGGER.debug("Verifying data access...")
        data = await api.get_data(entry.data[CONF_CID])
        if not data:
            _LOGGER.error("Failed to get initial data")
            return False
        _LOGGER.debug("Initial data fetch successful: %s", data)

    except Exception as err:
        _LOGGER.error("Error during initial setup: %s", err)
        return False

    async def async_update_data():
        """Fetch data from API."""
        try:
            async with async_timeout.timeout(30):
                retry_count = 0
                max_retries = 3
                last_error = None

                while retry_count < max_retries:
                    try:
                        # Always try to get data first
                        _LOGGER.debug("Attempting to fetch data (attempt %d)...", retry_count + 1)
                        data = await api.get_data(entry.data[CONF_CID])
                        
                        if data:
                            # Get and parse device status data
                            try:
                                device_status = await api.get_device_status(entry.data[CONF_CID], raw=True)
                                if device_status:
                                    parsed_status = parse_device_status(device_status)
                                    if parsed_status:
                                        data["device_status"] = parsed_status
                                        _LOGGER.debug("Device status parsed successfully: %s", parsed_status)
                                    else:
                                        _LOGGER.warning("Failed to parse device status data")
                            except Exception as err:
                                _LOGGER.warning("Error getting device status: %s", err)
                            
                            _LOGGER.debug("Data fetch successful: %s", data)
                            return data
                        
                        # If data fetch failed, try logging in again
                        _LOGGER.debug("Data fetch failed, attempting login...")
                        if await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]):
                            # Try getting data again after successful login
                            data = await api.get_data(entry.data[CONF_CID])
                            if data:
                                # Get and parse device status data
                                try:
                                    device_status = await api.get_device_status(entry.data[CONF_CID], raw=True)
                                    if device_status:
                                        parsed_status = parse_device_status(device_status)
                                        if parsed_status:
                                            # Compare with previous device status to see what changed
                                            if coordinator.data and "device_status" in coordinator.data:
                                                old_status = coordinator.data["device_status"]
                                                for device_id, new_state in parsed_status.items():
                                                    if device_id in old_status:
                                                        old_state = old_status[device_id]
                                                        if old_state.get("current_value") != new_state.get("current_value"):
                                                            _LOGGER.debug(
                                                                "Device %s state changed: %s -> %s",
                                                                device_id,
                                                                old_state.get("current_text"),
                                                                new_state.get("current_text")
                                                            )
                                            
                                            data["device_status"] = parsed_status
                                            _LOGGER.debug("Device status parsed successfully: %s", parsed_status)
                                        else:
                                            _LOGGER.warning("Failed to parse device status data")
                                except Exception as err:
                                    _LOGGER.warning("Error getting device status: %s", err)
                                
                                _LOGGER.debug("Data fetch successful: %s", data)
                                return data
                    
                    except Exception as err:
                        last_error = err
                        _LOGGER.warning(
                            "Error during update attempt %d: %s", 
                            retry_count + 1, 
                            err
                        )
                    
                    retry_count += 1

                # If we get here, all retries failed
                raise UpdateFailed(
                    f"Failed to get data after {max_retries} attempts. Last error: {last_error}"
                )

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    # Get refresh interval from config entry or use default
    refresh_interval = entry.data.get("refresh_interval", DEFAULT_REFRESH_INTERVAL)
    
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=refresh_interval),
    )

    # Do first refresh to verify everything works
    await coordinator.async_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,  # Store API instance to maintain session
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("Bayrol Pool integration setup completed successfully")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
