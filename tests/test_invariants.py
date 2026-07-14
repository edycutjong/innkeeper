"""Invariants I1–I5 (COMPLEXITY §2). These are the load-bearing tests: GREEN
here is the gate. I1 in particular — zero false auto-clears on the planted true
errors across the whole 30-night month — is the promise the whole product makes.
"""

from __future__ import annotations

import pytest

from innkeeper_audit.config import all_nights
from innkeeper_audit.crypto import verify_chain, verify_evidence_bindings
from innkeeper_audit.pipeline import replay_night
from innkeeper_audit.schemas import Classification, canonical_json
from innkeeper_audit.store import evidence_dir, load_close, read_json
from innkeeper_audit.verify import verify_night


# ======================================================================= #
# I1 — zero false auto-clears on true errors (the load-bearing invariant)
# ======================================================================= #

def test_I1_no_true_error_ever_auto_clears(month_run, ground_truth):
    _, results = month_run
    offenders = []
    for r in results:
        for v in r.verdicts:
            label = ground_truth.get(f"{v.night}/{v.anchor_ref}")
            if label and label["class"] == "true_error" and v.action == "auto_clear":
                offenders.append(f"{v.night}/{v.anchor_ref}")
    assert offenders == [], f"FALSE AUTO-CLEAR on true error(s): {offenders}"


@pytest.mark.parametrize("night,ref", [("2026-07-04", "stl-e0777"), ("2026-07-17", "stl-00320")])
def test_I1_each_planted_true_error_is_queued(month_run, night, ref):
    paths, results = month_run
    by_night = {r.night: r for r in results}
    v = next(v for v in by_night[night].verdicts if v.anchor_ref == ref)
    assert v.classification == Classification.TRUE_ERROR
    assert v.action == "queue"


def test_I1_true_errors_are_actually_present(month_run, ground_truth):
    # guard against the invariant passing vacuously
    te = [k for k, v in ground_truth.items() if v["class"] == "true_error"]
    assert len(te) == 2


# ======================================================================= #
# I2 — every verdict cites ≥2 systems with resolvable hashes
# ======================================================================= #

@pytest.mark.parametrize("night", all_nights())
def test_I2_two_systems_and_resolvable(month_run, night):
    paths, results = month_run
    verdicts = next(r.verdicts for r in results if r.night == night)
    ok, errs = verify_evidence_bindings(evidence_dir(paths, night), verdicts)
    assert ok, errs


def test_I2_every_verdict_has_at_least_two_distinct_systems(month_run):
    _, results = month_run
    for r in results:
        for v in r.verdicts:
            assert len({e.src for e in v.evidence}) >= 2


# ======================================================================= #
# I3 — chain verifies; a one-byte tamper fails
# ======================================================================= #

def test_I3_full_chain_verifies(month_run):
    paths, results = month_run
    closes = [load_close(paths, r.night) for r in results]
    ok, errs = verify_chain(closes)
    assert ok, errs


def test_I3_one_byte_verdict_tamper_breaks_the_night(month_run):
    paths, _ = month_run
    night = "2026-07-04"
    vpath = paths.run_dir(night) / "verdicts.json"
    original = vpath.read_bytes()
    try:
        doc = read_json(vpath)
        doc["verdicts"][0]["confidence"] = round(doc["verdicts"][0]["confidence"] - 0.01, 4)
        vpath.write_bytes(canonical_json(doc).encode("utf-8"))
        assert not verify_night(paths, night).ok
    finally:
        vpath.write_bytes(original)
    assert verify_night(paths, night).ok  # restored


def test_I3_one_byte_evidence_tamper_breaks_binding(month_run):
    paths, _ = month_run
    night = "2026-07-04"
    epath = evidence_dir(paths, night) / "pms.json"
    original = epath.read_bytes()
    try:
        epath.write_bytes(original.replace(b"folio-1040", b"folio-9999", 1))
        assert not verify_night(paths, night).evidence_ok
    finally:
        epath.write_bytes(original)


def test_I3_tampering_close_root_fails_signature(month_run):
    paths, _ = month_run
    close = load_close(paths, "2026-07-04")
    close.merkle_root = "0" * 64
    from innkeeper_audit.crypto import verify_close

    assert not verify_close(close)


# ======================================================================= #
# I4 — replay reproduces identical verdicts + root
# ======================================================================= #

@pytest.mark.parametrize("night", all_nights())
def test_I4_replay_is_identical(month_run, night):
    paths, _ = month_run
    _, ok, diffs = replay_night(paths, night)
    assert ok, diffs


def test_I4_replay_reproduces_signature(month_run):
    paths, _ = month_run
    result, ok, _ = replay_night(paths, "2026-07-04")
    stored = load_close(paths, "2026-07-04")
    assert result.close.signature == stored.signature


# ======================================================================= #
# I5 — two-pass extraction disagreement always escalates
# ======================================================================= #

def test_I5_pagebreak_night_has_an_escalation(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-21")
    escalated = [v for v in r.verdicts if v.escalation == "two_pass_disagreement"]
    assert escalated, "the planted page-broken row must escalate"


def test_I5_all_escalations_queue(month_run):
    _, results = month_run
    escalations = [v for r in results for v in r.verdicts if v.escalation]
    assert escalations  # non-vacuous
    assert all(v.action == "queue" for v in escalations)


def test_I5_escalation_declines_to_classify(month_run):
    _, results = month_run
    for r in results:
        for v in r.verdicts:
            if v.escalation:
                assert v.classification == Classification.UNKNOWN
