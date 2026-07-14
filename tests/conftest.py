"""Shared fixtures. The seeded month + full run are session-scoped (built once
into a temp root, fully hermetic — the real repo ledger is never touched)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    from innkeeper_audit.config import Paths
    from innkeeper_audit.seed import generate_month

    root = tmp_path_factory.mktemp("innkeeper_root")
    paths = Paths(root=Path(root))
    generate_month(paths)
    return paths


@pytest.fixture(scope="session")
def month_run(seeded):
    """Run every night once; return (paths, results)."""
    from innkeeper_audit.pipeline import run_month

    results = run_month(seeded)
    return seeded, results


@pytest.fixture(scope="session")
def ground_truth(seeded):
    from innkeeper_audit.store import load_ground_truth

    return load_ground_truth(seeded)


@pytest.fixture(scope="session")
def all_nights_list(seeded):
    from innkeeper_audit.config import all_nights

    return all_nights()


def ota_lines_for(paths, night: str):
    """The extracted OTA lines for a night, with the two-pass flag set."""
    from innkeeper_audit.qwen import FakeQwen

    return FakeQwen().extract_statement_for_night(paths, "2026-07", night)
