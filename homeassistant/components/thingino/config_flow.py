"""Config flow for the Thingino integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from types import MappingProxyType
from typing import Any

import aiohttp
import defusedxml.ElementTree as ET
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_NETWORK,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DOMAIN,
    ThinginoDeviceInfo,
)
from .onvif_client import ThinginoOnvifClient

_LOGGER = logging.getLogger(__name__)


async def discover_thingino_cameras_http(
    hass: HomeAssistant, username: str, password: str, network: str | None = None
) -> list[ThinginoDeviceInfo]:
    """Discover Thingino cameras using HTTP-based ONVIF requests."""
    if not network:
        network = DEFAULT_NETWORK

    _LOGGER.info("Starting HTTP-based ONVIF discovery on network: %s", network)

    try:
        network_obj = ipaddress.IPv4Network(network, strict=False)
    except ValueError as e:
        _LOGGER.error("Invalid network format '%s': %s", network, e)
        return []

    # Get already configured camera IPs to skip them
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    configured_ips = {
        entry.data.get(CONF_HOST)
        for entry in existing_entries
        if entry.data.get(CONF_HOST)
    }

    # Generate list of IPs to scan, excluding already configured ones
    all_hosts = [str(ip) for ip in network_obj.hosts()]
    hosts_to_scan = [ip for ip in all_hosts if ip not in configured_ips]

    _LOGGER.info(
        "Scanning %d hosts in network %s (skipping %d already configured cameras)",
        len(hosts_to_scan),
        network,
        len(all_hosts) - len(hosts_to_scan),
    )

    # Create semaphore to limit concurrent connections
    semaphore = asyncio.Semaphore(20)  # More aggressive since we're using HTTP only

    async def check_host_http(ip: str) -> ThinginoDeviceInfo | None:
        """Check if a host is a Thingino camera using HTTP ONVIF requests."""
        async with semaphore:
            try:
                _LOGGER.debug("Checking host %s with HTTP ONVIF", ip)

                # Create session with proper timeout (no auth for now)
                session = None
                try:
                    session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=1.0),
                        connector=aiohttp.TCPConnector(limit=1, limit_per_host=1),
                    )

                    # Try ONVIF device service endpoint
                    onvif_url = f"http://{ip}/onvif/device_service"

                    # Create ONVIF client for this IP
                    onvif_client = ThinginoOnvifClient(
                        host=ip, port=80, username=username, password=password
                    )

                    # Create SOAP request with WS-Security authentication
                    soap_request = onvif_client.create_ws_security_soap_request(
                        "<tds:GetDeviceInformation/>"
                    )

                    async with asyncio.timeout(1.0):
                        async with session.post(
                            onvif_url,
                            data=soap_request,
                            headers={
                                "Content-Type": "application/soap+xml; charset=utf-8",
                                "SOAPAction": "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation",
                            },
                        ) as response:
                            _LOGGER.debug(
                                "Host %s ONVIF response status: %d", ip, response.status
                            )
                            if response.status == 200:
                                xml_content = await response.text()
                                _LOGGER.info(
                                    "=== FULL ONVIF XML Response from %s ===", ip
                                )
                                _LOGGER.info("%s", xml_content)
                                _LOGGER.info("=== END ONVIF XML Response ===")
                                # Parse device information using ONVIF client
                                device_info = onvif_client.parse_thingino_device_info(
                                    xml_content
                                )
                                if device_info:
                                    _LOGGER.info(
                                        "Found Thingino camera at %s: %s %s (MAC: %s)",
                                        ip,
                                        device_info.manufacturer,
                                        device_info.model,
                                        device_info.mac_address,
                                    )
                                else:
                                    _LOGGER.debug(
                                        "Host %s is not a Thingino camera", ip
                                    )
                                return device_info
                            if response.status == 401:
                                _LOGGER.debug("Host %s requires authentication", ip)
                            else:
                                _LOGGER.debug(
                                    "Host %s returned status %d", ip, response.status
                                )

                except TimeoutError:
                    _LOGGER.debug("Host %s ONVIF timeout", ip)
                except aiohttp.ClientError as e:
                    _LOGGER.debug("Host %s ONVIF connection error: %s", ip, e)
                except (ET.ParseError, UnicodeDecodeError) as e:
                    _LOGGER.debug("Host %s ONVIF XML parsing error: %s", ip, e)
                except (OSError, ValueError) as e:
                    _LOGGER.debug("Host %s ONVIF error: %s", ip, e)
                finally:
                    if session:
                        await session.close()

            except (OSError, ValueError, aiohttp.ClientError) as e:
                _LOGGER.debug("Failed to check host %s: %s", ip, e)
            return None

    # Run discovery on all hosts
    _LOGGER.debug("Starting concurrent HTTP ONVIF checks")
    tasks = [asyncio.create_task(check_host_http(ip)) for ip in hosts_to_scan]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter successful results
    discovered_cameras = [
        result for result in results if isinstance(result, ThinginoDeviceInfo)
    ]

    _LOGGER.info(
        "HTTP ONVIF discovery complete. Found %d Thingino cameras",
        len(discovered_cameras),
    )
    return discovered_cameras


class ThinginoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thingino."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_cameras: list[ThinginoDeviceInfo] = []
        self._discovery_credentials: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - unified form for single IP or network range."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Determine if input is a single IP or network range
                address_input = user_input["address"].strip()

                # Try to parse as network first (handles both single IPs and CIDR)
                try:
                    if "/" in address_input:
                        # User provided CIDR notation - this is network discovery
                        network_obj = ipaddress.IPv4Network(address_input, strict=False)
                        # Store credentials and network for discovery
                        self._discovery_credentials = {
                            "username": user_input[CONF_USERNAME],
                            "password": user_input[CONF_PASSWORD],
                            "network": str(network_obj),
                        }
                        return await self.async_step_select_cameras()

                    # Single IP address - validate and add directly
                    ip_obj = ipaddress.IPv4Address(address_input)
                    # Use discovery function with single IP as /32 network
                    discovered_cameras = await discover_thingino_cameras_http(
                        self.hass,
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                        f"{ip_obj!s}/32",
                    )

                    if not discovered_cameras:
                        errors["address"] = "cannot_connect"
                    else:
                        device_info = discovered_cameras[0]

                        # Use MAC address for unique ID
                        unique_id = f"thingino_{device_info.normalized_mac}"

                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()

                        # Create config data from device info
                        config_data = {
                            "host": device_info.host,
                            "serial": device_info.mac_address,
                            "manufacturer": device_info.manufacturer,
                            "model": device_info.model,
                            "firmware": device_info.firmware_version,
                            "hardware_id": device_info.hardware_id,
                            "camera_name": device_info.camera_name,
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        }

                        # Use device title from dataclass
                        device_title = device_info.device_title

                        return self.async_create_entry(
                            title=device_title,
                            data=config_data,
                            options={"skip_device_setup": True},
                        )

                except ipaddress.AddressValueError:
                    errors["address"] = "invalid_address"

            except Exception:
                _LOGGER.exception("Unexpected exception during configuration")
                errors["base"] = "unknown"

        # Detect default network for the form
        default_network = DEFAULT_NETWORK
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            detected_network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            if detected_network.is_private:
                default_network = str(detected_network)
        except (OSError, ValueError, ipaddress.AddressValueError):
            pass

        # Show unified form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("address", default=default_network): str,
                    vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                    vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "default_network": default_network,
            },
        )

    async def async_step_select_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle camera selection after discovery."""
        if user_input is not None:
            # User selected multiple cameras with checkboxes
            selected_cameras = []
            for device_info in self._discovered_cameras:
                # Use MAC address for checkbox key
                checkbox_key = f"camera_{device_info.mac_address}"
                if user_input.get(checkbox_key, False):
                    selected_cameras.append(device_info)

            if not selected_cameras:
                return self.async_show_form(
                    step_id="select_cameras",
                    data_schema=self._create_discovery_schema(),
                    errors={"base": "no_cameras_selected"},
                    description_placeholders={
                        "count": str(len(self._discovered_cameras)),
                    },
                )

            # Create all selected cameras silently
            credentials = getattr(
                self,
                "_discovery_credentials",
                {"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
            )

            created_count = 0
            for device_info in selected_cameras:
                # Use MAC address for unique ID
                unique_id = f"thingino_{device_info.normalized_mac}"

                # Check if already configured
                existing_entries = self.hass.config_entries.async_entries(DOMAIN)
                if any(entry.unique_id == unique_id for entry in existing_entries):
                    continue  # Skip if already exists

                # Create entry data for this camera
                entry_data = {
                    CONF_HOST: device_info.host,
                    CONF_USERNAME: credentials["username"],
                    CONF_PASSWORD: credentials["password"],
                    "serial": device_info.mac_address,
                    "camera_name": device_info.camera_name,
                    "manufacturer": device_info.manufacturer,
                    "model": device_info.model,
                    "firmware": device_info.firmware_version,
                    "hardware_id": device_info.hardware_id,
                }

                # Use device title from dataclass
                entry_title = device_info.device_title

                # Create the config entry directly using the manager
                await self.hass.config_entries.async_add(
                    ConfigEntry(
                        version=1,
                        minor_version=1,
                        domain=DOMAIN,
                        title=entry_title,
                        data=entry_data,
                        options={},
                        source="discovery",
                        unique_id=unique_id,
                        discovery_keys=MappingProxyType({}),
                        subentries_data={},
                    )
                )
                created_count += 1
                _LOGGER.info("Added camera %s silently", device_info.host)

            # Show completion message with link to integration page
            return self.async_abort(
                reason="cameras_added",
                description_placeholders={"count": str(created_count)},
            )

        # Discover cameras using HTTP-based ONVIF
        credentials = getattr(
            self,
            "_discovery_credentials",
            {
                "username": DEFAULT_USERNAME,
                "password": DEFAULT_PASSWORD,
                "network": DEFAULT_NETWORK,
            },
        )
        all_discovered_cameras = await discover_thingino_cameras_http(
            self.hass,
            username=credentials["username"],
            password=credentials["password"],
            network=credentials.get("network", DEFAULT_NETWORK),
        )

        # Filter out already configured cameras
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        existing_hosts = {entry.data.get(CONF_HOST) for entry in existing_entries}

        self._discovered_cameras = [
            camera
            for camera in all_discovered_cameras
            if camera.host not in existing_hosts
        ]

        if not self._discovered_cameras:
            return self.async_abort(reason="no_cameras_found")

        return self.async_show_form(
            step_id="select_cameras",
            data_schema=self._create_discovery_schema(),
            description_placeholders={
                "count": str(len(self._discovered_cameras)),
            },
        )

    def _create_discovery_schema(self) -> vol.Schema:
        """Create the discovery form schema with checkboxes for each camera."""
        schema_dict = {}
        for device_info in self._discovered_cameras:
            # Use MAC address for checkbox key
            checkbox_key = f"camera_{device_info.mac_address}"
            schema_dict[vol.Optional(checkbox_key, default=False)] = bool

        return vol.Schema(schema_dict)

    async def async_step_auto_discovery(
        self, discovery_info: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle auto discovery of additional cameras."""
        if discovery_info and discovery_info.get("auto_create"):
            camera_info = discovery_info["camera_info"]

            # Use ThinginoDeviceInfo dataclass properties
            unique_id = f"thingino_{camera_info.normalized_mac}"
            title = camera_info.device_title
            data = {
                CONF_HOST: camera_info.host,
                CONF_USERNAME: DEFAULT_USERNAME,
                CONF_PASSWORD: DEFAULT_PASSWORD,
                "serial": camera_info.mac_address,
                "manufacturer": camera_info.manufacturer,
                "model": camera_info.model,
                "firmware": camera_info.firmware_version,
                "hardware_id": camera_info.hardware_id,
                "camera_name": camera_info.camera_name,
            }

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=title, data=data, options={"skip_device_setup": True}
            )

        return self.async_abort(reason="invalid_discovery_info")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
