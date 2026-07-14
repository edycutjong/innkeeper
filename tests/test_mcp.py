"""The three MCP mock servers: JSON-RPC handshake, tools/list, tools/call, and
error handling — exercised in-process against the same handler that serves stdio."""

from __future__ import annotations

import json

import pytest

from innkeeper_audit.mcp import (
    build_ota_server,
    build_pms_server,
    build_processor_server,
    ota_get_statement_pdf,
    pms_get_folios,
    processor_get_settlements,
)


def _rpc(server, method, params=None, req_id=1):
    return server.handle({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})


def _servers(paths):
    return {
        "pms": build_pms_server(paths),
        "processor": build_processor_server(paths),
        "ota": build_ota_server(paths),
    }


def test_initialize_handshake(seeded):
    for s in _servers(seeded).values():
        resp = _rpc(s, "initialize")
        assert resp["result"]["protocolVersion"]
        assert resp["result"]["serverInfo"]["name"].startswith("innkeeper-")


@pytest.mark.parametrize("name,tool", [
    ("pms", "pms.get_folios"),
    ("processor", "processor.get_settlements"),
    ("ota", "ota.get_statement_pdf"),
])
def test_tools_list(seeded, name, tool):
    s = _servers(seeded)[name]
    resp = _rpc(s, "tools/list")
    assert [t["name"] for t in resp["result"]["tools"]] == [tool]


def test_pms_tool_call_returns_folios(seeded):
    s = build_pms_server(seeded)
    resp = _rpc(s, "tools/call", {"name": "pms.get_folios", "arguments": {"night": "2026-07-04"}})
    txns = json.loads(resp["result"]["content"][0]["text"])
    assert len(txns) == 21
    assert txns[0]["src"] == "pms"


def test_processor_tool_call(seeded):
    s = build_processor_server(seeded)
    resp = _rpc(s, "tools/call",
                {"name": "processor.get_settlements", "arguments": {"night": "2026-07-04"}})
    txns = json.loads(resp["result"]["content"][0]["text"])
    assert any(t["ref"] == "stl-e0777" for t in txns)


def test_ota_tool_call_returns_metadata(seeded):
    s = build_ota_server(seeded)
    resp = _rpc(s, "tools/call", {"name": "ota.get_statement_pdf", "arguments": {}})
    meta = json.loads(resp["result"]["content"][0]["text"])
    assert meta["pdf_sha256"] and meta["pages"] and "sealed" in meta["note"]


def test_unknown_tool_is_json_rpc_error(seeded):
    s = build_pms_server(seeded)
    resp = _rpc(s, "tools/call", {"name": "nope", "arguments": {}})
    assert resp["error"]["code"] == -32601


def test_unknown_method_is_error(seeded):
    s = build_pms_server(seeded)
    assert _rpc(s, "frobnicate")["error"]["code"] == -32601


def test_notification_returns_none(seeded):
    s = build_pms_server(seeded)
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tool_error_surfaces_as_rpc_error(seeded):
    s = build_pms_server(seeded)
    # missing required 'night' argument → handler raises → JSON-RPC error
    resp = _rpc(s, "tools/call", {"name": "pms.get_folios", "arguments": {}})
    assert "error" in resp


def test_direct_tool_functions(seeded):
    assert len(pms_get_folios(seeded, "2026-07-04")) == 21
    assert len(processor_get_settlements(seeded, "2026-07-04")) == 18
    assert ota_get_statement_pdf(seeded)["pages"] >= 1


def test_ping_method(seeded):
    s = build_pms_server(seeded)
    resp = _rpc(s, "ping")
    assert resp["result"] == {}


def test_request_without_id_is_treated_as_a_notification(seeded):
    s = build_pms_server(seeded)
    # a method that otherwise succeeds, but carries no "id" -> per JSON-RPC 2.0
    # that's a notification: the handler still runs, but no response is sent.
    assert s.handle({"jsonrpc": "2.0", "method": "ping"}) is None
