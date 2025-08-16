"""Thingino sensor platform."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import defusedxml.ElementTree as ET

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ThinginoConfigEntry
from .const import DOMAIN, ThinginoDeviceInfo
from .onvif_client import ThinginoOnvifClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThinginoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Thingino sensor platform."""
    entities = []

    # Add ONVIF event-based motion sensor
    entities.append(ThinginoMotionSensor(entry))

    async_add_entities(entities)


class ThinginoMotionSensor(BinarySensorEntity):
    """ONVIF event-based motion detection sensor for Thingino cameras."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_should_poll = False

    def __init__(self, entry: ThinginoConfigEntry) -> None:
        """Initialize the ONVIF motion sensor."""
        self._entry = entry
        config = entry.runtime_data

        # Create device info from config data
        self._device_info = ThinginoDeviceInfo(
            host=config["host"],
            mac_address=config.get("serial", "unknown"),
            manufacturer=config.get("manufacturer", "Thingino"),
            model=config.get("model", "Camera"),
            firmware_version=config.get("firmware", "unknown"),
            hardware_id=config.get("hardware_id", ""),
            camera_name=config.get(
                "camera_name", f"Thingino Camera ({config['host']})"
            ),
        )

        self._host = self._device_info.host
        self._username = config["username"]
        self._password = config["password"]

        # Use device info for unique ID
        self._attr_unique_id = f"thingino_motion_{self._device_info.normalized_mac}"
        self._attr_name = "Motion"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_info.device_identifier)},
            name=self._device_info.device_title,
            manufacturer=self._device_info.manufacturer,
            model=self._device_info.model,
            configuration_url=f"http://{self._host}",
        )

        # Initialize motion state
        self._attr_is_on = False
        self._attr_available = True
        self._events_supported = False

        # Initialize ONVIF client
        self._onvif_client = ThinginoOnvifClient(
            host=self._host,
            port=80,
            username=self._username,
            password=self._password,
        )

    async def async_added_to_hass(self) -> None:
        """Set up ONVIF event subscription when added to hass."""
        await super().async_added_to_hass()

        # Start ONVIF event monitoring in the background
        self.hass.async_create_background_task(
            self._setup_onvif_events(),
            f"thingino_motion_events_{self._host}",
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up resources when removed."""
        await super().async_will_remove_from_hass()

    async def _setup_onvif_events(self) -> None:
        """Set up ONVIF event subscription for motion detection."""
        try:
            # Check if camera supports events service using HTTP POST
            if not await self._check_events_service_support():
                _LOGGER.info(
                    "Camera %s does not support ONVIF events service", self._host
                )
                self._attr_available = False
                self.async_write_ha_state()
                return

            # For now, mark as not available since we need to implement
            # HTTP POST-based event subscription for Thingino cameras
            _LOGGER.warning(
                "ONVIF events service detected but HTTP POST-based event subscription "
                "not yet implemented for Thingino camera %s",
                self._host,
            )
            self._attr_available = False
            self.async_write_ha_state()

        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ) as err:
            _LOGGER.warning("Failed to setup ONVIF events for %s: %s", self._host, err)
            self._attr_available = False
            self.async_write_ha_state()

    async def _check_events_service_support(self) -> bool:
        """Check if the camera supports ONVIF events service using HTTP POST."""
        try:
            # Make HTTP POST request to get capabilities
            soap_body = "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>"
            capabilities_xml = await self._onvif_client.make_request(
                "device_service", soap_body
            )

            if not capabilities_xml:
                return False

            # Parse capabilities to check for events service
            capabilities = self._onvif_client.parse_capabilities(capabilities_xml)
            return "Events" in capabilities  # noqa: TRY300

        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ) as err:
            _LOGGER.debug(
                "Error checking events service support for %s: %s", self._host, err
            )
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "host": self._host,
            "detection_method": "ONVIF Events",
        }
