"""Common fixtures for the Thingino tests."""

import pytest

from homeassistant.components.thingino.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from tests.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations defined in the test dir."""


@pytest.fixture
def config_entry():
    """Create a config entry for testing with real data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
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
    entry.runtime_data = {
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
    return entry


@pytest.fixture
def config_entry_no_mqtt():
    """Create a config entry without MQTT for testing with real data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
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
    entry.runtime_data = {
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
    return entry
