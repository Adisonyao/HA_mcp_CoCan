"""Select platform for MCP Device.

Config-driven: creates select entities based on user config.

Config fields for a select:
  - set_tool: MCP tool to call when user selects an option
  - set_arg_name: Argument name to pass the selected value (e.g. "strategy")
  - options: List of raw values (ints or strings) that can be selected
  - option_labels: Display labels for each option (parallel array)
  - poll_tool: MCP tool to read current selection (optional)
  - field: JSON path to read current value (optional)
  - value_map: Map raw API values to internal option values (optional)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
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
    """Set up MCP Device select entities from config."""
    coordinator: McpDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_config: list[dict] = entry.data.get(CONF_ENTITIES, [])

    entities: list[SelectEntity] = []
    for config in entities_config:
        if config.get("type") == "select":
            entities.append(McpConfigSelect(coordinator, config))

    if entities:
        _LOGGER.info("Creating %d select entities", len(entities))
        async_add_entities(entities)


class McpConfigSelect(McpDeviceEntity, SelectEntity):
    """A select entity driven by user configuration."""

    def __init__(self, coordinator: McpDeviceCoordinator, config: dict) -> None:
        super().__init__(coordinator, config)

        # Build the display options list
        option_labels = config.get("option_labels")
        if option_labels:
            self._attr_options = [str(label) for label in option_labels]
        else:
            self._attr_options = [str(opt) for opt in config.get("options", [])]

    @property
    def current_option(self) -> str | None:
        """Return the current selected option as a display label.

        Supports ``__coordinator__.*`` fields for write-only controls
        (e.g. charging strategy) that have no MCP read API.

        Security: the raw value from the MCP server is only accepted
        if it matches one of the user-configured options. Unknown
        values return None rather than passing through the raw value,
        preventing a compromised server from injecting arbitrary strings.
        """
        field = self._config.get("field", "")

        # __coordinator__ field: read from coordinator internal state
        if field.startswith("__coordinator__."):
            attr_path = field[len("__coordinator__."):]
            parts = attr_path.split(".")
            obj = self.coordinator
            for part in parts:
                if obj is None:
                    return None
                obj = getattr(obj, part, None)
            raw = obj
        else:
            # Standard poll_tool + field extraction
            if not self._config.get("poll_tool"):
                return None
            raw = self._get_raw_value()

        if raw is None:
            return None

        options = self._config.get("options", [])
        option_labels = self._config.get("option_labels")

        # Try to match raw value against known options only
        for i, opt in enumerate(options):
            if str(opt) == str(raw):
                if option_labels and i < len(option_labels):
                    return str(option_labels[i])
                return str(opt)

        # Unknown value — do NOT return raw value (security)
        _LOGGER.warning(
            "Select %s: received unknown value %r, ignoring",
            self._attr_name, raw,
        )
        return None

    async def async_select_option(self, option: str) -> None:
        """Set the option via MCP tool."""
        tool = self._config.get("set_tool")
        arg_name = self._config.get("set_arg_name", "value")
        options = self._config.get("options", [])
        option_labels = self._config.get("option_labels")

        # Find the raw value for the selected label
        raw_value: Any = None
        if option_labels:
            for i, label in enumerate(option_labels):
                if str(label) == option and i < len(options):
                    raw_value = options[i]
                    break
        if raw_value is None:
            # Try matching directly against options
            for opt in options:
                if str(opt) == option:
                    raw_value = opt
                    break

        if raw_value is None:
            _LOGGER.warning("Could not find raw value for option %s", option)
            return

        _LOGGER.info(
            "Setting %s to %s (raw: %s)",
            self._attr_name,
            option,
            raw_value,
        )
        try:
            await self.coordinator.async_call_tool(
                tool, {arg_name: raw_value}
            )
            # Cache write-only values in coordinator so they survive refreshes
            field = self._config.get("field", "")
            if field == "__coordinator__.charging_strategy":
                try:
                    self.coordinator.set_charging_strategy(int(raw_value))
                except (ValueError, TypeError):
                    pass
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to set %s: %s", self._attr_name, exc)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
