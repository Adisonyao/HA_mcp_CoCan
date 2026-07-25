"""Base entity class for MCP Device entities.

Config-driven: each entity receives its configuration dict at init time
and uses it to resolve values from the coordinator's cached poll data.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import McpDeviceCoordinator
from .utils import convert_value, resolve_path

_LOGGER = logging.getLogger(__name__)

# Maximum length for string values pulled from MCP server responses.
# Prevents a compromised server from injecting huge strings into HA's
# device registry or entity state, which could cause memory exhaustion
# or UI rendering issues.
MAX_STRING_LEN = 255


def _sanitise_string(value: Any) -> str:
    """Sanitise a string from an MCP server response.

    - Truncates to MAX_STRING_LEN to prevent memory exhaustion
    - Strips control characters (except tab/newline) that could cause
      log injection or UI rendering issues
    - Returns "unknown" for None/empty values
    """
    if value is None:
        return "unknown"
    s = str(value)
    # Remove control characters except tab (\t) and newline (\n)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    # Truncate
    if len(s) > MAX_STRING_LEN:
        s = s[:MAX_STRING_LEN]
    return s if s else "unknown"


class McpDeviceEntity(CoordinatorEntity):
    """Base class for all config-driven MCP Device entities.

    Each entity is initialised with a ``config`` dict that specifies:
      - name, unique_id, type
      - poll_tool, field (for reading state)
      - device_class, state_class, unit, icon, entity_category
      - Type-specific control fields (on_tool, off_tool, set_tool, etc.)
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: McpDeviceCoordinator,
        config: dict[str, Any],
    ) -> None:
        """Initialize the entity from a config dict."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._config = config

        # Entity identity
        self._attr_name = config.get("name", "MCP Entity")
        self._attr_unique_id = config.get("unique_id", self._attr_name)
        self._attr_icon = config.get("icon")
        ec = config.get("entity_category")
        if ec:
            try:
                self._attr_entity_category = EntityCategory(ec)
            except ValueError:
                _LOGGER.warning("Invalid entity_category '%s' for %s", ec, self._attr_name)

        # Device info — all values from MCP server are sanitised to
        # prevent injection of control chars or oversized strings.
        # Priority:
        #   - manufacturer: hard-coded "制糖工厂" (CoCan brand_zh)
        #   - model: get_machine_facts.product_family (e.g. "CP-02S")
        #   - sw_version: get_device_info.fpga_version + app_version
        device_info = coordinator.device_info
        psn = _sanitise_string(device_info.get("psn"))
        if not psn or psn == "unknown":
            psn = coordinator.device_name.replace(" ", "_").lower()

        # Model from machine_facts.product_family (CP-02S, CP-02, etc.)
        model = _sanitise_string(
            device_info.get("product_family")  # merged from get_machine_facts
            or device_info.get("model", "MCP Device")
        )

        # Firmware version = fpga_version + app_version from get_device_info
        fpga = _sanitise_string(device_info.get("fpga_version", ""))
        app = _sanitise_string(device_info.get("app_version", ""))
        if fpga and fpga != "unknown" and app and app != "unknown":
            sw_version = f"FPGA {fpga} / App {app}"
        elif fpga and fpga != "unknown":
            sw_version = f"FPGA {fpga}"
        elif app and app != "unknown":
            sw_version = f"App {app}"
        else:
            sw_version = _sanitise_string(
                device_info.get("firmware_version")
                or device_info.get("fw_version", "unknown")
            )

        # Hard-coded manufacturer from machine_facts.brand_zh
        manufacturer = "制糖工厂"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, psn)},
            name=coordinator.device_name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version,
        )

    @property
    def config(self) -> dict[str, Any]:
        """Return this entity's configuration dict."""
        return self._config

    def _get_raw_value(self) -> Any:
        """Extract the raw value from coordinator data using the entity's poll_tool + field.

        Supports:
          - ``compute`` for derived fields (multiply/add/subtract/sum_multiply)
          - ``__coordinator__.*`` fields to read coordinator attributes directly
            (e.g. ``__coordinator__.total_allocated_power``)
        """
        # Computed field: multiply two fields together
        compute = self._config.get("compute")
        if compute:
            return self._compute_value(compute)

        field = self._config.get("field")
        if field and field.startswith("__coordinator__."):
            attr_path = field[len("__coordinator__."):]
            parts = attr_path.split(".")
            obj = self.coordinator
            for part in parts:
                if obj is None:
                    return None
                obj = getattr(obj, part, None)
            return obj

        return self.coordinator.get_entity_value(self._config)

    def _compute_value(self, compute: str) -> Any:
        """Compute a derived value from two or more fields.

        Supported operations:
          - "multiply": field_a * field_b (then divide_by, round applied)
          - "divide": field_a / field_b (then multiply_by, round applied)
          - "add": field_a + field_b
          - "subtract": field_a - field_b
          - "sum_multiply": sum of (field_a * field_b) for each port in field_sources
        """
        if compute == "sum_multiply":
            return self._compute_sum_multiply()

        field_a_path = self._config.get("field_a")
        field_b_path = self._config.get("field_b")
        if not field_a_path or not field_b_path:
            return None

        # Extract both values using the same poll_tool
        poll_tool = self._config.get("poll_tool")
        raw_data = self.coordinator.data.get(poll_tool) if self.coordinator.data else None
        if raw_data is None:
            return None

        val_a = resolve_path(raw_data, field_a_path)
        val_b = resolve_path(raw_data, field_b_path)
        if val_a is None or val_b is None:
            return None

        try:
            a = float(val_a)
            b = float(val_b)
        except (ValueError, TypeError):
            return None

        if compute == "multiply":
            result = a * b
        elif compute == "add":
            result = a + b
        elif compute == "subtract":
            result = a - b
        elif compute == "divide":
            if b == 0:
                return None
            result = a / b
        else:
            return None

        return convert_value(
            result,
            divide_by=self._config.get("divide_by"),
            multiply_by=self._config.get("multiply_by"),
            round_digits=self._config.get("round_digits"),
        )

    def _compute_sum_multiply(self) -> Any:
        """Sum (vout_mv * iout_ma) across all ports for total power.

        Uses field_sources (list of per-port field pairs) instead of
        a single field_a + field_b. Each source is a dict:
          {"field_a": "ports.0.vout_mv", "field_b": "ports.0.iout_ma"}
        """
        poll_tool = self._config.get("poll_tool")
        raw_data = self.coordinator.data.get(poll_tool) if self.coordinator.data else None
        if raw_data is None:
            return None

        field_sources = self._config.get("field_sources", [])
        if not field_sources:
            # Fallback: try field_a / field_b as single-port (unlikely for total)
            field_a_path = self._config.get("field_a")
            field_b_path = self._config.get("field_b")
            if not field_a_path or not field_b_path:
                return None
            val_a = resolve_path(raw_data, field_a_path)
            val_b = resolve_path(raw_data, field_b_path)
            if val_a is None or val_b is None:
                return None
            try:
                return float(val_a) * float(val_b)
            except (ValueError, TypeError):
                return None

        total = 0.0
        valid_count = 0
        for source in field_sources:
            fa = source.get("field_a")
            fb = source.get("field_b")
            if not fa or not fb:
                continue
            val_a = resolve_path(raw_data, fa)
            val_b = resolve_path(raw_data, fb)
            if val_a is None or val_b is None:
                continue
            try:
                total += float(val_a) * float(val_b)
                valid_count += 1
            except (ValueError, TypeError):
                continue

        if valid_count == 0:
            return None

        return convert_value(
            total,
            divide_by=self._config.get("divide_by"),
            multiply_by=self._config.get("multiply_by"),
            round_digits=self._config.get("round_digits"),
        )

    def _get_converted_value(self) -> Any:
        """Extract and convert the value using the entity's config."""
        raw = self._get_raw_value()

        # Apply value_map if present
        value_map = self._config.get("value_map")
        if value_map and raw is not None:
            raw_str = str(raw)
            if raw_str in value_map:
                return value_map[raw_str]
            if raw_str.lower() in value_map:
                return value_map[raw_str.lower()]

        # If compute is used, _compute_value already applied divide_by /
        # round_digits. Don't apply them again to avoid double-division.
        if self._config.get("compute"):
            return raw

        # For non-computed fields, apply numeric conversions
        return convert_value(
            raw,
            divide_by=self._config.get("divide_by"),
            multiply_by=self._config.get("multiply_by"),
            round_digits=self._config.get("round_digits"),
        )
