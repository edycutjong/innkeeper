"""bench.py scoring: accuracy floor, the zero-false-clear invariant, queue
precision/recall, and the τ-sweep whose false-clear column stays 0 throughout."""

from __future__ import annotations

import pytest

from innkeeper_audit.benchmark import _tau_sweep, bench_markdown, run_bench
from innkeeper_audit.schemas import Classification, EvidenceRef, Hypothesis, Verdict


@pytest.fixture(scope="module")
def report(seeded):
    return run_bench(seeded)


def test_accuracy_clears_floor(report):
    assert report.classification_accuracy >= 0.92


def test_zero_false_auto_clears(report):
    assert report.false_auto_clears == 0


def test_action_accuracy_is_perfect(report):
    # every HITL decision matches the intended policy label
    assert report.action_accuracy == 1.0


def test_queue_precision_and_recall(report):
    assert report.queue_precision == 1.0
    assert report.queue_recall == 1.0


def test_counts_add_up(report):
    assert report.n_cleared + report.n_queued == report.n_mismatches
    assert report.n_mismatches == 281


def test_single_class_disagreement_is_the_escalation(report):
    # the only class mismatch is the page-broken row declining to classify
    assert len(report.misclassified) == 1
    assert "escalated" in report.misclassified[0]


def test_tau_sweep_monotonic_and_safe(report):
    rates = [row["auto_clear_rate"] for row in report.tau_sweep]
    assert rates == sorted(rates)  # automation rises with τ
    assert all(row["false_clears"] == 0 for row in report.tau_sweep)  # safety floor holds


def test_tau_sweep_spans_a_range(report):
    rates = [row["auto_clear_rate"] for row in report.tau_sweep]
    assert rates[0] < rates[-1]  # the knob actually moves the needle


def test_residue_and_cost_reported(report):
    assert 0 < report.residue_fraction < 1
    assert report.est_cost_per_night_usd > 0


def test_bench_markdown_has_table(report):
    md = bench_markdown(report)
    assert "false auto-clears on true errors" in md
    assert "τ-sweep" in md
    assert "| classification accuracy |" in md


def test_headline_format(report):
    assert "false clears" in report.headline()


# ---- edge cases the clean 30-night seed never happens to trigger --------- #

def test_tau_sweep_counts_false_clears_on_a_misclassified_true_error():
    # _tau_sweep is exercised end-to-end above with real data, where the
    # seeded month's true_errors always classify correctly and so the
    # false-clear column stays 0 (by design, invariant I1). To exercise the
    # counter itself, feed it a synthetic *misclassification*: a verdict the
    # adjudicator got wrong (called it a routine fee) whose ground truth says
    # true_error — exactly the case the safety floor exists to catch.
    h = "a" * 64
    v = Verdict(
        mismatch_id="m-01", night="2026-07-01", anchor_ref="stl-99999",
        classification=Classification.FEE, subtype="ota_commission", confidence=0.99,
        evidence=[EvidenceRef(src="pms", uri="a", sha256=h),
                  EvidenceRef(src="processor", uri="b", sha256=h)],
        hypotheses=[Hypothesis(h="x", p=0.99)],
        materiality_usd=1.0, delta_usd=1.0,
    )
    gt = {"2026-07-01/stl-99999": {"class": "true_error", "expected_action": "queue"}}
    rows = _tau_sweep([v], gt, [100_000])  # a huge tau auto-clears everything
    assert rows[0]["n_cleared"] == 1
    assert rows[0]["false_clears"] == 1


def test_run_bench_skips_verdicts_with_no_ground_truth_label(seeded, monkeypatch):
    # the seeded month labels every surfaced mismatch (matcher tests assert
    # this 1:1), so run_bench's own defensive "unlabelled verdict" skip never
    # fires against the real fixtures. Strip one label to exercise it.
    import innkeeper_audit.benchmark as benchmark_mod
    from innkeeper_audit.store import load_ground_truth as real_load_gt

    def stripped_gt(paths):
        gt = dict(real_load_gt(paths))
        assert gt.pop("2026-07-04/folio-1042", None) is not None
        return gt

    monkeypatch.setattr(benchmark_mod, "load_ground_truth", stripped_gt)
    stripped_report = run_bench(seeded)
    assert stripped_report.n_mismatches == 281  # every mismatch is still adjudicated
    assert sum(d["n"] for d in stripped_report.per_class.values()) == 280  # one goes unscored


def test_run_bench_counts_queue_confusion_and_false_auto_clear_misses(seeded):
    """The seeded month's queue precision/recall and false_auto_clears are all
    perfect (1.0 / 1.0 / 0) by construction (invariant I1), so run_bench's own
    false-positive / false-negative / false-auto-clear counters never
    increment against the real fixtures. Force one gate mismatch in each
    direction with a wrapper gate to exercise the counting branches a clean
    run never touches."""
    from innkeeper_audit.policy import DEFAULT_GATE

    class _ForcingGate:
        def apply(self, verdict):
            d = DEFAULT_GATE.apply(verdict)
            if verdict.night == "2026-07-04" and verdict.anchor_ref == "folio-1042":
                # normally auto_clears (fee, conf 0.94) -> force a false positive
                verdict.action = "queue"
            if verdict.night == "2026-07-04" and verdict.anchor_ref == "stl-e0777":
                # normally queues (true_error) -> force a false negative AND
                # a false auto-clear on a true error, in one move
                verdict.action = "auto_clear"
            return d

    report = run_bench(seeded, gate=_ForcingGate())
    assert report.queue_precision < 1.0
    assert report.queue_recall < 1.0
    assert report.false_auto_clears == 1
