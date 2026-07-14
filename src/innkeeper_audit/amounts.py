"""Money arithmetic in integer cents — the only place float dollars are converted.

Every amount that participates in matching, gate math, or hashing goes through
these helpers so that 189.00 - 183.33 is exactly 567 cents, never 5.669999.
"""

from __future__ import annotations


def to_cents(dollars: float | int | str) -> int:
    """Convert a dollar amount to integer cents, exactly."""
    if isinstance(dollars, str):
        dollars = float(dollars)
    return int(round(dollars * 100))


def to_dollars(cents: int) -> float:
    """Convert integer cents back to a 2-decimal float dollar amount."""
    return round(cents / 100.0, 2)


def fmt_usd(cents: int) -> str:
    """$1,234.56 formatting (negative -> -$1,234.56)."""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100:,}.{c % 100:02d}"


def pct_of(cents: int, numerator: int, denominator: int) -> int:
    """Exact integer percentage of an amount: pct_of(18900, 3, 100) == 567."""
    return (cents * numerator) // denominator
