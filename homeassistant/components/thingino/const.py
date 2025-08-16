"""Constants for the Thingino integration."""

from dataclasses import dataclass
import os
import sys

import onvif

from homeassistant.const import Platform

DOMAIN = "thingino"

# Configuration keys

# Default values
DEFAULT_USERNAME = "thingino"
DEFAULT_PASSWORD = "thingino"
DEFAULT_NETWORK = "192.168.1.0/24"

# ONVIF XML namespaces (support both SOAP-ENV and soap prefixes)
ONVIF_NAMESPACES = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "SOAP-ENV": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}


def normalize_mac_address(mac: str) -> str:
    """Normalize MAC address by removing colons and converting to lowercase."""
    return mac.replace(":", "").lower()


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


@dataclass
class ThinginoDeviceInfo:
    """Thingino camera device information from ONVIF."""

    host: str
    mac_address: str  # Always the MAC address (from ONVIF SerialNumber)
    manufacturer: str
    model: str
    firmware_version: str
    hardware_id: str
    camera_name: str

    @property
    def normalized_mac(self) -> str:
        """MAC address normalized for use in entity IDs (lowercase, no colons)."""
        return self.mac_address.replace(":", "").lower()

    @property
    def device_identifier(self) -> str:
        """Unique device identifier for Home Assistant device registry."""
        return self.mac_address if self.mac_address != "unknown" else self.host

    @property
    def entity_id_base(self) -> str:
        """Base string for entity IDs (thingino_<normalized_mac>)."""
        return f"thingino_{self.normalized_mac}"

    @property
    def device_title(self) -> str:
        """Human-readable device title."""
        if self.mac_address != "unknown":
            return f"Thingino {self.mac_address}"
        return f"Thingino Camera ({self.host})"
