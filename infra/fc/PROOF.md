# Alibaba Function Compute — deployment proof

**The pitch is production shape: the cron IS the proof.** A night auditor that
runs itself at 2 AM is the track's "production over toy" made literal — an
unattended timer, not a human clicking Run.

## What is here

- [`s.yaml`](./s.yaml) — the Serverless Devs (FC 3.0) definition with a **timer
  trigger at `0 0 2 * * *` (02:00 daily)**, `python3.12` runtime, the audit
  handler, and env-injected secrets (`DASHSCOPE_API_KEY`, the Ed25519 signing
  key). This is the exact config a deploy uses.
- [`audit_handler.py`](./audit_handler.py) — the FC entrypoint: resolves the
  business night, runs `fetch → extract → match → adjudicate → gate → signed
  close`, returns the close stats.

## What deploying shows (the money shot)

```bash
export DASHSCOPE_API_KEY=…            # qwen3-vl-plus / qwen3.7-max
export INNKEEPER_SIGNING_KEY=…        # hex Ed25519 seed, FC env only
s deploy                              # Serverless Devs
# → then the FC console "Invocation" log at 02:00:
#   2026-07-05T02:00:00Z  nightly-0200 (timer)  →  200
#   {"night":"2026-07-04","merkle_root":"d175694c…","n_cleared":11,"n_queued":1}
```

The recording of that 02:00 timer line firing on its own — separate from the
demo video — is the strongest "unattended production" artifact in the portfolio.

## Status

**Deployed live on Alibaba Function Compute** (managed `python3.10`, HTTP handler
`infra.fc.wsgi.handler`) at <https://innkeeper-temfmzpqug.ap-southeast-1.fcapp.run>
— offline `/health`, `/verify`, `/run` endpoints; full transcript in
[`../../docs/proof/DEPLOY_PROOF.md`](../../docs/proof/DEPLOY_PROOF.md).

- The **02:00 timer trigger** described above is configured in `s.yaml` but the
  captured console recording of the cron firing on its own is the pending step:
  it needs a funded `DASHSCOPE_API_KEY` in the FC env. The deployed HTTP
  endpoints run offline with zero keys today.
- The signed-close **private key** lives only in the FC env; the committed demo
  keypair (derived from the fixture seed) is for local verification and is
  labelled demo-only.
- Ledger persistence assumes a NAS mount at `/mnt/audit`; locally the same
  documents live under `ledger/` and drive `replay` / `verify-chain` with no
  cloud dependency.

Everything the audit *does* is provable offline today
(`python scripts/verify_offline.py`); the FC timer is the deployment envelope
around that same code.
