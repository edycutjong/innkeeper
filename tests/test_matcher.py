"""The deterministic matcher is tested against the ground-truth labels BEFORE
any model is involved: every labelled discrepancy must surface, none spurious,
and the three tiers must each fire."""

from __future__ import annotations

import pytest

from innkeeper_audit.config import all_nights
from innkeeper_audit.matcher import edit_distance, match_night
from innkeeper_audit.schemas import MismatchKind, Txn
from innkeeper_audit.store import load_pms, load_processor

from conftest import ota_lines_for


def _match(paths, night):
    return match_night(night, load_pms(paths, night), load_processor(paths, night),
                       ota_lines_for(paths, night))


# ---- edit distance (fuzzy tier primitive) -------------------------------- #

@pytest.mark.parametrize("a,b,d", [
    ("folio-1234-E5", "folio-1234-E5", 0),
    ("folio-1234-E5", "folio-1234-_E5", 1),
    ("abc", "abd", 1),
    ("abc", "abcde", 2),
])
def test_edit_distance(a, b, d):
    assert edit_distance(a, b) == d


def test_edit_distance_caps():
    assert edit_distance("aaaa", "bbbb", cap=2) == 3  # cap+1 short-circuit


def test_edit_distance_length_diff_short_circuits_before_the_dp_loop():
    # len("a") - len("abcdef") = 5 > cap(2) -> the length guard returns
    # cap+1 immediately, never entering the Levenshtein DP loop.
    assert edit_distance("a", "abcdef", cap=2) == 3


# ---- coverage vs ground truth across the whole month --------------------- #

@pytest.mark.parametrize("night", all_nights())
def test_every_labelled_mismatch_surfaces(seeded, ground_truth, night):
    mr = _match(seeded, night)
    surfaced = {m.anchor_ref for m in mr.mismatches}
    labelled = {k.split("/", 1)[1] for k in ground_truth if k.startswith(night + "/")}
    assert labelled - surfaced == set(), f"labelled but not surfaced on {night}"


@pytest.mark.parametrize("night", all_nights())
def test_no_spurious_mismatches(seeded, ground_truth, night):
    mr = _match(seeded, night)
    surfaced = {m.anchor_ref for m in mr.mismatches}
    labelled = {k.split("/", 1)[1] for k in ground_truth if k.startswith(night + "/")}
    assert surfaced - labelled == set(), f"surfaced but unlabelled on {night}"


@pytest.mark.parametrize("night", all_nights())
def test_mismatch_ids_unique_and_ordered(seeded, night):
    mr = _match(seeded, night)
    ids = [m.mismatch_id for m in mr.mismatches]
    assert ids == sorted(ids)  # m-01, m-02, ... ascending
    assert len(set(ids)) == len(ids)
    mats = [m.materiality_cents for m in mr.mismatches]
    assert mats == sorted(mats)  # numbered by materiality ascending


# ---- the demo night ------------------------------------------------------ #

def test_night4_has_exactly_twelve(seeded):
    mr = _match(seeded, "2026-07-04")
    assert len(mr.mismatches) == 12


def test_night4_seventh_is_the_189_commission(seeded):
    mr = _match(seeded, "2026-07-04")
    m7 = mr.mismatches[6]
    assert m7.mismatch_id == "m-07"
    assert m7.anchor_ref == "folio-1042"
    assert m7.delta_cents == 567  # $189.00 - $183.33
    assert m7.counterpart_src == "ota"


def test_night4_twelfth_is_the_walkin(seeded):
    mr = _match(seeded, "2026-07-04")
    m12 = mr.mismatches[11]
    assert m12.mismatch_id == "m-12"
    assert m12.anchor_ref == "stl-e0777"
    assert m12.kind == MismatchKind.ORPHAN
    assert m12.materiality_cents == 31000


# ---- tiers --------------------------------------------------------------- #

def test_ref_exact_tier_fires(seeded):
    mr = _match(seeded, "2026-07-04")
    assert mr.tier_stats["ref_exact"] > 0


def test_amount_date_tier_recovers_dropped_ref(seeded):
    # night 11 has a drop_ref extra the matcher must still pair on amount+date
    total_amount_date = sum(_match(seeded, n).tier_stats["amount_date"] for n in all_nights())
    assert total_amount_date > 0


def test_fuzzy_tier_recovers_typod_ref(seeded):
    total_fuzzy = sum(_match(seeded, n).tier_stats["fuzzy"] for n in all_nights())
    assert total_fuzzy > 0


def test_cash_rows_are_noops_not_mismatches(seeded):
    # cash-paid rows never become mismatches
    total_cash = sum(_match(seeded, n).tier_stats["cash_noop"] for n in all_nights())
    assert total_cash > 0


def test_duplicate_detected_on_night_11(seeded):
    mr = _match(seeded, "2026-07-11")
    assert any(m.kind == MismatchKind.DUPLICATE_CANDIDATE for m in mr.mismatches)


def test_reserve_releases_are_orphans(seeded):
    mr = _match(seeded, "2026-07-11")
    releases = [m for m in mr.mismatches
                if m.kind == MismatchKind.ORPHAN and m.flags.get("proc_kind") == "reserve_release"]
    assert releases


def test_extraction_escalation_on_pagebreak_night(seeded):
    mr = _match(seeded, "2026-07-21")
    assert any(m.kind == MismatchKind.EXTRACTION_ESCALATION for m in mr.mismatches)


def test_both_true_error_nights_produce_orphans(seeded):
    for night, ref in [("2026-07-04", "stl-e0777"), ("2026-07-17", "stl-00320")]:
        mr = _match(seeded, night)
        assert any(m.anchor_ref == ref and m.kind == MismatchKind.ORPHAN for m in mr.mismatches)


# ---- synthetic edge cases the 30-night seed never happens to plant -------- #
# (the seed's OTA folios always have a statement line, and every PMS card row
# always settles, so these two matcher branches need a hand-built input.)

def test_ota_folio_with_no_statement_line_is_an_orphan():
    pms = [Txn(src="pms", ref="folio-9001", amount_cents=15000, date="2026-07-01",
               method="ota_collect")]
    mr = match_night("2026-07-01", pms, [], [])  # no OTA lines extracted at all
    assert len(mr.mismatches) == 1
    m = mr.mismatches[0]
    assert m.kind == MismatchKind.ORPHAN
    assert m.anchor_ref == "folio-9001"
    assert m.flags["orphan_side"] == "ota"
    assert m.materiality_cents == 15000


def test_leftover_pms_card_row_with_no_settlement_is_an_orphan():
    pms = [Txn(src="pms", ref="folio-9002", amount_cents=12900, date="2026-07-01",
               method="card")]
    mr = match_night("2026-07-01", pms, [], [])  # no processor settlements at all
    assert len(mr.mismatches) == 1
    m = mr.mismatches[0]
    assert m.kind == MismatchKind.ORPHAN
    assert m.anchor_ref == "folio-9002"
    assert m.counterpart_src is None
    assert m.flags["orphan_side"] == "pms"
    assert m.materiality_cents == 12900
