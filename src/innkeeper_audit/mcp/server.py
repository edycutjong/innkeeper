"""A minimal, dependency-free MCP-compatible JSON-RPC server.

Implements the handshake and tool surface the MCP stdio transport uses —
``initialize`` / ``tools/list`` / ``tools/call`` as JSON-RPC 2.0 messages,
newline-delimited on stdio. It is deliberately tiny (no third-party ``mcp``
dependency) so the mock systems ship as a self-contained developer asset; the
handler is exercised in-process by the test suite and can also be driven over a
real pipe with ``python -m mcp.pms_server``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from innkeeper_audit import __version__

PROTOCOL_VERSION = "2024-11-05"
Handler = Callable[[dict[str, Any]], Any]


def text_content(obj: Any) -> dict[str, Any]:
    """Wrap a tool result as an MCP text content block."""
    return {"content": [{"type": "text", "text": json.dumps(obj, sort_keys=True)}]}


class MockMCPServer:
    def __init__(self, name: str, version: str = __version__) -> None:
        self.name = name
        self.version = version
        self._tools: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, spec: dict[str, Any], handler: Handler) -> None:
        self._tools[spec["name"]] = spec
        self._handlers[spec["name"]] = handler

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        return list(self._tools.values())

    # -- JSON-RPC dispatch -------------------------------------------------- #

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process one JSON-RPC request; returns the response (or None for a
        notification, which carries no id)."""
        method = request.get("method")
        req_id = request.get("id")
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version},
                }
            elif method == "notifications/initialized":
                return None
            elif method == "tools/list":
                result = {"tools": self.tool_specs}
            elif method == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                if name not in self._handlers:
                    return self._error(req_id, -32601, f"unknown tool {name}")
                args = params.get("arguments", {}) or {}
                result = text_content(self._handlers[name](args))
            elif method == "ping":
                result = {}
            else:
                return self._error(req_id, -32601, f"unknown method {method}")
        except Exception as exc:  # surface tool errors as JSON-RPC errors
            return self._error(req_id, -32000, f"{type(exc).__name__}: {exc}")
        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve_stdio(server: MockMCPServer) -> None:  # pragma: no cover - real I/O loop
    """Serve newline-delimited JSON-RPC over stdio until EOF."""
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            continue
        response = server.handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
