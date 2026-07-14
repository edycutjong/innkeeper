"""``innkeeper`` — the operator CLI (COMPLEXITY §4).

    innkeeper seed --nights 30      regenerate the deterministic month + PDFs
    innkeeper run --night 2026-07-04 run one night end to end (signed close)
    innkeeper replay --night …      re-derive from stored evidence, prove I4
    innkeeper verify-chain          zero-key chain + evidence verification
    innkeeper bench                 score the month vs ground truth
    innkeeper report --night …      render the morning report
"""

from __future__ import annotations

import typer

from .config import MONTH, NIGHTS, Paths

app = typer.Typer(add_completion=False, help="Autopilot night audit for small hotels.")


@app.command()
def seed(nights: int = NIGHTS, month: str = MONTH, regen: bool = False) -> None:
    """Generate (or --regen) the deterministic seeded month + rendered PDFs."""
    from .seed import generate_month

    paths = Paths()
    manifest = generate_month(paths, nights=nights, month=month)
    typer.echo(f"seeded {nights} nights → {paths.fixtures}")
    typer.echo(f"  files: {len(manifest['files'])} · pdf sha256 {manifest['pdf_sha256'][:16]}… · "
               f"ground-truth mismatches: {_gt_total(paths)}")


@app.command()
def run(night: str = typer.Option(..., help="business date YYYY-MM-DD"),
        live: bool = False, report: bool = False, month: str = MONTH) -> None:
    """Run one night: fetch → extract → match → adjudicate → gate → signed close."""
    from .pipeline import run_night
    from .qwen import get_adjudicator

    paths = Paths()
    adj = get_adjudicator(live=live)
    result = run_night(paths, night, adjudicator=adj, month=month)
    s = result.stats
    assert s is not None and result.close is not None
    typer.echo(f"{night}: {s.n_txns} txns · {s.n_matched} matched · "
               f"{len(result.verdicts)} mismatches → {s.n_cleared} auto-cleared, "
               f"{s.n_queued} queued")
    typer.echo(f"  close root {result.close.merkle_root[:16]}… signed "
               f"{result.close.signer_pubkey[:12]}…")
    for v in result.verdicts:
        if v.action == "queue":
            typer.echo(f"  → QUEUE {v.mismatch_id} {v.classification.value}/{v.subtype} "
                       f"${v.materiality_usd:.2f} conf {v.confidence:.2f}")
    if report:
        from .report import render_markdown

        out = paths.run_dir(night) / "report.md"
        out.write_text(render_markdown(result), encoding="utf-8")
        typer.echo(f"  report → {out}")


@app.command()
def replay(night: str = typer.Option(..., help="business date YYYY-MM-DD"),
           month: str = MONTH) -> None:
    """Re-derive a night from stored evidence and compare to its signed close."""
    from .pipeline import replay_night

    paths = Paths()
    result, ok, diffs = replay_night(paths, night, month=month)
    assert result.close is not None
    if ok:
        typer.echo(f"replay {night}: IDENTICAL · root {result.close.merkle_root[:16]}… "
                   f"· signature reproduced (invariant I4)")
    else:
        typer.echo(f"replay {night}: MISMATCH · {'; '.join(diffs)}")
        raise typer.Exit(1)


@app.command(name="verify-chain")
def verify_chain(night: str = typer.Option(None, help="verify a single night (default: whole chain)")) -> None:
    """Verify the signed close chain + evidence bindings (zero keys required)."""
    from .verify import format_chain_report, verify_all, verify_night

    paths = Paths()
    if night:
        r = verify_night(paths, night)
        typer.echo(f"{night}: {'OK' if r.ok else 'FAILED'} "
                   f"root={r.root_ok} sig={r.signature_ok} evidence={r.evidence_ok}")
        if not r.ok:
            for e in r.errors:
                typer.echo(f"  ! {e}")
            raise typer.Exit(1)
        return
    cv = verify_all(paths)
    typer.echo(format_chain_report(cv))
    if not cv.ok:
        raise typer.Exit(1)


@app.command()
def bench(markdown: bool = False) -> None:
    """Score the seeded month against ground truth (accuracy, false-clears, τ-sweep)."""
    from .benchmark import bench_markdown, run_bench

    paths = Paths()
    report = run_bench(paths)
    if markdown:
        typer.echo(bench_markdown(report))
        return
    typer.echo(report.headline())
    typer.echo(f"  action accuracy {report.action_accuracy:.4f} · "
               f"queue precision/recall {report.queue_precision:.2f}/{report.queue_recall:.2f}")
    typer.echo(f"  residue {report.residue_fraction:.2%} · runtime {report.runtime_s:.2f}s · "
               f"modelled ${report.est_cost_per_night_usd:.4f}/night")
    if report.false_auto_clears:
        raise typer.Exit(1)


@app.command()
def report(night: str = typer.Option(..., help="business date YYYY-MM-DD"),
           html: bool = False, month: str = MONTH) -> None:
    """Render the morning report for a night (runs it if needed)."""
    from .pipeline import run_night
    from .report import render_html, render_markdown

    paths = Paths()
    result = run_night(paths, night, month=month)
    if html:
        out = paths.run_dir(night) / "report.html"
        out.write_text(render_html(result), encoding="utf-8")
    else:
        out = paths.run_dir(night) / "report.md"
        out.write_text(render_markdown(result), encoding="utf-8")
    typer.echo(render_markdown(result))
    typer.echo(f"\n(written to {out})")


def _gt_total(paths: Paths) -> int:
    from .store import read_json

    return read_json(paths.ground_truth)["counts"]["total"]


if __name__ == "__main__":  # pragma: no cover
    app()
