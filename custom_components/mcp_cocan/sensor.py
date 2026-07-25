"""Sensor platform for MCP Device.

Config-driven: creates sensor entities based on the user's entity config.
Each sensor config specifies poll_tool, field, and optional conversions.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITIES, DOMAIN, SENSOR_DEVICE_CLASSES, SENSOR_STATE_CLASSES
from .coordinator import McpDeviceCoordinator
from .entity import McpDeviceEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MCP Device sensor entities from config."""
    coordinator: McpDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_config: list[dict] = entry.data.get(CONF_ENTITIES, [])

    entities: list[SensorEntity] = []
    for config in entities_config:
        if config.get("type") == "sensor":
            entities.append(McpConfigSensor(coordinator, config))

    if entities:
        _LOGGER.info("Creating %d sensor entities", len(entities))
        async_add_entities(entities)


class McpConfigSensor(McpDeviceEntity, SensorEntity):
    """A sensor entity driven by user configuration.

    Config fields:
      - poll_tool: MCP tool to call for data
      - field: JSON path to extract value (e.g. "ports.0.vout_mv")
      - device_class: HA sensor device class (power, voltage, current, etc.)
      - state_class: measurement, total, total_increasing
      - unit: Unit of measurement (W, V, A, etc.)
      - divide_by: Divide raw value (e.g. 1000 for mV→V)
      - multiply_by: Multiply raw value
      - round_digits: Round to N decimal places
      - value_map: Map raw values to display strings
      - icon: MDI icon name
    """

    def __init__(self, coordinator: McpDeviceCoordinator, config: dict) -> None:
        super().__init__(coordinator, config)

        # Set device class
        dc_str = config.get("device_class")
        if dc_str and dc_str in SENSOR_DEVICE_CLASSES:
            self._attr_device_class = SensorDeviceClass(
                SENSOR_DEVICE_CLASSES[dc_str]
            )

        # Set state class
        sc_str = config.get("state_class")
        if sc_str and sc_str in SENSOR_STATE_CLASSES:
            self._attr_state_class = SensorStateClass(
                SENSOR_STATE_CLASSES[sc_str]
            )

        # Set unit
        self._attr_native_unit_of_measurement = config.get("unit")

        # For enum sensors, set options
        if config.get("options") and not dc_str:
            self._attr_options = config["options"]

    @property
    def native_value(self) -> Any:
        """Return the sensor value, extracted and converted from poll data.

        Security: if a device_class implies numeric (power, voltage, current,
        etc.), the value is validated as numeric before returning. A
        compromised MCP server cannot inject arbitrary strings into numeric
        sensor states.
        """
        value = self._get_converted_value()

        # For numeric device classes, reject non-numeric values to prevent
        # type confusion attacks from a compromised MCP server
        numeric_classes = (
            "power", "voltage", "current", "temperature", "energy",
            "humidity", "pressure", "battery", "frequency", "signal_strength",
            "data_rate", "data_size", "distance", "weight", "volume",
            "irradiance", "atmospheric_pressure", "monetary",
        )
        dc = self._config.get("device_class")
        if dc in numeric_classes and value is not None:
            if not isinstance(value, (int, float)):
                _LOGGER.warning(
                    "Sensor %s: expected numeric value for device_class=%s, got %s",
                    self._attr_name, dc, type(value).__name__,
                )
                return None

        # Sanitise string values for non-numeric sensors
        if isinstance(value, str):
            # Strip control characters
            value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
            # Truncate
            if len(value) > 255:
                value = value[:255]

        return value
