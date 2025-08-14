"""Simple tests for the Thingino integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.thingino.const import DOMAIN


async def test_domain_exists():
    """Test that the domain constant exists."""
    assert DOMAIN == "thingino"


async def test_config_flow_import():
    """Test that config flow can be imported."""
    from homeassistant.components.thingino.config_flow import ThinginoConfigFlow

    assert ThinginoConfigFlow is not None


async def test_camera_import():
    """Test that camera module can be imported."""
    from homeassistant.components.thingino.camera import ThinginoCamera

    assert ThinginoCamera is not None


async def test_binary_sensor_import():
    """Test that binary sensor module can be imported."""
    from homeassistant.components.thingino.binary_sensor import ThinginoMotionSensor

    assert ThinginoMotionSensor is not None


@patch("onvif.ONVIFCamera")
async def test_validate_input_success(mock_onvif):
    """Test successful validation of input."""
    from homeassistant.components.thingino.config_flow import validate_input

    # Mock ONVIF camera
    camera_instance = MagicMock()
    mock_onvif.return_value = camera_instance

    device_service = AsyncMock()
    device_info = MagicMock()
    device_info.Manufacturer = "Ingenic"
    device_info.Model = "Thingino Camera"
    device_service.GetDeviceInformation.return_value = device_info
    camera_instance.create_device_service.return_value = device_service

    # Test data
    data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "port": 554,
    }

    # Mock hass
    hass = MagicMock()

    result = await validate_input(hass, data)
    assert result["title"] == "Thingino Camera 192.168.1.100"


@patch("onvif.ONVIFCamera")
async def test_validate_input_invalid_device(mock_onvif):
    """Test validation with invalid device."""
    from homeassistant.components.thingino.config_flow import (
        InvalidAuth,
        validate_input,
    )

    # Mock ONVIF camera
    camera_instance = MagicMock()
    mock_onvif.return_value = camera_instance

    device_service = AsyncMock()
    device_info = MagicMock()
    device_info.Manufacturer = "SomeOtherManufacturer"
    device_info.Model = "SomeOtherModel"
    device_service.GetDeviceInformation.return_value = device_info
    camera_instance.create_device_service.return_value = device_service

    # Test data
    data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "port": 554,
    }

    # Mock hass
    hass = MagicMock()

    with pytest.raises(InvalidAuth):
        await validate_input(hass, data)


@patch("onvif.ONVIFCamera")
async def test_validate_input_connection_error(mock_onvif):
    """Test validation with connection error."""
    from homeassistant.components.thingino.config_flow import (
        CannotConnect,
        validate_input,
    )

    # Mock ONVIF camera to raise exception
    mock_onvif.side_effect = Exception("Connection failed")

    # Test data
    data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "port": 554,
    }

    # Mock hass
    hass = MagicMock()

    with pytest.raises(CannotConnect):
        await validate_input(hass, data)


def test_camera_stream_source():
    """Test camera stream source generation."""
    from homeassistant.components.thingino.camera import ThinginoCamera

    from tests.common import MockConfigEntry

    # Create mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "admin",
            "password": "secret",
            "port": 554,
        },
    )
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "admin",
        "password": "secret",
        "port": 554,
    }

    with patch("onvif.ONVIFCamera"):
        camera = ThinginoCamera(config_entry)
        stream_source = camera.stream_source
        assert stream_source == "rtsp://admin:secret@192.168.1.100:554/ch0"


def test_camera_stream_source_no_password():
    """Test camera stream source generation without password."""
    from homeassistant.components.thingino.camera import ThinginoCamera

    from tests.common import MockConfigEntry

    # Create mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "thingino",
            "password": "",
            "port": 554,
        },
    )
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "port": 554,
    }

    with patch("onvif.ONVIFCamera"):
        camera = ThinginoCamera(config_entry)
        stream_source = camera.stream_source
        assert stream_source == "rtsp://thingino:@192.168.1.100:554/ch0"
