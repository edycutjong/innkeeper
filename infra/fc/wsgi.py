"""Alibaba Function Compute 3.0 — MANAGED python runtime entrypoint (EVENT handler).

No container / no ACR: FC installs requirements.txt and invokes this event
``handler(event, context)`` for the HTTP trigger. Innkeeper targets 3.12 and uses
``enum.StrEnum`` (3.11+); the managed runtime is 3.10, so we shim it BEFORE
importing the package (StrEnum is just str+Enum — byte-identical behaviour).

Everything below runs OFFLINE, zero keys, on the committed fixtures + ledger:
  GET /         service info
  GET /health   liveness → {"status":"ok"}
  GET /verify   re-verify the committed signed-close chain + replay + tamper-catch
  GET /run      run one deterministic offline night audit (?night=YYYY-MM-DD)
"""

from __future__ import annotations

import enum
import json
import os
import sys

# --- 3.10 compat shim: must run before any innkeeper_audit import ------------
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):  # noqa: D401 - drop-in for 3.11 enum.StrEnum
        def __str__(self) -> str:
            return str(self.value)
    enum.StrEnum = StrEnum  # type: ignore[attr-defined]

# Code bundle layout in FC: the build dir is copied to /code, so this file lives
# at /code/infra/fc/wsgi.py — the package ships under /code/src, the committed
# fixtures + ledger under /code/{fixtures,ledger}. Pin INNKEEPER_ROOT so
# Paths() resolves them regardless of cwd, and put src on sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
os.environ.setdefault("INNKEEPER_ROOT", _ROOT)
_SRC = os.path.join(_ROOT, "src")
if os.path.isdir(_SRC):
    sys.path.insert(0, _SRC)

DEFAULT_NIGHT = "2026-07-04"  # the one devastating night (see DEMO.md)


def _verify() -> dict:
    """Re-verify the committed offline ledger end to end (no key, no network).

    I2/I3  every signed close's Merkle root + Ed25519 signature + evidence
           bindings recompute from the bytes on disk;
    I4     the target night replays byte-identically from stored evidence;
    I3     a one-byte tamper of a stored verdict breaks the root (caught).
    """
    from innkeeper_audit.config import Paths
    from innkeeper_audit.crypto import derive_demo_keys, recompute_root
    from innkeeper_audit.pipeline import replay_night
    from innkeeper_audit.store import load_close, load_verdicts
    from innkeeper_audit.verify import verify_all

    paths = Paths()
    keys = derive_demo_keys()  # in-memory; never touches the read-only bundle
    checks = []

    cv = verify_all(paths)
    checks.append({
        "name": "I2/I3 signed-close chain + evidence bindings",
        "ok": cv.ok,
        "detail": (f"{cv.n_closes} signed closes: roots, Ed25519 signatures and "
                   f"evidence sha256 bindings all verify"
                   if cv.ok else f"chain errors: {cv.chain_errors[:2]}"),
    })

    result, replay_ok, diffs = replay_night(paths, DEFAULT_NIGHT, keys=keys)
    root = result.close.merkle_root if result.close else ""
    checks.append({
        "name": f"I4 replay {DEFAULT_NIGHT} byte-identical",
        "ok": replay_ok,
        "detail": (f"re-derived from stored evidence; root {root[:16]}… + signature reproduced"
                   if replay_ok else f"replay diffs: {diffs}"),
    })

    tamper_ok, tamper_detail = _tamper_detected(paths, DEFAULT_NIGHT, load_close,
                                                load_verdicts, recompute_root)
    checks.append({
        "name": "I3 one-byte tamper is detected",
        "ok": tamper_ok,
        "detail": tamper_detail,
    })

    overall = all(c["ok"] for c in checks)
    return {
        "overall": "PASS" if overall else "FAILED",
        "target_night": DEFAULT_NIGHT,
        "signed_closes": cv.n_closes,
        "checks": checks,
        "source": "committed offline ledger (FakeQwen — zero keys, no network)",
    }


def _tamper_detected(paths, night, load_close, load_verdicts, recompute_root) -> tuple[bool, str]:
    """In-memory tamper proof (the bundle is read-only): flip one verdict's
    confidence by a cent's worth and confirm the recomputed root diverges."""
    close = load_close(paths, night)
    verdicts = load_verdicts(paths, night)
    if recompute_root(close, verdicts) != close.merkle_root:
        return False, "stored root does not match verdicts before tamper"
    tampered = list(verdicts)
    bumped = round(tampered[0].confidence - 0.01, 4)
    tampered[0] = tampered[0].model_copy(update={"confidence": bumped})
    if recompute_root(close, tampered) == close.merkle_root:
        return False, "tamper was NOT detected — root unchanged"
    return True, "root no longer matches the signed close after a 1-cent verdict edit"


def _run(night: str) -> dict:
    """Run one night's audit offline and return a compact summary.

    write=False / update_chain=False: pure computation on the read-only bundle
    (no evidence/ledger writes, no key files), so it is safe on FC's read-only
    /code mount and produces the same verdict counts + Merkle root as the CLI.
    """
    from innkeeper_audit.config import Paths
    from innkeeper_audit.crypto import derive_demo_keys
    from innkeeper_audit.pipeline import run_night

    r = run_night(Paths(), night, keys=derive_demo_keys(), write=False, update_chain=False)
    assert r.close is not None and r.stats is not None
    return {
        "night": night,
        "transport": "FakeQwen (offline deterministic — no key required)",
        "n_txns": r.match.n_txns,
        "n_matched": r.match.n_matched,
        "n_mismatches": len(r.match.mismatches),
        "n_cleared": r.n_cleared,
        "n_queued": r.n_queued,
        "delta_total_usd": r.stats.delta_total_usd,
        "merkle_root": r.close.merkle_root,
        "signer_pubkey": r.close.signer_pubkey,
    }


def _route(path: str, qs: dict) -> tuple[int, dict]:
    path = path.rstrip("/") or "/"
    if path == "/":
        return 200, {
            "service": "innkeeper — autopilot night audit for small hotels (Qwen Cloud)",
            "endpoints": {
                "/health": "liveness",
                "/verify": "re-verify the committed signed-close chain + replay + tamper-catch (I2/I3/I4)",
                "/run": "run one deterministic offline night audit (?night=YYYY-MM-DD)",
            },
            "repo": "https://github.com/edycutjong/innkeeper",
        }
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/verify":
        return 200, _verify()
    if path == "/run":
        return 200, _run(qs.get("night", [DEFAULT_NIGHT])[0])
    return 404, {"error": f"no route {path}"}


def handler(event, context):
    """FC 3.0 event handler for an HTTP trigger.

    ``event`` is the HTTP request as JSON bytes; return {statusCode, headers, body}.
    """
    from urllib.parse import parse_qs
    try:
        req = json.loads(event) if isinstance(event, (bytes, bytearray, str)) else (event or {})
    except Exception:
        req = {}
    rc_http = (req.get("requestContext") or {}).get("http") or {}
    path = req.get("rawPath") or req.get("path") or rc_http.get("path") or "/"
    qp = req.get("queryParameters") or req.get("queryStringParameters")
    if qp:
        qs = {k: (v if isinstance(v, list) else [v]) for k, v in qp.items()}
    else:
        qs = parse_qs(req.get("rawQueryString", "") or "")
    try:
        code, payload = _route(path, qs)
    except Exception as exc:  # never 500 opaque
        code, payload = 500, {"error": type(exc).__name__, "detail": str(exc)[:400]}
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "isBase64Encoded": False,
        "body": json.dumps(payload, sort_keys=True, indent=2),
    }
