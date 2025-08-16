"""The Thingino Camera integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
import traceback

import aiofiles
import aiohttp
import defusedxml.ElementTree as ET
from onvif import ONVIFCamera
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, get_wsdl_dir
from .onvif_client import ThinginoOnvifClient

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ThinginoConfigEntry = ConfigEntry[dict[str, str]]

# Service schemas
CAPTURE_SNAPSHOT_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("filename"): cv.string,
    }
)

PTZ_MOVE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("direction"): vol.In(
            [
                "up",
                "down",
                "left",
                "right",
                "up_left",
                "up_right",
                "down_left",
                "down_right",
            ]
        ),
        vol.Optional("speed", default=0.5): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=1.0)
        ),
        vol.Optional("duration", default=1.0): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=10.0)
        ),
    }
)

PTZ_STOP_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)

PTZ_PRESET_GOTO_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("preset"): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    }
)

PTZ_PRESET_SET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("preset"): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Thingino integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ThinginoConfigEntry) -> bool:
    """Set up Thingino from a config entry."""
    _LOGGER.debug("Setting up Thingino integration for %s", entry.data[CONF_HOST])
    camera = None
    try:
        # Test connection to camera during setup with proper cleanup
        _LOGGER.debug("Creating ONVIF connection to %s", entry.data[CONF_HOST])

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
                "Device info: Manufacturer=%s, Model=%s, FirmwareVersion=%s, HardwareId=%s, SerialNumber=%s",
                device_info.Manufacturer,
                device_info.Model,
                device_info.FirmwareVersion,
                device_info.HardwareId,
                device_info.SerialNumber,
            )
    except Exception as exc:
        _LOGGER.error("Failed to connect to %s: %s", entry.data[CONF_HOST], exc)
        _LOGGER.debug("Full exception details: %r", exc)
        _LOGGER.debug("Traceback: %s", traceback.format_exc())
        raise ConfigEntryNotReady(
            f"Unable to connect to Thingino camera at {entry.data[CONF_HOST]}"
        ) from exc
    finally:
        # Clean up ONVIF camera resources after setup test
        if camera:
            with contextlib.suppress(Exception):
                # Use the public close method to properly clean up resources
                await camera.close()

    entry.runtime_data = {
        "host": entry.data[CONF_HOST],
        "username": entry.data[CONF_USERNAME],
        "password": entry.data[CONF_PASSWORD],
        # Persist discovery metadata for entities, prefer ONVIF serial number
        "serial": getattr(device_info, "SerialNumber", "unknown")
        if "device_info" in locals()
        else entry.data.get("serial", "unknown"),
        "camera_name": entry.data.get("camera_name", "Thingino Camera"),
        "manufacturer": entry.data.get("manufacturer", "Thingino"),
        "model": entry.data.get("model", "Camera"),
        "firmware": entry.data.get("firmware", "unknown"),
        # Add ONVIF device information if available
        "hardware_id": getattr(device_info, "HardwareId", "")
        if "device_info" in locals()
        else "",
        "firmware_version": getattr(device_info, "FirmwareVersion", "unknown")
        if "device_info" in locals()
        else "unknown",
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def capture_snapshot_service(call: ServiceCall) -> None:
        """Handle the capture snapshot service call."""
        await _async_capture_snapshot(hass, call)

    async def ptz_move_service(call: ServiceCall) -> None:
        """Handle the PTZ move service call."""
        await _async_ptz_move(hass, call)

    async def ptz_stop_service(call: ServiceCall) -> None:
        """Handle the PTZ stop service call."""
        await _async_ptz_stop(hass, call)

    async def ptz_preset_goto_service(call: ServiceCall) -> None:
        """Handle the PTZ preset goto service call."""
        await _async_ptz_preset_goto(hass, call)

    async def ptz_preset_set_service(call: ServiceCall) -> None:
        """Handle the PTZ preset set service call."""
        await _async_ptz_preset_set(hass, call)

    hass.services.async_register(
        DOMAIN,
        "capture_snapshot",
        capture_snapshot_service,
        schema=CAPTURE_SNAPSHOT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN, "ptz_move", ptz_move_service, schema=PTZ_MOVE_SCHEMA
    )

    hass.services.async_register(
        DOMAIN, "ptz_stop", ptz_stop_service, schema=PTZ_STOP_SCHEMA
    )

    hass.services.async_register(
        DOMAIN,
        "ptz_preset_goto",
        ptz_preset_goto_service,
        schema=PTZ_PRESET_GOTO_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN, "ptz_preset_set", ptz_preset_set_service, schema=PTZ_PRESET_SET_SCHEMA
    )

    return True


async def _get_onvif_snapshot_url(
    host: str, username: str, password: str, entity_id: str
) -> str | None:
    """Get ONVIF snapshot URL for the camera."""

    # Create ONVIF client for this request
    onvif_client = ThinginoOnvifClient(
        host=host, port=80, username=username, password=password
    )

    # Determine preferred profile token based on entity_id (main vs sub stream)
    preferred_tokens = (
        ["profile_0"] if "main" in entity_id.lower() else ["profile_1", "profile_2"]
    )

    # Try ONVIF snapshot via HTTP SOAP for preferred tokens
    for token in preferred_tokens:
        try:
            soap_body = f"<trt:GetSnapshotUri><trt:ProfileToken>{token}</trt:ProfileToken></trt:GetSnapshotUri>"
            snapshot_xml = await onvif_client.make_authenticated_request(
                "media_service", soap_body
            )
            if snapshot_xml:
                uri = onvif_client.parse_snapshot_uri(snapshot_xml)
                if uri:
                    return uri
        except (
            aiohttp.ClientError,
            TimeoutError,
            ET.ParseError,
            AttributeError,
            ValueError,
        ):
            continue

    return None


async def get_snapshot_uri_for_entity(
    host: str, username: str, password: str, entity_id: str
) -> str | None:
    """Public wrapper for getting ONVIF snapshot URI for an entity."""
    return await _get_onvif_snapshot_url(host, username, password, entity_id)


async def _async_capture_snapshot(hass: HomeAssistant, call: ServiceCall) -> None:
    """Capture a snapshot from a Thingino camera."""
    entity_id = call.data["entity_id"]
    filename = call.data["filename"]

    # Get the camera entity
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)

    if not entity_entry or entity_entry.platform != DOMAIN:
        raise ServiceValidationError(f"Entity {entity_id} is not a Thingino camera")

    # Find the config entry for this entity
    config_entry = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entity_entry.config_entry_id == entry.entry_id:
            config_entry = entry
            break

    if not config_entry:
        raise ServiceValidationError(f"Could not find config entry for {entity_id}")

    # Get camera details from config entry
    host = config_entry.runtime_data["host"]
    username = config_entry.runtime_data["username"]
    password = config_entry.runtime_data["password"]

    # Get ONVIF snapshot URL
    snapshot_url = await _get_onvif_snapshot_url(host, username, password, entity_id)
    if not snapshot_url:
        raise ServiceValidationError(
            f"No ONVIF snapshot URI available for camera {entity_id}"
        )

    # Create auth for HTTP request
    auth = aiohttp.BasicAuth(username, password) if username and password else None

    # Ensure the directory exists
    www_path = Path(hass.config.path("www"))
    file_path = www_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Capture the snapshot
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                snapshot_url, auth=auth, timeout=aiohttp.ClientTimeout(total=10)
            ) as response,
        ):
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(content)
                _LOGGER.info("Snapshot saved to %s", file_path)
            else:
                raise ServiceValidationError(
                    f"Failed to capture snapshot: HTTP {response.status}"
                )
    except aiohttp.ClientError as err:
        raise ServiceValidationError(f"Failed to capture snapshot: {err}") from err
    except OSError as err:
        raise ServiceValidationError(f"Failed to save snapshot: {err}") from err


def _validate_profiles(profiles: list, host: str) -> None:
    """Validate that profiles are available for the camera."""
    if not profiles:
        raise ServiceValidationError(f"No profiles found for camera {host}")


def _validate_direction(direction: str, direction_map: dict) -> None:
    """Validate that the direction is supported."""
    if direction not in direction_map:
        raise ServiceValidationError(f"Invalid direction: {direction}")


async def _async_get_camera_onvif(
    hass: HomeAssistant, entity_id: str
) -> tuple[str, str, str]:
    """Get camera ONVIF connection details from entity."""
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)

    if not entity_entry or entity_entry.platform != DOMAIN:
        raise ServiceValidationError(f"Entity {entity_id} is not a Thingino camera")

    # Find the config entry for this entity
    config_entry = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entity_entry.config_entry_id == entry.entry_id:
            config_entry = entry
            break

    if not config_entry:
        raise ServiceValidationError(f"Could not find config entry for {entity_id}")

    # Get camera details from config entry
    host = config_entry.runtime_data["host"]
    username = config_entry.runtime_data["username"]
    password = config_entry.runtime_data["password"]

    return host, username, password


async def _async_ptz_move(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle PTZ move command."""
    entity_id = call.data["entity_id"]
    direction = call.data["direction"]
    speed = call.data.get("speed", 0.5)
    duration = call.data.get("duration", 1.0)

    def _validate_profiles(profiles: list, host: str) -> None:
        """Validate that profiles are available for the camera."""
        if not profiles:
            raise ServiceValidationError(f"No profiles found for camera {host}")

    host, username, password = await _async_get_camera_onvif(hass, entity_id)

    try:
        camera = ONVIFCamera(
            host, 80, username, password, get_wsdl_dir(), no_cache=True
        )
        ptz_service = await camera.create_ptz_service()

        # Get PTZ configuration
        profiles = await camera.get_profiles()
        _validate_profiles(profiles, host)

        profile = profiles[0]  # Use first profile

        # Direction mapping
        direction_map = {
            "up": (0, speed, 0),
            "down": (0, -speed, 0),
            "left": (-speed, 0, 0),
            "right": (speed, 0, 0),
            "up_left": (-speed, speed, 0),
            "up_right": (speed, speed, 0),
            "down_left": (-speed, -speed, 0),
            "down_right": (speed, -speed, 0),
        }

        _validate_direction(direction, direction_map)

        x, y, z = direction_map[direction]

        # Create velocity vector
        velocity = {"PanTilt": {"x": x, "y": y}, "Zoom": {"x": z}}

        # Start continuous move
        await ptz_service.ContinuousMove(profile.token, velocity)

        # Wait for duration
        await asyncio.sleep(duration)

        # Stop movement
        await ptz_service.Stop(profile.token)

        _LOGGER.info("PTZ move %s completed for %s", direction, host)

    except Exception as err:
        _LOGGER.error("PTZ move failed for %s: %s", host, err)
        raise ServiceValidationError(f"PTZ move failed: {err}") from err


