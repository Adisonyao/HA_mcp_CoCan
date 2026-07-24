"""Utility functions for MCP Device integration.

Provides JSON path resolution, value conversion, and config validation helpers.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Maximum nesting depth for resolve_path to prevent stack exhaustion
# from a compromised MCP server returning deeply nested JSON.
MAX_PATH_DEPTH = 20


def resolve_path(data: Any, path: str) -> Any:
    """Resolve a dot-and-bracket path against nested data.

    Supports:
      - ``ports.0.voltage``  -> data["ports"][0]["voltage"]
      - ``ports[0].voltage`` -> data["ports"][0]["voltage"]
      - ``ports[port=3].voltage`` -> find in ports list where port==3, get voltage
      - ``device.psn``        -> data["device"]["psn"]
      - ``ports.#.power``    -> list of power values from all ports
      - ``__root__``          -> the root data object itself

    The ``#`` wildcard expands a list -- ``ports.#.power`` returns
    ``[port1_power, port2_power, ...]``.

    The ``[key=value]`` filter finds a single element in a list where
    ``element[key] == value``. Useful for dynamic lists like PD status
    that only contain active ports.

    Returns ``None`` if any segment is missing or max depth is exceeded.

    Security: depth is capped at MAX_PATH_DEPTH to prevent a compromised
    MCP server from causing stack overflow via deeply nested data.
    """
    if not path or not data:
        return None

    if path == "__root__":
        return data

    # Normalise to dot-separated tokens, with optional # wildcard
    # ports[0].voltage -> ports.0.voltage (existing)
    path = re.sub(r"\[(\d+)\]", r".\1", path)
    # ports[port=3].voltage -> ports.@port=3.voltage (filter syntax)
    path = re.sub(r"\[([a-zA-Z_]\w*)=([^\]]+)\]", r".@\1=\2", path)
    tokens = path.split(".")

    # Reject excessively deep paths
    if len(tokens) > MAX_PATH_DEPTH:
        _LOGGER.warning(
            "JSON path depth %d exceeds max %d, refusing to resolve",
            len(tokens), MAX_PATH_DEPTH,
        )
        return None

    return _resolve_tokens(data, tokens, depth=0)


def _resolve_tokens(data: Any, tokens: list[str], depth: int = 0) -> Any:
    """Recursively resolve tokens against data.

    Security: depth is tracked to prevent stack exhaustion.
    """
    if not tokens:
        return data
    if data is None:
        return None

    # Prevent stack overflow from deeply nested data
    if depth >= MAX_PATH_DEPTH:
        _LOGGER.warning("resolve_path max depth %d exceeded", MAX_PATH_DEPTH)
        return None

    token = tokens[0]
    rest = tokens[1:]

    # Wildcard: expand a list
    if token == "#":
        if not isinstance(data, list):
            return None
        results = []
        for item in data:
            val = _resolve_tokens(item, rest, depth + 1)
            if val is not None:
                results.append(val)
        return results if results else None

    # Filter syntax: @key=value — find first matching element in a list
    if token.startswith("@") and "=" in token:
        filter_expr = token[1:]  # strip leading @
        key, _, value_str = filter_expr.partition("=")
        if not isinstance(data, list):
            return None
        # Try to match key=value in each list element
        for item in data:
            if isinstance(item, dict) and str(item.get(key)) == value_str:
                return _resolve_tokens(item, rest, depth + 1)
        return None

    # Index access
    if token.isdigit():
        idx = int(token)
        if isinstance(data, list) and 0 <= idx < len(data):
            return _resolve_tokens(data[idx], rest, depth + 1)
        return None

    # Dict key access
    if isinstance(data, dict):
        if token in data:
            return _resolve_tokens(data[token], rest, depth + 1)
        return None

    if isinstance(data, list):
        # If data is a list but token is not # or digit, try each element
        results = []
        for item in data:
            val = _resolve_tokens(item, [token] + rest, depth + 1)
            if val is not None:
                results.append(val)
        return results if results else None

    return None


def convert_value(
    raw: Any,
    divide_by: float | None = None,
    multiply_by: float | None = None,
    round_digits: int | None = None,
    value_map: dict[str, Any] | None = None,
) -> Any:
    """Apply unit conversion / mapping to a raw value.

    Args:
        raw: The raw value from the MCP tool result.
        divide_by: Divide the raw value by this number (e.g. 1000 to convert mV->V).
        multiply_by: Multiply the raw value by this number.
        round_digits: Round to this many decimal places.
        value_map: Map raw string/int values to display values.
    """
    if raw is None:
        return None

    # If value_map is provided and raw matches a key, return mapped value
    if value_map:
        raw_str = str(raw)
        if raw_str in value_map:
            return value_map[raw_str]
        # Try lowercase
        if raw_str.lower() in value_map:
            return value_map[raw_str.lower()]

    # Numeric conversions
    if divide_by is not None or multiply_by is not None:
        try:
            val = float(raw)
            if divide_by:
                val = val / divide_by
            if multiply_by:
                val = val * multiply_by
            if round_digits is not None:
                val = round(val, round_digits)
            return val
        except (ValueError, TypeError):
            return raw

    if round_digits is not None:
        try:
            return round(float(raw), round_digits)
        except (ValueError, TypeError):
            return raw

    return raw


def validate_entity_config(entity: dict[str, Any]) -> list[str]:
    """Validate a single entity config dict.

    Returns a list of error messages (empty list = valid).
    """
    errors: list[str] = []

    # Required fields for all types
    entity_type = entity.get("type")
    if not entity_type:
        errors.append("Missing required field: type")
    elif entity_type not in ("sensor", "switch", "select", "number"):
        errors.append(f"Invalid entity type: {entity_type} (must be sensor/switch/select/number)")

    name = entity.get("name")
    if not name:
        errors.append("Missing required field: name")

    unique_id = entity.get("unique_id")
    if not unique_id:
        errors.append("Missing required field: unique_id")

    if errors:
        return errors  # Don't continue if basics are missing

    # Type-specific validation
    if entity_type == "sensor":
        has_field = entity.get("field")
        has_coordinator_field = (
            has_field and str(has_field).startswith("__coordinator__.")
        )
        has_compute_standard = (
            entity.get("compute")
            and entity.get("field_a")
            and entity.get("field_b")
        )
        has_compute_sum = (
            entity.get("compute") == "sum_multiply"
            and entity.get("field_sources")
        )
        has_compute = has_compute_standard or has_compute_sum
        # poll_tool required unless reading from coordinator directly
        if not entity.get("poll_tool") and not has_coordinator_field:
            errors.append(f"Sensor '{name}': missing 'poll_tool'")
        if not has_field and not has_compute:
            errors.append(
                f"Sensor '{name}': missing 'field' (or 'compute' + 'field_a' + 'field_b' or 'field_sources')"
            )

    elif entity_type == "switch":
        if not entity.get("on_tool"):
            errors.append(f"Switch '{name}': missing 'on_tool'")
        if not entity.get("off_tool"):
            errors.append(f"Switch '{name}': missing 'off_tool'")
        if entity.get("poll_tool") and not entity.get("field"):
            errors.append(f"Switch '{name}': has 'poll_tool' but missing 'field' for state reading")

    elif entity_type == "select":
        if not entity.get("set_tool"):
            errors.append(f"Select '{name}': missing 'set_tool'")
        if not entity.get("options"):
            errors.append(f"Select '{name}': missing 'options'")
        if entity.get("poll_tool") and not entity.get("field"):
            errors.append(f"Select '{name}': has 'poll_tool' but missing 'field' for state reading")

    elif entity_type == "number":
        if not entity.get("set_tool"):
            errors.append(f"Number '{name}': missing 'set_tool'")
        if not entity.get("min") and entity.get("min") != 0:
            errors.append(f"Number '{name}': missing 'min'")
        if not entity.get("max") and entity.get("max") != 0:
            errors.append(f"Number '{name}': missing 'max'")
        # Power allocation numbers don't need poll_tool/field
        if entity.get("poll_tool") and not entity.get("field"):
            errors.append(f"Number '{name}': has 'poll_tool' but missing 'field' for state reading")
        if entity.get("set_tool") == "set_port_power_allocation" and not entity.get("port_index"):
            errors.append(f"Number '{name}': power allocation needs 'port_index'")

    return errors


def validate_entities_config(
    entities: list[dict[str, Any]],
    known_tools: list[str] | None = None,
) -> list[str]:
    """Validate a list of entity configs. Returns list of all errors.

    Args:
        entities: List of entity config dicts.
        known_tools: If provided, entity tool names are validated against
            this list (whitelist of tools offered by the MCP server).
    """
    all_errors: list[str] = []
    seen_ids: set[str] = set()

    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            all_errors.append(f"Entity #{i}: config must be a JSON object")
            continue

        errors = validate_entity_config(entity)
        for err in errors:
            all_errors.append(f"Entity #{i}: {err}")

        uid = entity.get("unique_id", "")
        if uid:
            if uid in seen_ids:
                all_errors.append(f"Entity '{uid}': duplicate unique_id")
            seen_ids.add(uid)

        # Validate tool names against known_tools whitelist
        if known_tools is not None:
            for tool_field in ("poll_tool", "on_tool", "off_tool", "set_tool"):
                tool_name = entity.get(tool_field)
                if tool_name and tool_name not in known_tools:
                    all_errors.append(
                        f"Entity '{uid}': tool '{tool_name}' ({tool_field}) "
                        f"is not offered by the MCP server"
                    )

    return all_errors
