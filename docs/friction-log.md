# Friction log — building Innkeeper

Honest notes on what fought back. Kept because the friction *is* the argument for
the design choices.

## OTA statements are hostile documents on purpose

The seeded statement is rendered with the three hazards a real partner statement
throws at you, and each one shaped a rule:

1. **8-pt table text.** The whole settlement table renders at 8 points. This is
   why the model is `qwen3-vl-plus` and not a lighter VL tier or plain OCR —
   dense small-print tables are exactly where the cheaper paths smear digits, and
   a smeared digit here is a wrong payout in someone's books. The bbox citation
   requirement falls out of this: every extracted figure carries the rectangle it
   came from, so a human can land on the pixel in dispute.

2. **A footnote asterisk that changes a total.** One line's payout carries a
   `*` — "less promotional co-funding $12.00" — and that same $12 is baked into
   the statement's Total Payout row. A naive `gross × 0.97` reconciliation
   silently over-counts by $12.00. The adjudicator only clears that line because
   it reads the footnote: the verdict's subtype is `promo_cofunding`, not
   `ota_commission`, and the rationale names the footnote. This is the single
   clearest "the model earned its keep" moment — the delta does **not** equal 3%,
   and the only way to explain it is to have read the small print.

3. **A row split across a page break.** One row's gross/commission sit at the
   bottom of a page and the payout cell is carried to the top of the next. This
   is the planted **two-pass disagreement**: pass A and pass B read different
   payouts for that row, and the rule is to *escalate, never average* (invariant
   I5). A money decision must never rest on a figure two reads couldn't agree on.

## The two-pass protocol

Extraction runs twice (in the live path, temperature-varied on
`qwen3-vl-plus`; in the offline fixture, the sidecar encodes both passes).
Agreement accepts the figure; disagreement flags the line, the matcher turns it
into an `extraction_escalation`, and the gate hard-queues it. There is no
"pick the higher-confidence read" — the whole point is that the agent knows when
it can't trust its own eyes.

## The determinism bug that actually bit (reportlab)

`--regen` is supposed to produce byte-identical fixtures, and it didn't: two
seeds of the same month produced different PDF bytes (and therefore a different
`pdf_sha256`, which cascades into the sidecar and the manifest). The cause was
subtle — `Canvas(...)` was created first and `canvas._doc.invariant = 1` set
*afterwards*, but the random document ID and CreationDate are seeded at canvas
construction, so the flag came too late. Fix: pass `invariant=1` to the
constructor. Determinism is a correctness property here, not a nicety — `replay`
(I4) and the whole tamper story (I3) rest on it, so this got its own test
(`test_regen_is_byte_identical`).

## Why the matcher is tested before the model

The load-bearing safety property — *never auto-clear a true error* — has to hold
regardless of what any model says. So the deterministic matcher is unit-tested
against the ground-truth labels first: across all 30 nights it surfaces exactly
the 281 planted discrepancies, no more, no fewer. The unposted walk-in can only
be auto-cleared if the matcher fails to surface it, so that coverage test is
upstream of everything the language model does.

## Residue is higher than a generic reconciler — deliberately

The LLM touches ~23% of transactions, not the ~5% a bare netting engine would.
That is a choice: Innkeeper adjudicates *every* fee/timing/FX gap into an
evidence-cited verdict rather than silently netting known deductions, because the
product is an auditable decision log, not a smaller number. The deterministic
matcher still clears ~77% at zero model cost, and the modelled spend is
~$0.03/night.
