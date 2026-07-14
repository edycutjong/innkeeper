"""The Verdict validator is the first gate: citation-less or single-system
verdicts are rejected at parse time, before any money decision."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from innkeeper_audit.schemas import (
    Classification,
    EvidenceRef,
    Hypothesis,
    Verdict,
    canonical_json,
    doc_hash,
    sha256_hex,
)

H = "a" * 64


def _ev(src, uri):
    return EvidenceRef(src=src, uri=uri, sha256=H)


def _verdict(evidence, hypotheses=None, confidence=0.9):
    if hypotheses is None:
        hypotheses = [Hypothesis(h="x", p=0.9)]
    return Verdict(
        mismatch_id="m-01", night="2026-07-04", classification=Classification.FEE,
        confidence=confidence, evidence=evidence, hypotheses=hypotheses,
    )


def test_valid_verdict_two_systems():
    v = _verdict([_ev("pms", "evidence/pms.json#f-1"), _ev("ota", "evidence/ota_lines.json#L1")])
    assert v.action == "queue"  # default until the gate runs


def test_rejects_single_evidence_item():
    with pytest.raises(ValidationError):
        _verdict([_ev("pms", "a")])


def test_rejects_single_system_even_with_two_items():
    with pytest.raises(ValidationError, match=r">=2 systems"):
        _verdict([_ev("pms", "a"), _ev("pms", "b")])


def test_rejects_no_hypotheses():
    with pytest.raises(ValidationError):
        _verdict([_ev("pms", "a"), _ev("ota", "b")], hypotheses=[])


def test_rejects_hypotheses_over_one():
    with pytest.raises(ValidationError, match="sum"):
        _verdict([_ev("pms", "a"), _ev("ota", "b")],
                 hypotheses=[Hypothesis(h="x", p=0.7), Hypothesis(h="y", p=0.7)])


def test_sha256_validator_rejects_bad_hex():
    with pytest.raises(ValidationError):
        EvidenceRef(src="pms", uri="a", sha256="nothex")
    with pytest.raises(ValidationError):
        EvidenceRef(src="pms", uri="a", sha256="abc")  # too short


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        _verdict([_ev("pms", "a"), _ev("ota", "b")], confidence=1.5)
    with pytest.raises(ValidationError):
        _verdict([_ev("pms", "a"), _ev("ota", "b")], confidence=-0.1)


def test_canonical_json_is_sorted_and_tight():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_sha256_hex_str_and_bytes_agree():
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("abc")) == 64


def test_doc_hash_deterministic():
    v = _verdict([_ev("pms", "a"), _ev("ota", "b")])
    assert doc_hash(v) == doc_hash(v.model_copy(deep=True))


def test_doc_hash_changes_on_field_change():
    v = _verdict([_ev("pms", "a"), _ev("ota", "b")])
    assert doc_hash(v) != doc_hash(v.model_copy(update={"confidence": 0.5}))
