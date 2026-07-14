"""The gate is math. Boundary cases at EXACTLY $50 and EXACTLY 0.85, plus the
true_error / escalation hard-queues that no threshold can override."""

from __future__ import annotations

import pytest

from innkeeper_audit.policy import PolicyGate, expected_loss_cents
from innkeeper_audit.schemas import (
    Classification,
    EvidenceRef,
    Hypothesis,
    Verdict,
)

H = "c" * 64


def V(materiality_usd, confidence, cls=Classification.FEE, escalation=None):
    return Verdict(
        mismatch_id="m-01", night="2026-07-04", classification=cls,
        confidence=confidence,
        evidence=[EvidenceRef(src="pms", uri="a", sha256=H),
                  EvidenceRef(src="ota", uri="b", sha256=H)],
        hypotheses=[Hypothesis(h="x", p=min(confidence, 1.0))],
        materiality_usd=materiality_usd, escalation=escalation,
    )


GATE = PolicyGate()


# ---- classic-rule boundaries -------------------------------------------- #

def test_exactly_50_dollars_auto_clears():
    assert GATE.decide(V(50.00, 0.90)).action == "auto_clear"


def test_just_over_50_queues():
    assert GATE.decide(V(50.01, 0.99)).action == "queue"


def test_exactly_085_confidence_auto_clears():
    assert GATE.decide(V(10.00, 0.85)).action == "auto_clear"


def test_just_under_085_queues():
    assert GATE.decide(V(10.00, 0.849)).action == "queue"


@pytest.mark.parametrize("mat,conf,action", [
    (5.67, 0.94, "auto_clear"),   # the demo commission
    (0.04, 0.97, "auto_clear"),   # FX noise
    (49.99, 0.85, "auto_clear"),
    (50.00, 0.85, "auto_clear"),
    (50.01, 0.85, "queue"),
    (10.00, 0.84, "queue"),
    (179.00, 0.90, "queue"),      # duplicate: materiality cap
])
def test_classic_matrix(mat, conf, action):
    assert GATE.decide(V(mat, conf)).action == action


# ---- hard constraints ---------------------------------------------------- #

@pytest.mark.parametrize("conf", [0.0, 0.5, 0.85, 0.99, 1.0])
@pytest.mark.parametrize("mat", [0.01, 5.0, 50.0, 500.0])
def test_true_error_always_queues(conf, mat):
    d = GATE.decide(V(mat, conf, cls=Classification.TRUE_ERROR))
    assert d.action == "queue" and "I1" in d.reason


@pytest.mark.parametrize("conf", [0.0, 0.85, 0.99])
def test_escalation_always_queues(conf):
    d = GATE.decide(V(1.0, conf, escalation="two_pass_disagreement"))
    assert d.action == "queue" and "I5" in d.reason


# ---- E[loss] generalisation ---------------------------------------------- #

@pytest.mark.parametrize("mat,conf,eloss", [
    (50.00, 0.85, 750),   # exactly τ default
    (100.0, 0.99, 100),
    (5.67, 0.94, 34),
])
def test_expected_loss_math(mat, conf, eloss):
    assert expected_loss_cents(round(mat * 100), conf) == eloss


def test_eloss_mode_boundary_at_tau():
    g = PolicyGate(tau_cents=750, use_eloss=True)
    # E[loss] = 5000 * 0.15 = 750 == τ → auto_clear (inclusive)
    assert g.decide(V(50.00, 0.85)).action == "auto_clear"
    # E[loss] = 5001*0.15 = 750.15 → 750 rounded == τ still clears; push clearly over
    assert g.decide(V(60.00, 0.85)).action == "queue"  # 6000*0.15=900 > 750


def test_eloss_mode_still_honours_true_error():
    g = PolicyGate(tau_cents=10 ** 9, use_eloss=True)  # τ huge
    assert g.decide(V(1.0, 0.99, cls=Classification.TRUE_ERROR)).action == "queue"


def test_apply_writes_action_onto_verdict():
    v = V(5.67, 0.94)
    assert v.action == "queue"  # default
    GATE.apply(v)
    assert v.action == "auto_clear"


def test_decision_carries_eloss_and_policy():
    d = GATE.decide(V(5.67, 0.94))
    assert d.eloss_cents == 34
    assert d.policy["rule"] == "classic"
