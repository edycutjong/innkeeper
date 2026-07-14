"""FakeQwen adjudication policies — genuinely computed per archetype, never
reading the ground-truth labels. Each verdict cites ≥2 systems."""

from __future__ import annotations

import pytest

from innkeeper_audit.matcher import match_night
from innkeeper_audit.qwen import FakeQwen
from innkeeper_audit.qwen.base import EvidenceContext
from innkeeper_audit.schemas import Classification, Mismatch, MismatchKind, Txn
from innkeeper_audit.store import load_pms, load_processor

from conftest import ota_lines_for

CTX = EvidenceContext(night="2026-07-04", pms_sha="a" * 64, processor_sha="b" * 64, ota_sha="c" * 64)


def _verdicts(paths, night):
    mr = match_night(night, load_pms(paths, night), load_processor(paths, night),
                     ota_lines_for(paths, night))
    fake = FakeQwen()
    ctx = EvidenceContext(night=night, pms_sha="a" * 64, processor_sha="b" * 64, ota_sha="c" * 64)
    return {v.anchor_ref: v for v in (fake.adjudicate(m, ctx) for m in mr.mismatches)}


def test_ota_commission_is_fee_at_094(seeded):
    v = _verdicts(seeded, "2026-07-04")["folio-1042"]
    assert v.classification == Classification.FEE and v.subtype == "ota_commission"
    assert v.confidence == 0.94
    assert v.materiality_usd == 5.67


def test_ota_commission_cites_bbox(seeded):
    v = _verdicts(seeded, "2026-07-04")["folio-1042"]
    assert any(e.bbox for e in v.evidence)
    assert {e.src for e in v.evidence} == {"pms", "ota"}


def test_fx_rounding_is_fx_at_097(seeded):
    v = _verdicts(seeded, "2026-07-04")["folio-1044"]
    assert v.classification == Classification.FX and v.subtype == "fx_rounding"
    assert v.confidence == 0.97


def test_rolling_reserve_is_timing_at_093(seeded):
    v = _verdicts(seeded, "2026-07-04")["folio-1048"]
    assert v.classification == Classification.TIMING and v.subtype == "rolling_reserve"
    assert v.confidence == 0.93


def test_walkin_is_true_error_at_06_with_two_hypotheses(seeded):
    v = _verdicts(seeded, "2026-07-04")["stl-e0777"]
    assert v.classification == Classification.TRUE_ERROR
    assert v.confidence == 0.60
    ps = sorted((h.p for h in v.hypotheses), reverse=True)
    assert ps == [0.60, 0.40]  # the "knows what it doesn't know" split


def test_reserve_release_is_benign_timing(seeded):
    v = _verdicts(seeded, "2026-07-11")["stl-00064"]
    assert v.classification == Classification.TIMING and v.subtype == "reserve_release"
    assert v.confidence >= 0.85


def test_duplicate_is_duplicate_at_090(seeded):
    v = _verdicts(seeded, "2026-07-11")["stl-00198"]
    assert v.classification == Classification.DUPLICATE
    assert v.confidence == 0.90


def test_promo_cofunding_reads_the_footnote(seeded):
    # night 9, folio-1137? the footnote sits on room 201's line; find it by
    # the promo subtype
    vs = _verdicts(seeded, "2026-07-09")
    promo = [v for v in vs.values() if v.subtype == "promo_cofunding"]
    assert promo, "the footnoted promo co-funding line must be recognised"
    assert promo[0].classification == Classification.FEE
    assert promo[0].confidence >= 0.85  # still auto-clears


def test_escalation_is_unknown_and_flagged(seeded):
    vs = _verdicts(seeded, "2026-07-21")
    esc = [v for v in vs.values() if v.escalation]
    assert esc
    assert esc[0].classification == Classification.UNKNOWN
    assert esc[0].escalation == "two_pass_disagreement"


@pytest.mark.parametrize("night", ["2026-07-04", "2026-07-11", "2026-07-17", "2026-07-21"])
def test_all_verdicts_cite_two_systems(seeded, night):
    for v in _verdicts(seeded, night).values():
        assert len({e.src for e in v.evidence}) >= 2


def test_adjudicator_does_not_read_ground_truth(seeded):
    # sanity: FakeQwen has no access to the labels — classification is computed.
    import inspect

    src = inspect.getsource(FakeQwen)
    assert "ground_truth" not in src and "load_ground_truth" not in src


def test_hypotheses_probabilities_never_exceed_one(seeded):
    for night in ["2026-07-04", "2026-07-09", "2026-07-11", "2026-07-17", "2026-07-21"]:
        for v in _verdicts(seeded, night).values():
            assert sum(h.p for h in v.hypotheses) <= 1.0 + 1e-9


