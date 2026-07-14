#!/usr/bin/env python
"""Standalone card-processor mock MCP server.

Exposes ``processor.get_settlements`` over newline-delimited JSON-RPC.
MOCK SYSTEM: settlements come from the committed seeded fixtures. See
mcp/README.md.
"""

from innkeeper_audit.mcp import build_processor_server, serve_stdio

if __name__ == "__main__":
    serve_stdio(build_processor_server())