async def _async_ptz_stop(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle PTZ stop command."""
    entity_id = call.data["entity_id"]

    host, username, password = await _async_get_camera_onvif(hass, entity_id)

    try:
        camera = ONVIFCamera(
            host, 80, username, password, get_wsdl_dir(), no_cache=True
        )
        ptz_service = await camera.create_ptz_service()

        # Get PTZ configuration
        profiles = await camera.get_profiles()
        _validate_profiles(profiles, host)

        profile = profiles[0]  # Use first profile

        # Stop all movements
        await ptz_service.Stop(profile.token)

        _LOGGER.info("PTZ stop completed for %s", host)

    except Exception as err:
        _LOGGER.error("PTZ stop failed for %s: %s", host, err)
        raise ServiceValidationError(f"PTZ stop failed: {err}") from err


async def _async_ptz_preset_goto(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle PTZ preset goto command."""
    entity_id = call.data["entity_id"]
    preset = call.data["preset"]

    host, username, password = await _async_get_camera_onvif(hass, entity_id)

    try:
        camera = ONVIFCamera(
            host, 80, username, password, get_wsdl_dir(), no_cache=True
        )
        ptz_service = await camera.create_ptz_service()

        # Get PTZ configuration
        profiles = await camera.get_profiles()
        _validate_profiles(profiles, host)

        profile = profiles[0]  # Use first profile

        # Go to preset
        await ptz_service.GotoPreset(profile.token, preset)

        _LOGGER.info("PTZ goto preset %s completed for %s", preset, host)

    except Exception as err:
        _LOGGER.error("PTZ goto preset failed for %s: %s", host, err)
        raise ServiceValidationError(f"PTZ goto preset failed: {err}") from err


async def _async_ptz_preset_set(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle PTZ preset set command."""
    entity_id = call.data["entity_id"]
    preset = call.data["preset"]

    host, username, password = await _async_get_camera_onvif(hass, entity_id)

    try:
        camera = ONVIFCamera(
            host, 80, username, password, get_wsdl_dir(), no_cache=True
        )
        ptz_service = await camera.create_ptz_service()

        # Get PTZ configuration
        profiles = await camera.get_profiles()
        _validate_profiles(profiles, host)

        profile = profiles[0]  # Use first profile

        # Set preset
        await ptz_service.SetPreset(profile.token, preset)

        _LOGGER.info("PTZ set preset %s completed for %s", preset, host)

    except Exception as err:
        _LOGGER.error("PTZ set preset failed for %s: %s", host, err)
        raise ServiceValidationError(f"PTZ set preset failed: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ThinginoConfigEntry) -> bool:
    """Unload a config entry."""
    # Unregister services when the last entry is unloaded
    if len(hass.config_entries.async_entries(DOMAIN)) == 1:
        hass.services.async_remove(DOMAIN, "capture_snapshot")
        hass.services.async_remove(DOMAIN, "ptz_move")
        hass.services.async_remove(DOMAIN, "ptz_stop")
        hass.services.async_remove(DOMAIN, "ptz_preset_goto")
        hass.services.async_remove(DOMAIN, "ptz_preset_set")

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
