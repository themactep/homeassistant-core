"""The Thingino integration."""

from __future__ import annotations

import asyncio
import logging
import os

import onvif
from onvif import ONVIFCamera
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    DOMAIN,
    PLATFORMS,
    get_wsdl_dir,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ThinginoConfigEntry = ConfigEntry[dict[str, str]]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Thingino integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ThinginoConfigEntry) -> bool:
    """Set up Thingino from a config entry."""
    _LOGGER.debug(f"Setting up Thingino integration for {entry.data[CONF_HOST]}")
    camera = None
    try:
        # Test connection to camera during setup with proper cleanup
        _LOGGER.debug(f"Creating ONVIF connection to {entry.data[CONF_HOST]}")

        async with asyncio.timeout(10):  # 10 second timeout for setup
            camera = ONVIFCamera(
                entry.data[CONF_HOST],
                80,
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
                get_wsdl_dir(),
                no_cache=True,
            )
            _LOGGER.debug("ONVIF camera instance created, creating device service")
            device_service = await camera.create_devicemgmt_service()
            _LOGGER.debug("Device service created, getting device information")
            device_info = await device_service.GetDeviceInformation()
            _LOGGER.debug(
                f"Device info: Manufacturer={device_info.Manufacturer}, Model={device_info.Model}"
            )
    except Exception as exc:
        from homeassistant.exceptions import ConfigEntryNotReady

        _LOGGER.error(f"Failed to connect to {entry.data[CONF_HOST]}: {exc}")
        _LOGGER.debug(f"Full exception details: {exc!r}")
        import traceback

        _LOGGER.debug(f"Traceback: {traceback.format_exc()}")
        raise ConfigEntryNotReady(
            f"Unable to connect to Thingino camera at {entry.data[CONF_HOST]}"
        ) from exc
    finally:
        # Clean up ONVIF camera resources after setup test
        if camera:
            try:
                # Try to close internal sessions if they exist
                if hasattr(camera, "_session") and camera._session:
                    await camera._session.close()
                if hasattr(camera, "_snapshot_client") and camera._snapshot_client:
                    await camera._snapshot_client.close()
            except Exception:
                pass  # Ignore cleanup errors

    entry.runtime_data = {
        "host": entry.data[CONF_HOST],
        "username": entry.data[CONF_USERNAME],
        "password": entry.data[CONF_PASSWORD],
        "mqtt_host": entry.data.get(CONF_MQTT_HOST, ""),
        "mqtt_username": entry.data.get(CONF_MQTT_USERNAME, ""),
        "mqtt_password": entry.data.get(CONF_MQTT_PASSWORD, ""),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThinginoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
