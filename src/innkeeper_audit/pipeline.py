"""The nightly run orchestrator (SPEC §4 pipeline).

    fetch (3× MCP) → extract (qwen3-vl-plus, two-pass) → deterministic match
    → write evidence → adjudicate residue (qwen3.7-max) → policy gate
    → signed Merkle night-close → chain.

Every stage is a pure function of the committed fixtures, so ``replay`` re-runs
the identical computation and must reproduce the identical signed close
(invariant I4). The language model only ever sees the mismatch residue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import PIPELINE_VERSION
from .config import GENESIS_ROOT, MONTH, Paths, all_nights
from .crypto import (
    DemoKeys,
    build_close,
    ensure_demo_keys,
    sign_close,
)
from .matcher import match_night
from .mcp.tools import pms_get_folios, processor_get_settlements
from .policy import DEFAULT_GATE, PolicyGate
from .schemas import CloseStats, GateDecision, MatchResult, NightClose, Txn, Verdict
from .store import (
    evidence_docs,
    load_close,
    load_sidecar,
    read_json,
    upsert_chain_entry,
    write_close,
    write_evidence,
    write_json,
)
from .qwen import FakeQwen
from .qwen.base import EvidenceContext


@dataclass
class RunResult:
    night: str
    match: MatchResult
    verdicts: list[Verdict]
    decisions: list[GateDecision] = field(default_factory=list)
    close: NightClose | None = None
    stats: CloseStats | None = None

    @property
    def n_cleared(self) -> int:
        return sum(1 for v in self.verdicts if v.action == "auto_clear")

    @property
    def n_queued(self) -> int:
        return sum(1 for v in self.verdicts if v.action == "queue")


def _prev_root(paths: Paths, night: str, month: str) -> str:
    """Merkle root of the previous calendar night's close, else the genesis
    root. Chains the ledger-of-ledgers deterministically."""
    nights = all_nights(month, 31)  # generous upper bound; index lookup only
    try:
        idx = nights.index(night)
    except ValueError:
        return GENESIS_ROOT
    if idx == 0:
        return GENESIS_ROOT
    prev = nights[idx - 1]
    if (paths.run_dir(prev) / "close.json").exists():
        return load_close(paths, prev).merkle_root
    return GENESIS_ROOT


def run_night(
    paths: Paths,
    night: str,
    *,
    gate: PolicyGate = DEFAULT_GATE,
    adjudicator: Any = None,
    extractor: Any = None,
    keys: DemoKeys | None = None,
    month: str = MONTH,
    prev_root: str | None = None,
    write: bool = True,
    update_chain: bool = True,
) -> RunResult:
    """Run one night end to end. Returns the (optionally persisted) result."""
    fake = FakeQwen()
    adjudicator = adjudicator or fake
    extractor = extractor or (adjudicator if hasattr(adjudicator, "extract_statement") else fake)
    keys = keys or ensure_demo_keys(paths)

    # 1. fetch via the (mock) MCP tools
    pms = [Txn(**t) for t in pms_get_folios(paths, night)]
    proc = [Txn(**t) for t in processor_get_settlements(paths, night)]

    # 2. OTA statement extraction (qwen3-vl-plus, two-pass agreement)
    ota_lines = extractor.extract_statement_for_night(paths, month, night)

    # 3. deterministic three-way match — LLM only sees the residue
    match = match_night(night, pms, proc, ota_lines)

    # 4. evidence artifacts (citations bind to these hashes: I2/I3)
    sidecar = load_sidecar(paths, month)
    pdf_sha = sidecar.get("pdf_sha256", "")
    payloads, shas = evidence_docs(night, pms, proc, ota_lines, pdf_sha)
    if write:
        sealed = paths.ota_sealed(month).read_bytes() if paths.ota_sealed(month).exists() else None
        write_evidence(paths, night, pms, proc, ota_lines, pdf_sha, sealed_pdf=sealed)
    ctx = EvidenceContext(
        night=night, pms_sha=shas["pms.json"],
        processor_sha=shas["processor.json"], ota_sha=shas["ota_lines.json"],
    )

    # 5. adjudicate + gate
    verdicts: list[Verdict] = []
    decisions: list[GateDecision] = []
    for m in match.mismatches:
        v = adjudicator.adjudicate(m, ctx)
        d = gate.apply(v)  # writes v.action
        verdicts.append(v)
        decisions.append(d)

    # 6. stats + signed Merkle close
    delta_total = round(sum(v.delta_usd for v in verdicts), 2)
    stats = CloseStats(
        date=night, n_txns=match.n_txns, n_matched=match.n_matched,
        n_mismatches=len(match.mismatches),
        n_cleared=sum(1 for v in verdicts if v.action == "auto_clear"),
        n_queued=sum(1 for v in verdicts if v.action == "queue"),
        delta_total_usd=delta_total,
    )
    prev = prev_root if prev_root is not None else _prev_root(paths, night, month)
    close = build_close(night, verdicts, prev, stats, PIPELINE_VERSION)
    sign_close(close, keys)

    if write:
        _write_run(paths, night, match, verdicts, decisions, close, stats)
        if update_chain:
            upsert_chain_entry(paths, close)

    return RunResult(night=night, match=match, verdicts=verdicts,
                     decisions=decisions, close=close, stats=stats)


def _write_run(
    paths: Paths, night: str, match: MatchResult, verdicts: list[Verdict],
    decisions: list[GateDecision], close: NightClose, stats: CloseStats,
) -> None:
    from .store import write_verdicts

    write_verdicts(paths, night, verdicts)
    write_close(paths, close)
    write_json(paths.run_dir(night) / "gate.json", {
        "night": night,
        "decisions": [
            {"mismatch_id": v.mismatch_id, "anchor_ref": v.anchor_ref,
             "classification": v.classification.value, "subtype": v.subtype,
             "confidence": v.confidence, "action": d.action,
             "reason": d.reason, "eloss_cents": d.eloss_cents,
             "materiality_usd": v.materiality_usd}
            for v, d in zip(verdicts, decisions)
        ],
    })
    write_json(paths.run_dir(night) / "match.json", {
        "night": night, "n_txns": match.n_txns, "n_matched": match.n_matched,
        "tier_stats": match.tier_stats, "n_mismatches": len(match.mismatches),
    })
    write_json(paths.run_dir(night) / "stats.json", stats.model_dump(mode="json"))


def replay_night(
    paths: Paths,
    night: str,
    *,
    adjudicator: Any = None,
    extractor: Any = None,
    keys: DemoKeys | None = None,
    month: str = MONTH,
) -> tuple[RunResult, bool, list[str]]:
    """Re-derive a night from stored evidence and compare to its stored close.

    Uses the stored ``prev_root`` (an input to the night, not a derived value)
    and does not touch disk, so a byte-identical re-derivation proves I4.
    """
    stored = load_close(paths, night)
    result = run_night(
        paths, night, adjudicator=adjudicator, extractor=extractor, keys=keys,
        month=month, prev_root=stored.prev_root, write=False, update_chain=False,
    )
    assert result.close is not None
    diffs: list[str] = []
    if result.close.merkle_root != stored.merkle_root:
        diffs.append(f"merkle_root {result.close.merkle_root[:12]} != {stored.merkle_root[:12]}")
    if result.close.verdict_hashes != stored.verdict_hashes:
        diffs.append("verdict_hashes differ")
    if result.close.signature != stored.signature:
        diffs.append("signature differs")
    if result.close.stats.model_dump() != stored.stats.model_dump():
        diffs.append("stats differ")
    return result, (not diffs), diffs


def run_month(
    paths: Paths, *, gate: PolicyGate = DEFAULT_GATE, adjudicator: Any = None,
    month: str = MONTH, nights: int | None = None,
) -> list[RunResult]:
    """Run every night in order, building the full signed chain."""
    keys = ensure_demo_keys(paths)
    results: list[RunResult] = []
    for night in all_nights(month, nights or _month_nights(paths)):
        results.append(run_night(paths, night, gate=gate, adjudicator=adjudicator,
                                  keys=keys, month=month))
    return results


def _month_nights(paths: Paths) -> int:
    """How many nights the current fixture set actually covers."""
    manifest = read_json(paths.manifest)
    return int(manifest.get("nights", 30))
