"""The MCP Device integration.

Config-driven: entities are created from a user-configured JSON stored in the
config entry data. No code changes are needed to support new MCP devices.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_NAME,
    CONF_ENTITIES,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_SCAN_INTERVAL,
    CONF_TRANSPORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TransportType,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MCP Device from a config entry."""
    # Lazy import to avoid failing during handler registration
    # if the mcp dependency is not yet installed.
    from .coordinator import McpDeviceCoordinator

    url = entry.data[CONF_MCP_URL]
    transport = TransportType(entry.data[CONF_TRANSPORT])
    token = entry.data.get(CONF_MCP_TOKEN) or None
    device_name = entry.data.get(CONF_DEVICE_NAME, "MCP Device")
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    entities_config = entry.data.get(CONF_ENTITIES, [])

    _LOGGER.info(
        "Setting up MCP Device '%s' with %d entities, transport=%s, interval=%ds",
        device_name,
        len(entities_config),
        transport,
        scan_interval,
    )

    coordinator = McpDeviceCoordinator(
        hass,
        url=url,
        transport=transport,
        token=token,
        device_name=device_name,
        update_interval=scan_interval,
        entities_config=entities_config,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
