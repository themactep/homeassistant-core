"""ONVIF HTTP client for Thingino cameras."""

import base64
from datetime import UTC, datetime
import hashlib
import logging
import secrets
from typing import Any

import aiohttp
import defusedxml.ElementTree as ET

from .const import ThinginoDeviceInfo

_LOGGER = logging.getLogger(__name__)


class ThinginoOnvifClient:
    """HTTP-based ONVIF client for Thingino cameras."""

    def __init__(
        self, host: str, port: int = 80, username: str = "", password: str = ""
    ) -> None:
        """Initialize the ONVIF client."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._auth = aiohttp.BasicAuth(username, password) if username else None

    def create_ws_security_soap_request(self, soap_body: str) -> str:
        """Create ONVIF SOAP request with WS-Security authentication."""
        if not self._username or not self._password:
            # Return basic SOAP envelope without WS-Security
            return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
    <soap:Body>
        {soap_body}
    </soap:Body>
</soap:Envelope>"""

        # Generate nonce and timestamp for WS-Security
        nonce = secrets.token_bytes(16)
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Create password digest: Base64(SHA1(nonce + created + password))
        digest_input = nonce + created.encode("utf-8") + self._password.encode("utf-8")
        password_digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode(
            "utf-8"
        )

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
    <soap:Header>
        <wsse:Security soap:mustUnderstand="true">
            <wsse:UsernameToken wsu:Id="UsernameToken-1">
                <wsse:Username>{self._username}</wsse:Username>
                <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{password_digest}</wsse:Password>
                <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</wsse:Nonce>
                <wsu:Created>{created}</wsu:Created>
            </wsse:UsernameToken>
        </wsse:Security>
    </soap:Header>
    <soap:Body>
        {soap_body}
    </soap:Body>