# ============================================================================
# synthetic edge cases the honest 30-night seed never happens to plant: every
# planted OTA gap is exactly 3% commission (+ the one footnoted promo), and
# every planted processor delta is exactly FX rounding or a 5% reserve, so
# FakeQwen's "I genuinely don't know" fallbacks never fire against the real
# fixtures. Hand-build a Mismatch for each so those honest "unknown" verdicts
# are exercised too.
# ============================================================================

def test_ota_delta_with_no_commission_or_footnote_match_is_unknown():
    line = {"line_no": 1, "payout": 90.99, "gross": 100.0, "bbox": [0.0, 0.0, 10.0, 10.0], "page": 1}
    m = Mismatch(
        mismatch_id="m-01", night="2026-07-01", kind=MismatchKind.AMOUNT_DELTA,
        tier="ref_exact", anchor_ref="folio-9101", pms_ref="folio-9101",
        counterpart_ref="ota-line-1", counterpart_src="ota",
        amounts={"pms": 100.0, "ota": 90.99},
        delta_cents=999, materiality_cents=999,  # not 3% of $100 (300¢), no footnote
        txns=[], flags={"ota_line": line, "ota_gross_cents": 10000, "two_pass_disagreement": False},
    )
    v = FakeQwen().adjudicate(m, CTX)
    assert v.classification == Classification.UNKNOWN
    assert v.subtype == "ota_gap"
    assert len({e.src for e in v.evidence}) >= 2


def test_processor_delta_with_no_fx_or_reserve_signature_is_unknown():
    m = Mismatch(
        mismatch_id="m-02", night="2026-07-01", kind=MismatchKind.AMOUNT_DELTA,
        tier="ref_exact", anchor_ref="folio-9102", pms_ref="folio-9102",
        counterpart_ref="stl-9102", counterpart_src="processor",
        amounts={"pms": 100.0, "processor": 96.67},
        delta_cents=333, materiality_cents=333,  # not FX (not EUR/±40¢), not 5% reserve (500¢)
        txns=[], flags={"proc_memo": "misc adjustment", "proc_currency": "USD"},
    )
    v = FakeQwen().adjudicate(m, CTX)
    assert v.classification == Classification.UNKNOWN
    assert v.subtype == "unexplained_delta"


def test_orphan_on_the_pms_side_is_a_true_error():
    # the matcher's "OTA folio with no statement line" / "leftover PMS card
    # row" branches both set orphan_side to something other than "processor";
    # FakeQwen routes that to the unsettled-charge true-error path.
    m = Mismatch(
        mismatch_id="m-03", night="2026-07-01", kind=MismatchKind.ORPHAN,
        tier="unmatched", anchor_ref="folio-9103", pms_ref="folio-9103",
        counterpart_ref=None, counterpart_src=None,
        amounts={"pms": 155.0}, delta_cents=0, materiality_cents=15500,
        txns=[], flags={"orphan_side": "pms"},
    )
    v = FakeQwen().adjudicate(m, CTX)
    assert v.classification == Classification.TRUE_ERROR
    assert v.subtype == "unsettled_charge"
    assert {e.src for e in v.evidence} == {"pms", "processor"}  # cites the PMS absence too


# ---- FakeQwen's static helpers: fallbacks the matcher never triggers ------ #

def test_pms_ref_falls_back_to_the_pms_txn_when_pms_ref_is_unset():
    m = Mismatch(
        mismatch_id="m-04", night="2026-07-01", kind=MismatchKind.ORPHAN,
        tier="unmatched", anchor_ref="stl-1", pms_ref=None,
        counterpart_ref="stl-1", counterpart_src="processor",
        amounts={}, delta_cents=0, materiality_cents=100,
        txns=[Txn(src="pms", ref="folio-7", amount_cents=100, date="2026-07-01")],
        flags={},
    )
    assert FakeQwen._pms_ref(m) == "folio-7"


def test_pms_ref_falls_back_to_anchor_ref_when_no_pms_txn_exists():
    m = Mismatch(
        mismatch_id="m-05", night="2026-07-01", kind=MismatchKind.ORPHAN,
        tier="unmatched", anchor_ref="stl-2", pms_ref=None,
        counterpart_ref="stl-2", counterpart_src="processor",
        amounts={}, delta_cents=0, materiality_cents=50,
        txns=[], flags={},
    )
    assert FakeQwen._pms_ref(m) == "stl-2"


def test_proc_txn_returns_none_when_no_processor_txn_is_present():
    m = Mismatch(
        mismatch_id="m-06", night="2026-07-01", kind=MismatchKind.ORPHAN,
        tier="unmatched", anchor_ref="folio-8", pms_ref="folio-8",
        counterpart_ref=None, counterpart_src=None,
        amounts={}, delta_cents=0, materiality_cents=10,
        txns=[Txn(src="pms", ref="folio-8", amount_cents=10, date="2026-07-01")],
        flags={"orphan_side": "pms"},
    )
    assert FakeQwen._proc_txn(m) is None
