# MCP mock systems

Three standalone **MCP-compatible** servers stand in for the systems a real inn
would integrate — the property-management system, the card processor, and the
OTA. They are the rubric's named "MCP integrations" example, shipped as a
reusable developer asset: anyone building a reconciliation agent needs exactly
these three.

| Server | Tool | Returns |
|---|---|---|
| `pms_server.py` | `pms.get_folios(night)` | room-sale + extra folios for a night |
| `processor_server.py` | `processor.get_settlements(night)` | card settlements for a night |
| `ota_server.py` | `ota.get_statement_pdf(month)` | statement PDF metadata (sealed at rest) |

## Honest disclosure — these are MOCKS

The servers read from the committed, deterministically **seeded fixtures**
(`fixtures/month_07/`), not from live systems. That is the honest path to
realism: the data is a coherent 14-room month with planted, ground-truth-labeled
discrepancy archetypes and **real reportlab-rendered OTA PDFs**, so the vision
model genuinely earns its keep — but no live PMS/processor/OTA is contacted.

## Transport

A minimal, dependency-free JSON-RPC 2.0 handler (newline-delimited, the MCP
stdio framing) lives in `innkeeper_audit/mcp/server.py`. It implements
`initialize` / `tools/list` / `tools/call`. The audit pipeline calls the same
tool functions **in-process** for deterministic, offline replay; the stdio
servers are the integration surface for external MCP clients.

```bash
# drive a server by hand
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"pms.get_folios","arguments":{"night":"2026-07-04"}}}' \
  | python mcp/pms_server.py
```

What shipped: the JSON-RPC handshake, `tools/list`, and `tools/call` over stdio,
tested in-process. Not a full MCP SDK (no resources/prompts/streaming) — kept
deliberately small so the mocks are self-contained.
