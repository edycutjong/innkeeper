# Benchmark — Innkeeper

Seeded month, 30 nights, 1199 transactions, FakeQwen (deterministic, offline). Regenerate with `python scripts/bench.py`.

| metric | value | target |
|---|---|---|
| classification accuracy | **0.9964** | ≥ 0.92 |
| HITL action accuracy | 1.0000 | — |
| **false auto-clears on true errors** | **0** | **0 (invariant)** |
| auto-cleared / mismatches | 277/281 (98.58%) | — |
| queue precision / recall | 1.00 / 1.00 | — |
| residue fraction (LLM-touched) | 23.44% | small |
| runtime (30 nights, offline) | 0.16s | < 5 min/night |
| modelled cost / night | $0.0327 | ~$0.15 |

## Per-class

| class | n | class-correct | action-correct |
|---|---|---|---|
| duplicate | 1 | 1/1 | 1/1 |
| fee | 135 | 134/135 | 135/135 |
| fx | 41 | 41/41 | 41/41 |
| timing | 102 | 102/102 | 102/102 |
| true_error | 2 | 2/2 | 2/2 |

## τ-sweep (E[loss] = amount × (1 − confidence) ≤ τ)

| τ (¢) | auto-clear rate | cleared | false clears |
|---|---|---|---|
| 100 | 96.80% | 272 | 0 |
| 250 | 98.58% | 277 | 0 |
| 500 | 98.58% | 277 | 0 |
| 750 | 98.58% | 277 | 0 |
| 1000 | 98.58% | 277 | 0 |
| 2500 | 98.93% | 278 | 0 |
| 5000 | 98.93% | 278 | 0 |

_The false-clear column is 0 across the entire τ sweep: the `true_error` and extraction-escalation constraints hard-queue at every threshold, so the risk knob trades automation against review load without ever touching the safety floor._

Class disagreements (1): 2026-07-21/folio-1250: got unknown, want fee [escalated: declined to classify]
