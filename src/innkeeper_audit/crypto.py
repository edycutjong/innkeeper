"""Cryptographic spine (COMPLEXITY §2).

Three primitives, all offline and deterministic:

  * **Signed Merkle night-closes** — each night's verdicts are hashed into a
    Merkle tree; the root + stats are Ed25519-signed and chained via
    ``prev_root`` into a tamper-evident ledger-of-ledgers.
  * **Evidence binding** — every verdict cites artifacts by ``sha256``; the
    citations must resolve against the bytes on disk (invariant I2/I3).
  * **Payload envelope** — OTA statement PDFs are ECIES-sealed at rest with a
    pynacl :class:`SealedBox` (anonymous sender), unsealed only in the worker.

The demo keypair is derived deterministically from ``config.SEED`` so
``seed.py --regen`` reproduces byte-identical *plaintext*; the SealedBox
ciphertext is intentionally non-deterministic (ephemeral sender key) and is
excluded from the fixture manifest, with the unseal round-trip asserted by test.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from nacl.exceptions import BadSignatureError, CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey

from .config import GENESIS_ROOT, SEED, Paths
from .schemas import (
    CloseStats,
    EvidenceRef,
    NightClose,
    Verdict,
    canonical_json,
    doc_hash,
    sha256_hex,
)

# --------------------------------------------------------------------------- #
# deterministic demo keys
# --------------------------------------------------------------------------- #


def _seed32(label: str) -> bytes:
    """A fixed 32-byte seed for a named key, derived from the global SEED."""
    return hashlib.sha256(f"{label}:{SEED}".encode("utf-8")).digest()


@dataclass(frozen=True)
class DemoKeys:
    """The night-close signing keypair + the statement-sealing keypair.

    In production the Ed25519 *private* signing key lives in the FC env and only
    the public key is committed (PRODUCTION_PLAN.md). Here both are derived from
    the seed so any machine reproduces the same signatures for replay tests.
    """

    signing_key: SigningKey
    verify_key: VerifyKey
    sealing_priv: PrivateKey
    sealing_pub: PublicKey

    @property
    def signer_pubkey_hex(self) -> str:
        return self.verify_key.encode().hex()


def derive_demo_keys() -> DemoKeys:
    sk = SigningKey(_seed32("innkeeper-signing"))
    sp = PrivateKey(_seed32("innkeeper-sealing"))
    return DemoKeys(
        signing_key=sk,
        verify_key=sk.verify_key,
        sealing_priv=sp,
        sealing_pub=sp.public_key,
    )


def ensure_demo_keys(paths: Paths) -> DemoKeys:
    """Derive the demo keys and persist their public halves (+ a demo private
    key) under ``fixtures/.../keys`` so a judge can verify closes with zero
    setup. Idempotent and deterministic."""
    keys = derive_demo_keys()
    d = paths.keys_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "close_signing.pub").write_text(keys.signer_pubkey_hex + "\n", encoding="utf-8")
    # demo-only private key (real deployments keep this in the FC env, gitignored)
    (d / "close_signing.demo.key").write_text(
        bytes(keys.signing_key).hex() + "\n", encoding="utf-8"
    )
    (d / "statement_sealing.pub").write_text(
        bytes(keys.sealing_pub).hex() + "\n", encoding="utf-8"
    )
    (d / "statement_sealing.demo.key").write_text(
        bytes(keys.sealing_priv).hex() + "\n", encoding="utf-8"
    )
    (d / "README.txt").write_text(
        "DEMO KEYS ONLY — derived deterministically from the fixture seed.\n"
        "Never reuse for anything real. Production signing keys live in the FC\n"
        "environment; only close_signing.pub is committed there.\n",
        encoding="utf-8",
    )
    return keys


def load_verify_key(paths: Paths) -> VerifyKey:
    """Load the committed public signing key (the zero-key judge path)."""
    hexed = (paths.keys_dir / "close_signing.pub").read_text(encoding="utf-8").strip()
    return VerifyKey(bytes.fromhex(hexed))


# --------------------------------------------------------------------------- #
# payload envelope: ECIES SealedBox
# --------------------------------------------------------------------------- #


def seal_bytes(data: bytes, sealing_pub: PublicKey) -> bytes:
    """ECIES seal (anonymous sender). Ciphertext is non-deterministic."""
    return SealedBox(sealing_pub).encrypt(data)


def unseal_bytes(ciphertext: bytes, sealing_priv: PrivateKey) -> bytes:
    """Inverse of :func:`seal_bytes`. Raises on tamper/wrong key."""
    return SealedBox(sealing_priv).decrypt(ciphertext)


# --------------------------------------------------------------------------- #
# Merkle tree over verdict hashes
# --------------------------------------------------------------------------- #

_EMPTY_ROOT = hashlib.sha256(b"innkeeper:empty-night").hexdigest()


def _merkle_leaf(h_hex: str) -> str:
    return sha256_hex("leaf:" + h_hex)


def _merkle_node(a: str, b: str) -> str:
    return sha256_hex("node:" + a + b)


def merkle_root(leaf_hashes: list[str]) -> str:
    """Root over ordered leaf hashes. Domain-separated leaf/node prefixes guard
    against second-preimage tricks; an odd level duplicates its last node."""
    if not leaf_hashes:
        return _EMPTY_ROOT
    level = [_merkle_leaf(h) for h in leaf_hashes]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_merkle_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def verdict_leaf_hashes(verdicts: list[Verdict]) -> list[str]:
    """The Merkle leaves: the canonical doc-hash of each verdict, in list order."""
    return [doc_hash(v) for v in verdicts]


# --------------------------------------------------------------------------- #
# night close: build / sign / verify
# --------------------------------------------------------------------------- #


def close_payload(close: NightClose) -> bytes:
    """The exact bytes that get signed — root + prev + stats + version.

    Excludes the signature/pubkey fields themselves and never includes wall
    clock time, so ``replay`` reproduces an identical signature (invariant I4).
    """
    return canonical_json(
        {
            "night": close.night,
            "merkle_root": close.merkle_root,
            "prev_root": close.prev_root,
            "stats": close.stats.model_dump(mode="json"),
            "pipeline_version": close.pipeline_version,
            "verdict_hashes": close.verdict_hashes,
        }
    ).encode("utf-8")


def build_close(
    night: str,
    verdicts: list[Verdict],
    prev_root: str,
    stats: CloseStats,
    pipeline_version: str,
) -> NightClose:
    """Assemble an *unsigned* close: compute leaves + root, carry prev_root."""
    leaves = verdict_leaf_hashes(verdicts)
    return NightClose(
        night=night,
        merkle_root=merkle_root(leaves),
        prev_root=prev_root,
        stats=stats,
        pipeline_version=pipeline_version,
        verdict_hashes=leaves,
    )


def sign_close(close: NightClose, keys: DemoKeys) -> NightClose:
    sig = keys.signing_key.sign(close_payload(close)).signature
    close.signature = sig.hex()
    close.signer_pubkey = keys.signer_pubkey_hex
    return close


def verify_close(close: NightClose) -> bool:
    """True iff the signature is valid for the payload under the stated pubkey."""
    if not close.signature or not close.signer_pubkey:
        return False
    try:
        VerifyKey(bytes.fromhex(close.signer_pubkey)).verify(
            close_payload(close), bytes.fromhex(close.signature)
        )
        return True
    except (BadSignatureError, ValueError):
        return False


def recompute_root(close: NightClose, verdicts: list[Verdict]) -> str:
    """Re-derive the root from the actual verdicts — for tamper detection (I3)."""
    return merkle_root(verdict_leaf_hashes(verdicts))


# --------------------------------------------------------------------------- #
# chain verification
# --------------------------------------------------------------------------- #


def verify_chain(closes: list[NightClose]) -> tuple[bool, list[str]]:
    """Verify signatures + prev_root linkage across an ordered list of closes.

    Returns ``(ok, errors)``. A one-byte tamper anywhere flips ``ok`` to False.
    """
    errors: list[str] = []
    prev = GENESIS_ROOT
    for c in sorted(closes, key=lambda c: c.night):
        if not verify_close(c):
            errors.append(f"{c.night}: signature invalid")
        if c.prev_root != prev:
            errors.append(
                f"{c.night}: prev_root {c.prev_root[:12]} != expected {prev[:12]}"
            )
        prev = c.merkle_root
    return (not errors, errors)


# --------------------------------------------------------------------------- #
# evidence-hash binding (invariant I2 / I3)
# --------------------------------------------------------------------------- #


def _artifact_path(evidence_root: Path, uri: str) -> tuple[Path, str | None]:
    """Split ``evidence/pms.json#folio-1188`` into (file path, fragment)."""
    body = uri.split("#", 1)
    frag = body[1] if len(body) > 1 else None
    rel = body[0]
    if rel.startswith("evidence/"):
        rel = rel[len("evidence/") :]
    return evidence_root / rel, frag


