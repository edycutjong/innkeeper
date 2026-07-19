# Morning report — 2026-07-04

> **11 auto-cleared · 1 for you · books closed** · 10 matched of 39 transactions

Night close signed by `689bcf7a1dbcaaf1…` · Merkle root `d175694c4fd5427b…` · chained to `91293bfe…`

## For you
- `m-12` **TRUE ERROR** (unposted_walkin) · $310.00 · conf 0.60 · cites [pms+processor]
    - processor sale $310.00 with no PMS folio; memo: keyed terminal capture 22:41
    - hypothesis: room sold at the card terminal, never posted to a PMS folio — p=0.60
    - hypothesis: mis-keyed deposit or an OTA capture that failed to link — p=0.40
    - E[loss] = $310.00 × (1 − 0.60) = 12400¢ → queued

## Auto-cleared
- **OTA / processor fee** × 4 · $20.01 total
- **FX rounding** × 4 · $0.69 total
- **timing** × 3 · $23.15 total

_Δ reconciled tonight: $43.01 · pipeline `innkeeper-audit/1.1.1+rules-v1`_
