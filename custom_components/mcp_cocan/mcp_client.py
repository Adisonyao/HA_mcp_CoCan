"""Lightweight MCP client — no external mcp package dependency.

Implements the MCP (Model Context Protocol) over HTTP using only aiohttp.
This avoids version mismatches with the third-party `mcp` Python package and
prevents Home Assistant's "blocking call" warnings.

Supported transports:
  - streamable_http: POST JSON-RPC requests, read JSON responses
  - sse: legacy SSE transport (falls back to streamable HTTP POST)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp # type: ignore

from .const import TransportType

_LOGGER = logging.getLogger(__name__)

# Maximum JSON response size (1 MB) — prevents JSON bomb DoS
MAX_JSON_SIZE = 1_048_576


class McpError(Exception):
    """Raised when the MCP server returns an error or is unreachable."""


class McpClient:
    """Async MCP client using aiohttp.

    Manages a single session: initialize -> list tools -> call tools.
    For Streamable HTTP, sends POST requests with JSON-RPC bodies.
    For SSE, falls back to Streamable HTTP POST (most modern servers
    support both on the same endpoint).
    """

    def __init__(
        self,
        url: str,
        transport: TransportType,
        token: str | None = None,
    ) -> None:
        """Create a client (not yet connected)."""
        self._url = url
        self._transport = transport
        self._token = token
        self._session_id: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._msg_id = 0

    async def __aenter__(self) -> McpClient:
        """Open aiohttp session and perform MCP initialize handshake."""
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        # Use TCPConnector with verify_ssl=True (default) to avoid blocking call
        # warnings from HA. aiohttp handles SSL certificate loading
        # asynchronously inside the connector.
        connector = aiohttp.TCPConnector(
            ssl=True,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        self._session = aiohttp.ClientSession(
            headers=headers,
            connector=connector,
            timeout=timeout,
        )

        await self._init_streamable_http()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Close aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None

    # -- Internal helpers ------------------------------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _make_payload(self, method: str, params: dict[str, Any] | None = None) -> dict:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params:
            payload["params"] = params
        return payload

    async def _post_json(self, payload: dict) -> dict:
        """POST a JSON-RPC payload and return the parsed response."""
        if self._session is None:
            raise McpError("Client not connected")

        headers: dict[str, str] = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        _LOGGER.debug("POST %s -> payload: %s", self._url, payload.get("method"))

        try:
            async with self._session.post(
                self._url,
                json=payload,
                headers=headers,
            ) as resp:
                _LOGGER.debug("POST %s <- HTTP %d", self._url, resp.status)

                if resp.status >= 400:
                    text = await resp.text()
                    _LOGGER.error(
                        "MCP POST %s failed: HTTP %d, body: %s",
                        payload.get("method"), resp.status, text[:200],
                    )
                    raise McpError(f"HTTP {resp.status}: {text[:200]}")

                # Try to get session ID from response headers
                if "Mcp-Session-Id" in resp.headers:
                    self._session_id = resp.headers["Mcp-Session-Id"]

                # Parse JSON response
                try:
                    data = await resp.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    text = await resp.text()
                    _LOGGER.error(
                        "Invalid JSON from MCP server: %s (body: %s)",
                        exc, text[:500],
                    )
                    raise McpError(f"Invalid JSON response: {exc}") from exc

                # Check for JSON-RPC error
                if isinstance(data, dict) and "error" in data:
                    err = data["error"]
                    _LOGGER.error(
                        "MCP error for %s: code=%s, message=%s",
                        payload.get("method"),
                        err.get("code"),
                        err.get("message"),
                    )
                    raise McpError(
                        f"MCP error {err.get('code')}: {err.get('message')}"
                    )

                return data.get("result", {}) if isinstance(data, dict) else {}

        except aiohttp.ClientError as exc:
            _LOGGER.error(
                "MCP POST %s failed: %s: %s",
                payload.get("method"), type(exc).__name__, exc,
            )
            raise McpError(f"Request failed: {type(exc).__name__}: {exc}") from exc

    async def _init_streamable_http(self) -> None:
        """Perform MCP initialize handshake for Streamable HTTP."""
        payload = self._make_payload(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ha-mcp-device", "version": "0.3.6"},
            },
        )
        result = await self._post_json(payload)
        _LOGGER.debug("MCP initialize result: %s", result)

        # Send initialized notification (fire-and-forget)
        notify = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        try:
            async with self._session.post(self._url, json=notify): # type: ignore
                pass
        except Exception:
            pass

    # -- Public API -------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return list of available tools from the MCP server."""
        payload = self._make_payload("tools/list", {})
        result = await self._post_json(payload)
        tools = result.get("tools", []) if isinstance(result, dict) else []
        _LOGGER.debug("MCP server offers %d tools", len(tools))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call an MCP tool and return the parsed result."""
        payload = self._make_payload(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        result = await self._post_json(payload)

        # Parse tool result content
        if not isinstance(result, dict):
            return result

        content = result.get("content", [])
        if not content:
            return result

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if isinstance(text, str) and len(text) > MAX_JSON_SIZE:
                    text = text[:MAX_JSON_SIZE]
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, ValueError, RecursionError):
                    return text

        return result


# -- Public helpers ----------------------------------------------------

async def call_mcp_tool(
    url: str,
    transport: TransportType,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    """One-shot tool call. Opens a temporary session, calls the tool, closes it.

    Used by coordinator for polling and by entities for control actions.
    """
    async with McpClient(url, transport, token) as client:
        return await client.call_tool(tool_name, arguments)


def parse_tool_result(result: Any) -> Any:
    """Parse a tool result for backward compatibility.

    McpClient.call_tool already returns parsed dicts, but this function
    is kept for code that passes the raw result through.
    """
    return result if result is not None else {}
