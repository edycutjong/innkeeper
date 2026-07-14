"""Shared adjudicator/extractor contracts + evidence-citation builders.

The Verdict is the contract between the model and the policy gate: the gate is
math over typed fields, so any adjudicator (fake or live) must return a fully
formed :class:`~innkeeper_audit.schemas.Verdict` whose citations resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..schemas import EvidenceRef, Mismatch, Verdict

# Verified Qwen Cloud model IDs (SPEC §5).
MODEL_ADJUDICATOR = "qwen3.7-max"  # + thinking, for adjudication
MODEL_VL = "qwen3-vl-plus"  # OTA statement extraction with bbox citations


@dataclass(frozen=True)
class EvidenceContext:
    """Everything an adjudicator needs to cite the night's evidence artifacts.

    The three ``*_sha`` values are the sha256 of the canonical evidence files
    written by the pipeline *before* adjudication, so a verdict's citations bind
    to bytes already on disk (invariants I2/I3).
    """

    night: str
    pms_sha: str
    processor_sha: str
    ota_sha: str

    def pms_row(self, ref: str) -> EvidenceRef:
        return EvidenceRef(src="pms", kind="row", uri=f"evidence/pms.json#{ref}", sha256=self.pms_sha)

    def pms_absence(self, note: str) -> EvidenceRef:
        # A resolvable citation that the PMS holds *no* folio for this charge —
        # the second system a lone processor row reconciles against.
        return EvidenceRef(
            src="pms", kind="absence", uri=f"evidence/pms.json#absence:{note}", sha256=self.pms_sha
        )

    def processor_row(self, ref: str, batch: str | None = None, row: int | None = None) -> EvidenceRef:
        return EvidenceRef(
            src="processor", kind="row", uri=f"evidence/processor.json#{ref}",
            sha256=self.processor_sha, batch=batch, row=row,
        )

    def ota_line(self, line: dict[str, Any]) -> EvidenceRef:
        return EvidenceRef(
            src="ota", kind="pdf_line", uri=f"evidence/ota_lines.json#L{line['line_no']}",
            sha256=self.ota_sha, line=line["line_no"], bbox=line.get("bbox"),
            page=line.get("page"),
        )


class Adjudicator(Protocol):
    def adjudicate(self, mismatch: Mismatch, ctx: EvidenceContext) -> Verdict: ...


class Extractor(Protocol):
    def extract_statement(self, paths: Any, month: str) -> list[dict[str, Any]]: ...
