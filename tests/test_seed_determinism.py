"""The seeded month is deterministic (byte-identical --regen) and plants every
archetype + PDF hazard the audit depends on."""

from __future__ import annotations

import random
from pathlib import Path

from innkeeper_audit.config import Paths
from innkeeper_audit.seed import FOOTNOTE_NIGHT, _stay_plan, generate_month
from innkeeper_audit.store import load_ground_truth, load_sidecar, read_json


def _fresh(tmp_path) -> Paths:
    p = Paths(root=Path(tmp_path))
    generate_month(p)
    return p


def test_regen_is_byte_identical(tmp_path):
    p = Paths(root=Path(tmp_path))
    m1 = generate_month(p)
    m2 = generate_month(p)
    assert m1["files"] == m2["files"]
    assert m1["pdf_sha256"] == m2["pdf_sha256"]


def test_pdf_is_byte_identical_across_roots(tmp_path_factory):
    a = _fresh(tmp_path_factory.mktemp("a"))
    b = _fresh(tmp_path_factory.mktemp("b"))
    assert a.ota_pdf().read_bytes() == b.ota_pdf().read_bytes()


def test_ground_truth_counts(seeded):
    gt = read_json(seeded.ground_truth)
    counts = gt["counts"]
    assert counts["total"] == 281
    assert counts["true_error"] == 2
    assert counts["duplicate"] == 1
    assert counts["fee"] > 0 and counts["timing"] > 0 and counts["fx"] > 0


def test_both_true_errors_present(seeded):
    gt = load_ground_truth(seeded)
    te = [k for k, v in gt.items() if v["class"] == "true_error"]
    assert set(te) == {"2026-07-04/stl-e0777", "2026-07-17/stl-00320"}
    for k in te:
        assert gt[k]["expected_action"] == "queue"


def test_walkin_amounts_in_rate_grid(seeded):
    # the walk-ins are $310 and $155 — real room rates, so they cannot be
    # trivially dismissed
    proc4 = read_json(seeded.processor_dir / "2026-07-04.json")["txns"]
    assert any(t["ref"] == "stl-e0777" and t["amount_cents"] == 31000 for t in proc4)


def test_pdf_hazards_present_in_sidecar(seeded):
    sc = load_sidecar(seeded, "2026-07")
    assert sc["font_pt"] == 8  # H1: 8-pt table text
    assert any(l.get("footnote_adjustment") for l in sc["lines"])  # H2: footnote adj
    assert any(l.get("hazard") == "page_broken" for l in sc["lines"])  # H3: page break


def test_page_broken_row_has_two_pass_divergence(seeded):
    sc = load_sidecar(seeded, "2026-07")
    pb = [l for l in sc["lines"] if l.get("hazard") == "page_broken"]
    assert pb
    for l in pb:
        assert l["pass_b_payout"] != l["payout"]  # the planted I5 disagreement


def test_footnote_changes_a_total(seeded):
    sc = load_sidecar(seeded, "2026-07")
    assert sc["totals"]["adjustments"] > 0  # the * co-funding hits the total


def test_manifest_excludes_sealed(seeded):
    manifest = read_json(seeded.manifest)
    assert not any(k.endswith(".sealed") for k in manifest["files"])


def test_sealed_statement_written(seeded):
    assert seeded.ota_sealed("2026-07").exists()


def test_thirty_nights_of_fixtures(seeded):
    assert seeded.pms_dir.exists()
    nights = sorted(p.stem for p in seeded.pms_dir.glob("*.json"))
    assert len(nights) == 30
    assert nights[0] == "2026-07-01" and nights[-1] == "2026-07-30"


def test_stay_plan_guarantees_room_201_on_the_footnote_night():
    """Room 201 must always appear on FOOTNOTE_NIGHT (the promo co-funding
    footnote is hand-anchored to it). The fixed SEED's random draw happens to
    include 201 in its initial room sample every time, so the correction
    fallback (`if "201" not in rooms: rooms = ...`) never fires against the
    real fixtures. Force the random sample to omit 201 to exercise it."""

    class _Never201(random.Random):
        def sample(self, population, k):
            result = super().sample(population, k)
            if "201" in result:
                pool = list(population)
                replacement = next(x for x in pool if x not in result)
                result = [replacement if x == "201" else x for x in result]
            return result

    plan = _stay_plan(_Never201(f"seed-test:{FOOTNOTE_NIGHT}"), FOOTNOTE_NIGHT)
    rooms = [s["room"] for s in plan]
    assert "201" in rooms  # the fallback correction put it back
    assert len(rooms) == len(set(rooms))  # still no duplicate rooms


def test_render_statement_pushes_totals_to_a_new_page_when_the_last_page_is_full(tmp_path):
    """pdfgen reserves 6 rows of headroom for the totals block; when the last
    page already has more rows than that, the totals block must wrap to a
    fresh page rather than overprint. The real 30-night statement never lands
    exactly on this boundary, so build a synthetic statement that does."""
    from innkeeper_audit.pdfgen import ROWS_PER_PAGE, render_statement

    lines = [
        {
            "line_no": i, "night": "2026-07-01", "folio": f"folio-{1000 + i}",
            "guest": "T. Test", "room": "101", "gross": 100.0,
            "commission": 3.0, "payout": 97.0,
        }
        for i in range(1, ROWS_PER_PAGE + 1)  # exactly fills page 1: rows_on_page == ROWS_PER_PAGE
    ]
    totals = {"gross": 100.0 * len(lines), "commission": 3.0 * len(lines),
              "adjustments": 0.0, "payout": 97.0 * len(lines)}
    sidecar = render_statement("2026-07", lines, totals, tmp_path / "statement.pdf")
    assert sidecar["pages"] == 2  # totals wrapped onto a second page
    assert len(sidecar["lines"]) == len(lines)


def test_repo_root_falls_back_to_the_package_layout_without_the_env_override(monkeypatch):
    """Every other test sets INNKEEPER_ROOT (directly or via the `seeded` /
    `cli_root` fixtures); with it unset, `Paths()` must still resolve to a
    real, existing directory by walking up from config.py's own location."""
    from innkeeper_audit.config import repo_root

    monkeypatch.delenv("INNKEEPER_ROOT", raising=False)
    root = repo_root()
    assert root.is_absolute()
    assert root.is_dir()
    assert (root / "src" / "innkeeper_audit" / "config.py").exists()
