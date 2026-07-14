"""Merkle roots, Ed25519 close signatures, chain linkage, and ECIES sealing."""

from __future__ import annotations

import pytest

from innkeeper_audit.config import GENESIS_ROOT, Paths
from innkeeper_audit.crypto import (
    build_close,
    derive_demo_keys,
    ensure_demo_keys,
    load_verify_key,
    merkle_root,
    resolve_evidence,
    seal_bytes,
    sign_close,
    try_unseal_statement,
    unseal_bytes,
    verify_chain,
    verify_close,
    verify_evidence_bindings,
)
from innkeeper_audit.schemas import (
    Classification,
    CloseStats,
    EvidenceRef,
    Hypothesis,
    Verdict,
)

H = "b" * 64


def _v(mid, conf=0.9):
    return Verdict(
        mismatch_id=mid, night="2026-07-04", classification=Classification.FEE,
        confidence=conf,
        evidence=[EvidenceRef(src="pms", uri="a", sha256=H), EvidenceRef(src="ota", uri="b", sha256=H)],
        hypotheses=[Hypothesis(h="x", p=conf)],
    )


def _stats(night="2026-07-04"):
    return CloseStats(date=night, n_txns=39, n_matched=27, n_mismatches=12,
                      n_cleared=11, n_queued=1, delta_total_usd=1.0)


# ---- Merkle -------------------------------------------------------------- #

def test_merkle_deterministic():
    assert merkle_root(["a", "b", "c"]) == merkle_root(["a", "b", "c"])


def test_merkle_empty_is_defined():
    assert len(merkle_root([])) == 64


def test_merkle_order_matters():
    assert merkle_root(["a", "b"]) != merkle_root(["b", "a"])


def test_merkle_single_leaf():
    assert merkle_root(["x"]) != merkle_root([])


def test_merkle_odd_level_handled():
    # 3 leaves exercises the duplicate-last branch without error
    assert len(merkle_root(["a", "b", "c"])) == 64


def test_merkle_leaf_change_changes_root():
    assert merkle_root(["a", "b", "c"]) != merkle_root(["a", "b", "d"])


# ---- keys / signing ------------------------------------------------------ #

def test_keys_are_deterministic():
    a, b = derive_demo_keys(), derive_demo_keys()
    assert a.signer_pubkey_hex == b.signer_pubkey_hex
    assert bytes(a.sealing_pub) == bytes(b.sealing_pub)


def test_sign_and_verify_close():
    keys = derive_demo_keys()
    close = build_close("2026-07-04", [_v("m-01"), _v("m-02")], GENESIS_ROOT, _stats(), "v1")
    sign_close(close, keys)
    assert verify_close(close)
    assert close.signer_pubkey == keys.signer_pubkey_hex


def test_signature_is_reproducible():
    # Ed25519 is deterministic → replay reproduces the exact signature (I4)
    keys = derive_demo_keys()
    c1 = sign_close(build_close("2026-07-04", [_v("m-01")], GENESIS_ROOT, _stats(), "v1"), keys)
    c2 = sign_close(build_close("2026-07-04", [_v("m-01")], GENESIS_ROOT, _stats(), "v1"), keys)
    assert c1.signature == c2.signature


def test_verify_fails_on_tampered_root():
    keys = derive_demo_keys()
    close = sign_close(build_close("2026-07-04", [_v("m-01")], GENESIS_ROOT, _stats(), "v1"), keys)
    close.merkle_root = "0" * 64
    assert not verify_close(close)


def test_verify_fails_on_tampered_stats():
    keys = derive_demo_keys()
    close = sign_close(build_close("2026-07-04", [_v("m-01")], GENESIS_ROOT, _stats(), "v1"), keys)
    close.stats.n_cleared = 999
    assert not verify_close(close)


def test_unsigned_close_does_not_verify():
    close = build_close("2026-07-04", [_v("m-01")], GENESIS_ROOT, _stats(), "v1")
    assert not verify_close(close)


# ---- chain --------------------------------------------------------------- #

def test_chain_verifies_when_linked():
    keys = derive_demo_keys()
    c1 = sign_close(build_close("2026-07-01", [_v("m-01")], GENESIS_ROOT, _stats("2026-07-01"), "v1"), keys)
    c2 = sign_close(build_close("2026-07-02", [_v("m-02")], c1.merkle_root, _stats("2026-07-02"), "v1"), keys)
    ok, errs = verify_chain([c1, c2])
    assert ok and not errs


