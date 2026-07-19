# Deploy Proof — Innkeeper on Alibaba Function Compute 3.0

Managed `python3.10` runtime (no container / no ACR / no real-name
verification). Event handler `infra.fc.wsgi.handler`; anonymous HTTP trigger.
Every endpoint runs OFFLINE, zero keys, on the committed `fixtures/` +
`ledger/` — no DASHSCOPE key, no vision model, no network.

- Region: ap-southeast-1 (Singapore)
- Function: `innkeeper`  ·  App: `innkeeper-fc`
- Live URL: <https://innkeeper-temfmzpqug.ap-southeast-1.fcapp.run>
- Deployed: 2026-07-19

## `GET /health`
```json
{
  "status": "ok"
}
```

## `GET /verify` — re-verify the committed signed-close chain (I2/I3/I4)
```json
{
  "checks": [
    {
      "detail": "30 signed closes: roots, Ed25519 signatures and evidence sha256 bindings all verify",
      "name": "I2/I3 signed-close chain + evidence bindings",
      "ok": true
    },
    {
      "detail": "re-derived from stored evidence; root d175694c4fd5427b\u2026 + signature reproduced",
      "name": "I4 replay 2026-07-04 byte-identical",
      "ok": true
    },
    {
      "detail": "root no longer matches the signed close after a 1-cent verdict edit",
      "name": "I3 one-byte tamper is detected",
      "ok": true
    }
  ],
  "overall": "PASS",
  "signed_closes": 30,
  "source": "committed offline ledger (FakeQwen \u2014 zero keys, no network)",
  "target_night": "2026-07-04"
}
```

## `GET /run` — one deterministic offline night audit (night=2026-07-04)
```json
{
  "delta_total_usd": 43.01,
  "merkle_root": "d175694c4fd5427be72739125c232e5a9cc51fc1204870913d9c0fdf86b363d3",
  "n_cleared": 11,
  "n_matched": 10,
  "n_mismatches": 12,
  "n_queued": 1,
  "n_txns": 39,
  "night": "2026-07-04",
  "signer_pubkey": "689bcf7a1dbcaaf1a668a720f54676d26ba71e07a28c614ab427726d1ffcfe3c",
  "transport": "FakeQwen (offline deterministic \u2014 no key required)"
}
```

Counts match DEMO.md exactly: 39 transactions, 12 mismatches, 11 auto-cleared,
1 queued (the planted unposted walk-in true error); Merkle root
`d175694c…` reproduces the committed signed close for the night.
