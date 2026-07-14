"""The `innkeeper` CLI — the judge's interface. Every command exits 0 against a
freshly seeded temp root (INNKEEPER_ROOT), hermetic from the repo ledger."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from innkeeper_audit.cli import app

runner = CliRunner()


@pytest.fixture(scope="module")
def cli_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("cli_root")
    import os

    os.environ["INNKEEPER_ROOT"] = str(root)
    assert runner.invoke(app, ["seed", "--nights", "30"]).exit_code == 0
    yield root
    os.environ.pop("INNKEEPER_ROOT", None)


def test_seed_reports_counts(cli_root):
    r = runner.invoke(app, ["seed", "--nights", "30"])
    assert r.exit_code == 0
    assert "281" in r.stdout


def test_run_night(cli_root):
    r = runner.invoke(app, ["run", "--night", "2026-07-04"])
    assert r.exit_code == 0
    assert "12 mismatches" in r.stdout
    assert "QUEUE m-12" in r.stdout


def test_run_all_prereq_nights_then_replay(cli_root):
    for d in range(1, 5):
        assert runner.invoke(app, ["run", "--night", f"2026-07-0{d}"]).exit_code == 0
    r = runner.invoke(app, ["replay", "--night", "2026-07-04"])
    assert r.exit_code == 0
    assert "IDENTICAL" in r.stdout


def test_verify_chain_single_night(cli_root):
    runner.invoke(app, ["run", "--night", "2026-07-01"])
    r = runner.invoke(app, ["verify-chain", "--night", "2026-07-01"])
    assert r.exit_code == 0
    assert "OK" in r.stdout


def test_bench_exits_zero_and_reports(cli_root):
    r = runner.invoke(app, ["bench"])
    assert r.exit_code == 0
    assert "0 false clears" in r.stdout


def test_bench_markdown(cli_root):
    r = runner.invoke(app, ["bench", "--markdown"])
    assert r.exit_code == 0
    assert "τ-sweep" in r.stdout


def test_report_renders(cli_root):
    r = runner.invoke(app, ["report", "--night", "2026-07-04"])
    assert r.exit_code == 0
    assert "auto-cleared" in r.stdout


def test_run_writes_report_flag(cli_root):
    r = runner.invoke(app, ["run", "--night", "2026-07-04", "--report"])
    assert r.exit_code == 0
    assert "report" in r.stdout.lower()


def test_report_html_flag(cli_root):
    r = runner.invoke(app, ["report", "--night", "2026-07-04", "--html"])
    assert r.exit_code == 0
    from innkeeper_audit.config import Paths

    paths = Paths()
    out = paths.run_dir("2026-07-04") / "report.html"
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_replay_reports_mismatch_when_stored_close_is_tampered(cli_root):
    night = "2026-07-25"
    assert runner.invoke(app, ["run", "--night", night]).exit_code == 0
    from innkeeper_audit.config import Paths
    from innkeeper_audit.store import read_json, write_json

    paths = Paths()
    close_path = paths.run_dir(night) / "close.json"
    original = close_path.read_bytes()
    try:
        doc = read_json(close_path)
        doc["merkle_root"] = "f" * 64
        write_json(close_path, doc)
        r = runner.invoke(app, ["replay", "--night", night])
        assert r.exit_code == 1
        assert "MISMATCH" in r.stdout
    finally:
        close_path.write_bytes(original)


def test_verify_chain_single_night_reports_failure(cli_root):
    night = "2026-07-26"
    assert runner.invoke(app, ["run", "--night", night]).exit_code == 0
    from innkeeper_audit.config import Paths
    from innkeeper_audit.store import read_json, write_json

    paths = Paths()
    close_path = paths.run_dir(night) / "close.json"
    original = close_path.read_bytes()
    try:
        doc = read_json(close_path)
        doc["signature"] = "00" * 64
        write_json(close_path, doc)
        r = runner.invoke(app, ["verify-chain", "--night", night])
        assert r.exit_code == 1
        assert "FAILED" in r.stdout
        assert "!" in r.stdout  # per-error lines are printed
    finally:
        close_path.write_bytes(original)


def test_verify_chain_whole_ledger_ok(cli_root):
    assert runner.invoke(app, ["run", "--night", "2026-07-27"]).exit_code == 0
    r = runner.invoke(app, ["verify-chain"])
    assert r.exit_code == 0
    assert "chain: OK" in r.stdout


def test_verify_chain_whole_ledger_reports_failure(cli_root):
    night = "2026-07-28"
    assert runner.invoke(app, ["run", "--night", night]).exit_code == 0
    from innkeeper_audit.config import Paths
    from innkeeper_audit.store import read_json, write_json

    paths = Paths()
    close_path = paths.run_dir(night) / "close.json"
    original = close_path.read_bytes()
    try:
        doc = read_json(close_path)
        doc["signature"] = "00" * 64
        write_json(close_path, doc)
        r = runner.invoke(app, ["verify-chain"])
        assert r.exit_code == 1
        assert "chain: FAILED" in r.stdout
    finally:
        close_path.write_bytes(original)


def test_bench_exits_nonzero_on_false_auto_clears(cli_root, monkeypatch):
    from innkeeper_audit.benchmark import BenchReport
    import innkeeper_audit.benchmark as benchmark_mod

    fake_report = BenchReport(
        n_nights=1, n_txns=10, n_mismatches=2, classification_accuracy=1.0,
        action_accuracy=1.0, false_auto_clears=1, n_cleared=1, n_queued=1,
        auto_clear_rate=0.5, queue_precision=1.0, queue_recall=1.0,
        per_class={}, tau_sweep=[], residue_fraction=0.2, runtime_s=0.01,
        est_cost_per_night_usd=0.01,
    )
    monkeypatch.setattr(benchmark_mod, "run_bench", lambda paths: fake_report)
    r = runner.invoke(app, ["bench"])
    assert r.exit_code == 1
