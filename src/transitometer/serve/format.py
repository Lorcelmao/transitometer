"""Display formatting shared by both frontends: one rounding rule for every figure shown.

Standard library only, so the JSON export and the hosted app stay light. The views ship these
strings to the Next.js site, so both frontends show the same text for the same value (Python
and JavaScript round some halves differently; formatting once avoids that).
"""

from __future__ import annotations

import math
from datetime import date

MISSING = "—"


def pct(value: float | None, digits: int = 1) -> str:
    """0.4741 -> '47.4 %'."""
    if value is None or math.isnan(value):
        return MISSING
    return f"{100 * value:.{digits}f} %"


def count(value: int | None) -> str:
    """12345 -> '12,345'."""
    return MISSING if value is None else f"{int(value):,}"


def day_label(day: str) -> str:
    """'20260922' -> 'Tue 22 Sep 2026'."""
    stamp = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    return f"{stamp:%a} {stamp.day} {stamp:%b %Y}"


def minutes(seconds: float | None) -> str:
    """198.6 -> '3.3 min'; negative values (early) get a true minus sign."""
    if seconds is None or math.isnan(seconds):
        return MISSING
    sign = "−" if seconds < 0 else ""
    return f"{sign}{abs(seconds) / 60:.1f} min"


def score(value: float | None) -> str:
    """Feed conformance score: 87.5 -> '87.5 / 100'."""
    return MISSING if value is None or math.isnan(value) else f"{value:.1f} / 100"


def decimal(value: float | None, digits: int = 2) -> str:
    """F1 scores and other unitless ratios: 0.613 -> '0.61'."""
    return MISSING if value is None or math.isnan(value) else f"{value:.{digits}f}"


def check_value(value: float | None, unit: str) -> str:
    """A feed-quality measurement in its unit: '%' shares or 's' durations."""
    if value is None or math.isnan(value):
        return "no data"
    return pct(value, 2) if unit == "%" else f"{value:,.1f} s"


def check_threshold(threshold: float, unit: str) -> str:
    return f"≤ {pct(threshold, 2)}" if unit == "%" else f"≤ {threshold:,.0f} s"
