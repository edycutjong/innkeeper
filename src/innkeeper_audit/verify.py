"""Chain + evidence verification (the zero-key judge path).

``verify-chain`` re-derives everything from what is on disk: each night's Merkle
root is recomputed from its stored verdicts and checked against the signed
close, every signature is checked, the ``prev_root`` linkage is walked, and
every verdict's evidence citations are resolved by sha256. A one-byte change to
any verdict, evidence file, or close flips the result to failure (invariant I3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Paths
from .crypto import recompute_root, verify_chain, verify_close, verify_evidence_bindings
from .schemas import NightClose
from .store import (
    evidence_dir,
    load_chain,
    load_close,
    load_verdicts,
)


@dataclass
class NightVerification:
    night: str
    root_ok: bool
    signature_ok: bool
    evidence_ok: bool
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.root_ok and self.signature_ok and self.evidence_ok


@dataclass
class ChainVerification:
    ok: bool
    n_closes: int
    nights: list[NightVerification] = field(default_factory=list)
    chain_errors: list[str] = field(default_factory=list)


def verify_night(paths: Paths, night: str) -> NightVerification:
    close = load_close(paths, night)
    verdicts = load_verdicts(paths, night)
    errors: list[str] = []

    derived = recompute_root(close, verdicts)
    root_ok = derived == close.merkle_root
    if not root_ok:
        errors.append(f"merkle root mismatch: stored {close.merkle_root[:12]} != "
                      f"recomputed {derived[:12]}")

    sig_ok = verify_close(close)
    if not sig_ok:
        errors.append("close signature invalid")

    ev_ok, ev_errs = verify_evidence_bindings(evidence_dir(paths, night), verdicts)
    errors.extend(ev_errs)

    return NightVerification(night=night, root_ok=root_ok, signature_ok=sig_ok,
                             evidence_ok=ev_ok, errors=errors)


def verify_all(paths: Paths) -> ChainVerification:
    """Verify every close on the chain + each night's roots/signatures/evidence."""
    chain = load_chain(paths)
    nights = [c["night"] for c in chain]
    closes: list[NightClose] = [load_close(paths, n) for n in nights]

    chain_ok, chain_errs = verify_chain(closes)
    night_reports = [verify_night(paths, n) for n in nights]
    all_ok = chain_ok and all(r.ok for r in night_reports)
    return ChainVerification(ok=all_ok, n_closes=len(closes),
                             nights=night_reports, chain_errors=chain_errs)


def format_chain_report(cv: ChainVerification) -> str:
    lines = [f"chain: {'OK' if cv.ok else 'FAILED'} · {cv.n_closes} signed closes"]
    if cv.chain_errors:
        for e in cv.chain_errors:
            lines.append(f"  chain! {e}")
    for r in cv.nights:
        mark = "ok " if r.ok else "BAD"
        lines.append(f"  [{mark}] {r.night} root={r.root_ok} sig={r.signature_ok} "
                     f"evidence={r.evidence_ok}"
                     + (f"  {r.errors[0]}" if r.errors else ""))
    return "\n".join(lines)
