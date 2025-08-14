"""Test the Thingino integration initialization."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.thingino.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_entry_success(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test successful setup of config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.config.components


async def test_setup_entry_connection_error(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Test setup fails when cannot connect to camera."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.ONVIFCamera") as mock_onvif:
        mock_onvif.side_effect = Exception("Connection failed")

        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_onvif_error(hass: HomeAssistant, mock_config_entry) -> None:
    """Test setup fails when ONVIF service fails."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.thingino.ONVIFCamera") as mock_onvif:
        camera_instance = AsyncMock()
        mock_onvif.return_value = camera_instance

        device_service = AsyncMock()
        device_service.GetDeviceInformation.side_effect = Exception("ONVIF error")
        camera_instance.create_device_service.return_value = device_service

        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test unloading the config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_runtime_data_setup(
    hass: HomeAssistant, mock_config_entry, mock_onvif_camera
) -> None:
    """Test that runtime data is properly set up."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that runtime data is set
    assert mock_config_entry.runtime_data is not None
    runtime_data = mock_config_entry.runtime_data

    assert runtime_data["host"] == "192.168.1.100"
    assert runtime_data["username"] == "thingino"
    assert runtime_data["password"] == ""
    assert runtime_data["port"] == 554
    assert runtime_data["mqtt_host"] == "192.168.1.1"
    assert runtime_data["mqtt_username"] == "mqtt_user"
    assert runtime_data["mqtt_password"] == "mqtt_pass"


async def test_setup_entry_no_mqtt(
    hass: HomeAssistant, mock_config_entry_no_mqtt, mock_onvif_camera
) -> None:
    """Test setup with no MQTT configuration."""
    mock_config_entry_no_mqtt.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry_no_mqtt.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry_no_mqtt.state is ConfigEntryState.LOADED

    # Check runtime data for empty MQTT fields
    runtime_data = mock_config_entry_no_mqtt.runtime_data
    assert runtime_data["mqtt_host"] == ""
    assert runtime_data["mqtt_username"] == ""
    assert runtime_data["mqtt_password"] == ""
