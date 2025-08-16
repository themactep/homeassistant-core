"""Component providing support for Thingino Cameras."""

import asyncio
import logging

import aiohttp
import defusedxml.ElementTree as ET

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ThinginoConfigEntry
from .const import DOMAIN, ONVIF_NAMESPACES, ThinginoDeviceInfo
from .onvif_client import ThinginoOnvifClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Thingino camera platform."""
    # Create both main and sub-stream camera entities
    entities = [
        ThinginoCamera(entry, stream_type="main"),
        ThinginoCamera(entry, stream_type="sub"),
    ]
    async_add_entities(entities)

    # Log available profiles for debugging
    try:
        await entities[0].log_available_profiles()
    except (
        aiohttp.ClientError,
        TimeoutError,
        ET.ParseError,
        AttributeError,
        ValueError,
    ) as err:
        _LOGGER.debug("Failed to log profiles: %s", err)


class ThinginoCamera(Camera):
    """Representation of a Thingino camera."""

    _attr_has_entity_name = True
    _attr_name: str | None = None
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, entry: ThinginoConfigEntry, stream_type: str = "main") -> None:
        """Initialize the Thingino camera."""
        super().__init__()
        self._entry = entry
        self._stream_type = stream_type
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

        _LOGGER.info(
            "Created device info for %s: MAC=%s",
            self._host,
            self._device_info.mac_address,
        )

        if self._device_info.mac_address == "unknown":
            raise ValueError(f"No MAC address available for camera {self._host}")

        # Use device info for unique ID
        self._attr_unique_id = f"{self._device_info.entity_id_base}_{stream_type}"

        # Get hardware information from device info
        hardware_info = None
        if self._device_info.hardware_id:
            hardware_info = self._device_info.hardware_id
        elif self._device_info.firmware_version != "unknown":
            hardware_info = f"Firmware: {self._device_info.firmware_version}"

        # Set entity name based on stream type
        # Follow Home Assistant best practice: enable sub stream for previews, disable main stream by default
        if stream_type == "main":
            self._attr_name = "Main Stream"  # Give main stream a specific name
            self._attr_entity_registry_enabled_default = (
                False  # Disabled by default, enable when needed
            )
            _LOGGER.info(
                "Creating MAIN stream entity for %s with unique_id: %s",
                self._host,
                self._attr_unique_id,
            )
        else:
            self._attr_name = "Sub Stream"
            self._attr_entity_registry_enabled_default = (
                True  # Enable sub stream for preview cards
            )
            _LOGGER.info(
                "Creating SUB stream entity for %s with unique_id: %s",
                self._host,
                self._attr_unique_id,
            )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_info.device_identifier)},
            connections={("ip", self._host)},
            name=f"{self._device_info.device_title}",
            manufacturer=self._device_info.manufacturer,
            model=self._device_info.model,
            configuration_url=f"http://{self._host}",
            hw_version=hardware_info,  # Show hardware/firmware information
        )
        # Debug/diagnostic fields
        self._chosen_profile_token: str | None = None
        self._chosen_profile_resolution: tuple[int, int] | None = None
        self._chosen_stream_uri: str | None = None
        self._chosen_snapshot_uri: str | None = None

        # Store ONVIF connection details for HTTP requests
        self._onvif_port = 80
        self._auth = (
            aiohttp.BasicAuth(self._username, self._password)
            if self._username and self._password
            else None
        )

        # Initialize ONVIF client
        self._onvif_client = ThinginoOnvifClient(
            host=self._host,
            port=self._onvif_port,
            username=self._username,
            password=self._password,
        )

        # Stream and snapshot URI caching
        self._stream_uri: str | None = None
        self._snapshot_uri: str | None = None
        self._stream_uri_future: asyncio.Future[str] | None = None
        self._profiles: list | None = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        # Discover and cache stream and snapshot URIs once during setup
        self.hass.async_create_background_task(
            self._discover_and_cache_uris(),
            name=f"thingino_discover_uris_{self._host}_{self._stream_type}",
        )

    async def _discover_and_cache_uris(self) -> None:
        """Discover and permanently cache the stream and snapshot URIs."""
        try:
            # Try to get URIs from ONVIF profiles
            profiles = await self.get_onvif_profiles()
            if profiles:
                # Find the appropriate profile for this stream type
                profiles_with_uri = [p for p in profiles if "stream_uri" in p]
                if profiles_with_uri:
                    profile = self._select_profile_for_stream_type(profiles_with_uri)
                    if profile and "stream_uri" in profile:
                        # Cache stream URI
                        self._stream_uri = profile["stream_uri"]
                        self._chosen_profile_token = profile.get("token")
                        w = int(
                            profile.get("encoder_width") or profile.get("width") or 0
                        )
                        h = int(
                            profile.get("encoder_height") or profile.get("height") or 0
                        )
                        self._chosen_profile_resolution = (w, h) if w and h else None
                        self._chosen_stream_uri = self._stream_uri

                        # Also discover and cache snapshot URI for this profile
                        await self._discover_snapshot_uri(profile.get("token"))

                        _LOGGER.info(
                            "Cached ONVIF URIs for %s (%s): stream=%s, snapshot=%s",
                            self._host,
                            self._stream_type,
                            self._stream_uri.split("@")[1]
                            if "@" in self._stream_uri
                            else self._stream_uri,
                            self._snapshot_uri.split("@")[1]
                            if self._snapshot_uri and "@" in self._snapshot_uri
                            else self._snapshot_uri,
                        )
                        return

            # No ONVIF URIs available
            _LOGGER.warning(
                "No ONVIF URIs available for %s (%s)", self._host, self._stream_type
            )
        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
            OSError,
        ) as err:
            _LOGGER.warning("Failed to discover URIs for %s: %s", self._host, err)

    async def _discover_snapshot_uri(self, profile_token: str | None) -> None:
        """Discover and cache snapshot URI for the given profile."""
        if not profile_token:
            return

        try:
            soap_body = f"<trt:GetSnapshotUri><trt:ProfileToken>{profile_token}</trt:ProfileToken></trt:GetSnapshotUri>"
            snapshot_xml = await self._make_authenticated_onvif_request(
                "media_service", soap_body
            )
            if snapshot_xml:
                uri = self._parse_snapshot_uri(snapshot_xml)
                if uri:
                    self._snapshot_uri = uri
                    self._chosen_snapshot_uri = uri
        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ) as err:
            _LOGGER.debug("Failed to get ONVIF snapshot URI: %s", err)

    def _select_profile_for_stream_type(self, profiles_with_uri: list) -> dict | None:
        """Select the appropriate profile for the current stream type."""

        def _token_lc(profile):
            return profile.get("token", "").lower()

        def _profile_resolution(profile):
            w = int(profile.get("encoder_width") or profile.get("width") or 0)
            h = int(profile.get("encoder_height") or profile.get("height") or 0)
            return w * h

        if self._stream_type == "main":
            # Prefer Profile_0; fall back to profile0, main, mainstream
            preferred_tokens = ["profile_0", "profile0", "main", "mainstream"]
        else:
            # Prefer Profile_1; fall back to Profile_2; support variations
            preferred_tokens = [
                "profile_1",
                "profile1",
                "sub",
                "substream",
                "profile_2",
                "profile2",
            ]

        # Try to find by token name first
        tokens_lc = [_token_lc(p) for p in profiles_with_uri]
        for token in preferred_tokens:
            try:
                idx = tokens_lc.index(token)
                return profiles_with_uri[idx]
            except ValueError:
                continue

        # If no token match, fall back to resolution-based heuristic
        if self._stream_type == "main":
            return max(profiles_with_uri, key=_profile_resolution)

        positive = [p for p in profiles_with_uri if _profile_resolution(p) > 0]
        return (
            min(positive, key=_profile_resolution)
            if positive
            else profiles_with_uri[-1]
        )

    async def _make_onvif_request(self, endpoint: str, soap_body: str) -> str | None:
        """Make an ONVIF HTTP request and return the XML response."""
        return await self._onvif_client.make_request(endpoint, soap_body)

    async def _make_authenticated_onvif_request(
        self, endpoint: str, soap_body: str
    ) -> str | None:
        """Make an authenticated ONVIF HTTP request and return the XML response."""
        return await self._onvif_client.make_authenticated_request(endpoint, soap_body)

    def _parse_device_info(self, xml_content: str) -> dict[str, str] | None:
        """Parse device information from ONVIF XML response."""
        device_info = self._onvif_client.parse_device_info(xml_content)
        return device_info if device_info else None

    def _parse_capabilities(self, xml_content: str) -> dict[str, str]:
        """Parse capabilities from ONVIF XML response."""
        return self._onvif_client.parse_capabilities(xml_content)

    def _parse_services(self, xml_content: str) -> list[dict[str, str]]:
        """Parse services from ONVIF XML response."""
        return self._onvif_client.parse_services(xml_content)

    async def _get_onvif_profiles(self, _media_service_url: str) -> list[dict]:
        """Get ONVIF profiles using authenticated HTTP request to Media service."""
        _LOGGER.info("=== Getting ONVIF Profiles for %s ===", self._host)

        # Create authenticated GetProfiles request using ONVIF client
        soap_body = "<trt:GetProfiles/>"

        profiles_xml = await self._make_authenticated_onvif_request(
            "media_service", soap_body
        )
        if profiles_xml:
            _LOGGER.info(
                "=== FULL ONVIF GetProfiles XML Response for %s ===", self._host
            )
            _LOGGER.info("%s", profiles_xml)
            _LOGGER.info("=== END GetProfiles XML ===")
            profiles = self._parse_profiles(profiles_xml)

            # Get stream URIs for each profile
            for profile in profiles:
                if "token" in profile:
                    stream_uri = await self._get_stream_uri_from_profile(profile)
                    if stream_uri:
                        profile["stream_uri"] = stream_uri
                        _LOGGER.info(
                            "Profile %s stream URI: %s",
                            profile.get("name", profile["token"]),
                            stream_uri,
                        )
                    else:
                        _LOGGER.warning(
                            "No stream URI returned for profile %s",
                            profile.get("name", profile["token"]),
                        )

            return profiles
        _LOGGER.warning("No XML response from GetProfiles for %s", self._host)
        return []

    def _parse_stream_uri(self, xml_content: str) -> str | None:
        """Parse stream URI from ONVIF GetStreamUri XML response."""
        try:
            root = ET.fromstring(xml_content)
            namespaces = ONVIF_NAMESPACES

            # Find the GetStreamUriResponse
            response = root.find(".//trt:GetStreamUriResponse", namespaces)
            if response is None:
                response = root.find(".//GetStreamUriResponse")

            if response is not None:
                # MediaUri is in trt namespace
                media_uri = response.find(".//trt:MediaUri", namespaces)

                # Fallback to tt namespace
                if media_uri is None:
                    media_uri = response.find(".//tt:MediaUri", namespaces)

                # Fallback without namespaces
                if media_uri is None:
                    media_uri = response.find(".//MediaUri")

                if media_uri is not None:
                    # Uri is in tt namespace
                    uri_elem = media_uri.find("tt:Uri", namespaces)

                    # Fallback without namespaces
                    if uri_elem is None:
                        uri_elem = media_uri.find("Uri")

                    if uri_elem is not None and uri_elem.text:
                        uri = uri_elem.text

                        # Fix incomplete URIs from Thingino cameras
                        if not uri.startswith(("rtsp://", "http://", "https://")):
                            # Thingino returns incomplete URIs like "192.168.1.123/ch1"
                            uri = f"rtsp://{uri}"

                        # Add authentication to the URI if needed and not already present
                        if (
                            self._username
                            and self._password
                            and "://" in uri
                            and "@" not in uri
                        ):
                            protocol, rest = uri.split("://", 1)
                            return (
                                f"{protocol}://{self._username}:{self._password}@{rest}"
                            )

                        return uri
        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse stream URI XML: %s", err)
        return None

    def _parse_snapshot_uri(self, xml_content: str) -> str | None:
        """Parse snapshot URI from ONVIF GetSnapshotUri XML response."""
        try:
            root = ET.fromstring(xml_content)
            namespaces = ONVIF_NAMESPACES

            # Find the GetSnapshotUriResponse
            response = root.find(".//trt:GetSnapshotUriResponse", namespaces)
            if response is None:
                response = root.find(".//GetSnapshotUriResponse")

            if response is not None:
                # MediaUri is in trt namespace
                media_uri = response.find(".//trt:MediaUri", namespaces)

                # Fallback to tt namespace
                if media_uri is None:
                    media_uri = response.find(".//tt:MediaUri", namespaces)

                # Fallback without namespaces
                if media_uri is None:
                    media_uri = response.find(".//MediaUri")

                if media_uri is not None:
                    # Uri is in tt namespace
                    uri_elem = media_uri.find("tt:Uri", namespaces)

                    # Fallback without namespaces
                    if uri_elem is None:
                        uri_elem = media_uri.find("Uri")

                    if uri_elem is not None and uri_elem.text:
                        return uri_elem.text
        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse snapshot URI XML: %s", err)
        return None

    def _parse_profiles(self, xml_content: str) -> list[dict]:
        """Parse profiles from ONVIF GetProfiles XML response."""
        profiles: list[dict] = []
        try:
            root = ET.fromstring(xml_content)
            namespaces = ONVIF_NAMESPACES

            # Find all profiles in the response
            response = root.find(".//trt:GetProfilesResponse", namespaces)
            if response is None:
                return profiles

            profile_elements = response.findall("trt:Profiles", namespaces)
            for profile_elem in profile_elements:
                profile = self._parse_single_profile(profile_elem, namespaces)
                if profile:  # Only add if we got some data
                    profiles.append(profile)

        except (ET.ParseError, AttributeError, ValueError) as err:
            _LOGGER.debug("Failed to parse profiles XML: %s", err)

        return profiles

    def _parse_single_profile(self, profile_elem, namespaces: dict) -> dict:
        """Parse a single profile element."""
        profile = {}

        # Get profile token and name
        profile["token"] = profile_elem.get("token", "")
        name_elem = profile_elem.find("tt:Name", namespaces)
        if name_elem is not None and name_elem.text:
            profile["name"] = name_elem.text

        # Get video source configuration
        self._parse_video_source_config(profile_elem, profile, namespaces)

        # Get video encoder configuration
        self._parse_video_encoder_config(profile_elem, profile, namespaces)

        return profile

    def _parse_video_source_config(
        self, profile_elem, profile: dict, namespaces: dict
    ) -> None:
        """Parse video source configuration from profile element."""
        video_source = profile_elem.find(".//tt:VideoSourceConfiguration", namespaces)
        if video_source is None:
            return

        source_token = video_source.get("token", "")
        profile["video_source_token"] = source_token

        # Get video source bounds (resolution)
        bounds = video_source.find(".//tt:Bounds", namespaces)
        if bounds is not None:
            profile["width"] = int(bounds.get("width", "0"))
            profile["height"] = int(bounds.get("height", "0"))

    def _parse_video_encoder_config(
        self, profile_elem, profile: dict, namespaces: dict
    ) -> None:
        """Parse video encoder configuration from profile element."""
        video_encoder = profile_elem.find(".//tt:VideoEncoderConfiguration", namespaces)
        if video_encoder is None:
            return

        encoder_token = video_encoder.get("token", "")
        profile["video_encoder_token"] = encoder_token

        # Get encoding details
        encoding = video_encoder.find("tt:Encoding", namespaces)
        if encoding is not None and encoding.text:
            profile["encoding"] = encoding.text

        resolution = video_encoder.find(".//tt:Resolution", namespaces)
        if resolution is not None:
            width_elem = resolution.find("tt:Width", namespaces)
            height_elem = resolution.find("tt:Height", namespaces)
            if width_elem is not None and height_elem is not None:
                profile["encoder_width"] = int(width_elem.text or "0")
                profile["encoder_height"] = int(height_elem.text or "0")

    async def _get_device_info(self) -> dict[str, str] | None:
        """Get device information via ONVIF HTTP request."""
        soap_body = "<tds:GetDeviceInformation/>"
        device_info_xml = await self._make_onvif_request("device_service", soap_body)
        if device_info_xml:
            return self._parse_device_info(device_info_xml)
        return None

    async def stream_source(self) -> str | None:
        """Return the cached RTSP stream source."""
        return self._stream_uri

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera using cached ONVIF snapshot URI."""
        if not self._snapshot_uri:
            _LOGGER.warning(
                "No cached snapshot URI available for camera %s", self._host
            )
            return None

        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                self._snapshot_uri,
                auth=aiohttp.BasicAuth(self._username, self._password),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    return await response.read()
                _LOGGER.warning(
                    "Snapshot URI %s returned status %s for camera %s",
                    self._snapshot_uri,
                    response.status,
                    self._host,
                )
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.warning("Failed to get snapshot from %s: %s", self._host, e)

        return None

    async def _get_stream_uri_from_profile(self, profile) -> str | None:
        """Get stream URI from an ONVIF profile using HTTP-based ONVIF requests."""
        try:
            profile_token = getattr(
                profile,
                "token",
                profile.get("token") if isinstance(profile, dict) else None,
            )
            if not profile_token:
                _LOGGER.warning("No profile token found for %s", self._host)
                return None

            _LOGGER.debug("Getting stream URI for profile %s", profile_token)

            # Create GetStreamUri SOAP request
            soap_body = f"""<trt:GetStreamUri xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
                <trt:StreamSetup>
                    <trt:Stream>RTP-Unicast</trt:Stream>
                    <trt:Transport>
                        <trt:Protocol>RTSP</trt:Protocol>
                    </trt:Transport>
                </trt:StreamSetup>
                <trt:ProfileToken>{profile_token}</trt:ProfileToken>
            </trt:GetStreamUri>"""

            # Make authenticated request to media service
            response_xml = await self._onvif_client.make_authenticated_request(
                "media_service", soap_body
            )

            if not response_xml:
                _LOGGER.warning(
                    "No response from GetStreamUri for profile %s on %s",
                    profile_token,
                    self._host,
                )
                return None

            _LOGGER.debug(
                "GetStreamUri response for %s profile %s: %s",
                self._host,
                profile_token,
                response_xml,
            )

            # Parse the response to extract the URI
            uri = self._parse_stream_uri(response_xml)

        except (aiohttp.ClientError, TimeoutError, AttributeError, ValueError) as err:
            _LOGGER.warning(
                "Failed to get stream URI from profile for %s: %s", self._host, err
            )
            return None
        else:
            if uri:
                # Add authentication to the URI if credentials are available and not already present
                if (
                    self._username
                    and self._password
                    and "://" in uri
                    and "@" not in uri
                ):
                    protocol, rest = uri.split("://", 1)
                    authenticated_uri = (
                        f"{protocol}://{self._username}:{self._password}@{rest}"
                    )
                    _LOGGER.info("Got ONVIF stream URI for %s: %s", self._host, uri)
                    return authenticated_uri
                _LOGGER.info("Got ONVIF stream URI for %s: %s", self._host, uri)
                return uri

            _LOGGER.debug("Failed to parse stream URI from response for %s", self._host)
            return None

    async def get_onvif_profiles(self) -> list:
        """Get all ONVIF profiles for this camera."""
        if not self._profiles:
            try:
                _LOGGER.debug("Getting ONVIF profiles via HTTP for %s", self._host)
                self._profiles = await self._get_onvif_profiles("")
                _LOGGER.info(
                    "Successfully got %d ONVIF profiles for %s",
                    len(self._profiles or []),
                    self._host,
                )
            except (
                aiohttp.ClientError,
                TimeoutError,
                ET.ParseError,
                AttributeError,
                ValueError,
            ) as err:
                _LOGGER.warning(
                    "Failed to get ONVIF profiles for %s: %s", self._host, err
                )
                _LOGGER.debug(
                    "ONVIF profiles error details for %s", self._host, exc_info=True
                )
                return []
        return self._profiles or []

    @property
    def extra_state_attributes(self) -> dict[str, str | int] | None:
        """Expose debug attributes for verification."""
        attrs: dict[str, str | int] = {}
        if self._chosen_profile_token:
            attrs["chosen_profile_token"] = self._chosen_profile_token
        if self._chosen_profile_resolution:
            w, h = self._chosen_profile_resolution
            attrs["chosen_profile_resolution"] = f"{w}x{h}"
        if self._chosen_stream_uri:
            attrs["chosen_stream_uri"] = self._chosen_stream_uri
        if self._chosen_snapshot_uri:
            attrs["chosen_snapshot_uri"] = self._chosen_snapshot_uri
        return attrs if attrs else None

    async def _log_full_camera_response(self) -> None:
        """Log comprehensive camera information during initial setup."""
        _LOGGER.info("=== FULL CAMERA RESPONSE FOR %s ===", self._host)

        # Test ONVIF-provided endpoints only
        await self._test_onvif_endpoints()

        # Also log ONVIF information
        await self.log_available_profiles()

        _LOGGER.info("=== END FULL CAMERA RESPONSE FOR %s ===", self._host)

    async def _test_onvif_endpoints(self) -> None:
        """Test ONVIF-provided endpoints for debugging."""
        auth = (
            aiohttp.BasicAuth(self._username, self._password)
            if self._username and self._password
            else None
        )

        # Get ONVIF profiles to find snapshot URIs
        profiles = await self.get_onvif_profiles()
        if not profiles:
            _LOGGER.info("No ONVIF profiles available to test endpoints")
            return

        async with aiohttp.ClientSession() as session:
            # Test snapshot URIs from ONVIF profiles
            for profile in profiles:
                profile_name = profile.get("name", "Unknown")
                profile_token = profile.get("token", "Unknown")

                # Try to get snapshot URI for this profile
                try:
                    soap_body = f"<trt:GetSnapshotUri><trt:ProfileToken>{profile_token}</trt:ProfileToken></trt:GetSnapshotUri>"
                    snapshot_xml = await self._make_authenticated_onvif_request(
                        "media_service", soap_body
                    )
                    if snapshot_xml:
                        uri = self._parse_snapshot_uri(snapshot_xml)
                        if uri:
                            _LOGGER.info(
                                "Testing ONVIF snapshot URI for profile %s: %s",
                                profile_name,
                                uri,
                            )

                            try:
                                async with session.get(
                                    uri,
                                    auth=auth,
                                    timeout=aiohttp.ClientTimeout(total=10),
                                ) as response:
                                    _LOGGER.info(
                                        "ONVIF snapshot URI %s status: %s",
                                        uri,
                                        response.status,
                                    )
                                    if response.status == 200:
                                        content_length = response.headers.get(
                                            "content-length", "unknown"
                                        )
                                        _LOGGER.info(
                                            "ONVIF snapshot URI %s content-length: %s",
                                            uri,
                                            content_length,
                                        )
                                    else:
                                        error_text = await response.text()
                                        _LOGGER.info(
                                            "ONVIF snapshot URI %s error: %s",
                                            uri,
                                            error_text[:500],
                                        )
                            except (aiohttp.ClientError, TimeoutError) as err:
                                _LOGGER.info(
                                    "Failed to test ONVIF snapshot URI %s: %s", uri, err
                                )
                        else:
                            _LOGGER.info(
                                "No snapshot URI found for profile %s", profile_name
                            )
                except (aiohttp.ClientError, TimeoutError) as err:
                    _LOGGER.info(
                        "Failed to get snapshot URI for profile %s: %s",
                        profile_name,
                        err,
                    )

    async def log_available_profiles(self) -> None:
        """Log all available ONVIF profiles for debugging."""
        try:
            # First, let's check what ONVIF services are available
            await self.log_onvif_capabilities()

            profiles = await self.get_onvif_profiles()
            if not profiles:
                _LOGGER.info("No ONVIF profiles found for camera %s", self._host)
                return

            _LOGGER.info(
                "Found %d ONVIF profiles for camera %s:", len(profiles), self._host
            )
            for i, profile in enumerate(profiles):
                profile_name = profile.get("name", "Unknown")
                profile_token = profile.get("token", "Unknown")
                profile_info = (
                    f"  Profile {i + 1}: {profile_name} (Token: {profile_token})"
                )

                # Add video encoding information if available
                if profile.get("encoding"):
                    encoding = profile.get("encoding")
                    width = profile.get("encoder_width", profile.get("width", 0))
                    height = profile.get("encoder_height", profile.get("height", 0))
                    if width and height:
                        profile_info += f" - Video: {encoding} {width}x{height}"
                    else:
                        profile_info += f" - Video: {encoding}"

                _LOGGER.info(profile_info)
        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ) as err:
            _LOGGER.warning(
                "Failed to log available profiles for %s: %s", self._host, err
            )
            _LOGGER.debug(
                "Profile logging error details for %s", self._host, exc_info=True
            )

    async def log_onvif_capabilities(self) -> None:
        """Log ONVIF capabilities and services for debugging."""
        try:
            _LOGGER.info("=== ONVIF Capabilities for %s ===", self._host)

            # Get device information via HTTP
            soap_body = "<tds:GetDeviceInformation/>"
            device_info_xml = await self._make_onvif_request(
                "device_service", soap_body
            )

            if device_info_xml:
                _LOGGER.info(
                    "=== FULL ONVIF GetDeviceInformation XML Response for %s ===",
                    self._host,
                )
                _LOGGER.info("%s", device_info_xml)
                _LOGGER.info("=== END GetDeviceInformation XML ===")

                # Parse device info from XML
                device_info = self._parse_device_info(device_info_xml)
                if device_info:
                    _LOGGER.info(
                        "Device Info for %s: Manufacturer=%s, Model=%s, FirmwareVersion=%s",
                        self._host,
                        device_info.get("Manufacturer", "Unknown"),
                        device_info.get("Model", "Unknown"),
                        device_info.get("FirmwareVersion", "Unknown"),
                    )

            # Get capabilities via HTTP
            soap_body = "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>"
            capabilities_xml = await self._make_onvif_request(
                "device_service", soap_body
            )

            if capabilities_xml:
                _LOGGER.info(
                    "=== FULL ONVIF GetCapabilities XML Response for %s ===", self._host
                )
                _LOGGER.info("%s", capabilities_xml)
                _LOGGER.info("=== END GetCapabilities XML ===")

                # Parse and log capabilities
                capabilities = self._parse_capabilities(capabilities_xml)
                _LOGGER.info("ONVIF Capabilities for %s:", self._host)

                if capabilities.get("Media"):
                    _LOGGER.info("  Media Service: %s", capabilities["Media"])
                else:
                    _LOGGER.warning("  Media Service: NOT AVAILABLE")

                if capabilities.get("PTZ"):
                    _LOGGER.info("  PTZ Service: %s", capabilities["PTZ"])
                else:
                    _LOGGER.info("  PTZ Service: Not available")

                if capabilities.get("Events"):
                    _LOGGER.info("  Events Service: %s", capabilities["Events"])
                else:
                    _LOGGER.info("  Events Service: Not available")

                if capabilities.get("Analytics"):
                    _LOGGER.info("  Analytics Service: %s", capabilities["Analytics"])
                else:
                    _LOGGER.info("  Analytics Service: Not available")

            # Get services via HTTP
            soap_body = "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>"
            services_xml = await self._make_onvif_request("device_service", soap_body)

            if services_xml:
                _LOGGER.info(
                    "=== FULL ONVIF GetServices XML Response for %s ===", self._host
                )
                _LOGGER.info("%s", services_xml)
                _LOGGER.info("=== END GetServices XML ===")

                # Parse and log services
                services = self._parse_services(services_xml)
                _LOGGER.info("Available ONVIF Services for %s:", self._host)
                for service in services:
                    _LOGGER.info(
                        "  Service: %s - %s", service["Namespace"], service["XAddr"]
                    )

        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ) as err:
            _LOGGER.warning(
                "Failed to get ONVIF capabilities for %s: %s", self._host, err
            )
            _LOGGER.debug(
                "ONVIF capabilities error details for %s", self._host, exc_info=True
            )
