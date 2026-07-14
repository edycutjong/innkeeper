#!/usr/bin/env python
"""Run the benchmark, write docs/BENCH.md, and assert the invariants.

    python scripts/bench.py

Exit non-zero if classification accuracy < 0.92 or any true error was
auto-cleared (the load-bearing invariant). The written table is what the README
quotes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from innkeeper_audit.benchmark import bench_markdown, run_bench  # noqa: E402
from innkeeper_audit.config import Paths  # noqa: E402
from innkeeper_audit.seed import generate_month  # noqa: E402

ACCURACY_FLOOR = 0.92


def main() -> int:
    paths = Paths()
    if not paths.ground_truth.exists():
        print("seeding fixtures first…")
        generate_month(paths)

    report = run_bench(paths)
    md = bench_markdown(report)
    out = paths.root / "docs" / "BENCH.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    print(report.headline())
    print(f"  action accuracy {report.action_accuracy:.4f} · "
          f"queue P/R {report.queue_precision:.2f}/{report.queue_recall:.2f} · "
          f"residue {report.residue_fraction:.2%} · "
          f"runtime {report.runtime_s:.2f}s · modelled ${report.est_cost_per_night_usd:.4f}/night")
    print(f"  wrote {out}")

    ok = True
    if report.false_auto_clears != 0:
        print(f"FAIL: {report.false_auto_clears} false auto-clears on true errors (must be 0)")
        ok = False
    if report.classification_accuracy < ACCURACY_FLOOR:
        print(f"FAIL: accuracy {report.classification_accuracy:.4f} < {ACCURACY_FLOOR}")
        ok = False
    print("BENCH OK" if ok else "BENCH FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