</soap:Envelope>"""

    async def make_request(self, endpoint: str, soap_body: str) -> str | None:
        """Make an ONVIF HTTP request and return the XML response."""
        url = f"http://{self._host}:{self._port}/onvif/{endpoint}"
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "SOAPAction": "",
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    url,
                    data=soap_body,
                    headers=headers,
                    auth=self._auth,
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as response,
            ):
                if response.status == 200:
                    return await response.text()
                _LOGGER.debug(
                    "ONVIF request failed: %s %s",
                    response.status,
                    await response.text(),
                )
                return None
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.debug("ONVIF request error: %s", err)
            return None

    async def make_authenticated_request(
        self, endpoint: str, soap_body: str
    ) -> str | None:
        """Make an authenticated ONVIF HTTP request with WS-Security and return the XML response."""
        # Create WS-Security authenticated SOAP request
        authenticated_soap = self.create_ws_security_soap_request(soap_body)

        url = f"http://{self._host}:{self._port}/onvif/{endpoint}"
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "SOAPAction": "",
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    url,
                    data=authenticated_soap,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as response,
            ):
                if response.status == 200:
                    return await response.text()
                _LOGGER.debug(
                    "Authenticated ONVIF request failed: %s %s",
                    response.status,
                    await response.text(),
                )
                return None
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.debug("Authenticated ONVIF request error: %s", err)
            return None

    def parse_capabilities(self, xml_content: str) -> dict[str, str]:
        """Parse capabilities from ONVIF XML response."""
        capabilities = {}
        try:
            root = ET.fromstring(xml_content)

            namespaces = {
                "soap": "http://www.w3.org/2003/05/soap-envelope",
                "tds": "http://www.onvif.org/ver10/device/wsdl",
                "tt": "http://www.onvif.org/ver10/schema",
            }

            # Find the GetCapabilitiesResponse
            response = root.find(".//tds:GetCapabilitiesResponse", namespaces)
            if response is not None:
                caps = response.find("tds:Capabilities", namespaces)
                if caps is not None:
                    # Extract service URLs
                    media = caps.find("tt:Media", namespaces)
                    if media is not None:
                        xaddr = media.find("tt:XAddr", namespaces)
                        if xaddr is not None and xaddr.text:
                            capabilities["Media"] = xaddr.text

                    ptz = caps.find("tt:PTZ", namespaces)
                    if ptz is not None:
                        xaddr = ptz.find("tt:XAddr", namespaces)
                        if xaddr is not None and xaddr.text:
                            capabilities["PTZ"] = xaddr.text

                    events = caps.find("tt:Events", namespaces)
                    if events is not None:
                        xaddr = events.find("tt:XAddr", namespaces)
                        if xaddr is not None and xaddr.text:
                            capabilities["Events"] = xaddr.text

                    analytics = caps.find("tt:Analytics", namespaces)
                    if analytics is not None:
                        xaddr = analytics.find("tt:XAddr", namespaces)
                        if xaddr is not None and xaddr.text:
                            capabilities["Analytics"] = xaddr.text

        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse capabilities XML: %s", err)

        return capabilities

    def parse_device_info(self, xml_content: str) -> dict[str, str]:
        """Parse device information from ONVIF XML response."""
        device_info = {}
        try:
            root = ET.fromstring(xml_content)

            namespaces = {
                "soap": "http://www.w3.org/2003/05/soap-envelope",
                "tds": "http://www.onvif.org/ver10/device/wsdl",
            }

            # Find the GetDeviceInformationResponse
            response = root.find(".//tds:GetDeviceInformationResponse", namespaces)
            if response is not None:
                # Extract device information fields
                for field in (
                    "Manufacturer",
                    "Model",
                    "FirmwareVersion",
                    "SerialNumber",
                    "HardwareId",
                ):
                    element = response.find(f"tds:{field}", namespaces)
                    if element is not None and element.text:
                        device_info[field] = element.text

        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse device info XML: %s", err)

        return device_info

    def parse_thingino_device_info(self, xml_content: str) -> ThinginoDeviceInfo | None:
        """Parse device info and check if it's a Thingino camera."""
        device_info = self.parse_device_info(xml_content)

        if not device_info:
            return None

        manufacturer = device_info.get("Manufacturer", "")
        model = device_info.get("Model", "")

        # Check if it's a Thingino camera
        manufacturer_lower = manufacturer.lower()
        model_lower = model.lower()

        if "thingino" in manufacturer_lower or "thingino" in model_lower:
            # Extract MAC address from SerialNumber field
            mac_address = device_info.get("SerialNumber", "unknown")

            # Create a proper camera name from manufacturer and model
            if model and model.strip():
                camera_name = f"{manufacturer} {model}".strip()
            else:
                camera_name = (
                    manufacturer.strip() if manufacturer.strip() else "Thingino Camera"
                )

            _LOGGER.info(
                "Creating ThinginoDeviceInfo for %s with MAC: %s",
                self._host,
                mac_address,
            )

            return ThinginoDeviceInfo(
                host=self._host,
                mac_address=mac_address,
                manufacturer=manufacturer,
                model=model,
                firmware_version=device_info.get("FirmwareVersion", "unknown"),
                hardware_id=device_info.get("HardwareId", ""),
                camera_name=camera_name,
            )

        return None

    def parse_snapshot_uri(self, xml_content: str) -> str | None:
        """Parse snapshot URI from ONVIF GetSnapshotUri XML response."""
        try:
            root = ET.fromstring(xml_content)
            namespaces = {
                "soap": "http://www.w3.org/2003/05/soap-envelope",
                "trt": "http://www.onvif.org/ver10/media/wsdl",
                "tt": "http://www.onvif.org/ver10/schema",
            }

            # Find GetSnapshotUriResponse
            response = root.find(".//trt:GetSnapshotUriResponse", namespaces)
            if response is None:
                return None

            # Extract MediaUri/Uri
            media_uri = response.find(".//tt:MediaUri", namespaces)
            if media_uri is None:
                return None

            uri_elem = media_uri.find("tt:Uri", namespaces)
            if uri_elem is None or not uri_elem.text:
                return None

            uri = uri_elem.text.strip()
            return self._add_auth_to_uri(uri)

        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse snapshot URI XML: %s", err)

        return None

    def _add_auth_to_uri(self, uri: str) -> str:
        """Add authentication to URI if needed."""
        if not (self._username and self._password and "@" not in uri and "://" in uri):
            return uri

        protocol, rest = uri.split("://", 1)
        return f"{protocol}://{self._username}:{self._password}@{rest}"

    def parse_services(self, xml_content: str) -> list[dict[str, Any]]:
        """Parse services from ONVIF XML response."""
        services = []
        try:
            root = ET.fromstring(xml_content)

            namespaces = {
                "soap": "http://www.w3.org/2003/05/soap-envelope",
                "tds": "http://www.onvif.org/ver10/device/wsdl",
            }

            # Find the GetServicesResponse
            response = root.find(".//tds:GetServicesResponse", namespaces)
            if response is not None:
                service_elements = response.findall("tds:Service", namespaces)
                for service_elem in service_elements:
                    service = {}

                    # Extract namespace
                    namespace_elem = service_elem.find("tds:Namespace", namespaces)
                    if namespace_elem is not None and namespace_elem.text:
                        service["Namespace"] = namespace_elem.text

                    # Extract XAddr
                    xaddr_elem = service_elem.find("tds:XAddr", namespaces)
                    if xaddr_elem is not None and xaddr_elem.text:
                        service["XAddr"] = xaddr_elem.text

                    # Extract version
                    version_elem = service_elem.find("tds:Version", namespaces)
                    if version_elem is not None:
                        major_elem = version_elem.find("tds:Major", namespaces)
                        minor_elem = version_elem.find("tds:Minor", namespaces)
                        if major_elem is not None and minor_elem is not None:
                            service["Version"] = f"{major_elem.text}.{minor_elem.text}"

                    if service:
                        services.append(service)

        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse services XML: %s", err)

        return services
