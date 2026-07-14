"""Qwen Cloud surface: PDF extraction (qwen3-vl-plus) + adjudication
(qwen3.7-max + thinking).

Offline-first: :class:`FakeQwen` is a fully deterministic stand-in that parses
the committed statement fixture and computes verdicts from the mismatch data,
so the whole pipeline — and every invariant test — runs green with no network
and no API key. :class:`LiveQwen` is the real transport (DashScope
OpenAI-compatible mode), used only when ``DASHSCOPE_API_KEY`` is set and
explicitly selected.
"""

from __future__ import annotations

from .base import (
    MODEL_ADJUDICATOR,
    MODEL_VL,
    Adjudicator,
    EvidenceContext,
    Extractor,
)
from .fake import FakeQwen

__all__ = [
    "MODEL_ADJUDICATOR",
    "MODEL_VL",
    "Adjudicator",
    "Extractor",
    "EvidenceContext",
    "FakeQwen",
    "get_adjudicator",
    "get_extractor",
]


def get_adjudicator(live: bool = False):
    """Return the adjudicator. ``live=True`` requires the openai extra + key."""
    if live:
        from .live import LiveQwen

        return LiveQwen()
    return FakeQwen()


def get_extractor(live: bool = False):
    if live:
        from .live import LiveQwen

        return LiveQwen()
    return FakeQwen()
