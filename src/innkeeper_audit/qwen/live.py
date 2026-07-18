"""LiveQwen — the real Qwen Cloud transport (DashScope OpenAI-compatible mode).

Used only when ``DASHSCOPE_API_KEY`` is set and ``--live`` is selected; the
offline pipeline and every test run on :class:`FakeQwen`. Two surfaces:

  * **adjudication** — ``qwen3.7-max`` with thinking + JSON structured output;
    the model returns the *judgment* (classification / hypotheses / confidence)
    and this harness binds the evidence citations deterministically, so a
    verdict can never cite a hash that does not resolve.
  * **extraction** — ``qwen3-vl-plus`` two-pass over the rasterised statement
    pages (temperature-varied); agreement accepts the figure, disagreement is
    flagged for escalation (invariant I5) — never silently averaged.

This module imports the ``openai`` SDK lazily so importing the package (and
running the offline suite) never requires the ``live`` extra.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..amounts import to_dollars
from ..schemas import (
    Classification,
    Hypothesis,
    Mismatch,
    MismatchKind,
    Verdict,
)
from .base import MODEL_ADJUDICATOR, MODEL_VL, EvidenceContext
from .fake import FakeQwen

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

_ADJUDICATION_SYSTEM = (
    "You are a hotel night auditor adjudicating a single reconciliation mismatch "
    "between three systems (PMS folios, card-processor settlements, an OTA statement). "
    "Reason carefully, then return ONLY a JSON object with keys: "
    "classification (one of timing|fee|fx|duplicate|true_error|unknown), "
    "subtype (short snake_case), confidence (0..1), "
    "hypotheses (list of {h: string, p: number}; probabilities sum to <=1), "
    "rationale (one sentence). If a lone card settlement has no PMS folio and no "
    "benign memo, it is a true_error. Never guess past the evidence."
)


class LiveQwen:
    """Real Qwen Cloud calls. Falls back to fixture extraction only if the VL
    two-pass path is unavailable; adjudication always calls the model."""

    model = MODEL_ADJUDICATOR

    def __init__(self, api_key: str | None = None, base_url: str = DASHSCOPE_BASE_URL) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "LiveQwen requires DASHSCOPE_API_KEY (offline runs use FakeQwen)."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - live-only path
            raise RuntimeError("LiveQwen needs the 'live' extra: pip install -e '.[live]'") from exc
        # A per-request timeout keeps one slow response (a stray thinking spin,
        # a large VL page) from hanging the whole audit run.
        self._client = OpenAI(
            api_key=self.api_key, base_url=base_url, timeout=120.0, max_retries=2
        )
        self._fake = FakeQwen()  # evidence construction + extraction fallback

    # ------------------------------------------------------------------ #
    # one JSON chat call — thinking is set EXPLICITLY per call
    # ------------------------------------------------------------------ #

    def _create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        thinking: bool = False,
    ):  # pragma: no cover - live
        # Qwen3 models default to "thinking" mode, spending thousands of
        # reasoning tokens per call (~45s+, and it times out on large prompts).
        # So we set enable_thinking EXPLICITLY on every call: OFF for the VL OCR
        # passes (structured emission, no reasoning needed), ON only for the
        # adjudication step where the judgment IS the reasoning.
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            extra_body={"enable_thinking": bool(thinking)},
        )

    # ------------------------------------------------------------------ #
    # adjudication: qwen3.7-max + thinking + structured output
    # ------------------------------------------------------------------ #

    def adjudicate(self, m: Mismatch, ctx: EvidenceContext) -> Verdict:  # pragma: no cover - live
        # A page-broken extraction disagreement escalates by rule, no model call.
        if m.kind == MismatchKind.EXTRACTION_ESCALATION:
            return self._fake.adjudicate(m, ctx)

        prompt = self._mismatch_prompt(m)
        resp = self._create(
            model=MODEL_ADJUDICATOR,
            messages=[
                {"role": "system", "content": _ADJUDICATION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            thinking=True,  # adjudication is the one genuine reasoning step
        )
        data = json.loads(resp.choices[0].message.content)
        evidence = self._fake_evidence(m, ctx)
        classification = _coerce_class(data.get("classification"))
        hypotheses = [
            Hypothesis(h=str(x["h"]), p=float(x["p"]))
            for x in data.get("hypotheses", [])[:4]
        ] or [Hypothesis(h=data.get("rationale", "adjudicated"), p=float(data.get("confidence", 0.5)))]
        return Verdict(
            mismatch_id=m.mismatch_id, night=m.night, anchor_ref=m.anchor_ref,
            pms_ref=m.pms_ref, amounts=m.amounts,
            classification=classification, subtype=str(data.get("subtype", "")),
            confidence=float(data.get("confidence", 0.5)),
            evidence=evidence, hypotheses=hypotheses,
            materiality_usd=to_dollars(m.materiality_cents),
            delta_usd=to_dollars(m.delta_cents),
            rationale=str(data.get("rationale", "")),
            model=f"{MODEL_ADJUDICATOR}+thinking",
        )

    def _mismatch_prompt(self, m: Mismatch) -> str:
        rows = [t.model_dump(mode="json") for t in m.txns]
        payload = {
            "mismatch_kind": m.kind.value,
            "amounts": m.amounts,
            "delta_usd": to_dollars(m.delta_cents),
            "materiality_usd": to_dollars(m.materiality_cents),
            "rows": rows,
            "ota_line": m.flags.get("ota_line"),
            "memo": m.flags.get("proc_memo"),
        }
        return "Adjudicate this mismatch:\n" + json.dumps(payload, indent=2, default=str)

    def _fake_evidence(self, m: Mismatch, ctx: EvidenceContext):
        """Reuse the deterministic citation builder so hashes always resolve."""
        return self._fake.adjudicate(m, ctx).evidence

    # ------------------------------------------------------------------ #
    # extraction: qwen3-vl-plus two-pass with bbox
    # ------------------------------------------------------------------ #

    def extract_statement(self, paths: Any, month: str) -> list[dict[str, Any]]:  # pragma: no cover
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            # VL rasteriser unavailable — fall back to the committed fixture.
            return self._fake.extract_statement(paths, month)
        return self._two_pass_vl(paths, month)

    def extract_statement_for_night(self, paths: Any, month: str, night: str):
        return [l for l in self.extract_statement(paths, month) if l["night"] == night]

    def _two_pass_vl(self, paths: Any, month: str) -> list[dict[str, Any]]:  # pragma: no cover - live
        import base64

        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(paths.ota_pdf(month)))
        images: list[str] = []
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=3.0)
            pil = bitmap.to_pil()
            import io

            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            images.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())

        pass_a = self._vl_pass(images, temperature=0.0)
        pass_b = self._vl_pass(images, temperature=0.4)
        by_line_b = {l["line_no"]: l for l in pass_b}
        out: list[dict[str, Any]] = []
        for la in pass_a:
            lb = by_line_b.get(la["line_no"], la)
            la = dict(la)
            la["pass_a_payout"] = la.get("payout")
            la["pass_b_payout"] = lb.get("payout")
            la["two_pass_disagreement"] = la["pass_a_payout"] != la["pass_b_payout"]
            out.append(la)
        return out

    def _vl_pass(self, images: list[str], temperature: float) -> list[dict[str, Any]]:  # pragma: no cover
        content: list[dict[str, Any]] = [
            {"type": "text", "text": (
                "Extract every settlement row from this OTA partner statement as JSON "
                "{lines:[{line_no,night,folio,room,gross,commission,payout,footnote_adjustment,"
                "page,bbox:[x0,y0,x1,y1]}]}. Read footnotes; a row split across a page break "
                "keeps one line_no. Return ONLY JSON.")},
        ]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
        resp = self._create(
            model=MODEL_VL,
            messages=[{"role": "user", "content": content}],
            temperature=temperature,
            thinking=False,  # OCR extraction: no reasoning, keep it fast
        )
        return json.loads(resp.choices[0].message.content).get("lines", [])


def _coerce_class(value: Any) -> Classification:
    try:
        return Classification(str(value))
    except ValueError:
        return Classification.UNKNOWN
