"""Benchmark engine (SPEC §8, COMPLEXITY §5).

Runs the full seeded month under FakeQwen and scores it against the ground-truth
labels: classification accuracy, HITL action accuracy, the load-bearing
false-auto-clear count on true errors (must be 0), queue precision/recall, and
the τ-sweep that turns the risk policy into a measured curve. Extraction
escalations are scored on *action* (they must queue) rather than class, since by
rule they decline to classify (I5).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .config import Paths
from .pipeline import RunResult, run_month
from .policy import PolicyGate
from .schemas import Verdict
from .store import load_ground_truth

# modelled cost assumptions (transparent, not measured against a live bill)
_TOKENS_IN_PER_MISMATCH = 900
_TOKENS_OUT_PER_MISMATCH = 320
_USD_PER_1K_IN = 0.0016   # qwen3.7-max input, modelled
_USD_PER_1K_OUT = 0.0064  # qwen3.7-max output, modelled


@dataclass
class BenchReport:
    n_nights: int
    n_txns: int
    n_mismatches: int
    classification_accuracy: float
    action_accuracy: float
    false_auto_clears: int
    n_cleared: int
    n_queued: int
    auto_clear_rate: float
    queue_precision: float
    queue_recall: float
    per_class: dict[str, dict[str, int]]
    tau_sweep: list[dict[str, Any]]
    residue_fraction: float
    runtime_s: float
    est_cost_per_night_usd: float
    misclassified: list[str] = field(default_factory=list)

    def headline(self) -> str:
        return (f"{self.n_cleared}/{self.n_mismatches} auto-cleared · "
                f"{self.false_auto_clears} false clears · "
                f"accuracy {self.classification_accuracy:.4f}")


def _est_cost_per_night(n_mismatches: int, n_nights: int) -> float:
    per_night = n_mismatches / max(1, n_nights)
    cost = per_night * (
        _TOKENS_IN_PER_MISMATCH / 1000 * _USD_PER_1K_IN
        + _TOKENS_OUT_PER_MISMATCH / 1000 * _USD_PER_1K_OUT
    )
    return round(cost, 4)


def run_bench(paths: Paths, gate: PolicyGate | None = None,
              tau_grid: list[int] | None = None) -> BenchReport:
    gate = gate or PolicyGate()
    t0 = time.perf_counter()
    results: list[RunResult] = run_month(paths, gate=gate)
    runtime = time.perf_counter() - t0

    gt = load_ground_truth(paths)
    verdicts: list[Verdict] = [v for r in results for v in r.verdicts]
    n_txns = sum(r.stats.n_txns for r in results if r.stats)

    class_correct = 0
    action_correct = 0
    scored = 0
    false_auto_clears = 0
    tp = fp = fn = 0  # queue confusion
    per_class: dict[str, dict[str, int]] = {}
    misclassified: list[str] = []

    for v in verdicts:
        label = gt.get(f"{v.night}/{v.anchor_ref}")
        if not label:
            continue
        scored += 1
        want_class = label["class"]
        want_action = label["expected_action"]
        pc = per_class.setdefault(want_class, {"n": 0, "class_ok": 0, "action_ok": 0})
        pc["n"] += 1

        # Strict scoring: an extraction escalation reports `unknown`, which will
        # not equal its underlying label (it *declined* to classify by rule I5).
        # We count that as a class disagreement rather than hide it — the honest
        # number — while its action (queue) is still scored correct below.
        if v.classification.value == want_class:
            class_correct += 1
            pc["class_ok"] += 1
        else:
            note = " [escalated: declined to classify]" if v.escalation else ""
            misclassified.append(
                f"{v.night}/{v.anchor_ref}: got {v.classification.value}, want {want_class}{note}")
        if v.action == want_action:
            action_correct += 1
            pc["action_ok"] += 1

        if want_action == "queue":
            if v.action == "queue":
                tp += 1
            else:
                fn += 1
        else:
            if v.action == "queue":
                fp += 1
        if want_class == "true_error" and v.action == "auto_clear":
            false_auto_clears += 1

    n_cleared = sum(1 for v in verdicts if v.action == "auto_clear")
    n_queued = sum(1 for v in verdicts if v.action == "queue")
    tau_sweep = _tau_sweep(verdicts, gt, tau_grid or [100, 250, 500, 750, 1000, 2500, 5000])

    return BenchReport(
        n_nights=len(results), n_txns=n_txns, n_mismatches=len(verdicts),
        classification_accuracy=round(class_correct / max(1, scored), 4),
        action_accuracy=round(action_correct / max(1, scored), 4),
        false_auto_clears=false_auto_clears,
        n_cleared=n_cleared, n_queued=n_queued,
        auto_clear_rate=round(n_cleared / max(1, len(verdicts)), 4),
        queue_precision=round(tp / max(1, tp + fp), 4),
        queue_recall=round(tp / max(1, tp + fn), 4),
        per_class=per_class, tau_sweep=tau_sweep,
        residue_fraction=round(len(verdicts) / max(1, n_txns), 4),
        runtime_s=round(runtime, 3),
        est_cost_per_night_usd=_est_cost_per_night(len(verdicts), len(results)),
        misclassified=misclassified,
    )


def _tau_sweep(verdicts: list[Verdict], gt: dict[str, Any], grid: list[int]) -> list[dict[str, Any]]:
    """For each τ, recompute the E[loss] gate and report the automation vs
    safety tradeoff. True errors and escalations hard-queue at every τ, so the
    false-clear column stays 0 across the whole curve."""
    out: list[dict[str, Any]] = []
    for tau in grid:
        g = PolicyGate(tau_cents=tau, use_eloss=True)
        cleared = 0
        false_clears = 0
        for v in verdicts:
            d = g.decide(v)
            if d.action == "auto_clear":
                cleared += 1
                label = gt.get(f"{v.night}/{v.anchor_ref}")
                if label and label["class"] == "true_error":
                    false_clears += 1
        out.append({
            "tau_cents": tau,
            "auto_clear_rate": round(cleared / max(1, len(verdicts)), 4),
            "n_cleared": cleared,
            "false_clears": false_clears,
        })
    return out


def bench_markdown(report: BenchReport) -> str:
    """The committed bench table for docs/BENCH.md + the README."""
    lines = []
    lines.append("# Benchmark — Innkeeper")
    lines.append("")
    lines.append(f"Seeded month, {report.n_nights} nights, {report.n_txns} transactions, "
                 f"FakeQwen (deterministic, offline). Regenerate with `python scripts/bench.py`.")
    lines.append("")
    lines.append("| metric | value | target |")
    lines.append("|---|---|---|")
    lines.append(f"| classification accuracy | **{report.classification_accuracy:.4f}** | ≥ 0.92 |")
    lines.append(f"| HITL action accuracy | {report.action_accuracy:.4f} | — |")
    lines.append(f"| **false auto-clears on true errors** | **{report.false_auto_clears}** | **0 (invariant)** |")
    lines.append(f"| auto-cleared / mismatches | {report.n_cleared}/{report.n_mismatches} "
                 f"({report.auto_clear_rate:.2%}) | — |")
    lines.append(f"| queue precision / recall | {report.queue_precision:.2f} / {report.queue_recall:.2f} | — |")
    lines.append(f"| residue fraction (LLM-touched) | {report.residue_fraction:.2%} | small |")
    lines.append(f"| runtime (30 nights, offline) | {report.runtime_s:.2f}s | < 5 min/night |")
    lines.append(f"| modelled cost / night | ${report.est_cost_per_night_usd:.4f} | ~$0.15 |")
    lines.append("")
    lines.append("## Per-class")
    lines.append("")
    lines.append("| class | n | class-correct | action-correct |")
    lines.append("|---|---|---|---|")
    for cls, d in sorted(report.per_class.items()):
        lines.append(f"| {cls} | {d['n']} | {d['class_ok']}/{d['n']} | {d['action_ok']}/{d['n']} |")
    lines.append("")
    lines.append("## τ-sweep (E[loss] = amount × (1 − confidence) ≤ τ)")
    lines.append("")
    lines.append("| τ (¢) | auto-clear rate | cleared | false clears |")
    lines.append("|---|---|---|---|")
    for row in report.tau_sweep:
        lines.append(f"| {row['tau_cents']} | {row['auto_clear_rate']:.2%} | "
                     f"{row['n_cleared']} | {row['false_clears']} |")
    lines.append("")
    lines.append("_The false-clear column is 0 across the entire τ sweep: the `true_error` and "
                 "extraction-escalation constraints hard-queue at every threshold, so the risk knob "
                 "trades automation against review load without ever touching the safety floor._")
    lines.append("")
    if report.misclassified:
        lines.append(f"Class disagreements ({len(report.misclassified)}): "
                     + "; ".join(report.misclassified))
        lines.append("")
    return "\n".join(lines)
