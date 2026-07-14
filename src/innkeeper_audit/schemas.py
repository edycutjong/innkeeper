"""Typed pipeline objects. The Verdict schema is SPEC §5 made executable:
the policy gate is math over these fields, so free-text never reaches a
money decision, and a citation-less verdict is rejected at parse time.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# canonical JSON + hashing
# --------------------------------------------------------------------------- #


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, tight separators, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def doc_hash(model: BaseModel) -> str:
    """sha256 over a model's canonical JSON form."""
    return sha256_hex(canonical_json(model.model_dump(mode="json")))


# --------------------------------------------------------------------------- #
# source transactions
# --------------------------------------------------------------------------- #

Source = Literal["pms", "processor", "ota"]


class Txn(BaseModel):
    """A normalized transaction row from any of the three systems."""

    src: Source
    ref: str  # folio-#### / auth id / statement line ref
    folio: str | None = None  # PMS folio the row claims to belong to (if any)
    amount_cents: int
    date: str  # YYYY-MM-DD business date
    currency: str = "USD"
    method: Literal["card", "cash", "ota_collect"] = "card"
    kind: str = "sale"  # sale | reserve_release | extra | ...
    memo: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class MismatchKind(StrEnum):
    AMOUNT_DELTA = "amount_delta"  # paired, amounts differ
    ORPHAN = "orphan"  # counterpart missing in the expected system
    DUPLICATE_CANDIDATE = "duplicate_candidate"  # second capture of a matched ref
    EXTRACTION_ESCALATION = "extraction_escalation"  # VL two-pass disagreement (I5)


class Mismatch(BaseModel):
    """The residue the matcher could not clear deterministically."""

    mismatch_id: str  # m-01 ... per night
    night: str
    kind: MismatchKind
    tier: Literal["ref_exact", "amount_date", "fuzzy", "unmatched"]
    anchor_ref: str  # the ref ground_truth is keyed on (pms folio or stl id)
    pms_ref: str | None = None
    counterpart_ref: str | None = None
    counterpart_src: Source | None = None
    amounts: dict[str, float] = Field(default_factory=dict)  # per-source dollars
    delta_cents: int = 0  # pms - counterpart (0 for orphans; see materiality)
    materiality_cents: int = 0  # |delta| for pairs, amount for orphans
    txns: list[Txn] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)  # e.g. two_pass_disagreement


class MatchResult(BaseModel):
    night: str
    n_txns: int
    n_matched: int
    matched_pairs: list[dict[str, Any]] = Field(default_factory=list)
    mismatches: list[Mismatch] = Field(default_factory=list)
    tier_stats: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# verdicts (SPEC §5)
# --------------------------------------------------------------------------- #


class Classification(StrEnum):
    TIMING = "timing"
    FEE = "fee"
    FX = "fx"
    DUPLICATE = "duplicate"
    TRUE_ERROR = "true_error"
    UNKNOWN = "unknown"


class EvidenceRef(BaseModel):
    """A citation that must resolve: uri -> artifact whose sha256 matches."""

    src: Source
    kind: str = "row"  # row | pdf_line | absence | pdf
    uri: str  # e.g. "evidence/pms.json#folio-1188"
    sha256: str  # sha256 of the artifact file the uri points into
    line: int | None = None  # OTA statement line number (1-based)
    bbox: list[float] | None = None  # [x0, y0, x1, y1] PDF points
    page: int | None = None
    batch: str | None = None
    row: int | None = None

    @field_validator("sha256")
    @classmethod
    def _hex64(cls, v: str) -> str:
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return v


class Hypothesis(BaseModel):
    h: str
    p: float = Field(ge=0.0, le=1.0)


class Verdict(BaseModel):
    """Structured adjudication output. The gate computes over these fields."""

    mismatch_id: str
    night: str
    anchor_ref: str = ""  # joins the verdict back to its ground_truth label
    pms_ref: str | None = None
    amounts: dict[str, float] = Field(default_factory=dict)
    classification: Classification
    subtype: str = ""  # ota_commission | rolling_reserve | fx_rounding | ...
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef]
    hypotheses: list[Hypothesis]
    action: Literal["auto_clear", "queue"] = "queue"
    materiality_usd: float = 0.0
    delta_usd: float = 0.0
    rationale: str = ""
    model: str = "fake-qwen/rules-v1"
    escalation: str | None = None  # e.g. "two_pass_disagreement" (I5)

    @model_validator(mode="after")
    def _validate_verdict(self) -> "Verdict":
        # Invariant I2 precondition: a verdict without citations from at least
        # two distinct systems is rejected at parse time, before any gate math.
        if len(self.evidence) < 2:
            raise ValueError("verdict must cite at least 2 evidence items")
        if len({e.src for e in self.evidence}) < 2:
            raise ValueError("verdict must cite line items from >=2 systems")
        if not self.hypotheses:
            raise ValueError("verdict must carry competing hypotheses")
        total_p = sum(h.p for h in self.hypotheses)
        if total_p > 1.0 + 1e-9:
            raise ValueError(f"hypothesis probabilities sum to {total_p} > 1")
        return self


class GateDecision(BaseModel):
    action: Literal["auto_clear", "queue"]
    reason: str
    eloss_cents: int
    policy: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# night close (COMPLEXITY §2)
# --------------------------------------------------------------------------- #


class CloseStats(BaseModel):
    date: str
    n_txns: int
    n_matched: int
    n_mismatches: int
    n_cleared: int
    n_queued: int
    delta_total_usd: float


class NightClose(BaseModel):
    """Merkle root over the night's verdicts, Ed25519-signed, chained."""

    night: str
    merkle_root: str
    prev_root: str
    stats: CloseStats
    pipeline_version: str
    verdict_hashes: list[str] = Field(default_factory=list)  # Merkle leaves, in order
    signer_pubkey: str = ""  # hex
    signature: str = ""  # hex, over canonical payload (see crypto.close_payload)
