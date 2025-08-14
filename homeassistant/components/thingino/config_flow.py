"""Config flow for the Thingino integration."""

from __future__ import annotations

import asyncio
from datetime import UTC
import ipaddress
import logging
from typing import Any
import xml.etree.ElementTree as ET

import aiohttp
from onvif import ONVIFCamera
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DOMAIN,
    get_wsdl_dir,
)

_LOGGER = logging.getLogger(__name__)


def create_onvif_soap_request(username: str, password: str) -> str:
    """Create ONVIF SOAP request with WS-Security authentication."""
    import base64
    from datetime import datetime
    import hashlib
    import secrets

    # Generate nonce and timestamp for WS-Security
    nonce = secrets.token_bytes(16)
    nonce_b64 = base64.b64encode(nonce).decode("utf-8")
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Create password digest: Base64(SHA1(nonce + created + password))
    digest_input = nonce + created.encode("utf-8") + password.encode("utf-8")
    password_digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode(
        "utf-8"
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
               xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
               xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
    <soap:Header>
        <wsse:Security soap:mustUnderstand="true">
            <wsse:UsernameToken wsu:Id="UsernameToken-1">
                <wsse:Username>{username}</wsse:Username>
                <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{password_digest}</wsse:Password>
                <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</wsse:Nonce>
                <wsu:Created>{created}</wsu:Created>
            </wsse:UsernameToken>
        </wsse:Security>
    </soap:Header>
    <soap:Body>
        <tds:GetDeviceInformation/>
    </soap:Body>
</soap:Envelope>"""


async def discover_thingino_cameras_http(
    hass: HomeAssistant, username: str, password: str, network: str | None = None
) -> list[dict[str, Any]]:
    """Discover Thingino cameras using HTTP-based ONVIF requests."""
    if not network:
        network = "192.168.1.0/24"  # Default network

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

    async def check_host_http(ip: str) -> dict[str, Any] | None:
        """Check if a host is a Thingino camera using HTTP ONVIF requests."""
        async with semaphore:
            try:
                _LOGGER.debug("Checking host %s with HTTP ONVIF", ip)

                # Create session with proper timeout (no auth for now)
                session = None
                try:
                    session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=1.5),
                        connector=aiohttp.TCPConnector(limit=1, limit_per_host=1),
                    )

                    # Try ONVIF device service endpoint
                    onvif_url = f"http://{ip}/onvif/device_service"

                    # Create SOAP request with WS-Security authentication
                    soap_request = create_onvif_soap_request(username, password)

                    async with asyncio.timeout(2):
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
                                _LOGGER.debug(
                                    "Host %s ONVIF response: %s", ip, xml_content[:500]
                                )
                                return await parse_onvif_device_info(ip, xml_content)
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
                except Exception as e:
                    _LOGGER.debug("Host %s ONVIF error: %s", ip, e)
                finally:
                    if session:
                        await session.close()

            except Exception as e:
                _LOGGER.debug("Failed to check host %s: %s", ip, e)
            return None

    # Run discovery on all hosts
    _LOGGER.debug("Starting concurrent HTTP ONVIF checks")
    tasks = [asyncio.create_task(check_host_http(ip)) for ip in hosts_to_scan]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter successful results
    discovered_cameras = []
    for result in results:
        if isinstance(result, dict) and result:
            discovered_cameras.append(result)

    _LOGGER.info(
        "HTTP ONVIF discovery complete. Found %d Thingino cameras",
        len(discovered_cameras),
    )
    return discovered_cameras


async def parse_onvif_device_info(ip: str, xml_content: str) -> dict[str, Any] | None:
    """Parse ONVIF GetDeviceInformation response and check if it's a Thingino camera."""
    try:
        # Parse XML response
        root = ET.fromstring(xml_content)

        # Define namespaces
        namespaces = {
            "soap": "http://www.w3.org/2003/05/soap-envelope",
            "tds": "http://www.onvif.org/ver10/device/wsdl",
        }

        # Find GetDeviceInformationResponse
        device_info_elem = root.find(".//tds:GetDeviceInformationResponse", namespaces)
        if device_info_elem is None:
            _LOGGER.debug("Host %s: No GetDeviceInformationResponse found", ip)
            return None

        # Extract device information
        manufacturer = device_info_elem.findtext("tds:Manufacturer", "", namespaces)
        model = device_info_elem.findtext("tds:Model", "", namespaces)
        serial = device_info_elem.findtext("tds:SerialNumber", "unknown", namespaces)
        firmware = device_info_elem.findtext(
            "tds:FirmwareVersion", "unknown", namespaces
        )

        _LOGGER.debug(
            "Host %s device info: Manufacturer='%s', Model='%s'",
            ip,
            manufacturer,
            model,
        )

        # Check if it's a Thingino camera
        manufacturer_lower = manufacturer.lower()
        model_lower = model.lower()

        if (
            "thingino" in manufacturer_lower
            or "thingino" in model_lower
            or "ingenic" in manufacturer_lower  # Thingino often shows as Ingenic
        ):
            _LOGGER.info("Found Thingino camera at %s: %s %s", ip, manufacturer, model)
            return {
                "host": ip,
                "manufacturer": manufacturer,
                "model": model,
                "serial": serial,
                "firmware": firmware,
            }
        _LOGGER.debug(
            "Host %s is not a Thingino camera: %s %s", ip, manufacturer, model
        )

    except ET.ParseError as e:
        _LOGGER.debug("Host %s: XML parse error: %s", ip, e)
    except Exception as e:
        _LOGGER.debug("Host %s: Error parsing device info: %s", ip, e)

    return None


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
        vol.Optional(CONF_MQTT_HOST, default=""): str,
        vol.Optional(CONF_MQTT_USERNAME, default=""): str,
        vol.Optional(CONF_MQTT_PASSWORD, default=""): str,
    }
)


