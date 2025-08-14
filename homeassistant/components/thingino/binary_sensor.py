"""Thingino sensor platform."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThinginoConfigEntry
from .const import CONF_MQTT_HOST, DOMAIN, MQTT_TOPIC_MOTION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThinginoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Thingino sensor platform."""
    config = entry.runtime_data
    if config[CONF_MQTT_HOST]:
        async_add_entities([ThinginoMotionSensor(entry)])


class ThinginoMotionSensor(BinarySensorEntity):
    """Representation of a Thingino motion sensor."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, entry: ThinginoConfigEntry) -> None:
        """Initialize the Thingino motion sensor."""
        self._entry = entry
        config = entry.runtime_data
        self._host = config["host"]
        self._mqtt_host = config[CONF_MQTT_HOST]
        self._mqtt_username = config.get("mqtt_username")
        self._mqtt_password = config.get("mqtt_password")
        self._attr_unique_id = f"thingino_motion_{self._host.replace('.', '_')}"
        self._attr_name = "Motion"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            name=f"Thingino Camera {self._host}",
            manufacturer="Thingino",
            model="Camera",
            configuration_url=f"http://{self._host}",
        )
        self._attr_available = False
        self._mqtt_client = None
        self._topic = MQTT_TOPIC_MOTION.format(self._host)

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT events."""
        await super().async_added_to_hass()
        self.async_on_remove(await self._async_setup_mqtt())

    async def _async_setup_mqtt(self) -> callable:
        """Set up MQTT client and subscription."""
        try:
            import aiomqtt
        except ImportError:
            _LOGGER.error("aiomqtt is not installed. Install with: pip install aiomqtt")
            return lambda: None

        async def mqtt_listener():
            """Listen for MQTT messages."""
            while True:
                try:
                    client_kwargs = {
                        "hostname": self._mqtt_host,
                        "port": 1883,
                        "keepalive": 60,
                    }
                    if self._mqtt_username and self._mqtt_password:
                        client_kwargs.update(
                            {
                                "username": self._mqtt_username,
                                "password": self._mqtt_password,
                            }
                        )

                    async with aiomqtt.Client(**client_kwargs) as client:
                        _LOGGER.info("Connected to MQTT broker %s", self._mqtt_host)
                        self._attr_available = True
                        self.async_write_ha_state()

                        await client.subscribe(self._topic)
                        async for message in client.messages:
                            await self._async_handle_mqtt_message(message)

                except Exception as exc:
                    _LOGGER.warning("MQTT connection failed: %s", exc)
                    self._attr_available = False
                    self.async_write_ha_state()
                    await asyncio.sleep(30)  # Retry after 30 seconds

        task = self.hass.async_create_task(mqtt_listener())

        def cleanup():
            task.cancel()

        return cleanup

    @callback
    async def _async_handle_mqtt_message(self, message) -> None:
        """Handle incoming MQTT messages."""
        try:
            payload = message.payload.decode()
            if payload == "start":
                self._attr_is_on = True
            elif payload == "stop":
                self._attr_is_on = False
            else:
                _LOGGER.warning("Unexpected MQTT payload: %s", payload)
                return

            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Failed to process MQTT message: %s", exc)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "mqtt_topic": self._topic,
            "mqtt_host": self._mqtt_host,
        }
