"""Paths, environment, and pipeline constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MONTH = "2026-07"
NIGHTS = 30  # 2026-07-01 .. 2026-07-30
SEED = 20260701  # fixed seed -> byte-identical --regen

# Policy gate defaults (SPEC §5): auto_clear iff confidence >= 0.85
# AND materiality <= $50 AND classification != true_error.
MIN_CONFIDENCE = 0.85
MATERIALITY_CAP_CENTS = 50_00
# Generalized gate (COMPLEXITY §3): E[loss] = amount x (1 - confidence) <= tau.
# 50_00 * (1 - 0.85) = 750 — the classic rule's worst-case expected loss.
DEFAULT_TAU_CENTS = 7_50

GENESIS_ROOT = "0" * 64


def repo_root() -> Path:
    """Repository root: env override first, else walk up from this file."""
    env = os.environ.get("INNKEEPER_ROOT")
    if env:
        return Path(env).resolve()
    # src/innkeeper_audit/config.py -> repo root is three parents up
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path = field(default_factory=repo_root)

    @property
    def fixtures(self) -> Path:
        return self.root / "fixtures" / "month_07"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger" / "month_07"

    @property
    def pms_dir(self) -> Path:
        return self.fixtures / "pms"

    @property
    def processor_dir(self) -> Path:
        return self.fixtures / "processor"

    @property
    def ota_dir(self) -> Path:
        return self.fixtures / "ota"

    @property
    def keys_dir(self) -> Path:
        return self.fixtures / "keys"

    @property
    def ground_truth(self) -> Path:
        return self.fixtures / "ground_truth.json"

    @property
    def manifest(self) -> Path:
        return self.fixtures / "seed_manifest.json"

    @property
    def chain_file(self) -> Path:
        return self.ledger / "closes" / "chain.json"

    def run_dir(self, night: str) -> Path:
        return self.ledger / "runs" / night

    def ota_pdf(self, month: str = MONTH) -> Path:
        return self.ota_dir / f"statement_{month}.pdf"

    def ota_sealed(self, month: str = MONTH) -> Path:
        return self.ota_dir / f"statement_{month}.pdf.sealed"

    def ota_sidecar(self, month: str = MONTH) -> Path:
        return self.ota_dir / f"statement_{month}.sidecar.json"


def night_str(month: str, day: int) -> str:
    return f"{month}-{day:02d}"


def all_nights(month: str = MONTH, nights: int = NIGHTS) -> list[str]:
    return [night_str(month, d) for d in range(1, nights + 1)]
