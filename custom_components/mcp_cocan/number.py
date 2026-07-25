"""Number platform for MCP Device.

Config-driven: creates number entities based on user config.

Special case — power allocation:
  When set_tool is "set_port_power_allocation", entities share a cached
  state held in the coordinator. Changing one port's value reads the
  current 5-port array, updates that single slot, checks the 160W total
  budget, and sends the full array to the MCP server atomically.

Config fields for a number:
  - set_tool: MCP tool to call when user sets a value
  - set_arg_name: Argument name to pass the value (e.g. "power_allocation")
  - poll_tool: MCP tool to read current value (optional)
  - field: JSON path to read current value (optional)
  - min: Minimum value (default 0)
  - max: Maximum value (required)
  - step: Step size (default 1)
  - unit: Unit of measurement (e.g. "W")
  - divide_by: Divide raw poll value (e.g. 1000 for mW→W)
  - multiply_by: Multiply raw poll value
  - round_digits: Round to N decimal places
  - port_index: (power allocation only) 1-indexed port this entity controls
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITIES, DOMAIN
from .coordinator import McpDeviceCoordinator
from .entity import McpDeviceEntity

_LOGGER = logging.getLogger(__name__)

# Tool name used for per-port power allocation
POWER_ALLOCATION_TOOL = "set_port_power_allocation"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MCP Device number entities from config."""
    coordinator: McpDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_config: list[dict] = entry.data.get(CONF_ENTITIES, [])

    entities: list[NumberEntity] = []
    for config in entities_config:
        if config.get("type") == "number":
            if config.get("set_tool") == POWER_ALLOCATION_TOOL:
                entities.append(McpPowerAllocationNumber(coordinator, config))
            else:
                entities.append(McpConfigNumber(coordinator, config))

    if entities:
        _LOGGER.info("Creating %d number entities", len(entities))
        async_add_entities(entities)


class McpConfigNumber(McpDeviceEntity, NumberEntity):
    """A standard number entity driven by user configuration."""

    def __init__(self, coordinator: McpDeviceCoordinator, config: dict) -> None:
        super().__init__(coordinator, config)

        self._attr_native_min_value = config.get("min", 0)
        self._attr_native_max_value = config.get("max", 100)
        self._attr_native_step = config.get("step", 1)
        self._attr_native_unit_of_measurement = config.get("unit")
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        """Return the current number value from poll data.

        Security: value is forcibly cast to float. A compromised MCP
        server cannot inject non-numeric values (strings, dicts, lists)
        into a number entity's state.
        """
        value = self._get_converted_value()
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Number %s: received non-numeric value %r from MCP server",
                self._attr_name, value,
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value via MCP tool."""
        tool = self._config.get("set_tool")
        arg_name = self._config.get("set_arg_name", "value")

        if not tool:
            _LOGGER.warning("Number %s has no set_tool", self._attr_name)
            return

        # Convert to int if step is integer
        if isinstance(self._attr_native_step, int) and self._attr_native_step >= 1:
            value = int(value)

        _LOGGER.info(
            "Setting %s to %s (%s=%s)",
            self._attr_name,
            value,
            arg_name,
            value,
        )
        try:
            await self.coordinator.async_call_tool(tool, {arg_name: value})
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to set %s: %s", self._attr_name, exc)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class McpPowerAllocationNumber(McpDeviceEntity, NumberEntity):
    """A number entity for per-port power allocation.

    Shares a cached 5-port power array in the coordinator. Changing this
    entity updates one slot and pushes the full array atomically via
    ``set_port_power_allocation``.
    """

    def __init__(self, coordinator: McpDeviceCoordinator, config: dict) -> None:
        super().__init__(coordinator, config)

        self._port_index = config.get("port_index", 0)
        self._attr_native_min_value = config.get("min", 0)
        self._attr_native_max_value = config.get("max", 140)
        self._attr_native_step = config.get("step", 1)
        self._attr_native_unit_of_measurement = config.get("unit", "W")
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        """Return the cached power allocation for this port."""
        val = self.coordinator.get_power_allocation(self._port_index)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set this port's allocation and push the full array."""
        value = int(value)
        ok = await self.coordinator.async_set_power_allocation(
            self._port_index, value
        )
        if not ok:
            _LOGGER.warning(
                "Power allocation for %s rejected (total would exceed 160W or "
                "MCP server refused)",
                self._attr_name,
            )
            # Don't raise — HA UI will show the slider snapping back
            # because native_value still reads the old cached value.
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
