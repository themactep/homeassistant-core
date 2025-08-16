"""Test the Thingino camera platform."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.camera import async_get_image
from homeassistant.components.thingino.camera import ThinginoCamera
from homeassistant.components.thingino.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry


async def test_camera_setup(hass: HomeAssistant, config_entry) -> None:
    """Test camera platform setup."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that camera entity is created with MAC-based entity ID
    entity_registry = er.async_get(hass)
    camera_entity = entity_registry.async_get("camera.thingino_aabbccddeeff_sub_stream")

    assert camera_entity is not None
    assert camera_entity.domain == "camera"
    assert camera_entity.platform == DOMAIN


async def test_camera_stream_source(hass: HomeAssistant, config_entry) -> None:
    """Test camera stream source property."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("camera.thingino_aabbccddeeff_sub_stream")
    assert state is not None

    # Get the camera entity
    camera_entity = None
    for entity in hass.data[DOMAIN][config_entry.entry_id]["camera"]:
        if entity.entity_id == "camera.thingino_aabbccddeeff_sub_stream":
            camera_entity = entity
            break

    assert camera_entity is not None

    # Test stream source with credentials
    stream_source = await camera_entity.stream_source()
    assert stream_source == "rtsp://thingino:@192.168.1.100:554/ch1"


async def test_camera_stream_source_with_password(hass: HomeAssistant) -> None:
    """Test camera stream source with password."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "admin",
            "password": "secret",
            "port": 554,
            "mqtt_host": "",
            "mqtt_username": "",
            "mqtt_password": "",
            "serial": "aa:bb:cc:dd:ee:ff",
            "camera_name": "Thingino Camera",
            "manufacturer": "Thingino",
            "model": "Camera",
            "firmware": "1.2.3",
        },
        unique_id="thingino_aa:bb:cc:dd:ee:ff",
    )
    # Set runtime_data directly for testing
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "admin",
        "password": "secret",
        "mqtt_host": "",
        "mqtt_username": "",
        "mqtt_password": "",
        "serial": "aa:bb:cc:dd:ee:ff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
        "firmware_version": "1.2.3",
    }
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the camera entity
    camera_entity = None
    for entity in hass.data[DOMAIN][config_entry.entry_id]["camera"]:
        camera_entity = entity
        break

    assert camera_entity is not None

    # Test stream source with credentials
    stream_source = await camera_entity.stream_source()
    assert stream_source == "rtsp://admin:secret@192.168.1.100:554/ch1"


async def test_camera_snapshot_success(hass: HomeAssistant, config_entry) -> None:
    """Test successful camera snapshot."""
    config_entry.add_to_hass(hass)

    # Mock aiohttp response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read.return_value = b"fake_image_data"

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_session.return_value.get.return_value.__aenter__.return_value = (
            mock_response
        )

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Test getting camera image
        image = await async_get_image(hass, "camera.thingino_aabbccddeeff_sub_stream")
        assert image.content == b"fake_image_data"


async def test_camera_snapshot_failure(hass: HomeAssistant, config_entry) -> None:
    """Test camera snapshot failure."""
    config_entry.add_to_hass(hass)

    # Mock aiohttp response with error
    mock_response = AsyncMock()
    mock_response.status = 404

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_session.return_value.get.return_value.__aenter__.return_value = (
            mock_response
        )

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Get the camera entity
        camera_entity = None
        for entity in hass.data[DOMAIN][config_entry.entry_id]["camera"]:
            camera_entity = entity
            break

        assert camera_entity is not None

        # Test snapshot returns None on failure
        image_data = await camera_entity.async_camera_image()
        assert image_data is None


async def test_camera_snapshot_exception(hass: HomeAssistant, config_entry) -> None:
    """Test camera snapshot with exception."""
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession"
    ) as mock_session:
        mock_session.return_value.get.side_effect = Exception("Network error")

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Get the camera entity
        camera_entity = None
        for entity in hass.data[DOMAIN][config_entry.entry_id]["camera"]:
            camera_entity = entity
            break

        assert camera_entity is not None

        # Test snapshot returns None on exception
        image_data = await camera_entity.async_camera_image()
        assert image_data is None


async def test_camera_device_info(hass: HomeAssistant, config_entry) -> None:
    """Test camera device info."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the camera entity
    camera_entity = None
    for entity in hass.data[DOMAIN][config_entry.entry_id]["camera"]:
        camera_entity = entity
        break

    assert camera_entity is not None

    device_info = camera_entity.device_info
    assert device_info is not None
    assert device_info["identifiers"] == {(DOMAIN, "aa:bb:cc:dd:ee:ff")}
    assert device_info["name"] == "Thingino aa:bb:cc:dd:ee:ff"
    assert device_info["manufacturer"] == "Thingino"
    assert device_info["model"] == "Camera"
    assert device_info["configuration_url"] == "http://192.168.1.100"
    # Hardware version should show hardware ID from config
    assert device_info["hw_version"] == "T31X_GC4653"


async def test_camera_device_info_with_hardware() -> None:
    """Test camera device info with hardware information."""
    # Create a config entry with hardware information
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "thingino",
            "password": "",
            "port": 554,
            "mqtt_host": "",
            "mqtt_username": "",
            "mqtt_password": "",
            "serial": "aa:bb:cc:dd:ee:ff",
            "camera_name": "Thingino Camera",
            "manufacturer": "Thingino",
            "model": "Camera",
            "firmware": "1.2.3",
        },
        unique_id="thingino_aa:bb:cc:dd:ee:ff",
    )

    # Set runtime_data with hardware information
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "mqtt_host": "",
        "mqtt_username": "",
        "mqtt_password": "",
        "serial": "aa:bb:cc:dd:ee:ff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
        "firmware_version": "1.2.3",
    }

    # Create camera entity directly
    camera = ThinginoCamera(config_entry, "main")

    device_info = camera.device_info
    assert device_info is not None
    assert device_info["identifiers"] == {(DOMAIN, "aa:bb:cc:dd:ee:ff")}
    assert device_info["name"] == "Thingino aa:bb:cc:dd:ee:ff"
    assert device_info["manufacturer"] == "Thingino"
    assert device_info["model"] == "Camera"
    assert device_info["configuration_url"] == "http://192.168.1.100"
    # Hardware version should show hardware ID from config
    assert device_info["hw_version"] == "T31X_GC4653"
