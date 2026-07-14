"""The three mock systems' tool functions + MCP server builders.

Each tool is a plain function ``(paths, **args) -> jsonable``; the pipeline
calls them directly and the MCP servers wrap them. All reads come from the
committed fixtures, so behaviour is identical in-process and over a pipe.
"""

from __future__ import annotations

from typing import Any

from ..config import MONTH, Paths
from ..store import read_json
from .server import MockMCPServer

# --------------------------------------------------------------------------- #
# tool functions
# --------------------------------------------------------------------------- #


def pms_get_folios(paths: Paths, night: str) -> list[dict[str, Any]]:
    """PMS folios (room sales + extras) posted on ``night``."""
    return read_json(paths.pms_dir / f"{night}.json")["txns"]


def processor_get_settlements(paths: Paths, night: str) -> list[dict[str, Any]]:
    """Card-processor settlements captured on ``night``."""
    return read_json(paths.processor_dir / f"{night}.json")["txns"]


def ota_get_statement_pdf(paths: Paths, month: str = MONTH) -> dict[str, Any]:
    """Metadata for the month's OTA partner statement (delivered as a sealed
    PDF). The bytes are ECIES-sealed at rest; ``qwen3-vl-plus`` extracts the
    lines in the worker (see the VL extraction step)."""
    sidecar = read_json(paths.ota_sidecar(month))
    return {
        "month": month,
        "pdf_sha256": sidecar.get("pdf_sha256", ""),
        "pages": sidecar.get("pages"),
        "font_pt": sidecar.get("font_pt"),
        "sealed_uri": f"fixtures/month_07/ota/statement_{month}.pdf.sealed",
        "n_lines": len(sidecar.get("lines", [])),
        "note": "sealed at rest (pynacl SealedBox); unsealed only in the worker",
    }


# --------------------------------------------------------------------------- #
# MCP tool specs
# --------------------------------------------------------------------------- #

_NIGHT_SCHEMA = {
    "type": "object",
    "properties": {"night": {"type": "string", "description": "business date YYYY-MM-DD"}},
    "required": ["night"],
}
_MONTH_SCHEMA = {
    "type": "object",
    "properties": {"month": {"type": "string", "description": "statement month YYYY-MM"}},
    "required": [],
}

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "pms.get_folios": {
        "name": "pms.get_folios",
        "description": "Fetch property-management folios (room sales + extras) for a night.",
        "inputSchema": _NIGHT_SCHEMA,
    },
    "processor.get_settlements": {
        "name": "processor.get_settlements",
        "description": "Fetch card-processor settlements for a night.",
        "inputSchema": _NIGHT_SCHEMA,
    },
    "ota.get_statement_pdf": {
        "name": "ota.get_statement_pdf",
        "description": "Fetch metadata for the month's OTA statement PDF (sealed at rest).",
        "inputSchema": _MONTH_SCHEMA,
    },
}


# --------------------------------------------------------------------------- #
# server builders
# --------------------------------------------------------------------------- #


def build_pms_server(paths: Paths | None = None) -> MockMCPServer:
    p = paths or Paths()
    s = MockMCPServer("innkeeper-pms")
    s.register(TOOL_SPECS["pms.get_folios"], lambda a: pms_get_folios(p, a["night"]))
    return s


def build_processor_server(paths: Paths | None = None) -> MockMCPServer:
    p = paths or Paths()
    s = MockMCPServer("innkeeper-processor")
    s.register(TOOL_SPECS["processor.get_settlements"],
               lambda a: processor_get_settlements(p, a["night"]))
    return s


def build_ota_server(paths: Paths | None = None) -> MockMCPServer:
    p = paths or Paths()
    s = MockMCPServer("innkeeper-ota")
    s.register(TOOL_SPECS["ota.get_statement_pdf"],
               lambda a: ota_get_statement_pdf(p, a.get("month", MONTH)))
    return s