def test_chain_detects_broken_prev_link():
    keys = derive_demo_keys()
    c1 = sign_close(build_close("2026-07-01", [_v("m-01")], GENESIS_ROOT, _stats("2026-07-01"), "v1"), keys)
    c2 = sign_close(build_close("2026-07-02", [_v("m-02")], "f" * 64, _stats("2026-07-02"), "v1"), keys)
    ok, errs = verify_chain([c1, c2])
    assert not ok and any("prev_root" in e for e in errs)


def test_chain_first_night_uses_genesis():
    keys = derive_demo_keys()
    c1 = sign_close(build_close("2026-07-01", [_v("m-01")], GENESIS_ROOT, _stats("2026-07-01"), "v1"), keys)
    ok, _ = verify_chain([c1])
    assert ok


# ---- ECIES seal ---------------------------------------------------------- #

def test_seal_unseal_roundtrip():
    keys = derive_demo_keys()
    data = b"partner statement bytes"
    sealed = seal_bytes(data, keys.sealing_pub)
    assert sealed != data
    assert unseal_bytes(sealed, keys.sealing_priv) == data


def test_seal_is_nondeterministic_but_unseals():
    keys = derive_demo_keys()
    a = seal_bytes(b"x", keys.sealing_pub)
    b = seal_bytes(b"x", keys.sealing_pub)
    assert a != b  # ephemeral sender key
    assert unseal_bytes(a, keys.sealing_priv) == unseal_bytes(b, keys.sealing_priv) == b"x"


def test_unseal_wrong_key_fails():
    keys = derive_demo_keys()
    sealed = seal_bytes(b"secret", keys.sealing_pub)
    other = derive_demo_keys().sealing_priv
    # same seed → same key here, so build a genuinely different key
    from nacl.public import PrivateKey

    with pytest.raises(Exception):
        unseal_bytes(sealed, PrivateKey.generate())
    assert unseal_bytes(sealed, other) == b"secret"


def test_try_unseal_statement_roundtrips():
    keys = derive_demo_keys()
    sealed = seal_bytes(b"night audit statement bytes", keys.sealing_pub)
    assert try_unseal_statement(sealed, keys) == b"night audit statement bytes"


def test_try_unseal_statement_returns_none_on_garbage():
    keys = derive_demo_keys()
    # not a valid SealedBox ciphertext at all -> CryptoError, swallowed to None
    assert try_unseal_statement(b"not a real sealed ciphertext, just junk", keys) is None


# ---- zero-key judge path: committed public key -------------------------- #

def test_load_verify_key_matches_derived_pubkey(tmp_path):
    paths = Paths(root=tmp_path)
    keys = ensure_demo_keys(paths)
    vk = load_verify_key(paths)
    assert vk.encode().hex() == keys.signer_pubkey_hex


# ---- evidence-hash binding ------------------------------------------------ #

def test_resolve_evidence_missing_artifact_file(tmp_path):
    ref = EvidenceRef(src="pms", uri="evidence/pms.json#folio-1", sha256=H)
    ok, detail = resolve_evidence(tmp_path, ref)
    assert not ok
    assert "missing artifact" in detail


def test_verify_evidence_bindings_flags_lt_two_systems(tmp_path):
    # the Verdict schema itself already forbids <2 distinct systems at
    # construction time; model_construct bypasses that to exercise this
    # module's own defense-in-depth check independently of the schema guard.
    v = Verdict.model_construct(
        mismatch_id="m-01", night="2026-07-01", anchor_ref="folio-1",
        classification=Classification.FEE, subtype="x", confidence=0.9,
        evidence=[EvidenceRef(src="pms", uri="a", sha256=H), EvidenceRef(src="pms", uri="b", sha256=H)],
        hypotheses=[Hypothesis(h="x", p=0.9)], action="queue",
        materiality_usd=1.0, delta_usd=1.0, model="test", escalation=None,
    )
    ok, errs = verify_evidence_bindings(tmp_path, [v])
    assert not ok
    assert any("cites <2 systems" in e for e in errs)


# ---- chain: invalid signature (distinct from broken prev_root) ----------- #

def test_chain_detects_invalid_signature_with_correct_linkage():
    keys = derive_demo_keys()
    c1 = sign_close(build_close("2026-07-01", [_v("m-01")], GENESIS_ROOT, _stats("2026-07-01"), "v1"), keys)
    c1.signature = "00" * 64  # corrupt the signature only; prev_root linkage stays correct
    ok, errs = verify_chain([c1])
    assert not ok
    assert any("signature invalid" in e for e in errs)
    assert not any("prev_root" in e for e in errs)
