#!/usr/bin/env python
"""Standalone OTA mock MCP server.

Exposes ``ota.get_statement_pdf`` (statement metadata; the bytes are sealed at
rest and read by qwen3-vl-plus in the worker) over newline-delimited JSON-RPC.
MOCK SYSTEM: the statement is a reportlab-rendered fixture. See mcp/README.md.
"""

from innkeeper_audit.mcp import build_ota_server, serve_stdio

if __name__ == "__main__":
    serve_stdio(build_ota_server())
