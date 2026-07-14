"""Deterministic three-way matcher (SPEC §4, no LLM).

The matcher clears the easy ~95% of transactions with pure arithmetic and
string logic, so the language model only ever sees the *residue*. Two
reconciliations run per night:

  * **PMS card rows ↔ processor settlements** — three tiers:
      1. ``ref_exact``   processor.folio == pms.ref
      2. ``fuzzy``       unique bounded-edit-distance folio when the ref is typo'd
      3. ``amount_date`` unique (amount, date) pair when the ref was dropped
    Equal amounts ⇒ a clean match; unequal ⇒ an ``amount_delta`` mismatch
    (FX / rolling-reserve). Leftover processor rows become ``orphan`` mismatches
    (reserve releases, and the planted unposted walk-in true error); a second
    capture of an already-matched folio is a ``duplicate_candidate``.

  * **PMS OTA-collect rows ↔ OTA statement lines** — paired by folio; the
    gross-vs-payout gap is always surfaced (commission at minimum). A line
    carrying a two-pass extraction disagreement becomes an
    ``extraction_escalation`` (invariant I5) instead of an amount delta.

Cash-paid PMS rows expect no settlement and are cleared as no-ops. Everything
here is a pure function of its inputs — no ground-truth, no randomness — so it
is unit-tested against the labels *before* any model is involved.
"""

from __future__ import annotations

from typing import Any

from .amounts import to_dollars
from .schemas import Mismatch, MismatchKind, MatchResult, Txn

FUZZY_MAX_DIST = 2


# --------------------------------------------------------------------------- #
# small bounded edit distance
# --------------------------------------------------------------------------- #


