"""Pure threshold and approval-gating rules for ChangeRequest records.

No RNG, I/O, pandas, or database access is used here. Deltas are derived from the
source values: price and quantity changes are signed percentages, while date changes
are signed calendar-day differences.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

DEFAULT_THRESHOLDS: dict[str, float] = {
    "price_change_pct": 5.0,
    "date_slip_days": 7.0,
    "quantity_change_pct": 10.0,
    "max_price_change_pct": 15.0,
    "max_date_slip_days": 30.0,
    "max_quantity_change_pct": 50.0,
}

_TYPE_ALIASES = {
    "PRICE_CHANGE": "price", "price": "price", "price_change": "price",
    "DATE_CHANGE": "date", "date": "date", "date_change": "date",
    "QUANTITY_CHANGE": "quantity", "quantity": "quantity", "quantity_change": "quantity",
}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def normalize_change_type(change: Mapping[str, Any]) -> str:
    """Return canonical ``price``, ``date`` or ``quantity`` for a change row."""
    raw = change.get("change_type") or change.get("request_type") or ""
    normalized = _TYPE_ALIASES.get(str(raw), _TYPE_ALIASES.get(str(raw).upper()))
    if normalized is None:
        raise ValueError(f"unsupported change type: {raw!r}")
    return normalized


def computed_delta(change_type: str, old_value: Any, new_value: Any) -> float:
    """Calculate signed delta percentage (price/quantity) or days (date)."""
    kind = _TYPE_ALIASES.get(str(change_type), _TYPE_ALIASES.get(str(change_type).upper()))
    if kind is None:
        raise ValueError(f"unsupported change type: {change_type!r}")
    if kind == "date":
        old_day = date.fromisoformat(str(old_value)[:10])
        new_day = date.fromisoformat(str(new_value)[:10])
        return float((new_day - old_day).days)
    old, new = _decimal(old_value), _decimal(new_value)
    if old is None or new is None:
        raise ValueError("old_value and new_value must be finite numbers for price/quantity changes")
    if old == 0:
        return 0.0 if new == 0 else 100.0
    return float((Decimal("100") * (new - old) / old).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def delta_for_change(change: Mapping[str, Any]) -> float:
    """Prefer recomputation from source values; trust stored delta only for legacy rows."""
    kind = normalize_change_type(change)
    if change.get("old_value") is not None and change.get("new_value") is not None:
        return computed_delta(kind, change["old_value"], change["new_value"])
    if change.get("delta") is not None:
        value = _decimal(change.get("delta"))
        if value is not None:
            return float(value)
    if kind == "price":
        old, new = change.get("previous_unit_price"), change.get("requested_unit_price")
    elif kind == "quantity":
        old, new = change.get("previous_qty"), change.get("requested_qty")
    else:
        old, new = change.get("previous_promised_date"), change.get("requested_promised_date")
    return computed_delta(kind, old, new)


def _threshold_mapping(thresholds: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not thresholds:
        return DEFAULT_THRESHOLDS
    if isinstance(thresholds.get("approval_thresholds"), Mapping):
        combined = dict(DEFAULT_THRESHOLDS)
        combined.update(thresholds["approval_thresholds"])
        return combined
    combined = dict(DEFAULT_THRESHOLDS)
    combined.update(thresholds)
    return combined


def evaluate_threshold(
    change: Mapping[str, Any], thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve route, threshold, hard limit, escalation reason, and downstream flag."""
    config = _threshold_mapping(thresholds)
    kind = normalize_change_type(change)
    delta = delta_for_change(change)
    measure = abs(delta)
    threshold_key = {"price": "price_change_pct", "date": "date_slip_days", "quantity": "quantity_change_pct"}[kind]
    threshold = float(config[threshold_key])
    # A date slip is the positive lateness component, not an early promise.
    measured = max(0.0, delta) if kind == "date" else measure
    within = measured <= threshold
    required_level = "planner" if within else "operations_manager"
    hard_key = {"price": "max_price_change_pct", "date": "max_date_slip_days", "quantity": "max_quantity_change_pct"}[kind]
    hard_limit = float(config.get(hard_key, DEFAULT_THRESHOLDS[hard_key]))
    hard_breach = measured > hard_limit
    threshold_name = {"price": "PRICE_CHANGE_PCT", "date": "DATE_SLIP_DAYS", "quantity": "QUANTITY_CHANGE_PCT"}[kind]
    reason = None
    if not within:
        if kind == "price":
            reason = f"Absolute price change {measured:.2f}% exceeds planner threshold ±{threshold:.2f}%; operations-manager approval required."
        elif kind == "date":
            reason = f"Date slip {measured:.0f} days exceeds planner threshold {threshold:.0f} days; operations-manager approval required."
        else:
            reason = f"Absolute quantity change {measured:.2f}% exceeds planner threshold {threshold:.2f}%; operations-manager approval required."
    if hard_breach:
        reason = (reason or "Change exceeds planner threshold.") + f" Hard policy limit {hard_limit:g} exceeded; reject."
    return {
        "change_type": kind,
        "delta": delta,
        "measured_delta": measured,
        "threshold_name": threshold_name,
        "threshold_value": threshold,
        "configured_threshold": threshold,
        "within_threshold": within,
        "required_approval_level": required_level,
        "hard_limit": hard_limit,
        "hard_limit_breach": hard_breach,
        "escalation_reason": reason,
        "downstream_impact_flag": kind == "date" and measured > threshold,
    }


def required_approval_level(
    change: Mapping[str, Any], thresholds: Mapping[str, Any] | None = None,
) -> str:
    """Derive the required approver from source values and configured thresholds."""
    return str(evaluate_threshold(change, thresholds)["required_approval_level"])


def can_apply(
    change: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]] | Any,
    thresholds: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    """Return whether the latest approval at the required level permits application.

    The input approval history is never mutated. The latest row at the required level
    wins, so a later rejection cannot be bypassed by an older approval. A later appeal
    is represented by a new Approval row with a larger approval round.
    """
    status = str(change.get("status") or "").upper()
    if status in {"REJECTED", "CANCELLED", "WITHDRAWN", "CLOSED", "IMPLEMENTED"}:
        return False, f"change status {status} is not applicable"
    required = required_approval_level(change, thresholds)
    change_id = change.get("change_request_id")
    if hasattr(approvals, "to_dict"):
        rows = approvals.to_dict(orient="records")
    else:
        rows = list(approvals or [])
    candidates = [row for row in rows if (change_id is None or row.get("change_request_id") == change_id)
                  and str(row.get("approval_level") or row.get("approver_role") or "").lower() == required]
    if not candidates:
        return False, f"required approval level '{required}' has no approval record"
    def order(row: Mapping[str, Any]) -> tuple[int, str]:
        try:
            round_no = int(row.get("approval_round", 0))
        except (TypeError, ValueError):
            round_no = 0
        return round_no, str(row.get("decided_at") or "")
    latest = max(candidates, key=order)
    decision = str(latest.get("status") or latest.get("decision") or "").upper()
    if decision != "APPROVED":
        return False, f"latest '{required}' decision is {decision or 'missing'}, not APPROVED"
    return True, f"approved at required level '{required}'"
