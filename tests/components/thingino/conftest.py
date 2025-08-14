"""Common fixtures for the Thingino tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.thingino.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from tests.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    return


@pytest.fixture(autouse=True)
def mock_zeroconf():
    """Mock zeroconf to prevent socket usage in tests."""
    with patch("homeassistant.components.zeroconf.async_setup", return_value=True):
        yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.thingino.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_onvif_camera():
    """Mock ONVIFCamera for testing."""
    with (
        patch("onvif.ONVIFCamera") as mock_onvif,
    ):
        # Mock camera instance
        camera_instance = MagicMock()
        mock_onvif.return_value = camera_instance

        # Mock device service
        device_service = AsyncMock()
        device_info = MagicMock()
        device_info.Manufacturer = "Ingenic"
        device_info.Model = "Thingino Camera"
        device_service.GetDeviceInformation.return_value = device_info
        camera_instance.create_device_service.return_value = device_service

        # Mock media service for camera snapshots
        media_service = AsyncMock()
        profiles = [MagicMock()]
        profiles[0].token = "profile_token"
        media_service.GetProfiles.return_value = profiles

        snapshot_uri = MagicMock()
        snapshot_uri.Uri = "http://192.168.1.100/snapshot.jpg"
        media_service.GetSnapshotUri.return_value = snapshot_uri
        camera_instance.create_media_service.return_value = media_service

        yield mock_onvif


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry for testing."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
            "mqtt_host": "192.168.1.1",
            "mqtt_username": "mqtt_user",
            "mqtt_password": "mqtt_pass",
        },
        unique_id="thingino_192_168_1_100",
    )


@pytest.fixture
def mock_config_entry_no_mqtt():
    """Create a mock config entry without MQTT for testing."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
            "mqtt_host": "",
            "mqtt_username": "",
            "mqtt_password": "",
        },
        unique_id="thingino_192_168_1_100",
    )
