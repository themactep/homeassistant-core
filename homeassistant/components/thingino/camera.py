"""Component providing support for Thingino Cameras."""

import ipaddress
import logging

import aiohttp
from onvif import ONVIFCamera

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ThinginoConfigEntry
from .const import DOMAIN, get_wsdl_dir

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Thingino camera platform."""
    async_add_entities([ThinginoCamera(entry)])


class ThinginoCamera(Camera):
    """Representation of a Thingino camera."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ThinginoConfigEntry) -> None:
        """Initialize the Thingino camera."""
        super().__init__()
        self._entry = entry
        config = entry.runtime_data
        self._host = config["host"]
        self._username = config["username"]
        self._password = config["password"]
        self._attr_unique_id = f"thingino_camera_{self._host.replace('.', '_')}"
        # Determine network subnet
        try:
            ip = ipaddress.IPv4Address(self._host)
            network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            network_info = str(network)
        except Exception:
            network_info = "Unknown"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            name=f"Thingino Camera {self._host}",
            manufacturer="Thingino",
            model="Camera",
            configuration_url=f"http://{self._host}",
            hw_version=network_info,  # Show network in hardware version field
        )
        # ONVIF connection uses port 80 for device management
        self._onvif = ONVIFCamera(
            self._host,
            80,
            self._username,
            self._password,
            get_wsdl_dir(),
            no_cache=True,
        )

    @property
    def stream_source(self) -> str | None:
        """Return the RTSP stream source."""
        # For now, use fallback URL. We'll get the real URL from ONVIF later
        credentials = (
            f"{self._username}:{self._password}@"
            if self._username and self._password
            else ""
        )
        return f"rtsp://{credentials}{self._host}:554/ch0"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera."""
        # Try direct HTTP snapshot first (faster and more reliable for Thingino)
        try:
            snapshot_url = f"http://{self._host}/image.jpg"
            session = async_get_clientsession(self.hass)
            async with session.get(
                snapshot_url,
                auth=aiohttp.BasicAuth(self._username, self._password),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    return await response.read()
        except Exception as e:
            _LOGGER.debug("HTTP snapshot failed: %s", e)

        # Fallback to ONVIF snapshot
        try:
            media_service = await self._onvif.create_media_service()
            profiles = await media_service.GetProfiles()
            if profiles:
                snapshot_uri = await media_service.GetSnapshotUri(profiles[0].token)
                session = async_get_clientsession(self.hass)
                async with session.get(
                    snapshot_uri.Uri,
                    auth=aiohttp.BasicAuth(self._username, self._password),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        return await response.read()
        except Exception as e:
            _LOGGER.debug("ONVIF snapshot failed: %s", e)

        _LOGGER.error("Failed to get snapshot from camera %s", self._host)
        return None
