"""Pure downstream-impact severity rules.

Severity is the worst of two explicit components: date risk is LOW through 2
conflict days, MEDIUM through 7, HIGH through 14, then CRITICAL; quantity risk
is LOW through 5% shortfall, MEDIUM through 10%, HIGH through 25%, then CRITICAL.
The combined impact takes the higher of the date and quantity bands.
"""
from __future__ import annotations


def _band(value: float, edges: tuple[float, float, float]) -> str:
    if value <= edges[0]:
        return "LOW"
    if value <= edges[1]:
        return "MEDIUM"
    if value <= edges[2]:
        return "HIGH"
    return "CRITICAL"


def compute_impact_severity(slip_days: int | float, shortfall_pct: float) -> str:
    """Compute the worst severity implied by non-negative slip and shortfall."""
    slip = max(0.0, float(slip_days))
    shortfall = max(0.0, float(shortfall_pct))
    date_band = _band(slip, (2.0, 7.0, 14.0))
    quantity_band = _band(shortfall, (5.0, 10.0, 25.0))
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return max((date_band, quantity_band), key=lambda name: order[name])