def resolve_evidence(evidence_root: Path, ref: EvidenceRef) -> tuple[bool, str]:
    """Check a single citation: the file exists and its sha256 matches ``ref``.

    ``evidence_root`` is the night's ``.../evidence`` directory. Returns
    ``(ok, detail)``.
    """
    path, _frag = _artifact_path(evidence_root, ref.uri)
    if not path.exists():
        return False, f"missing artifact {ref.uri}"
    actual = sha256_hex(path.read_bytes())
    if actual != ref.sha256:
        return False, f"sha256 mismatch for {ref.uri}: {actual[:12]} != {ref.sha256[:12]}"
    return True, "ok"


def verify_evidence_bindings(
    evidence_root: Path, verdicts: list[Verdict]
) -> tuple[bool, list[str]]:
    """Invariant I2: every verdict cites ≥2 systems and every citation resolves."""
    errors: list[str] = []
    for v in verdicts:
        systems = {e.src for e in v.evidence}
        if len(systems) < 2:
            errors.append(f"{v.mismatch_id}: cites <2 systems {sorted(systems)}")
        for ref in v.evidence:
            ok, detail = resolve_evidence(evidence_root, ref)
            if not ok:
                errors.append(f"{v.mismatch_id}: {detail}")
    return (not errors, errors)


def try_unseal_statement(sealed: bytes, keys: DemoKeys) -> bytes | None:
    """Best-effort unseal used by verify tooling; returns None on failure."""
    try:
        return unseal_bytes(sealed, keys.sealing_priv)
    except CryptoError:
        return None
