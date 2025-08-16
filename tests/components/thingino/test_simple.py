"""Simple tests for the Thingino integration."""

from homeassistant.components.thingino.binary_sensor import ThinginoMotionSensor
from homeassistant.components.thingino.camera import ThinginoCamera
from homeassistant.components.thingino.config_flow import ThinginoConfigFlow
from homeassistant.components.thingino.const import DOMAIN


async def test_domain_exists() -> None:
    """Test that the domain constant exists."""
    assert DOMAIN == "thingino"


async def test_config_flow_import() -> None:
    """Test that config flow can be imported."""
    assert ThinginoConfigFlow is not None


async def test_camera_import() -> None:
    """Test that camera module can be imported."""
    assert ThinginoCamera is not None


async def test_binary_sensor_import() -> None:
    """Test that binary sensor module can be imported."""
    assert ThinginoMotionSensor is not None
