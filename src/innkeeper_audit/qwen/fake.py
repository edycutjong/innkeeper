"""FakeQwen — a deterministic, offline stand-in for the Qwen Cloud surface.

**It does not read the ground-truth labels.** Every classification is *computed*
from the mismatch's own arithmetic and memos — the same signals a human night
auditor (or ``qwen3.7-max`` reading the same rows) would use:

  * a delta that equals exactly 3% of gross ⇒ OTA commission;
  * that delta plus a footnoted amount ⇒ commission + promo co-funding (the
    agent had to *read the small print* to explain it);
  * a sub-$0.40 delta on a EUR card ⇒ FX rounding;
  * a delta that equals exactly 5% held ⇒ rolling reserve (timing);
  * a lone processor credit whose memo says "reserve release" ⇒ benign timing;
  * a lone processor **sale** with no PMS folio ⇒ an unposted charge → true error;
  * the same auth captured twice ⇒ duplicate;
  * a two-pass extraction disagreement ⇒ escalate, never average (I5).

Because the labels are untouched, ``bench.py`` measures a *real* agreement rate
between this reasoning and the ground truth. Extraction reads the committed
statement sidecar (the fixture is keyed to the PDF by sha256) and surfaces the
planted two-pass disagreement on the page-broken row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..amounts import pct_of
from ..schemas import (
    Classification,
    EvidenceRef,
    Hypothesis,
    Mismatch,
    MismatchKind,
    Verdict,
    sha256_hex,
)
from .base import EvidenceContext

FX_ROUNDING_CAP_CENTS = 40  # ±$0.40 is the noise band
RESERVE_PCT = 5
COMMISSION_PCT = 3


class FakeQwen:
    """Deterministic adjudicator + extractor. ``model`` names the fixture."""

    model = "fake-qwen/rules-v1"

    # ------------------------------------------------------------------ #
    # extraction (qwen3-vl-plus stand-in)
    # ------------------------------------------------------------------ #

    def extract_statement(self, paths: Any, month: str) -> list[dict[str, Any]]:
        """Parse the committed statement fixture into per-line records.

        Two-pass protocol: pass A reads ``payout``, pass B reads
        ``pass_b_payout`` (equal on every clean row, divergent on the planted
        page-broken row). Disagreement is flagged, never silently reconciled.
        """
        from ..store import load_sidecar

        sidecar = load_sidecar(paths, month)
        pdf_path: Path = paths.ota_pdf(month)
        # the fixture is bound to THIS pdf by sha256 (honest provenance)
        if pdf_path.exists():
            actual = sha256_hex(pdf_path.read_bytes())
            if actual != sidecar.get("pdf_sha256"):
                raise ValueError(
                    f"statement sidecar sha256 mismatch: fixture is for a different PDF "
                    f"({actual[:12]} != {sidecar.get('pdf_sha256', '')[:12]})"
                )
        lines: list[dict[str, Any]] = []
        for entry in sidecar["lines"]:
            pass_a = entry["payout"]
            pass_b = entry.get("pass_b_payout", pass_a)
            rec = dict(entry)
            rec["pass_a_payout"] = pass_a
            rec["pass_b_payout"] = pass_b
            rec["two_pass_disagreement"] = pass_a != pass_b
            # accepted value is pass A; when the passes disagree the matcher
            # routes the line to an extraction escalation regardless.
            rec["payout"] = pass_a
            lines.append(rec)
        return lines

    def extract_statement_for_night(self, paths: Any, month: str, night: str) -> list[dict[str, Any]]:
        return [l for l in self.extract_statement(paths, month) if l["night"] == night]

    # ------------------------------------------------------------------ #
    # adjudication (qwen3.7-max + thinking stand-in)
    # ------------------------------------------------------------------ #

    def adjudicate(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        if m.kind == MismatchKind.EXTRACTION_ESCALATION:
            return self._escalate_extraction(m, ctx)
        if m.kind == MismatchKind.DUPLICATE_CANDIDATE:
            return self._duplicate(m, ctx)
        if m.kind == MismatchKind.ORPHAN:
            return self._orphan(m, ctx)
        # AMOUNT_DELTA — split by which second system it reconciles against
        if m.counterpart_src == "ota":
            return self._ota_delta(m, ctx)
        return self._processor_delta(m, ctx)

    # ---- amount-delta vs OTA statement -------------------------------- #

    def _ota_delta(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        line = m.flags["ota_line"]
        gross = m.flags["ota_gross_cents"]
        delta = m.delta_cents  # gross - payout = commission (+ footnote adj)
        commission = pct_of(gross, COMMISSION_PCT, 100)
        footnote_adj = round(line.get("footnote_adjustment", 0.0) * 100)
        pms = self._pms_ref(m)
        evidence = [ctx.ota_line(line), ctx.pms_row(pms)]

        if footnote_adj and delta == commission + footnote_adj:
            # the agent had to read the footnote asterisk to reconcile the total
            return self._verdict(
                m, ctx, Classification.FEE, "promo_cofunding", 0.88, evidence,
                [Hypothesis(h=f"3% commission (${commission/100:.2f}) + "
                            f"${footnote_adj/100:.2f} promo co-funding per statement footnote", p=0.88),
                 Hypothesis(h="OTA double-charged commission", p=0.10)],
                rationale=f"delta ${delta/100:.2f} = 3% commission + footnoted promo co-funding "
                          f"({line.get('footnote_text', '')})",
            )
        if delta == commission and not footnote_adj:
            return self._verdict(
                m, ctx, Classification.FEE, "ota_commission", 0.94, evidence,
                [Hypothesis(h="3% OTA commission withheld at source", p=0.94),
                 Hypothesis(h="partial refund", p=0.05)],
                rationale=f"${gross/100:.2f} gross − ${line['payout']:.2f} payout = "
                          f"${delta/100:.2f} = exactly 3%",
            )
        # unexplained OTA gap — do not guess
        return self._verdict(
            m, ctx, Classification.UNKNOWN, "ota_gap", 0.55, evidence,
            [Hypothesis(h="unexplained OTA payout gap", p=0.55),
             Hypothesis(h="commission plus an unlisted adjustment", p=0.40)],
            rationale=f"delta ${delta/100:.2f} ≠ 3% commission ${commission/100:.2f}",
        )

    # ---- amount-delta vs processor ------------------------------------ #

    def _processor_delta(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        memo = (m.flags.get("proc_memo") or "").lower()
        currency = m.flags.get("proc_currency", "USD")
        delta = m.delta_cents
        pms_cents = round(m.amounts.get("pms", 0.0) * 100)
        pms = self._pms_ref(m)
        proc = m.counterpart_ref or ""
        proc_row = self._proc_txn(m)
        evidence = [
            ctx.pms_row(pms),
            ctx.processor_row(proc, batch=proc_row.get("batch") if proc_row else None,
                              row=proc_row.get("row") if proc_row else None),
        ]

        if (currency == "EUR" or "fx" in memo) and abs(delta) <= FX_ROUNDING_CAP_CENTS:
            return self._verdict(
                m, ctx, Classification.FX, "fx_rounding", 0.97, evidence,
                [Hypothesis(h="EUR→USD FX conversion rounding", p=0.97),
                 Hypothesis(h="processor rounding", p=0.03)],
                rationale=f"${abs(delta)/100:.2f} delta on a EUR card, within the ±$0.40 band",
            )
        if "reserve" in memo and delta == pct_of(pms_cents, RESERVE_PCT, 100):
            return self._verdict(
                m, ctx, Classification.TIMING, "rolling_reserve", 0.93, evidence,
                [Hypothesis(h="5% rolling reserve held 7 days; self-heals on release", p=0.93),
                 Hypothesis(h="partial capture", p=0.07)],
                rationale=f"processor short by exactly 5% (${delta/100:.2f}); memo: {m.flags.get('proc_memo','')}",
            )
        return self._verdict(
            m, ctx, Classification.UNKNOWN, "unexplained_delta", 0.55, evidence,
            [Hypothesis(h="unexplained settlement delta", p=0.55),
             Hypothesis(h="fee or timing not evidenced in the memo", p=0.40)],
            rationale=f"delta ${delta/100:.2f} with no matching fee/FX/reserve signature",
        )

    # ---- orphan processor rows ---------------------------------------- #

    def _orphan(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        proc_kind = m.flags.get("proc_kind", "sale")
        memo = (m.flags.get("proc_memo") or "").lower()
        orphan_side = m.flags.get("orphan_side")
        proc = m.counterpart_ref or ""
        proc_row = self._proc_txn(m)

        if orphan_side == "processor":
            evidence = [
                ctx.processor_row(proc, batch=proc_row.get("batch") if proc_row else None,
                                  row=proc_row.get("row") if proc_row else None),
                ctx.pms_absence(proc),
            ]
            if proc_kind == "reserve_release" or "reserve release" in memo:
                return self._verdict(
                    m, ctx, Classification.TIMING, "reserve_release", 0.95, evidence,
                    [Hypothesis(h="reserve release crediting back a prior 5% hold", p=0.95),
                     Hypothesis(h="unexpected processor credit", p=0.05)],
                    rationale=f"lone processor credit; memo: {m.flags.get('proc_memo','')}",
                )
            # a settlement (sale) with no PMS folio: money captured, nothing
            # posted to a guest — an unposted charge. TRUE ERROR (I1): queues.
            return self._verdict(
                m, ctx, Classification.TRUE_ERROR, "unposted_walkin", 0.60, evidence,
                [Hypothesis(h="room sold at the card terminal, never posted to a PMS folio", p=0.60),
                 Hypothesis(h="mis-keyed deposit or an OTA capture that failed to link", p=0.40)],
                rationale=f"processor sale ${m.materiality_cents/100:.2f} with no PMS folio; "
                          f"memo: {m.flags.get('proc_memo','')}",
            )
        # orphan on the PMS/OTA side — a charge that never settled
        pms = self._pms_ref(m)
        evidence = [ctx.pms_row(pms), ctx.processor_row(f"absence:{pms}")] if False else [
            ctx.pms_row(pms),
            EvidenceRef(src="processor", kind="absence",
                        uri=f"evidence/processor.json#absence:{pms}", sha256=ctx.processor_sha),
        ]
        return self._verdict(
            m, ctx, Classification.TRUE_ERROR, "unsettled_charge", 0.60, evidence,
            [Hypothesis(h="a posted charge that never reached settlement", p=0.60),
             Hypothesis(h="a same-night settlement that is simply late", p=0.40)],
            rationale=f"PMS/OTA charge ${m.materiality_cents/100:.2f} with no counterpart",
        )

    # ---- duplicate ---------------------------------------------------- #

    def _duplicate(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        pms = m.pms_ref or self._pms_ref(m)
        proc = m.counterpart_ref or ""
        proc_row = self._proc_txn(m)
        evidence = [
            ctx.pms_row(pms),
            ctx.processor_row(proc, batch=proc_row.get("batch") if proc_row else None,
                              row=proc_row.get("row") if proc_row else None),
        ]
        return self._verdict(
            m, ctx, Classification.DUPLICATE, "duplicate_capture", 0.90, evidence,
            [Hypothesis(h=f"same auth {m.flags.get('auth','')} captured twice", p=0.90),
             Hypothesis(h="a legitimate second, unrelated charge", p=0.10)],
            rationale=f"second settlement of an already-matched folio ({m.flags.get('original_ref','')})",
        )

    # ---- extraction escalation (I5) ----------------------------------- #

    def _escalate_extraction(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:
        line = m.flags["ota_line"]
        pms = self._pms_ref(m)
        evidence = [ctx.ota_line(line), ctx.pms_row(pms)]
        a, b = line.get("pass_a_payout", line["payout"]), line.get("pass_b_payout", line["payout"])
        return self._verdict(
            m, ctx, Classification.UNKNOWN, "extraction_disagreement", 0.50, evidence,
            [Hypothesis(h=f"page-broken row misread: pass-A ${a:.2f} vs pass-B ${b:.2f}", p=0.50),
             Hypothesis(h="true payout matches one pass; re-scan needed", p=0.50)],
            escalation="two_pass_disagreement",
            rationale="two-pass VL extraction disagreed on the page-broken payout; escalating, "
                      "not averaging (invariant I5)",
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _pms_ref(m: Mismatch) -> str:
        if m.pms_ref:
            return m.pms_ref
        for t in m.txns:
            if t.src == "pms":
                return t.ref
        return m.anchor_ref

    @staticmethod
    def _proc_txn(m: Mismatch) -> dict[str, Any] | None:
        for t in m.txns:
            if t.src == "processor":
                return t.raw
        return None

    def _verdict(
        self,
        m: Mismatch,
        ctx: EvidenceContext,
        classification: Classification,
        subtype: str,
        confidence: float,
        evidence: list[EvidenceRef],
        hypotheses: list[Hypothesis],
        escalation: str | None = None,
        rationale: str = "",
    ) -> Verdict:
        return Verdict(
            mismatch_id=m.mismatch_id,
            night=m.night,
            anchor_ref=m.anchor_ref,
            pms_ref=m.pms_ref,
            amounts=m.amounts,
            classification=classification,
            subtype=subtype,
            confidence=confidence,
            evidence=evidence,
            hypotheses=hypotheses,
            materiality_usd=round(m.materiality_cents / 100.0, 2),
            delta_usd=round(m.delta_cents / 100.0, 2),
            rationale=rationale,
            model=self.model,
            escalation=escalation,
        )