def edit_distance(a: str, b: str, cap: int = FUZZY_MAX_DIST) -> int:
    """Levenshtein distance, short-circuited once it exceeds ``cap``."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #


def _amounts(pms: int | None = None, processor: int | None = None, ota: int | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    if pms is not None:
        out["pms"] = to_dollars(pms)
    if processor is not None:
        out["processor"] = to_dollars(processor)
    if ota is not None:
        out["ota"] = to_dollars(ota)
    return out


def match_night(
    night: str,
    pms: list[Txn],
    processor: list[Txn],
    ota_lines: list[dict[str, Any]],
) -> MatchResult:
    """Reconcile one night. ``ota_lines`` are the (already extracted) statement
    rows for this night; each may carry a ``two_pass_disagreement`` flag."""
    raw_mismatches: list[dict[str, Any]] = []
    matched_pairs: list[dict[str, Any]] = []
    tier_stats: dict[str, int] = {
        "ref_exact": 0, "amount_date": 0, "fuzzy": 0, "cash_noop": 0, "ota": 0,
    }

    # ----- partition inputs ------------------------------------------------- #
    pms_card = [t for t in pms if t.method == "card"]
    pms_cash = [t for t in pms if t.method == "cash"]
    pms_ota = [t for t in pms if t.method == "ota_collect"]
    proc_sales = [t for t in processor if t.kind == "sale"]
    proc_other = [t for t in processor if t.kind != "sale"]  # reserve releases etc.

    tier_stats["cash_noop"] = len(pms_cash)  # paid at the desk; no counterpart

    pms_by_ref: dict[str, Txn] = {t.ref: t for t in pms_card}
    consumed_pms: set[str] = set()
    consumed_proc: set[str] = set()
    # auth -> pms.ref of the settlement that already matched it (duplicate hunt)
    matched_auth: dict[str, str] = {}

    def _clean_or_delta(p: Txn, s: Txn, tier: str) -> None:
        tier_stats[tier] += 1
        auth = s.raw.get("auth")
        if p.amount_cents == s.amount_cents:
            matched_pairs.append(
                {"pms_ref": p.ref, "counterpart_ref": s.ref, "counterpart_src": "processor",
                 "tier": tier, "amount_cents": p.amount_cents}
            )
            if auth:
                matched_auth[auth] = p.ref
        else:
            delta = p.amount_cents - s.amount_cents
            raw_mismatches.append(
                {"kind": MismatchKind.AMOUNT_DELTA, "tier": tier, "anchor_ref": p.ref,
                 "pms_ref": p.ref, "counterpart_ref": s.ref, "counterpart_src": "processor",
                 "amounts": _amounts(pms=p.amount_cents, processor=s.amount_cents),
                 "delta_cents": delta, "materiality_cents": abs(delta),
                 "txns": [p, s], "flags": {"proc_memo": s.memo, "proc_currency": s.currency}}
            )
            if auth:
                matched_auth[auth] = p.ref
        consumed_pms.add(p.ref)
        consumed_proc.add(s.ref)

    # ----- tier 1: exact folio ref ----------------------------------------- #
    for s in proc_sales:
        if s.ref in consumed_proc or not s.folio:
            continue
        p = pms_by_ref.get(s.folio)
        if p is not None and p.ref not in consumed_pms:
            _clean_or_delta(p, s, "ref_exact")

    # ----- tier 2: unique fuzzy folio (typo'd ref) ------------------------- #
    # A near-identical folio is stronger evidence than a coincidental amount,
    # so the fuzzy-ref tier runs before the amount+date tier.
    for s in proc_sales:
        if s.ref in consumed_proc or not s.folio:
            continue
        cands = [
            p for p in pms_card
            if p.ref not in consumed_pms
            and p.date == s.date
            and p.amount_cents == s.amount_cents
            and 0 < edit_distance(p.ref, s.folio) <= FUZZY_MAX_DIST
        ]
        if len(cands) == 1:
            _clean_or_delta(cands[0], s, "fuzzy")

    # ----- tier 3: unique (amount, date) when the ref was dropped ---------- #
    for s in proc_sales:
        if s.ref in consumed_proc:
            continue
        cands = [
            p for p in pms_card
            if p.ref not in consumed_pms and p.amount_cents == s.amount_cents and p.date == s.date
        ]
        if len(cands) == 1:
            _clean_or_delta(cands[0], s, "amount_date")

    # ----- leftover processor sales: duplicate vs orphan ------------------- #
    for s in proc_sales:
        if s.ref in consumed_proc:
            continue
        auth = s.raw.get("auth")
        if auth and auth in matched_auth:
            orig = matched_auth[auth]
            raw_mismatches.append(
                {"kind": MismatchKind.DUPLICATE_CANDIDATE, "tier": "unmatched", "anchor_ref": s.ref,
                 "pms_ref": orig, "counterpart_ref": s.ref, "counterpart_src": "processor",
                 "amounts": _amounts(pms=s.amount_cents, processor=s.amount_cents),
                 "delta_cents": 0, "materiality_cents": s.amount_cents,
                 "txns": [pms_by_ref[orig], s] if orig in pms_by_ref else [s],
                 "flags": {"auth": auth, "original_ref": orig, "proc_memo": s.memo}}
            )
        else:
            # orphan processor sale: no PMS folio at all → the unposted-walk-in
            # true error lives here (the adjudicator distinguishes it from a
            # benign credit by memo/kind — the matcher stays neutral).
            raw_mismatches.append(
                {"kind": MismatchKind.ORPHAN, "tier": "unmatched", "anchor_ref": s.ref,
                 "pms_ref": None, "counterpart_ref": s.ref, "counterpart_src": "processor",
                 "amounts": _amounts(processor=s.amount_cents),
                 "delta_cents": 0, "materiality_cents": s.amount_cents,
                 "txns": [s], "flags": {"proc_memo": s.memo, "proc_kind": s.kind,
                                        "orphan_side": "processor"}}
            )
        consumed_proc.add(s.ref)

    # ----- processor non-sales (reserve releases) are always orphans ------- #
    for s in proc_other:
        raw_mismatches.append(
            {"kind": MismatchKind.ORPHAN, "tier": "unmatched", "anchor_ref": s.ref,
             "pms_ref": None, "counterpart_ref": s.ref, "counterpart_src": "processor",
             "amounts": _amounts(processor=s.amount_cents),
             "delta_cents": 0, "materiality_cents": s.amount_cents,
             "txns": [s], "flags": {"proc_memo": s.memo, "proc_kind": s.kind,
                                    "orphan_side": "processor"}}
        )

    # ----- OTA folios ↔ statement lines ------------------------------------ #
    ota_by_folio: dict[str, dict[str, Any]] = {l["folio"]: l for l in ota_lines}
    for p in pms_ota:
        line = ota_by_folio.get(p.ref)
        if line is None:
            # an OTA folio with no statement line — a genuine orphan
            raw_mismatches.append(
                {"kind": MismatchKind.ORPHAN, "tier": "unmatched", "anchor_ref": p.ref,
                 "pms_ref": p.ref, "counterpart_ref": None, "counterpart_src": "ota",
                 "amounts": _amounts(pms=p.amount_cents),
                 "delta_cents": 0, "materiality_cents": p.amount_cents,
                 "txns": [p], "flags": {"orphan_side": "ota"}}
            )
            continue
        tier_stats["ota"] += 1
        payout_cents = round(line["payout"] * 100)
        gross_cents = round(line["gross"] * 100)
        delta = p.amount_cents - payout_cents  # commission (+ any footnote adj)
        disagree = bool(line.get("two_pass_disagreement"))
        kind = MismatchKind.EXTRACTION_ESCALATION if disagree else MismatchKind.AMOUNT_DELTA
        raw_mismatches.append(
            {"kind": kind, "tier": "ref_exact", "anchor_ref": p.ref,
             "pms_ref": p.ref, "counterpart_ref": f"ota-line-{line['line_no']}",
             "counterpart_src": "ota",
             "amounts": _amounts(pms=p.amount_cents, ota=payout_cents),
             "delta_cents": delta, "materiality_cents": abs(delta),
             "txns": [p],
             "flags": {"ota_line": line, "ota_gross_cents": gross_cents,
                       "two_pass_disagreement": disagree}}
        )

    # ----- leftover PMS card rows: unsettled orphans ----------------------- #
    for p in pms_card:
        if p.ref in consumed_pms:
            continue
        raw_mismatches.append(
            {"kind": MismatchKind.ORPHAN, "tier": "unmatched", "anchor_ref": p.ref,
             "pms_ref": p.ref, "counterpart_ref": None, "counterpart_src": None,
             "amounts": _amounts(pms=p.amount_cents),
             "delta_cents": 0, "materiality_cents": p.amount_cents,
             "txns": [p], "flags": {"orphan_side": "pms"}}
        )

    # ----- number mismatches by materiality (stable demo ordering) --------- #
    raw_mismatches.sort(key=lambda m: (m["materiality_cents"], m["anchor_ref"]))
    mismatches = [
        Mismatch(mismatch_id=f"m-{i:02d}", night=night, **m)
        for i, m in enumerate(raw_mismatches, 1)
    ]

    n_txns = len(pms) + len(processor)
    n_matched = len(matched_pairs) + len(pms_cash)
    return MatchResult(
        night=night,
        n_txns=n_txns,
        n_matched=n_matched,
        matched_pairs=matched_pairs,
        mismatches=mismatches,
        tier_stats=tier_stats,
    )
