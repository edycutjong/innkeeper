"""LiveQwen — the real Qwen Cloud transport. The whole suite runs offline on
FakeQwen; these tests only exercise the parts of the live transport that don't
require a network call: key handling, evidence/prompt construction (shared
with FakeQwen so citations always resolve), the extraction-for-night filter,
and the classification coercion fallback. The actual `adjudicate` /
`extract_statement` model calls are `# pragma: no cover - live` in the source
(never run offline) and are correctly excluded, not silently skipped here.
"""

from __future__ import annotations

import json

import pytest

from innkeeper_audit.qwen import get_adjudicator, get_extractor
from innkeeper_audit.qwen.base import EvidenceContext
from innkeeper_audit.qwen.live import LiveQwen, _coerce_class
from innkeeper_audit.schemas import Classification, Mismatch, MismatchKind

CTX = EvidenceContext(night="2026-07-01", pms_sha="a" * 64, processor_sha="b" * 64, ota_sha="c" * 64)


def _mismatch(**overrides):
    base = dict(
        mismatch_id="m-01", night="2026-07-01", kind=MismatchKind.AMOUNT_DELTA,
        tier="ref_exact", anchor_ref="folio-9001", pms_ref="folio-9001",
        counterpart_ref="stl-9001", counterpart_src="processor",
        amounts={"pms": 100.0, "processor": 96.67}, delta_cents=333, materiality_cents=333,
        txns=[], flags={"proc_memo": "misc adjustment", "proc_currency": "USD"},
    )
    base.update(overrides)
    return Mismatch(**base)


# ---- construction: the DASHSCOPE_API_KEY guard --------------------------- #

def test_live_qwen_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        LiveQwen()


def test_live_qwen_reads_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-test-key")
    live = LiveQwen()
    assert live.api_key == "env-test-key"
    assert live.model == "qwen3.7-max"


def test_live_qwen_accepts_an_explicit_key_over_the_environment(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    live = LiveQwen(api_key="explicit-key")
    assert live.api_key == "explicit-key"


# ---- get_adjudicator / get_extractor: the live=True dispatch -------------- #

def test_get_adjudicator_live_returns_a_live_qwen(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dispatch-test-key")
    adj = get_adjudicator(live=True)
    assert isinstance(adj, LiveQwen)


def test_get_extractor_live_returns_a_live_qwen(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dispatch-test-key")
    ext = get_extractor(live=True)
    assert isinstance(ext, LiveQwen)


def test_get_adjudicator_offline_default_is_fake(monkeypatch):
    from innkeeper_audit.qwen import FakeQwen

    assert isinstance(get_adjudicator(), FakeQwen)
    assert isinstance(get_extractor(live=False), FakeQwen)


# ---- prompt / evidence construction (no network call) --------------------- #

def test_mismatch_prompt_is_valid_json_with_the_expected_fields(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "prompt-test-key")
    live = LiveQwen()
    m = _mismatch()
    prompt = live._mismatch_prompt(m)
    assert prompt.startswith("Adjudicate this mismatch:\n")
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["mismatch_kind"] == "amount_delta"
    assert payload["delta_usd"] == 3.33
    assert payload["memo"] == "misc adjustment"


def test_fake_evidence_delegates_to_fakeqwen_and_resolves_two_systems(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "evidence-test-key")
    live = LiveQwen()
    m = _mismatch()
    evidence = live._fake_evidence(m, CTX)
    assert len(evidence) >= 2
    assert {e.src for e in evidence} >= {"pms", "processor"}


# ---- extract_statement_for_night: pure filter over extract_statement ----- #

def test_extract_statement_for_night_filters_by_night(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "extract-test-key")
    live = LiveQwen()
    canned = [
        {"line_no": 1, "night": "2026-07-01", "payout": 90.0},
        {"line_no": 2, "night": "2026-07-02", "payout": 91.0},
        {"line_no": 3, "night": "2026-07-01", "payout": 92.0},
    ]
    monkeypatch.setattr(live, "extract_statement", lambda paths, month: canned)
    out = live.extract_statement_for_night(paths=None, month="2026-07", night="2026-07-01")
    assert [l["line_no"] for l in out] == [1, 3]


# ---- _coerce_class: unknown values never explode, they fall back ---------- #

@pytest.mark.parametrize("value,expected", [
    ("fee", Classification.FEE),
    ("true_error", Classification.TRUE_ERROR),
    ("timing", Classification.TIMING),
])
def test_coerce_class_accepts_known_values(value, expected):
    assert _coerce_class(value) == expected


@pytest.mark.parametrize("value", ["not_a_real_class", "", None, 42])
def test_coerce_class_falls_back_to_unknown_on_garbage(value):
    assert _coerce_class(value) == Classification.UNKNOWN
