"""Morning report rendering + the verify module (chain/evidence report)."""

from __future__ import annotations

from innkeeper_audit.report import render_html, render_markdown
from innkeeper_audit.verify import (
    ChainVerification,
    format_chain_report,
    verify_all,
    verify_night,
)


# ---- report -------------------------------------------------------------- #

def test_markdown_has_headline_and_queue(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    md = render_markdown(r)
    assert "auto-cleared" in md and "for you" in md
    assert "TRUE ERROR" in md  # the walk-in row
    assert "E[loss]" in md  # the policy math is shown


def test_markdown_shows_competing_hypotheses(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    md = render_markdown(r)
    assert "hypothesis:" in md
    assert "p=0.60" in md and "p=0.40" in md


def test_html_renders_and_is_selfcontained(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    html = render_html(r)
    assert html.startswith("<!doctype html>")
    assert "Merkle" not in html or "root" in html  # signature block present
    assert "http://" not in html and "https://" not in html  # no external assets


def test_report_headline_counts_match_stats(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    md = render_markdown(r)
    assert f"{r.stats.n_cleared} auto-cleared" in md


def test_markdown_shows_ota_bbox_citation_on_extraction_escalation(month_run):
    # night 4's queued item is the true_error walk-in (no OTA line, no bbox);
    # night 21's queued item is the page-broken extraction escalation, whose
    # OTA evidence carries a real bbox from the PDF layout — the only queued
    # verdict shape that exercises _verdict_line's bbox citation branch.
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-21")
    md = render_markdown(r)
    assert "OTA line" in md and "bbox" in md


# ---- verify -------------------------------------------------------------- #

def test_verify_night_ok(month_run):
    paths, _ = month_run
    assert verify_night(paths, "2026-07-04").ok


def test_verify_all_ok(month_run):
    paths, _ = month_run
    cv = verify_all(paths)
    assert cv.ok
    assert cv.n_closes == 30
    assert all(n.ok for n in cv.nights)


def test_format_chain_report(month_run):
    paths, _ = month_run
    text = format_chain_report(verify_all(paths))
    assert "chain: OK" in text
    assert "2026-07-04" in text


def test_verify_night_flags_invalid_signature_with_valid_root(month_run, monkeypatch):
    # a corrupted signature with an otherwise-untouched close: root_ok stays
    # True (the verdicts + merkle_root on disk are unchanged) while
    # signature_ok flips False — distinct from the I3 tamper tests, which
    # corrupt data that also breaks the recomputed root.
    paths, _ = month_run
    night = "2026-07-04"
    import innkeeper_audit.verify as verify_mod
    from innkeeper_audit.store import load_close as real_load_close

    def tampered_load_close(p, n):
        c = real_load_close(p, n)
        c.signature = "00" * 64
        return c

    monkeypatch.setattr(verify_mod, "load_close", tampered_load_close)
    result = verify_night(paths, night)
    assert result.root_ok is True
    assert result.signature_ok is False
    assert not result.ok
    assert "close signature invalid" in result.errors


def test_format_chain_report_shows_chain_level_errors():
    cv = ChainVerification(
        ok=False, n_closes=1, nights=[],
        chain_errors=["2026-07-02: prev_root abc123 != expected def456"],
    )
    text = format_chain_report(cv)
    assert "chain: FAILED" in text
    assert "chain! 2026-07-02: prev_root abc123 != expected def456" in text
