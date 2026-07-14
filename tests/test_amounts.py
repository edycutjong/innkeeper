"""Money arithmetic is exact integer cents — no float drift into gate math."""

from __future__ import annotations

import pytest

from innkeeper_audit.amounts import fmt_usd, pct_of, to_cents, to_dollars


@pytest.mark.parametrize("dollars,cents", [
    (189.00, 18900), (183.33, 18333), (0.04, 4), (310, 31000),
    (0.0, 0), (149.99, 14999), ("155.00", 15500),
])
def test_to_cents_exact(dollars, cents):
    assert to_cents(dollars) == cents


def test_the_canonical_567():
    # the demo's load-bearing subtraction: 189.00 - 183.33 == exactly $5.67
    assert to_cents(189.00) - to_cents(183.33) == 567


def test_no_float_drift():
    assert to_cents(189.00) - to_cents(183.33) != 566
    assert to_dollars(567) == 5.67


@pytest.mark.parametrize("cents,out", [(18900, 189.0), (4, 0.04), (0, 0.0), (31000, 310.0)])
def test_to_dollars_roundtrip(cents, out):
    assert to_dollars(cents) == out
    assert to_cents(to_dollars(cents)) == cents


@pytest.mark.parametrize("cents,num,den,out", [
    (18900, 3, 100, 567),   # 3% of $189.00
    (15500, 3, 100, 465),   # 3% of $155.00
    (12900, 5, 100, 645),   # 5% reserve of $129.00
    (24000, 5, 100, 1200),  # 5% reserve of $240.00
])
def test_pct_of_exact(cents, num, den, out):
    assert pct_of(cents, num, den) == out


@pytest.mark.parametrize("cents,text", [
    (18900, "$189.00"), (567, "$5.67"), (0, "$0.00"),
    (-31000, "-$310.00"), (123456, "$1,234.56"),
])
def test_fmt_usd(cents, text):
    assert fmt_usd(cents) == text
