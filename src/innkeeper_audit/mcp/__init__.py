"""Three mock source systems (PMS / processor / OTA) as MCP-compatible servers.

Honest disclosure: these are *mock* systems seeded from the committed fixtures,
exposed over a minimal MCP-compatible JSON-RPC (newline-delimited) transport —
the rubric's named "MCP integrations" example, shipped as a standalone,
reseedable developer asset. The audit pipeline calls the very same tool
functions in-process for deterministic, offline replay.
"""

from __future__ import annotations

from .server import MockMCPServer, serve_stdio
from .tools import (
    TOOL_SPECS,
    build_ota_server,
    build_pms_server,
    build_processor_server,
    ota_get_statement_pdf,
    pms_get_folios,
    processor_get_settlements,
)

__all__ = [
    "MockMCPServer",
    "serve_stdio",
    "TOOL_SPECS",
    "pms_get_folios",
    "processor_get_settlements",
    "ota_get_statement_pdf",
    "build_pms_server",
    "build_processor_server",
    "build_ota_server",
]
