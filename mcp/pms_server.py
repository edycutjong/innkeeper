#!/usr/bin/env python
"""Standalone PMS mock MCP server.

Speaks newline-delimited JSON-RPC (MCP stdio transport) exposing
``pms.get_folios``. Run it with ``python mcp/pms_server.py`` and pipe JSON-RPC,
or import ``innkeeper_audit.mcp.build_pms_server`` to drive it in-process.

MOCK SYSTEM: folios are read from the committed seeded fixtures, not a live
property-management system. See mcp/README.md.
"""

from innkeeper_audit.mcp import build_pms_server, serve_stdio

if __name__ == "__main__":
    serve_stdio(build_pms_server())
