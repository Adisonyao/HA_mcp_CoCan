"""Switch platform for MCP Device.

Config-driven: creates switch entities based on user config.

Config fields for a switch:
  - on_tool: MCP tool to turn on
  - on_args: Arguments dict for on_tool
  - off_tool: MCP tool to turn off
  - off_args: Arguments dict for off_tool
  - poll_tool: MCP tool to read state (optional)
  - field: JSON path to read state value (optional)
  - field_is_bitmask: If true, treat field as a bitmask and use bitmask_bit
  - bitmask_bit: Which bit to check in the bitmask (0-indexed)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITIES, DOMAIN
from .coordinator import McpDeviceCoordinator
from .entity import McpDeviceEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MCP Device switch entities from config."""
    coordinator: McpDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_config: list[dict] = entry.data.get(CONF_ENTITIES, [])

    entities: list[SwitchEntity] = []
    for config in entities_config:
        if config.get("type") == "switch":
            entities.append(McpConfigSwitch(coordinator, config))

    if entities:
        _LOGGER.info("Creating %d switch entities", len(entities))
        async_add_entities(entities)


class McpConfigSwitch(McpDeviceEntity, SwitchEntity):
    """A switch entity driven by user configuration."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the switch is on."""
        if not self._config.get("poll_tool"):
            return None

        # Get raw value from coordinator (handles bitmask extraction)
        raw = self._get_raw_value()
        if raw is None:
            return None

        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw > 0
        if isinstance(raw, str):
            return raw.lower() in ("on", "true", "1", "yes", "charging")
        return bool(raw)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on via MCP tool."""
        tool = self._config.get("on_tool")
        args = self._config.get("on_args", {})
        if not tool:
            _LOGGER.warning("Switch %s has no on_tool", self._attr_name)
            return
        _LOGGER.info("Turning on %s: %s(%s)", self._attr_name, tool, args)
        try:
            await self.coordinator.async_call_tool(tool, args)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to turn on %s: %s", self._attr_name, exc)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off via MCP tool."""
        tool = self._config.get("off_tool")
        args = self._config.get("off_args", {})
        if not tool:
            _LOGGER.warning("Switch %s has no off_tool", self._attr_name)
            return
        _LOGGER.info("Turning off %s: %s(%s)", self._attr_name, tool, args)
        try:
            await self.coordinator.async_call_tool(tool, args)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to turn off %s: %s", self._attr_name, exc)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
