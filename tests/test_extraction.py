"""FakeQwen PDF extraction: fixture keyed to the PDF by sha256, bbox per line,
and the planted two-pass disagreement on the page-broken row (I5 source)."""

from __future__ import annotations

import pytest

from innkeeper_audit.qwen import FakeQwen


def test_extract_returns_all_lines(seeded):
    lines = FakeQwen().extract_statement(seeded, "2026-07")
    assert len(lines) >= 100  # the whole month's OTA folios
    for l in lines:
        assert "bbox" in l and len(l["bbox"]) == 4
        assert l["pass_a_payout"] is not None


def test_extraction_fixture_bound_to_pdf_sha(seeded):
    # tamper the PDF → extraction must refuse (provenance check)
    pdf = seeded.ota_pdf("2026-07")
    original = pdf.read_bytes()
    try:
        pdf.write_bytes(original + b"%tamper")
        with pytest.raises(ValueError, match="sha256"):
            FakeQwen().extract_statement(seeded, "2026-07")
    finally:
        pdf.write_bytes(original)


def test_two_pass_disagreement_only_on_pagebroken(seeded):
    lines = FakeQwen().extract_statement(seeded, "2026-07")
    disagree = [l for l in lines if l["two_pass_disagreement"]]
    assert disagree, "the page-broken row must disagree"
    for l in disagree:
        assert l["hazard"] == "page_broken"
        assert l["pass_a_payout"] != l["pass_b_payout"]


def test_clean_lines_agree(seeded):
    lines = FakeQwen().extract_statement(seeded, "2026-07")
    clean = [l for l in lines if l.get("hazard") != "page_broken"]
    assert all(not l["two_pass_disagreement"] for l in clean)


def test_extract_for_night_filters(seeded):
    n4 = FakeQwen().extract_statement_for_night(seeded, "2026-07", "2026-07-04")
    assert n4 and all(l["night"] == "2026-07-04" for l in n4)


def test_demo_line_has_the_189_gross(seeded):
    n4 = FakeQwen().extract_statement_for_night(seeded, "2026-07", "2026-07-04")
    line = next(l for l in n4 if l["folio"] == "folio-1042")
    assert line["gross"] == 189.00
    assert line["payout"] == 183.33
    assert line["commission"] == 5.67
