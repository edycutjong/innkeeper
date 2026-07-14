"""The 7 AM morning report: what the owner reads over coffee.

Renders a run to Markdown (always) and an optional single-page HTML. The
headline is the brand promise — "N auto-cleared · M for you · books closed" —
and every queued item carries its competing hypotheses and the E[loss] math
that sent it to review, so the policy is visible on the page.
"""

from __future__ import annotations

from .pipeline import RunResult
from .schemas import Verdict

_CLASS_LABEL = {
    "fee": "OTA / processor fee",
    "timing": "timing",
    "fx": "FX rounding",
    "duplicate": "duplicate capture",
    "true_error": "TRUE ERROR",
    "unknown": "needs a human",
}


def _verdict_line(v: Verdict) -> str:
    systems = "+".join(sorted({e.src for e in v.evidence}))
    cite = ""
    for e in v.evidence:
        if e.bbox:
            cite = f" · OTA line {e.line} bbox {[round(x) for x in e.bbox]}"
            break
    return (f"- `{v.mismatch_id}` **{_CLASS_LABEL.get(v.classification.value, v.classification.value)}**"
            f" ({v.subtype}) · ${v.materiality_usd:.2f} · conf {v.confidence:.2f}"
            f" · cites [{systems}]{cite}\n    - {v.rationale}")


def render_markdown(result: RunResult) -> str:
    s = result.stats
    assert s is not None and result.close is not None
    cleared = [v for v in result.verdicts if v.action == "auto_clear"]
    queued = [v for v in result.verdicts if v.action == "queue"]

    lines: list[str] = []
    lines.append(f"# Morning report — {result.night}")
    lines.append("")
    lines.append(f"> **{s.n_cleared} auto-cleared · {s.n_queued} for you · "
                 f"books closed** · {s.n_matched} matched of {s.n_txns} transactions")
    lines.append("")
    lines.append(f"Night close signed by `{result.close.signer_pubkey[:16]}…` · "
                 f"Merkle root `{result.close.merkle_root[:16]}…` · "
                 f"chained to `{result.close.prev_root[:8]}…`")
    lines.append("")

    if queued:
        lines.append("## For you")
        for v in queued:
            lines.append(_verdict_line(v))
            for h in v.hypotheses:
                lines.append(f"    - hypothesis: {h.h} — p={h.p:.2f}")
            eloss = round(round(v.materiality_usd * 100) * (1 - v.confidence))
            lines.append(f"    - E[loss] = ${v.materiality_usd:.2f} × (1 − {v.confidence:.2f}) "
                         f"= {eloss}¢ → queued")
        lines.append("")

    if cleared:
        lines.append("## Auto-cleared")
        # group by classification
        by_class: dict[str, list[Verdict]] = {}
        for v in cleared:
            by_class.setdefault(v.classification.value, []).append(v)
        for cls, vs in sorted(by_class.items()):
            total = sum(v.materiality_usd for v in vs)
            lines.append(f"- **{_CLASS_LABEL.get(cls, cls)}** × {len(vs)} · ${total:.2f} total")
        lines.append("")

    lines.append(f"_Δ reconciled tonight: ${s.delta_total_usd:.2f} · pipeline "
                 f"`{result.close.pipeline_version}`_")
    lines.append("")
    return "\n".join(lines)


def _html_citation(v: Verdict) -> str:
    systems = "+".join(sorted({e.src for e in v.evidence}))
    cite = ""
    for e in v.evidence:
        if e.bbox:
            cite = f" · OTA L{e.line} bbox {[round(x) for x in e.bbox]}"
            break
    return f"<code>{systems}</code>{cite}"


def render_html(result: RunResult) -> str:
    """A minimal self-contained HTML report (ledger-at-dawn theme)."""
    s = result.stats
    assert s is not None and result.close is not None
    rows = []
    for v in result.verdicts:
        color = "#ef4444" if v.classification.value == "true_error" else (
            "#D4A373" if v.action == "queue" else "#10B981")
        rows.append(
            f"<tr><td><code>{v.mismatch_id}</code></td>"
            f"<td>{_CLASS_LABEL.get(v.classification.value, v.classification.value)}</td>"
            f"<td style='text-align:right'>${v.materiality_usd:.2f}</td>"
            f"<td style='text-align:right'>{v.confidence:.2f}</td>"
            f"<td style='font-size:.82rem'>{_html_citation(v)}</td>"
            f"<td style='color:{color};font-weight:600'>{v.action}</td></tr>"
        )

    # The "verdict cards" for queued items: the competing hypotheses and the
    # E[loss] math that sent each to review — the reasoning, made visible.
    cards = []
    for v in (x for x in result.verdicts if x.action == "queue"):
        hyps = "".join(
            f"<li>{h.h} — <b>p={h.p:.2f}</b></li>" for h in v.hypotheses
        )
        eloss = round(round(v.materiality_usd * 100) * (1 - v.confidence))
        cards.append(
            f"<div class=card><div class=ct><code>{v.mismatch_id}</code> "
            f"<b>{_CLASS_LABEL.get(v.classification.value, v.classification.value)}</b> "
            f"· ${v.materiality_usd:.2f} · conf {v.confidence:.2f} · "
            f"cites {_html_citation(v)}</div>"
            f"<div class=rat>{v.rationale}</div>"
            f"<ul>{hyps}</ul>"
            f"<div class=el>E[loss] = ${v.materiality_usd:.2f} × (1 − {v.confidence:.2f}) "
            f"= {eloss}¢ → <b>queued for review</b></div></div>"
        )
    cards_html = ("<h2>For you</h2>" + "".join(cards)) if cards else ""

    return f"""<!doctype html><meta charset=utf-8>
<title>Innkeeper — {result.night}</title>
<style>
body{{background:#0C0F0D;color:#e5e7eb;font-family:Inter,system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem}}
h1{{color:#10B981}} h2{{color:#D4A373;font-size:1rem;margin:1.4rem 0 .5rem}}
.head{{font-size:1.2rem;color:#D4A373;margin:.5rem 0 1rem}}
code{{font-family:'IBM Plex Mono',monospace;color:#9ca3af}}
table{{width:100%;border-collapse:collapse;font-size:.92rem}}
td,th{{padding:.35rem .5rem;border-bottom:1px solid #1f2937}} th{{text-align:left;color:#6b7280}}
.card{{border:1px solid #7f1d1d;border-left:3px solid #ef4444;border-radius:6px;padding:.7rem .9rem;margin:.6rem 0;background:#140f0f}}
.card .ct{{color:#e5e7eb}} .card .rat{{color:#9ca3af;font-size:.86rem;margin:.35rem 0}}
.card ul{{margin:.3rem 0 .3rem 1.1rem;padding:0;font-size:.86rem;color:#d1d5db}}
.card .el{{color:#D4A373;font-size:.86rem;margin-top:.4rem}}
.sig{{color:#6b7280;font-size:.8rem;margin-top:1rem;word-break:break-all}}
</style>
<h1>Morning report — {result.night}</h1>
<div class=head>{s.n_cleared} auto-cleared · {s.n_queued} for you · books closed</div>
<table><tr><th>#</th><th>class</th><th>amount</th><th>conf</th><th>evidence</th><th>action</th></tr>
{''.join(rows)}
</table>
{cards_html}
<div class=sig>signed {result.close.signer_pubkey[:24]}… · root {result.close.merkle_root}<br>
prev {result.close.prev_root} · {result.close.pipeline_version}</div>
"""
