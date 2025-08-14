"""Test the Thingino config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.components.thingino.config_flow import CannotConnect, InvalidAuth
from homeassistant.components.thingino.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


async def test_form(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_onvif_camera
) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thingino Camera 192.168.1.100"
    assert result["data"] == {
        CONF_HOST: "192.168.1.100",
        CONF_USERNAME: "thingino",
        CONF_PASSWORD: "",
        CONF_PORT: 554,
        "mqtt_host": "",
        "mqtt_username": "",
        "mqtt_password": "",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.thingino.config_flow.validate_input",
        side_effect=InvalidAuth,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.100",
                CONF_USERNAME: "wrong",
                CONF_PASSWORD: "wrong",
                CONF_PORT: 554,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    # Test recovery
    with patch(
        "homeassistant.components.thingino.config_flow.validate_input",
        return_value={"title": "Thingino Camera 192.168.1.100"},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.100",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "",
                CONF_PORT: 554,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thingino Camera 192.168.1.100"


async def test_form_cannot_connect(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.thingino.config_flow.validate_input",
        side_effect=CannotConnect,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.100",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "",
                CONF_PORT: 554,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # Test recovery
    with patch(
        "homeassistant.components.thingino.config_flow.validate_input",
        return_value={"title": "Thingino Camera 192.168.1.100"},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.100",
                CONF_USERNAME: "thingino",
                CONF_PASSWORD: "",
                CONF_PORT: 554,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thingino Camera 192.168.1.100"


async def test_duplicate_entry(hass: HomeAssistant, mock_onvif_camera) -> None:
    """Test that duplicate entries are handled."""
    # Create first entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.1.100", CONF_USERNAME: "thingino"},
        unique_id="thingino_192_168_1_100",
    )
    entry.add_to_hass(hass)

    # Try to create duplicate
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_discovery(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_onvif_camera
) -> None:
    """Test zeroconf discovery flow."""
    discovery_info = MagicMock()
    discovery_info.host = "192.168.1.100"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=discovery_info,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.100",
            CONF_USERNAME: "thingino",
            CONF_PASSWORD: "",
            CONF_PORT: 554,
            "mqtt_host": "",
            "mqtt_username": "",
            "mqtt_password": "",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thingino Camera 192.168.1.100"