async def discover_thingino_cameras(
    hass: HomeAssistant,
    username: str = "thingino",
    password: str = "thingino",
    network: str = None,
) -> list[dict[str, Any]]:
    """Discover Thingino cameras on the network."""
    discovered_cameras = []

    # Use provided network or detect local network
    networks_to_scan = []

    if network:
        # User specified a network
        try:
            user_network = ipaddress.IPv4Network(network, strict=False)
            networks_to_scan.append(user_network)
            _LOGGER.info("Scanning user-specified network: %s", user_network)
        except Exception as e:
            _LOGGER.error("Invalid network specified: %s - %s", network, e)
            return []
    else:
        # Auto-detect local network
        try:
            import socket

            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            detected_network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)

            # Only use detected network if it's a private network and not Docker
            if (
                detected_network.is_private
                and not str(detected_network).startswith(
                    "172.17."
                )  # Skip Docker networks
                and not str(detected_network).startswith("172.18.")
            ):
                networks_to_scan.append(detected_network)
                _LOGGER.info("Scanning detected local network: %s", detected_network)
            else:
                _LOGGER.warning(
                    "Detected network %s is not suitable, skipping discovery",
                    detected_network,
                )
        except Exception as e:
            _LOGGER.warning("Could not detect local network: %s", e)

        # If no suitable network detected, abort discovery
        if not networks_to_scan:
            _LOGGER.error("No suitable local network found for discovery")
            return []

    # Create semaphore to limit concurrent connections (improved)
    semaphore = asyncio.Semaphore(5)

    async def check_host(ip: str) -> dict[str, Any] | None:
        """Check if a host is a Thingino camera using improved session management."""
        async with semaphore:
            try:
                _LOGGER.debug("Checking host %s", ip)

                # First do a quick HTTP check with proper session management
                session = None
                try:
                    session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=2),
                        connector=aiohttp.TCPConnector(limit=1, limit_per_host=1),
                    )

                    async with asyncio.timeout(2):
                        async with session.get(f"http://{ip}") as response:
                            if response.status not in [200, 401, 403]:
                                return None  # No web server
                except Exception:
                    return None  # No HTTP response
                finally:
                    if session:
                        await session.close()

                # If HTTP responds, try ONVIF with proper cleanup
                camera = None
                try:
                    async with asyncio.timeout(1.5):
                        camera = ONVIFCamera(
                            ip, 80, username, password, get_wsdl_dir(), no_cache=True
                        )

                        device_service = await camera.create_devicemgmt_service()
                        device_info = await device_service.GetDeviceInformation()

                        # Check if it's a Thingino camera based on manufacturer/model
                        manufacturer = device_info.Manufacturer.lower()
                        model = device_info.Model.lower()

                        _LOGGER.debug(
                            "Host %s ONVIF info: Manufacturer='%s', Model='%s'",
                            ip,
                            device_info.Manufacturer,
                            device_info.Model,
                        )

                        if (
                            "thingino" in manufacturer
                            or "thingino" in model
                            or "ingenic"
                            in manufacturer  # Thingino often shows as Ingenic
                        ):
                            _LOGGER.info(
                                "Found Thingino camera at %s: %s %s",
                                ip,
                                device_info.Manufacturer,
                                device_info.Model,
                            )
                            return {
                                "host": ip,
                                "manufacturer": device_info.Manufacturer,
                                "model": device_info.Model,
                                "serial": getattr(
                                    device_info, "SerialNumber", "unknown"
                                ),
                                "firmware": getattr(
                                    device_info, "FirmwareVersion", "unknown"
                                ),
                            }
                        _LOGGER.debug(
                            "Host %s is not a Thingino camera: %s %s",
                            ip,
                            device_info.Manufacturer,
                            device_info.Model,
                        )
                except TimeoutError:
                    _LOGGER.debug("Host %s ONVIF timeout", ip)
                except Exception as e:
                    _LOGGER.debug("Host %s ONVIF failed: %s", ip, e)
                finally:
                    # Clean up ONVIF camera resources
                    if camera:
                        try:
                            # Try to close internal sessions if they exist
                            if hasattr(camera, "_session") and camera._session:
                                await camera._session.close()
                            if (
                                hasattr(camera, "_snapshot_client")
                                and camera._snapshot_client
                            ):
                                await camera._snapshot_client.close()
                        except Exception:
                            pass  # Ignore cleanup errors

            except Exception as e:
                _LOGGER.debug("Failed to check host %s: %s", ip, e)
            return None

    # Scan multiple networks
    all_tasks = []
    for network in networks_to_scan:
        _LOGGER.info("Scanning network %s for Thingino cameras", network)

        # Add tasks for this network (scan limited range for efficiency)
        count = 0
        for ip in network.hosts():
            if str(ip).endswith((".1", ".254", ".255")):  # Skip common router IPs
                continue
            # Only scan first 50 IPs per network to avoid resource issues
            if count >= 50:
                break
            all_tasks.append(check_host(str(ip)))
            count += 1

    # Execute scans with progress logging
    _LOGGER.info(
        "Checking %d potential hosts across %d networks",
        len(all_tasks),
        len(networks_to_scan),
    )
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    # Collect successful discoveries
    for result in results:
        if isinstance(result, dict) and result:
            discovered_cameras.append(result)
            _LOGGER.info(
                "Found Thingino camera at %s: %s %s",
                result["host"],
                result["manufacturer"],
                result["model"],
            )

    _LOGGER.info(
        "Discovery complete. Found %d Thingino cameras", len(discovered_cameras)
    )
    return discovered_cameras


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    try:
        camera = ONVIFCamera(
            data[CONF_HOST],
            80,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            get_wsdl_dir(),
            no_cache=True,
        )
        device_service = await camera.create_devicemgmt_service()
        device_info = await device_service.GetDeviceInformation()
        if (
            "ingenic" not in device_info.Manufacturer.lower()
            and "thingino" not in device_info.Manufacturer.lower()
            and "thingino" not in device_info.Model.lower()
        ):
            raise InvalidAuth("Device is not a Thingino camera")
    except Exception as exc:
        _LOGGER.error(f"Failed to connect to {data[CONF_HOST]}: {exc}")
        _LOGGER.debug(f"Full exception details: {exc!r}")
        import traceback

        _LOGGER.debug(f"Traceback: {traceback.format_exc()}")
        raise CannotConnect(f"Failed to connect: {exc}") from exc

    return {"title": f"Thingino Camera {data[CONF_HOST]}"}


class ThinginoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thingino."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_cameras: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            if user_input["setup_mode"] == "manual":
                return await self.async_step_manual()
            if user_input["setup_mode"] == "discover":
                return await self.async_step_discover()

        # Show setup mode selection form
        setup_schema = vol.Schema(
            {
                vol.Required("setup_mode", default="discover"): vol.In(
                    {
                        "discover": "Discover cameras automatically",
                        "manual": "Add camera manually",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=setup_schema,
            description_placeholders={},
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual camera configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"thingino_{user_input[CONF_HOST].replace('.', '_')}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                    options={"skip_device_setup": True},
                )

        return self.async_show_form(
            step_id="manual", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle camera discovery credentials."""
        if user_input is not None:
            # User provided credentials and network, now discover with HTTP ONVIF
            self._discovery_credentials = {
                "username": user_input["username"],
                "password": user_input["password"],
                "network": user_input["network"],
            }
            return await self.async_step_select_cameras()

        # Detect default network for the form
        default_network = "192.168.1.0/24"
        try:
            import socket

            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            detected_network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            if detected_network.is_private:
                default_network = str(detected_network)
        except Exception:
            pass

        # Show credentials and network form
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(
                {
                    vol.Required("username", default="thingino"): str,
                    vol.Required("password", default="thingino"): str,
                    vol.Required("network", default=default_network): str,
                }
            ),
        )

    async def async_step_select_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle camera selection after discovery."""
        if user_input is not None:
            # User selected multiple cameras with checkboxes
            selected_cameras = []
            for camera in self._discovered_cameras:
                checkbox_key = f"camera_{camera['host'].replace('.', '_')}"
                if user_input.get(checkbox_key, False):
                    selected_cameras.append(camera)

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
            for camera_info in selected_cameras:
                unique_id = f"thingino_{camera_info['host'].replace('.', '_')}"

                # Check if already configured
                existing_entries = self.hass.config_entries.async_entries(DOMAIN)
                if any(entry.unique_id == unique_id for entry in existing_entries):
                    continue  # Skip if already exists

                # Create entry data for this camera
                entry_data = {
                    CONF_HOST: camera_info["host"],
                    CONF_USERNAME: credentials["username"],
                    CONF_PASSWORD: credentials["password"],
                    CONF_MQTT_HOST: "",
                    CONF_MQTT_USERNAME: "",
                    CONF_MQTT_PASSWORD: "",
                }
                entry_title = f"Thingino Camera ({camera_info['host']})"

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
                        discovery_keys=set(),
                        subentries_data={},
                    )
                )
                created_count += 1
                _LOGGER.info("Added camera %s silently", camera_info["host"])

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
                "network": "192.168.1.0/24",
            },
        )
        all_discovered_cameras = await discover_thingino_cameras_http(
            self.hass,
            username=credentials["username"],
            password=credentials["password"],
            network=credentials.get("network", "192.168.1.0/24"),
        )

        # Filter out already configured cameras
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        existing_hosts = {entry.data.get(CONF_HOST) for entry in existing_entries}

        self._discovered_cameras = [
            camera
            for camera in all_discovered_cameras
            if camera["host"] not in existing_hosts
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
        for camera in self._discovered_cameras:
            checkbox_key = f"camera_{camera['host'].replace('.', '_')}"
            label = f"{camera['host']} - {camera['manufacturer']} {camera['model']}"
            schema_dict[vol.Optional(checkbox_key, default=False)] = bool

        return vol.Schema(schema_dict)

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle ONVIF discovery."""
        host = discovery_info.host
        await self.async_set_unique_id(f"thingino_{host.replace('.', '_')}")
        self._abort_if_unique_id_configured()

        try:
            camera = ONVIFCamera(
                host,
                80,
                "thingino",
                "thingino",
                get_wsdl_dir(),
                no_cache=True,
            )
            device_service = await camera.create_devicemgmt_service()
            device_info = await device_service.GetDeviceInformation()
            if (
                "ingenic" in device_info.Manufacturer.lower()
                or "thingino" in device_info.Manufacturer.lower()
                or "thingino" in device_info.Model.lower()
            ):
                return await self.async_step_zeroconf_confirm(
                    {
                        CONF_HOST: host,
                        CONF_USERNAME: "thingino",
                        CONF_PASSWORD: "thingino",
                        CONF_MQTT_HOST: "",
                        CONF_MQTT_USERNAME: "",
                        CONF_MQTT_PASSWORD: "",
                    }
                )
        except Exception:
            return self.async_abort(reason="not_thingino_device")

        return self.async_abort(reason="not_thingino_device")

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovered device."""
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                return self.async_show_form(
                    step_id="zeroconf_confirm",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "cannot_connect"},
                    description_placeholders={"host": user_input[CONF_HOST]},
                )
            except InvalidAuth:
                return self.async_show_form(
                    step_id="zeroconf_confirm",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "invalid_auth"},
                    description_placeholders={"host": user_input[CONF_HOST]},
                )
            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_show_form(
                    step_id="zeroconf_confirm",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "unknown"},
                    description_placeholders={"host": user_input[CONF_HOST]},
                )
            else:
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                    options={"skip_device_setup": True},
                )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Optional(CONF_USERNAME, default=user_input[CONF_USERNAME]): str,
                    vol.Optional(CONF_PASSWORD, default=user_input[CONF_PASSWORD]): str,
                    vol.Optional(
                        CONF_MQTT_HOST, default=user_input[CONF_MQTT_HOST]
                    ): str,
                    vol.Optional(
                        CONF_MQTT_USERNAME, default=user_input[CONF_MQTT_USERNAME]
                    ): str,
                    vol.Optional(
                        CONF_MQTT_PASSWORD, default=user_input[CONF_MQTT_PASSWORD]
                    ): str,
                }
            ),
            description_placeholders={"host": user_input[CONF_HOST]},
        )

    async def async_step_auto_discovery(
        self, discovery_info: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle auto discovery of additional cameras."""
        if discovery_info and discovery_info.get("auto_create"):
            camera_info = discovery_info["camera_info"]
            unique_id = f"thingino_{camera_info['host'].replace('.', '_')}"

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            data = {
                CONF_HOST: camera_info["host"],
                CONF_USERNAME: DEFAULT_USERNAME,
                CONF_PASSWORD: DEFAULT_PASSWORD,
                CONF_MQTT_HOST: "",
                CONF_MQTT_USERNAME: "",
                CONF_MQTT_PASSWORD: "",
            }
            title = f"Thingino Camera ({camera_info['host']})"

            return self.async_create_entry(
                title=title, data=data, options={"skip_device_setup": True}
            )

        return self.async_abort(reason="invalid_discovery_info")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
