"""Test the Thingino binary sensor platform."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.thingino.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry


async def test_binary_sensor_setup_with_onvif_events_supported(
    hass: HomeAssistant,
) -> None:
    """Test binary sensor setup when ONVIF events are supported."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "thingino",
            "password": "",
            "port": 554,
            "serial": "aabbccddeeff",
            "camera_name": "Thingino Camera",
            "manufacturer": "Thingino",
            "model": "Camera",
            "firmware": "1.2.3",
        },
        unique_id="thingino_aabbccddeeff",
    )
    # Set runtime_data directly for testing
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "serial": "aabbccddeeff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
        "firmware_version": "1.2.3",
    }
    config_entry.add_to_hass(hass)

    # Mock ONVIF capabilities response that includes Events service
    mock_capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
    <soap:Body>
        <tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
            <tds:Capabilities>
                <tt:Events xmlns:tt="http://www.onvif.org/ver10/schema">
                    <tt:XAddr>http://192.168.1.100:80/onvif/events_service</tt:XAddr>
                </tt:Events>
            </tds:Capabilities>
        </tds:GetCapabilitiesResponse>
    </soap:Body>
</soap:Envelope>"""

    # Mock the main integration setup to avoid ONVIF library calls
    mock_device_info = type(
        "MockDeviceInfo",
        (),
        {
            "Manufacturer": "Thingino",
            "Model": "Camera",
            "FirmwareVersion": "1.2.3",
            "HardwareId": "T31X_GC4653",
            "SerialNumber": "aabbccddeeff",
        },
    )()

    with (
        patch("homeassistant.components.thingino.ONVIFCamera") as mock_onvif_camera,
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.make_request",
            return_value=mock_capabilities_xml,
        ),
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.parse_capabilities",
            return_value={"Events": "http://192.168.1.100:80/onvif/events_service"},
        ),
    ):
        # Mock the ONVIF camera and device service
        mock_camera_instance = mock_onvif_camera.return_value
        mock_camera_instance.create_devicemgmt_service = AsyncMock()
        mock_device_service = (
            mock_camera_instance.create_devicemgmt_service.return_value
        )
        mock_device_service.GetDeviceInformation = AsyncMock(
            return_value=mock_device_info
        )
        mock_camera_instance.close = AsyncMock()

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    # Check that binary sensor entity is created
    entity_registry = er.async_get(hass)
    sensor_entity = entity_registry.async_get("binary_sensor.thingino_camera_motion")

    assert sensor_entity is not None
    assert sensor_entity.domain == "binary_sensor"
    assert sensor_entity.platform == DOMAIN


async def test_binary_sensor_setup_without_onvif_events(hass: HomeAssistant) -> None:
    """Test binary sensor setup when ONVIF events are not supported."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "thingino",
            "password": "",
            "port": 554,
            "serial": "aabbccddeeff",
            "camera_name": "Thingino Camera",
            "manufacturer": "Thingino",
            "model": "Camera",
            "firmware": "1.2.3",
        },
        unique_id="thingino_aabbccddeeff",
    )
    # Set runtime_data directly for testing
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "serial": "aabbccddeeff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
        "firmware_version": "1.2.3",
    }
    config_entry.add_to_hass(hass)

    # Mock ONVIF capabilities response that does NOT include Events service
    mock_capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
    <soap:Body>
        <tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
            <tds:Capabilities>
                <tt:Media xmlns:tt="http://www.onvif.org/ver10/schema">
                    <tt:XAddr>http://192.168.1.100:80/onvif/media_service</tt:XAddr>
                </tt:Media>
            </tds:Capabilities>
        </tds:GetCapabilitiesResponse>
    </soap:Body>
