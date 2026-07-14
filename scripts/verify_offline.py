#!/usr/bin/env python
"""Zero-key, network-disabled proof that a night replays and the chain verifies.

    python scripts/verify_offline.py

Installs a socket guard (any network call raises), then:
  1. seeds the fixtures if missing;
  2. runs the full seeded month offline (FakeQwen — no API key);
  3. replays night 2026-07-04 and asserts a byte-identical signed close (I4);
  4. verifies the whole signed close chain + evidence bindings (I2/I3);
  5. flips one byte in a stored verdict and asserts verification now FAILS (I3).

Exit 0 iff every check passes. This is the judge's "it works on my machine with
no keys" path.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Imports (reportlab etc.) run first so the guard cannot break them; the guard
# then blocks any *connection* — replacing socket.socket outright would break
# libraries that subclass it. What we prove is the audit does not phone home.
from innkeeper_audit.config import Paths  # noqa: E402
from innkeeper_audit.pipeline import replay_night, run_month  # noqa: E402
from innkeeper_audit.schemas import canonical_json  # noqa: E402
from innkeeper_audit.seed import generate_month  # noqa: E402
from innkeeper_audit.store import read_json  # noqa: E402
from innkeeper_audit.verify import verify_all, verify_night  # noqa: E402

TARGET = "2026-07-04"


def _install_network_guard() -> None:
    def _blocked(*_a, **_k):  # noqa: ANN001
        raise OSError("network disabled by verify_offline.py")

    socket.socket.connect = _blocked  # type: ignore[assignment]
    socket.socket.connect_ex = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]


def main() -> int:
    _install_network_guard()
    paths = Paths()
    if not paths.ground_truth.exists():
        print("seeding fixtures (offline)…")
        generate_month(paths)

    print("running the seeded month offline (FakeQwen, no key)…")
    run_month(paths)

    print(f"replaying {TARGET}…")
    result, ok, diffs = replay_night(paths, TARGET)
    assert result.close is not None
    if not ok:
        print(f"FAIL replay: {diffs}")
        return 1
    print(f"  replay identical · root {result.close.merkle_root[:16]}… (I4)")

    print("verifying the signed close chain + evidence…")
    cv = verify_all(paths)
    if not cv.ok:
        print(f"FAIL chain: {cv.chain_errors[:2]}")
        return 1
    print(f"  chain OK · {cv.n_closes} signed closes, roots + signatures + evidence all verify")

    print("tamper test: flipping one byte in a stored verdict…")
    if not _tamper_fails(paths, TARGET):
        print("FAIL: tamper was NOT detected")
        return 1
    print("  tamper detected — root no longer matches the signed close (I3)")

    print("\nOFFLINE VERIFY OK")
    return 0


def _tamper_fails(paths: Paths, night: str) -> bool:
    """Bump one verdict's confidence by a cent's worth and confirm the night no
    longer verifies; then restore."""
    vpath = paths.run_dir(night) / "verdicts.json"
    original = vpath.read_bytes()
    doc = read_json(vpath)
    doc["verdicts"][0]["confidence"] = round(doc["verdicts"][0]["confidence"] - 0.01, 4)
    vpath.write_bytes(canonical_json(doc).encode("utf-8"))
    try:
        report = verify_night(paths, night)
        return not report.ok  # tamper must break the root match
    finally:
        vpath.write_bytes(original)


if __name__ == "__main__":
    raise SystemExit(main())
