"""Constants for the Thingino integration."""

import os
import sys

import onvif

from homeassistant.const import Platform

DOMAIN = "thingino"

# Configuration keys
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"

# Default values
DEFAULT_USERNAME = "thingino"
DEFAULT_PASSWORD = "thingino"

# MQTT topic (adjust if your Thingino setup uses a different topic structure)
MQTT_TOPIC_MOTION = "thingino/{}/motion"


def get_wsdl_dir() -> str:
    """Find the WSDL directory for ONVIF."""
    for path in sys.path:
        wsdl_path = os.path.join(path, "wsdl")
        if os.path.exists(wsdl_path) and os.path.isfile(
            os.path.join(wsdl_path, "devicemgmt.wsdl")
        ):
            return wsdl_path
    # Fallback to onvif package directory
    return f"{os.path.dirname(onvif.__file__)}/wsdl/"


# Platforms
PLATFORMS = [Platform.BINARY_SENSOR, Platform.CAMERA]
