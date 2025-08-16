"""Test the Thingino config flow."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.components.thingino.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def mock_camera_info():
    """Mock camera info for testing."""
    return {
        "host": "192.168.1.100",
        "serial": "aabbccddeeff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
    }


async def test_form_single_ip(hass: HomeAssistant, mock_camera_info) -> None:
    """Test we can configure a single IP address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.thingino.config_flow.discover_thingino_cameras_http",
        return_value=[mock_camera_info],
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "192.168.1.100",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "thingino",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Thingino aabbccddeeff"
    assert result2["data"] == {
        CONF_HOST: "192.168.1.100",
        CONF_USERNAME: "thingino",
        CONF_PASSWORD: "thingino",
        "serial": "aabbccddeeff",
        "camera_name": "Thingino Camera",
        "manufacturer": "Thingino",
        "model": "Camera",
        "firmware": "1.2.3",
        "hardware_id": "T31X_GC4653",
    }


async def test_form_network_range(hass: HomeAssistant, mock_camera_info) -> None:
    """Test we can configure a network range for discovery."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.thingino.config_flow.discover_thingino_cameras_http",
        return_value=[mock_camera_info],
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "192.168.1.0/24",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "thingino",
            },
        )
        await hass.async_block_till_done()

    # Should go to camera selection step
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "select_cameras"


async def test_form_invalid_address(hass: HomeAssistant) -> None:
    """Test we handle invalid address input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "address": "invalid.address",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "thingino",
        },
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"address": "invalid_address"}


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.thingino.config_flow.discover_thingino_cameras_http",
        return_value=[],
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "192.168.1.100",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "thingino",
            },
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"address": "cannot_connect"}