</soap:Envelope>"""

    # Mock the main integration setup to avoid ONVIF library calls
    mock_device_info = type(
        "MockDeviceInfo",
        (),
        {
            "Manufacturer": "Thingino",
            "Model": "Camera",
            "FirmwareVersion": "1.2.3",
            "HardwareId": "T31X_GC4653",
            "SerialNumber": "aabbccddeeff",
        },
    )()

    with (
        patch("homeassistant.components.thingino.ONVIFCamera") as mock_onvif_camera,
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.make_request",
            return_value=mock_capabilities_xml,
        ),
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.parse_capabilities",
            return_value={},  # No Events service
        ),
    ):
        # Mock the ONVIF camera and device service
        mock_camera_instance = mock_onvif_camera.return_value
        mock_camera_instance.create_devicemgmt_service = AsyncMock()
        mock_device_service = (
            mock_camera_instance.create_devicemgmt_service.return_value
        )
        mock_device_service.GetDeviceInformation = AsyncMock(
            return_value=mock_device_info
        )
        mock_camera_instance.close = AsyncMock()

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    # Check that binary sensor entity is created but unavailable
    entity_registry = er.async_get(hass)
    sensor_entity = entity_registry.async_get("binary_sensor.thingino_camera_motion")

    assert sensor_entity is not None
    assert sensor_entity.domain == "binary_sensor"
    assert sensor_entity.platform == DOMAIN

    # Check that the entity is unavailable since events are not supported
    state = hass.states.get("binary_sensor.thingino_camera_motion")
    assert state is not None
    assert state.state == "unavailable"


async def test_binary_sensor_device_class(hass: HomeAssistant) -> None:
    """Test binary sensor device class."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.1.100",
            "username": "thingino",
            "password": "",
            "port": 554,
            "serial": "aabbccddeeff",
            "camera_name": "Thingino Camera",
            "manufacturer": "Thingino",
            "model": "Camera",
            "firmware": "1.2.3",
        },
        unique_id="thingino_aabbccddeeff",
    )
    # Set runtime_data directly for testing
    config_entry.runtime_data = {
        "host": "192.168.1.100",
        "username": "thingino",
        "password": "",
        "serial": "aabbccddeeff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
        "firmware_version": "1.2.3",
    }
    config_entry.add_to_hass(hass)

    # Mock ONVIF capabilities response that includes Events service
    mock_capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
    <soap:Body>
        <tds:GetCapabilitiesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
            <tds:Capabilities>
                <tt:Events xmlns:tt="http://www.onvif.org/ver10/schema">
                    <tt:XAddr>http://192.168.1.100:80/onvif/events_service</tt:XAddr>
                </tt:Events>
            </tds:Capabilities>
        </tds:GetCapabilitiesResponse>
    </soap:Body>
</soap:Envelope>"""

    # Mock the main integration setup to avoid ONVIF library calls
    mock_device_info = type(
        "MockDeviceInfo",
        (),
        {
            "Manufacturer": "Thingino",
            "Model": "Camera",
            "FirmwareVersion": "1.2.3",
            "HardwareId": "T31X_GC4653",
            "SerialNumber": "aabbccddeeff",
        },
    )()

    with (
        patch("homeassistant.components.thingino.ONVIFCamera") as mock_onvif_camera,
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.make_request",
            return_value=mock_capabilities_xml,
        ),
        patch(
            "homeassistant.components.thingino.onvif_client.ThinginoOnvifClient.parse_capabilities",
            return_value={"Events": "http://192.168.1.100:80/onvif/events_service"},
        ),
    ):
        # Mock the ONVIF camera and device service
        mock_camera_instance = mock_onvif_camera.return_value
        mock_camera_instance.create_devicemgmt_service = AsyncMock()
        mock_device_service = (
            mock_camera_instance.create_devicemgmt_service.return_value
        )
        mock_device_service.GetDeviceInformation = AsyncMock(
            return_value=mock_device_info
        )
        mock_camera_instance.close = AsyncMock()

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.thingino_camera_motion")
    assert state is not None
    assert state.attributes.get("device_class") == BinarySensorDeviceClass.MOTION
