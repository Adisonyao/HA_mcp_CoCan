"""Constants for the MCP Device integration."""

from enum import StrEnum
from typing import Final

DOMAIN: Final = "mcp_cocan"

# Config entry fields
CONF_MCP_URL: Final = "mcp_url"
CONF_MCP_TOKEN: Final = "mcp_token"
CONF_TRANSPORT: Final = "transport"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DEVICE_NAME: Final = "device_name"
CONF_ENTITIES: Final = "entities_config"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 15
DEFAULT_DEVICE_NAME: Final = "CoCan"


# ── Transport types ──────────────────────────────────────────────
class TransportType(StrEnum):
    """Supported MCP transport types."""

    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


# ── Entity type identifiers ─────────────────────────────────────
class EntityType(StrEnum):
    """Supported entity types for config-driven mapping."""

    SENSOR = "sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"


# ── Sensor device class mapping ──────────────────────────────────
SENSOR_DEVICE_CLASSES: Final = {
    "power": "power",
    "voltage": "voltage",
    "current": "current",
    "temperature": "temperature",
    "signal_strength": "signal_strength",
    "energy": "energy",
    "humidity": "humidity",
    "pressure": "pressure",
    "battery": "battery",
    "power_factor": "power_factor",
    "frequency": "frequency",
    "data_rate": "data_rate",
    "data_size": "data_size",
    "timestamp": "timestamp",
    "duration": "duration",
    "distance": "distance",
    "weight": "weight",
    "volume": "volume",
    "monetary": "monetary",
    "gas": "gas",
    "water": "water",
}

# State class mapping
SENSOR_STATE_CLASSES: Final = {
    "measurement": "measurement",
    "total": "total",
    "total_increasing": "total_increasing",
}
