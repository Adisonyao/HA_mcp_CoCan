"""Data update coordinator for MCP Device.

Data-driven: collects all unique poll_tool names from entity configs,
calls each tool once per cycle, and stores results keyed by tool name.
Entities then extract their values from this shared cache.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, TransportType
from .mcp_client import call_mcp_tool, parse_tool_result

_LOGGER = logging.getLogger(__name__)

# Max total power budget for CoCan Pro (from get_machine_facts)
MAX_TOTAL_POWER_BUDGET = 160


class McpDeviceCoordinator(DataUpdateCoordinator):
    """Coordinator that polls an MCP-connected device based on entity configs."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        transport: TransportType,
        token: str | None,
        device_name: str,
        update_interval: int,
        entities_config: list[dict[str, Any]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_name}",
            update_interval=timedelta(seconds=update_interval),
        )
        self._url = url
        self._transport = transport
        self._token = token
        self._device_name = device_name
        self._entities_config = entities_config
        self.device_info: dict[str, Any] = {}

        # Power allocation state — shared across 5 port power number entities.
        # Mutable list that each port entity reads and the coordinator updates.
        # Index 0 = Port A, 1-4 = Port C1-C4.
        self._power_allocations: list[int] = [0, 0, 0, 0, 0]

        # Charging strategy cache — shared by the Charging Strategy select.
        # This is a write-only control; the MCP server has no read API.
        # The value is set when the user picks an option and persisted here.
        self._charging_strategy: int | None = None

        # Collect unique poll tools from entity configs
        self._poll_tools: list[str] = []
        for entity in entities_config:
            tool = entity.get("poll_tool")
            if tool and tool not in self._poll_tools:
                self._poll_tools.append(tool)

        _LOGGER.info(
            "Coordinator initialised with %d entities, %d poll tools: %s",
            len(entities_config),
            len(self._poll_tools),
            self._poll_tools,
        )

    @property
    def url(self) -> str:
        """Return the MCP server URL."""
        return self._url

    @property
    def transport(self) -> TransportType:
        """Return the transport type."""
        return self._transport

    @property
    def device_name(self) -> str:
        """Return the device name."""
        return self._device_name

    @property
    def entities_config(self) -> list[dict[str, Any]]:
        """Return the entity configurations."""
        return self._entities_config

    def get_power_allocation(self, port_index: int) -> int | None:
        """Return the cached power allocation for a port (1-indexed)."""
        if 1 <= port_index <= 5:
            return self._power_allocations[port_index - 1]
        return None

    def get_total_allocated_power(self) -> int:
        """Return the sum of all port power allocations."""
        return sum(self._power_allocations)

    @property
    def charging_strategy(self) -> int | None:
        """Return the cached charging strategy value (write-only control)."""
        return self._charging_strategy

    def set_charging_strategy(self, value: int) -> None:
        """Cache the charging strategy after a successful set."""
        self._charging_strategy = value

    def _clamp_allocation(self, port_index: int, value: int) -> int:
        """Clamp a single port allocation to its per-port max.

        Port A (index 1) = 60W max.
        Ports C1-C4 (index 2-5) = 140W max.
        """
        per_port_max = 60 if port_index == 1 else 140
        return max(0, min(value, per_port_max))

    async def async_set_power_allocation(
        self, port_index: int, value: int
    ) -> bool:
        """Set power allocation for a single port and push the full array.

        Args:
            port_index: 1-indexed port (1=A, 2=C1, 3=C2, 4=C3, 5=C4).
            value: Watts to allocate to this port.

        Returns:
            True if the MCP server accepted the change, False if rejected
            or the new total would exceed the 160W budget.
        """
        if not 1 <= port_index <= 5:
            _LOGGER.warning("Invalid port index %d (must be 1-5)", port_index)
            return False

        # Clamp to per-port max
        clamped = self._clamp_allocation(port_index, int(value))

        # Copy current allocations and update the target port
        new_allocations = list(self._power_allocations)
        new_allocations[port_index - 1] = clamped

        # Check total budget
        new_total = sum(new_allocations)
        if new_total > MAX_TOTAL_POWER_BUDGET:
            _LOGGER.warning(
                "Power allocation rejected: total %dW exceeds %dW budget "
                "(port %d -> %dW)",
                new_total, MAX_TOTAL_POWER_BUDGET, port_index, clamped,
            )
            return False

        _LOGGER.info(
            "Setting power allocation: port %d = %dW, total = %dW / %dW",
            port_index, clamped, new_total, MAX_TOTAL_POWER_BUDGET,
        )

        try:
            raw = await call_mcp_tool(
                self._url,
                self._transport,
                "set_port_power_allocation",
                {"power_allocation": new_allocations},
                token=self._token,
            )
            parsed = parse_tool_result(raw)
            _LOGGER.debug("set_port_power_allocation response: %s", parsed)

            # Update cached state on success
            self._power_allocations = new_allocations

            # Trigger a refresh so other entities pick up the new state
            await self.async_request_refresh()
            return True
        except Exception as exc:
            _LOGGER.error(
                "Failed to set power allocation for port %d: %s",
                port_index, type(exc).__name__,
            )
            return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the MCP server.

        Calls each unique poll_tool once, stores results in a dict keyed
        by tool name. Entities extract their values using JSON paths.
        """
        data: dict[str, Any] = {}

        try:
            # Always fetch device_info and machine_facts for device registry
            # Merge both into device_info so entity.py can read manufacturer,
            # model, and firmware version from a single source.
            if not self.device_info:
                try:
                    raw_info = await call_mcp_tool(
                        self._url,
                        self._transport,
                        "get_device_info",
                        token=self._token,
                    )
                    self.device_info = parse_tool_result(raw_info) or {}
                except Exception:
                    _LOGGER.debug("Could not fetch device_info")
                    self.device_info = {}

            try:
                raw_facts = await call_mcp_tool(
                    self._url,
                    self._transport,
                    "get_machine_facts",
                    token=self._token,
                )
                facts = parse_tool_result(raw_facts) or {}
                # Merge machine_facts into device_info (prefer device_info values)
                for key, value in facts.items():
                    if key not in self.device_info or self.device_info[key] is None:
                        self.device_info[key] = value
            except Exception:
                _LOGGER.debug("Could not fetch machine_facts")

            # Call each unique poll tool
            for tool_name in self._poll_tools:
                if tool_name in data:
                    continue  # Already fetched (e.g. get_device_info)
                try:
                    raw = await call_mcp_tool(
                        self._url,
                        self._transport,
                        tool_name,
                        token=self._token,
                    )
                    parsed = parse_tool_result(raw)
                    data[tool_name] = parsed if parsed is not None else {}
                except Exception as exc:
                    _LOGGER.warning("Failed to call tool %s: %s", tool_name, type(exc).__name__)
                    data[tool_name] = {}

            _LOGGER.debug("Coordinator update success: %d tools polled", len(data))
            return data

        except Exception as exc:
            _LOGGER.error("Coordinator update failed: %s", type(exc).__name__)
            raise UpdateFailed("Error communicating with MCP server") from exc

    def get_entity_value(self, entity_config: dict[str, Any]) -> Any:
        """Extract a value for an entity from the cached poll data.

        Uses the entity's ``field`` JSON path to navigate the poll tool's
        result. Handles bitmask fields (for switches) and value maps.
        """
        poll_tool = entity_config.get("poll_tool")
        field = entity_config.get("field")

        if not poll_tool or not field:
            return None

        # Get the raw data from this entity's poll tool
        raw = self.data.get(poll_tool) if self.data else None
        if raw is None:
            return None

        # Handle bitmask fields (used by switches)
        if entity_config.get("field_is_bitmask"):
            bit = entity_config.get("bitmask_bit", 0)
            try:
                # The field might be a direct key in the result
                bitmask = self._extract_field(raw, field)
                if bitmask is not None:
                    return bool(int(bitmask) & (1 << bit))
            except (ValueError, TypeError):
                return None

        # Normal field extraction
        return self._extract_field(raw, field)

    def _extract_field(self, data: Any, field: str) -> Any:
        """Extract a value using a dot-separated JSON path."""
        from .utils import resolve_path

        return resolve_path(data, field)

    async def async_call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call an MCP tool and trigger a refresh.

        Used by switch/select/number entities when the user issues a command.
        """
        raw = await call_mcp_tool(
            self._url,
            self._transport,
            tool_name,
            arguments,
            token=self._token,
        )
        parsed = parse_tool_result(raw)
        # Force a refresh so entities pick up new state
        await self.async_request_refresh()
        return parsed
