"""The expected-loss policy gate (SPEC §5 + COMPLEXITY §3).

The human-in-the-loop boundary is *math, not a button*:

    auto_clear  ⟺  confidence ≥ 0.85  ∧  materiality ≤ $50  ∧  class ≠ true_error

generalised, for the τ-sweep, as the expected loss of being wrong:

    E[loss] = materiality × (1 − confidence) ≤ τ

Two hard constraints override any threshold and can only ever *queue*:

  * a ``true_error`` classification (invariant I1 — the load-bearing rule);
  * an extraction ``escalation`` (invariant I5 — a two-pass disagreement is
    never averaged into a money decision).

Both thresholds are inclusive (``≥`` / ``≤``) so the boundary cases at exactly
0.85 confidence and exactly $50 materiality auto-clear, and the default τ of
750¢ is exactly ``$50 × (1 − 0.85)`` — the classic rule's worst-case expected
loss, so the two formulations coincide at the corner.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_TAU_CENTS, MATERIALITY_CAP_CENTS, MIN_CONFIDENCE
from .schemas import Classification, GateDecision, Verdict


def expected_loss_cents(materiality_cents: int, confidence: float) -> int:
    """E[loss] = materiality × (1 − confidence), rounded to whole cents."""
    return round(materiality_cents * (1.0 - confidence))


@dataclass(frozen=True)
class PolicyGate:
    """A per-hotel risk policy object. ``use_eloss`` swaps the classic
    three-condition rule for the single τ threshold used by the bench sweep."""

    min_confidence: float = MIN_CONFIDENCE
    materiality_cap_cents: int = MATERIALITY_CAP_CENTS
    tau_cents: int = DEFAULT_TAU_CENTS
    use_eloss: bool = False

    def decide(self, verdict: Verdict) -> GateDecision:
        materiality_cents = round(verdict.materiality_usd * 100)
        eloss = expected_loss_cents(materiality_cents, verdict.confidence)
        policy = {
            "min_confidence": self.min_confidence,
            "materiality_cap_cents": self.materiality_cap_cents,
            "tau_cents": self.tau_cents,
            "rule": "eloss" if self.use_eloss else "classic",
        }

        # --- hard constraints: these can only queue --------------------- #
        if verdict.classification == Classification.TRUE_ERROR:
            return GateDecision(action="queue", reason="true_error → mandatory human review (I1)",
                                eloss_cents=eloss, policy=policy)
        if verdict.escalation:
            return GateDecision(action="queue",
                                reason=f"extraction escalation ({verdict.escalation}) → human review (I5)",
                                eloss_cents=eloss, policy=policy)

        # --- threshold rule -------------------------------------------- #
        if self.use_eloss:
            if eloss <= self.tau_cents:
                return GateDecision(action="auto_clear",
                                    reason=f"E[loss] {eloss}¢ ≤ τ {self.tau_cents}¢",
                                    eloss_cents=eloss, policy=policy)
            return GateDecision(action="queue",
                                reason=f"E[loss] {eloss}¢ > τ {self.tau_cents}¢",
                                eloss_cents=eloss, policy=policy)

        conf_ok = verdict.confidence >= self.min_confidence
        mat_ok = materiality_cents <= self.materiality_cap_cents
        if conf_ok and mat_ok:
            return GateDecision(
                action="auto_clear",
                reason=(f"confidence {verdict.confidence:.2f} ≥ {self.min_confidence:.2f} ∧ "
                        f"materiality ${materiality_cents/100:.2f} ≤ "
                        f"${self.materiality_cap_cents/100:.2f}"),
                eloss_cents=eloss, policy=policy,
            )
        why = []
        if not conf_ok:
            why.append(f"confidence {verdict.confidence:.2f} < {self.min_confidence:.2f}")
        if not mat_ok:
            why.append(f"materiality ${materiality_cents/100:.2f} > ${self.materiality_cap_cents/100:.2f}")
        return GateDecision(action="queue", reason=" ∧ ".join(why), eloss_cents=eloss, policy=policy)

    def apply(self, verdict: Verdict) -> GateDecision:
        """Decide and write the action back onto the verdict."""
        decision = self.decide(verdict)
        verdict.action = decision.action
        return decision


DEFAULT_GATE = PolicyGate()
