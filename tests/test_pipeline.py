"""End-to-end run orchestration: fetch → extract → match → adjudicate → gate →
signed close, plus the month chain."""

from __future__ import annotations

from pathlib import Path

from innkeeper_audit.config import GENESIS_ROOT, Paths
from innkeeper_audit.pipeline import run_night
from innkeeper_audit.store import load_close, load_verdicts


def test_run_night_produces_signed_close(month_run):
    paths, _ = month_run
    close = load_close(paths, "2026-07-04")
    assert close.signature and close.signer_pubkey
    assert close.merkle_root and len(close.merkle_root) == 64


def test_run_night_writes_verdicts_and_evidence(month_run):
    paths, _ = month_run
    verdicts = load_verdicts(paths, "2026-07-04")
    assert len(verdicts) == 12
    from innkeeper_audit.store import evidence_dir

    ev = evidence_dir(paths, "2026-07-04")
    for name in ("pms.json", "processor.json", "ota_lines.json", "MANIFEST.json"):
        assert (ev / name).exists()


def test_demo_night_stats(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    assert r.stats.n_cleared == 11
    assert r.stats.n_queued == 1
    assert r.stats.n_mismatches == 12


def test_demo_verdict_7_auto_clears(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    v7 = r.verdicts[6]
    assert v7.mismatch_id == "m-07"
    assert v7.action == "auto_clear"
    assert v7.confidence == 0.94
    assert v7.materiality_usd == 5.67


def test_demo_verdict_12_queues(month_run):
    paths, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    v12 = r.verdicts[11]
    assert v12.action == "queue"
    assert v12.classification.value == "true_error"


def test_first_night_prev_root_is_genesis(month_run):
    paths, _ = month_run
    assert load_close(paths, "2026-07-01").prev_root == GENESIS_ROOT


def test_chain_is_linked_night_to_night(month_run):
    paths, _ = month_run
    c3 = load_close(paths, "2026-07-03")
    c4 = load_close(paths, "2026-07-04")
    assert c4.prev_root == c3.merkle_root


def test_gate_log_written(month_run):
    paths, _ = month_run
    from innkeeper_audit.store import read_json

    gate = read_json(paths.run_dir("2026-07-04") / "gate.json")
    assert len(gate["decisions"]) == 12
    assert any(d["action"] == "queue" for d in gate["decisions"])


def test_run_night_write_false_touches_nothing(seeded, tmp_path):
    # a compute-only run must not create a ledger under a clean root
    from innkeeper_audit.config import Paths
    from innkeeper_audit.seed import generate_month
    from pathlib import Path

    p = Paths(root=Path(tmp_path))
    generate_month(p)
    r = run_night(p, "2026-07-04", write=False)
    assert r.close is not None
    assert not (p.run_dir("2026-07-04") / "close.json").exists()


def test_residue_is_a_minority(month_run):
    _, results = month_run
    total_txns = sum(r.stats.n_txns for r in results)
    total_mismatch = sum(len(r.verdicts) for r in results)
    assert total_mismatch < total_txns * 0.5  # matcher clears the majority deterministically


def test_run_result_n_cleared_and_n_queued_match_stats(month_run):
    _, results = month_run
    r = next(r for r in results if r.night == "2026-07-04")
    assert r.n_cleared == r.stats.n_cleared == 11
    assert r.n_queued == r.stats.n_queued == 1


def test_prev_root_falls_back_to_genesis_for_an_unknown_night():
    # a night string outside the generated calendar can't be indexed into
    # `all_nights()`; the ValueError is caught and genesis is returned.
    from innkeeper_audit.config import GENESIS_ROOT
    from innkeeper_audit.pipeline import _prev_root

    assert _prev_root(Paths(root=Path("/nonexistent")), "2099-01-01", "2026-07") == GENESIS_ROOT


def test_load_evidence_manifest_round_trips(month_run):
    from innkeeper_audit.store import load_evidence_manifest

    paths, _ = month_run
    manifest = load_evidence_manifest(paths, "2026-07-04")
    assert manifest["night"] == "2026-07-04"
    assert {"pms.json", "processor.json", "ota_lines.json"} <= set(manifest["sha256"])


def test_replay_detects_every_kind_of_tamper(seeded, monkeypatch):
    """Force each of replay_night's four diff branches at once by making the
    'stored' close (as loaded inside pipeline.replay_night) diverge from the
    freshly re-derived one on every field it compares."""
    import innkeeper_audit.pipeline as pipeline_mod
    from innkeeper_audit.store import load_close as real_load_close

    night = "2026-07-04"
    run_night(seeded, night)  # make sure a real close is on disk to base the tamper on

    def tampered_load_close(paths, n):
        c = real_load_close(paths, n)
        c.merkle_root = "f" * 64
        c.verdict_hashes = ["e" * 64]
        c.signature = "a" * 128
        c.stats.n_cleared = c.stats.n_cleared + 999
        return c

    monkeypatch.setattr(pipeline_mod, "load_close", tampered_load_close)
    result, ok, diffs = pipeline_mod.replay_night(seeded, night)
    assert not ok
    assert any("merkle_root" in d for d in diffs)
    assert any("verdict_hashes" in d for d in diffs)
    assert any("signature" in d for d in diffs)
    assert any("stats" in d for d in diffs)
