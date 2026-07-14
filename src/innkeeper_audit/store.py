"""Filesystem store: fixtures in, ledger (runs / closes / evidence) out.

Offline-first: everything a judge needs to re-derive a night lives in the
repo — no database required. The documented production target (ApsaraDB RDS)
maps 1:1 onto these JSON documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Paths
from .schemas import NightClose, Txn, Verdict, canonical_json, sha256_hex


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def file_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


# --------------------------------------------------------------------------- #
# fixtures (inputs)
# --------------------------------------------------------------------------- #


def load_pms(paths: Paths, night: str) -> list[Txn]:
    return [Txn(**t) for t in read_json(paths.pms_dir / f"{night}.json")["txns"]]


def load_processor(paths: Paths, night: str) -> list[Txn]:
    return [Txn(**t) for t in read_json(paths.processor_dir / f"{night}.json")["txns"]]


def load_sidecar(paths: Paths, month: str) -> dict[str, Any]:
    return read_json(paths.ota_sidecar(month))


def load_ground_truth(paths: Paths) -> dict[str, dict[str, Any]]:
    """Ground-truth labels keyed by "<night>/<anchor_ref>"."""
    gt = read_json(paths.ground_truth)
    return {f"{e['night']}/{e['anchor_ref']}": e for e in gt["mismatches"]}


# --------------------------------------------------------------------------- #
# ledger (outputs)
# --------------------------------------------------------------------------- #


def evidence_dir(paths: Paths, night: str) -> Path:
    return paths.run_dir(night) / "evidence"


def evidence_docs(
    night: str,
    pms: list[Txn],
    proc: list[Txn],
    ota_lines: list[dict[str, Any]],
    pdf_sha256: str,
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Build the canonical evidence payloads and their sha256s *without*
    touching disk. Pure and deterministic, so ``replay`` can rebind citations
    to identical hashes for the tamper/replay invariants."""
    docs_obj = {
        "pms.json": {"night": night, "txns": [t.model_dump(mode="json") for t in pms]},
        "processor.json": {"night": night, "txns": [t.model_dump(mode="json") for t in proc]},
        "ota_lines.json": {"night": night, "pdf_sha256": pdf_sha256, "lines": ota_lines},
    }
    payloads: dict[str, bytes] = {}
    shas: dict[str, str] = {}
    for name, doc in docs_obj.items():
        payload = canonical_json(doc).encode("utf-8")
        payloads[name] = payload
        shas[name] = sha256_hex(payload)
    return payloads, shas


def write_evidence(
    paths: Paths,
    night: str,
    pms: list[Txn],
    proc: list[Txn],
    ota_lines: list[dict[str, Any]],
    pdf_sha256: str,
    sealed_pdf: bytes | None = None,
) -> dict[str, str]:
    """Write per-night evidence artifacts; return {relname: sha256}.

    Verdicts cite into these files; invariant I2 requires every citation's
    sha256 to resolve against the bytes on disk.
    """
    ev = evidence_dir(paths, night)
    ev.mkdir(parents=True, exist_ok=True)
    payloads, shas = evidence_docs(night, pms, proc, ota_lines, pdf_sha256)
    for name, payload in payloads.items():
        (ev / name).write_bytes(payload)
    if sealed_pdf is not None:
        # ECIES-sealed statement at rest (COMPLEXITY §2 payload envelope).
        (ev / "statement.pdf.sealed").write_bytes(sealed_pdf)
    write_json(ev / "MANIFEST.json", {"night": night, "sha256": shas, "pdf_sha256": pdf_sha256})
    return shas


def load_evidence_manifest(paths: Paths, night: str) -> dict[str, Any]:
    return read_json(evidence_dir(paths, night) / "MANIFEST.json")


def write_verdicts(paths: Paths, night: str, verdicts: list[Verdict]) -> None:
    doc = {"night": night, "verdicts": [v.model_dump(mode="json") for v in verdicts]}
    payload = canonical_json(doc).encode("utf-8")
    p = paths.run_dir(night) / "verdicts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)


def load_verdicts(paths: Paths, night: str) -> list[Verdict]:
    doc = read_json(paths.run_dir(night) / "verdicts.json")
    return [Verdict(**v) for v in doc["verdicts"]]


def write_close(paths: Paths, close: NightClose) -> None:
    write_json(paths.run_dir(close.night) / "close.json", close.model_dump(mode="json"))


def load_close(paths: Paths, night: str) -> NightClose:
    return NightClose(**read_json(paths.run_dir(night) / "close.json"))


def load_chain(paths: Paths) -> list[dict[str, Any]]:
    if not paths.chain_file.exists():
        return []
    return read_json(paths.chain_file)["closes"]


def write_chain(paths: Paths, closes: list[dict[str, Any]]) -> None:
    write_json(paths.chain_file, {"closes": closes})


def upsert_chain_entry(paths: Paths, close: NightClose) -> None:
    closes = load_chain(paths)
    entry = {
        "night": close.night,
        "merkle_root": close.merkle_root,
        "prev_root": close.prev_root,
        "signature": close.signature,
        "signer_pubkey": close.signer_pubkey,
    }
    closes = [c for c in closes if c["night"] != close.night]
    closes.append(entry)
    closes.sort(key=lambda c: c["night"])
    write_chain(paths, closes)
