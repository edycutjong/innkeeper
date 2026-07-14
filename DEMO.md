# Demo — Innkeeper

Every command below runs **offline, zero keys** on the deterministic seeded
month. Copy-paste order.

## 0. Setup (30 seconds)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
innkeeper seed --nights 30      # deterministic month + rendered OTA PDFs
```

## 1. The one devastating query

```bash
innkeeper run --night 2026-07-04
```

You'll see 39 transactions, 12 mismatches, **11 auto-cleared, 1 queued**. The
two beats that matter:

- **`m-07` auto-clears** — `$189.00 gross − $183.33 payout = $5.67 = exactly 3%`
  OTA commission, cited to OTA statement line 7 with a bounding box, evidence
  from two systems, confidence 0.94.
- **`m-12` is queued** — a **$310 card capture with no PMS folio**: the planted
  *unposted walk-in true error*. It carries two competing hypotheses at
  **0.60 / 0.40** ("room sold at the terminal, never posted" vs "mis-keyed
  deposit") — the agent knowing what it doesn't know. It queues because
  `classification == true_error`, which no confidence threshold can override.

Render the owner's morning report:

```bash
innkeeper report --night 2026-07-04
```

## 2. Replay — re-derive the night with zero keys (invariant I4)

```bash
innkeeper replay --night 2026-07-04
# → replay 2026-07-04: IDENTICAL · root d175694c…· signature reproduced
```

Every verdict, the Merkle root, and the Ed25519 signature are re-derived from
stored evidence, byte for byte.

## 3. The signed books + tamper detection (I3)

```bash
innkeeper run --night 2026-07-01   # build a few nights so the chain links
innkeeper run --night 2026-07-02
innkeeper run --night 2026-07-03
innkeeper verify-chain             # every root recomputed, every signature checked
```

Full offline proof, including a one-byte tamper that must fail:

```bash
python scripts/verify_offline.py   # socket-guarded; exits 0
```

## 4. The benchmark (the invariant, as a number)

```bash
innkeeper bench
# 277/281 auto-cleared · 0 false clears · accuracy 0.9964
python scripts/bench.py            # writes docs/BENCH.md incl. the τ-sweep
```

**0 false auto-clears on true errors** across the whole month — and the τ-sweep
shows that stays 0 at every risk threshold.

## 5. The tests (GREEN is the gate)

```bash
pytest -q      # 404 passed
```

## 6. The MCP mock systems

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"pms.get_folios","arguments":{"night":"2026-07-04"}}}' \
 | python mcp/pms_server.py
```

## Optional — the real Qwen models on the real PDF (`--live`)

Everything above is keyless. To show the actual Qwen Cloud call on the real
reportlab statement (the one step this repo can't fake):

```bash
pip install -e ".[live]"                 # openai + pypdfium2
export DASHSCOPE_API_KEY=sk-…            # dashscope.console.aliyun.com/apiKey
innkeeper run --night 2026-07-04 --live  # qwen3-vl-plus two-pass + qwen3.7-max
```

Same pipeline, same signed close — the extractor now rasterizes the 8-pt PDF and
reads it with `qwen3-vl-plus`; the residue is adjudicated by `qwen3.7-max`.

## Video beat sheet (3:00)

`0:00` the $6.67 that became $2,300 · `0:20` `innkeeper run --night 2026-07-04`
streams fetch → extract → match → adjudicate → gate → signed close · `0:45`
`m-07` auto-clears — the verdict cites **OTA line 7** (bbox `[…]` + sha256) and
the PMS folio, `$189.00 − $183.33 = $5.67 = exactly 3%`, confidence 0.94 ·
`1:30` `m-12` → **queue** with two competing hypotheses (0.60 / 0.40) because
`classification == true_error` — the beat where the gate refuses to auto-clear ·
`2:05` `innkeeper report`: 11 cleared / 1 queued / books closed + `innkeeper
bench` (zero false clears) · `2:40` `innkeeper replay` re-derives the night
byte-identical, zero keys · `2:55` "the night auditor finally sleeps."

> The FC 02:00 timer is **configured, not deployed** (`infra/fc/`); don't imply
> a live cron on camera. If you want the unattended-run beat, invoke the handler
> locally — the exact function the timer calls at 02:00:
>
> ```bash
> python -c "import sys; sys.path.insert(0,'infra/fc'); \
>   from audit_handler import handler; print(handler('{\"night\":\"2026-07-04\"}', None))"
> # → {"night":"2026-07-04","merkle_root":"d175694c…","n_cleared":11,"n_queued":1,…}
> ```
>
> Or show `infra/fc/s.yaml` as the scaffold — see [`infra/fc/PROOF.md`](./infra/fc/PROOF.md).
