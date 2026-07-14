"""Alibaba Function Compute entrypoint for the nightly timer trigger.

The FC timer (s.yaml) invokes ``handler`` at 02:00. It resolves "auto" to
yesterday's business date, runs the audit end to end, and returns the signed
close stats. Signing uses the Ed25519 key from ``INNKEEPER_SIGNING_KEY`` (env),
never a committed key.

This is the deployment shape; see PROOF.md for the honest status of what is and
is not live.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from innkeeper_audit.config import Paths
from innkeeper_audit.pipeline import run_night
from innkeeper_audit.qwen import get_adjudicator


def _resolve_night(payload: dict) -> str:
    night = payload.get("night", "auto")
    if night == "auto":
        return (date.today() - timedelta(days=1)).isoformat()
    return night


def handler(event, context):  # noqa: ANN001 - FC signature
    payload = {}
    if event:
        try:
            payload = json.loads(event if isinstance(event, (str, bytes)) else event.decode())
        except (ValueError, AttributeError):
            payload = {}

    night = _resolve_night(payload)
    paths = Paths()
    # live VL + adjudication when the key is present; deterministic otherwise
    import os

    adjudicator = get_adjudicator(live=bool(os.environ.get("DASHSCOPE_API_KEY")))
    result = run_night(paths, night, adjudicator=adjudicator)
    assert result.stats is not None and result.close is not None

    body = {
        "night": night,
        "merkle_root": result.close.merkle_root,
        "signer": result.close.signer_pubkey[:16],
        "n_cleared": result.stats.n_cleared,
        "n_queued": result.stats.n_queued,
        "n_matched": result.stats.n_matched,
    }
    return json.dumps(body)
