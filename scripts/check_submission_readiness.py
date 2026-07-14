#!/usr/bin/env python
"""Submission readiness gate.

    python scripts/check_submission_readiness.py

Checks the deliverables the submission checklist requires exist and that the
core invariants still hold. Prints a checklist and exits non-zero if anything
mandatory is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from innkeeper_audit.benchmark import run_bench  # noqa: E402
from innkeeper_audit.config import Paths  # noqa: E402

MANDATORY = [
    "README.md",
    "LICENSE",
    "DEMO.md",
    "pyproject.toml",
    "docs/BENCH.md",
    "docs/friction-log.md",
    "infra/fc/s.yaml",
    "infra/fc/PROOF.md",
    "mcp/pms_server.py",
    "mcp/processor_server.py",
    "mcp/ota_server.py",
    "scripts/bench.py",
    "scripts/verify_offline.py",
    "src/innkeeper_audit/cli.py",
    "src/innkeeper_audit/crypto.py",
    "src/innkeeper_audit/matcher.py",
    "src/innkeeper_audit/policy.py",
    "src/innkeeper_audit/qwen/fake.py",
    "src/innkeeper_audit/qwen/live.py",
    "tests",
]

OPTIONAL = ["docs/SPEC-AUDIT.md", "docs/X402.md"]


def _count_tests() -> int:
    import re
    import subprocess

    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only"],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        m = re.search(r"(\d+)\s+tests?\s+collected", out.stdout)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return -1


def main() -> int:
    ok = True
    print("mandatory deliverables:")
    for rel in MANDATORY:
        exists = (ROOT / rel).exists()
        ok = ok and exists
        print(f"  [{'x' if exists else ' '}] {rel}")

    print("optional:")
    for rel in OPTIONAL:
        print(f"  [{'x' if (ROOT / rel).exists() else ' '}] {rel}")

    n_tests = _count_tests()
    print(f"\npytest collected: {n_tests if n_tests >= 0 else 'unknown'} tests")

    paths = Paths()
    if paths.ground_truth.exists():
        report = run_bench(paths)
        print(f"bench: {report.headline()}")
        if report.false_auto_clears != 0 or report.classification_accuracy < 0.92:
            ok = False
            print("  ! bench invariant failed")
    else:
        print("bench: (fixtures not seeded — run scripts/bench.py)")

    print("\nREADY" if ok else "\nNOT READY — missing items above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
