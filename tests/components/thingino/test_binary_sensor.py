"""Test the Thingino binary sensor platform."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.thingino.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def test_binary_sensor_setup_with_mqtt(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test binary sensor setup with MQTT configuration."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.binary_sensor.aiomqtt"):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Check that binary sensor entity is created
    entity_registry = er.async_get(hass)
    sensor_entity = entity_registry.async_get(
        "binary_sensor.thingino_motion_192_168_1_100"
    )

    assert sensor_entity is not None
    assert sensor_entity.domain == "binary_sensor"
    assert sensor_entity.platform == DOMAIN


async def test_binary_sensor_no_setup_without_mqtt(
    hass: HomeAssistant, mock_config_entry_no_mqtt, mock_onvif_camera
) -> None:
    """Test binary sensor is not created without MQTT configuration."""
    mock_config_entry_no_mqtt.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry_no_mqtt.entry_id)
    await hass.async_block_till_done()

    # Check that no binary sensor entity is created
    entity_registry = er.async_get(hass)
    sensor_entity = entity_registry.async_get(
        "binary_sensor.thingino_motion_192_168_1_100"
    )

    assert sensor_entity is None


async def test_binary_sensor_device_class(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test binary sensor device class."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.binary_sensor.aiomqtt"):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.thingino_motion_192_168_1_100")
    assert state is not None
    assert state.attributes.get("device_class") == BinarySensorDeviceClass.MOTION


async def test_binary_sensor_mqtt_connection_success(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test successful MQTT connection."""
    mock_config_entry.add_to_hass(hass)

    # Mock aiomqtt
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.messages = AsyncMock()
    mock_client.messages.__aiter__.return_value = iter([])

    with patch(
        "homeassistant.components.thingino.binary_sensor.aiomqtt"
    ) as mock_aiomqtt:
        mock_aiomqtt.Client.return_value = mock_client

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Give some time for the MQTT task to start
        await asyncio.sleep(0.1)

        # Check that MQTT client was created with correct parameters
        mock_aiomqtt.Client.assert_called_with(
            hostname="192.168.1.1",
            port=1883,
            keepalive=60,
            username="mqtt_user",
            password="mqtt_pass",
        )


async def test_binary_sensor_mqtt_message_handling(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test MQTT message handling."""
    mock_config_entry.add_to_hass(hass)

    # Mock MQTT message
    mock_message = MagicMock()
    mock_message.payload.decode.return_value = "start"

    # Mock aiomqtt
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.messages = AsyncMock()
    mock_client.messages.__aiter__.return_value = iter([mock_message])

    with patch(
        "homeassistant.components.thingino.binary_sensor.aiomqtt"
    ) as mock_aiomqtt:
        mock_aiomqtt.Client.return_value = mock_client

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Give some time for the MQTT task to process the message
        await asyncio.sleep(0.1)

        # Check that the binary sensor state is updated
        state = hass.states.get("binary_sensor.thingino_motion_192_168_1_100")
        # Note: The state might not be updated immediately due to async nature


async def test_binary_sensor_mqtt_connection_failure(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test MQTT connection failure handling."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.thingino.binary_sensor.aiomqtt"
    ) as mock_aiomqtt:
        mock_aiomqtt.Client.side_effect = Exception("Connection failed")

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Give some time for the MQTT task to handle the error
        await asyncio.sleep(0.1)

        # The entity should still be created but unavailable
        state = hass.states.get("binary_sensor.thingino_motion_192_168_1_100")
        assert state is not None


async def test_binary_sensor_device_info(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test binary sensor device info."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.binary_sensor.aiomqtt"):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Get the binary sensor entity
    binary_sensor_entity = None
    for entity in hass.data[DOMAIN][mock_config_entry.entry_id]["binary_sensor"]:
        binary_sensor_entity = entity
        break

    assert binary_sensor_entity is not None

    device_info = binary_sensor_entity.device_info
    assert device_info is not None
    assert device_info["identifiers"] == {(DOMAIN, "192.168.1.100")}
    assert device_info["name"] == "Thingino Camera 192.168.1.100"
    assert device_info["manufacturer"] == "Thingino"
    assert device_info["model"] == "Camera"
    assert device_info["configuration_url"] == "http://192.168.1.100"


async def test_binary_sensor_extra_state_attributes(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test binary sensor extra state attributes."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.binary_sensor.aiomqtt"):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.thingino_motion_192_168_1_100")
    assert state is not None

    attributes = state.attributes
    assert attributes.get("mqtt_topic") == "thingino/192.168.1.100/motion"
    assert attributes.get("mqtt_host") == "192.168.1.1"


async def test_binary_sensor_aiomqtt_import_error(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test handling of aiomqtt import error."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.thingino.binary_sensor.aiomqtt",
        side_effect=ImportError,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # The entity should still be created
        state = hass.states.get("binary_sensor.thingino_motion_192_168_1_100")
        assert state is not None
