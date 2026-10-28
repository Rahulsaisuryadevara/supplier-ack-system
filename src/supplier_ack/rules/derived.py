"""Single source of truth for workflow-derived values and clean-data reconciliation.

Pure derivation helpers are used by generators and by :func:`reconcile`.  The
reconciler never mutates the supplied dataset: it compares stored derived values
with independently recomputed expectations and returns machine-readable findings.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

import pandas as pd

from supplier_ack.rules.thresholds import evaluate_threshold, computed_delta
from supplier_ack.schema import STATUS_TRANSITIONS, is_legal_transition

CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")
THREE_DP = Decimal("0.001")


def decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return result if result.is_finite() else default


def money(value: Any) -> Decimal:
    parsed = decimal(value)
    if parsed is None:
        raise ValueError(f"not a finite monetary value: {value!r}")
    return parsed.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_line_total(quantity: Any, unit_price: Any) -> Decimal:
    qty, price = decimal(quantity), decimal(unit_price)
    if qty is None or price is None:
        raise ValueError("quantity and unit price must be finite decimals")
    return (qty * price).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_po_total(line_totals: Any) -> Decimal:
    total = Decimal("0.00")
    for value in line_totals:
        parsed = decimal(value)
        if parsed is None:
            raise ValueError(f"invalid line total: {value!r}")
        total += parsed.quantize(CENT, rounding=ROUND_HALF_UP)
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_percent_delta(old_value: Any, new_value: Any, *, zero_base: str = "zero") -> Decimal:
    old, new = decimal(old_value), decimal(new_value)
    if old is None or new is None:
        raise ValueError("old_value and new_value must be finite numbers")
    if old == 0:
        result = Decimal("0") if new == 0 or zero_base == "zero" else Decimal("100")
    else:
        result = Decimal("100") * (new - old) / old
    return result.quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def derive_ack_status(requested_qty: Any, accepted_qty: Any, *, revised: bool = False) -> str:
    """Return canonical full_accept/partial_accept/full_reject/revised label.

    Boundary policy: accepted <= 0 is full rejection; accepted >= requested is
    full acceptance; values in between are partial acceptance. `revised` takes
    precedence because superseded revisions retain their historical outcome.
    """
    if revised:
        return "revised"
    requested, accepted = decimal(requested_qty), decimal(accepted_qty)
    if requested is None or accepted is None or requested < 0 or accepted < 0:
        raise ValueError("requested and accepted quantities must be finite and non-negative")
    # Quantities are stored at three decimal places by the schema. Compare the
    # same rounded values that are persisted, using half-up business rounding.
    requested = requested.quantize(THREE_DP, rounding=ROUND_HALF_UP)
    accepted = accepted.quantize(THREE_DP, rounding=ROUND_HALF_UP)
    if accepted == 0 or requested == 0:
        return "full_reject" if accepted == 0 else "full_accept"
    if accepted >= requested:
        return "full_accept"
    return "partial_accept"


def acknowledgement_status_value(requested_qty: Any, accepted_qty: Any, *, revised: bool = False) -> str:
    """Map canonical acknowledgement status to the stored lifecycle enum."""
    return {
        "full_accept": "ACCEPTED",
        "partial_accept": "PARTIALLY_ACCEPTED",
        "full_reject": "REJECTED",
        "revised": "SUPERSEDED",
    }[derive_ack_status(requested_qty, accepted_qty, revised=revised)]


def derive_promise_date(promised_date: Any, requested_date: Any) -> dict[str, Any]:
    promised = date.fromisoformat(str(promised_date)[:10])
    requested = date.fromisoformat(str(requested_date)[:10])
    slip_days = (promised - requested).days
    return {"slip_days": slip_days, "is_late": bool(slip_days > 0)}


def derive_change_fields(change: Mapping[str, Any], thresholds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    kind = str(change.get("change_type") or change.get("request_type") or "").lower()
    delta = computed_delta(kind, change.get("old_value"), change.get("new_value"))
    rule = evaluate_threshold({**dict(change), "delta": delta}, thresholds)
    return {
        "delta": round(float(delta), 4),
        "delta_abs": round(abs(float(delta)), 4),
        "delta_pct": round(float(delta), 4) if kind in {"price", "quantity"} else None,
        "required_approval_level": str(rule["required_approval_level"]),
    }


def latest_approved_plan_versions(dataset: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """Return the latest plan version per PO line that passes its source gate.

    Baseline is always a valid projection. ACK versions require a processed ACK and
    matching positive promise. Change versions require an IMPLEMENTED ChangeRequest.
    """
    plans = _records(dataset, "inventory_plans")
    changes = {str(r["change_request_id"]): r for r in _records(dataset, "change_requests")}
    approvals_by_change: dict[str, list[dict[str, Any]]] = {}
    for approval in _records(dataset, "approvals"):
        approvals_by_change.setdefault(str(approval.get("change_request_id")), []).append(approval)
    acknowledgements = {str(r["ack_id"]): r for r in _records(dataset, "acknowledgements")}
    promises = _records(dataset, "promise_dates")
    promises_by_ack_line = {(str(r["ack_id"]), str(r["po_line_id"])): r for r in promises}
    current_promises_by_line: dict[str, list[dict[str, Any]]] = {}
    for promise in promises:
        if str(promise.get("status")) == "CURRENT":
            current_promises_by_line.setdefault(str(promise.get("po_line_id")), []).append(promise)
    eligible: dict[str, list[dict[str, Any]]] = {}
    for row in plans:
        line_id = str(row.get("po_line_id"))
        source = str(row.get("source"))
        ok = source == "po_baseline"
        if source == "approved_ack":
            # Locate the source promise by the line/quantity/date represented by the plan.
            matches = [p for p in current_promises_by_line.get(line_id, [])
                       if str(p.get("promised_date")) == str(row.get("projected_delivery_date"))
                       and decimal(p.get("promised_qty")) == decimal(row.get("projected_qty"))]
            ok = any(str(acknowledgements.get(str(p.get("ack_id")), {}).get("lifecycle_state")) == "PROCESSED" for p in matches)
        elif source == "approved_change":
            change = changes.get(str(row.get("change_request_id")), {})
            required = str(change.get("required_approval_level") or "")
            approved = any(str(a.get("status")) == "APPROVED" and str(a.get("approval_level")) == required
                           for a in approvals_by_change.get(str(row.get("change_request_id")), []))
            ok = str(change.get("status")) == "IMPLEMENTED" and approved
        if ok:
            eligible.setdefault(line_id, []).append(row)
    latest = {}
    for line_id, rows in eligible.items():
        latest[line_id] = max(rows, key=lambda row: int(row.get("plan_version", 0)))
    return latest


def derive_supplier_scores(dataset: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, float]]:
    suppliers = _records(dataset, "suppliers")
    pos = _records(dataset, "purchase_orders")
    acks = _records(dataset, "acknowledgements")
    promises = _records(dataset, "promise_dates")
    lines = {str(row["po_line_id"]): row for row in _records(dataset, "po_lines")}
    po_by_id = {str(row["po_id"]): row for row in pos}
    po_ids_by_supplier: dict[str, set[str]] = {}
    for po in pos:
        po_ids_by_supplier.setdefault(str(po["supplier_id"]), set()).add(str(po["po_id"]))
    acked_pos: dict[str, set[str]] = {}
    for ack in acks:
        acked_pos.setdefault(str(ack["supplier_id"]), set()).add(str(ack["po_id"]))
    current_promises = [row for row in promises if str(row.get("status")) == "CURRENT"]
    promise_stats: dict[str, list[int]] = {}
    for promise in current_promises:
        line = lines.get(str(promise.get("po_line_id")))
        po = po_by_id.get(str(promise.get("po_id")))
        if not line or not po:
            continue
        slip = derive_promise_date(promise.get("promised_date"), line.get("required_date"))["slip_days"]
        promise_stats.setdefault(str(po["supplier_id"]), []).append(int(slip))
    result: dict[str, dict[str, float]] = {}
    for supplier in suppliers:
        sid = str(supplier["supplier_id"])
        denomin = len(po_ids_by_supplier.get(sid, set()))
        acked = len(acked_pos.get(sid, set()))
        slips = promise_stats.get(sid, [])
        result[sid] = {
            "ack_rate": round(acked / denomin, 4) if denomin else 0.0,
            "on_time_promise_rate": round(sum(1 for slip in slips if slip <= 0) / len(slips), 4) if slips else 0.0,
            "avg_slip_days": round(sum(max(0, slip) for slip in slips) / len(slips), 3) if slips else 0.0,
        }
    return result


def derive_production_values(order: Mapping[str, Any], allocation_qty: Any, projected_qty: Any,
                             projected_date: Any) -> dict[str, Any]:
    allocated = decimal(allocation_qty, Decimal("0")) or Decimal("0")
    projected = decimal(projected_qty, Decimal("0")) or Decimal("0")
    required_by = date.fromisoformat(str(order.get("required_by_date"))[:10])
    delivery = date.fromisoformat(str(projected_date)[:10])
    return {
        "at_risk": str(order.get("status", "")).upper() in {"AT_RISK", "DELAYED"},
        "shortfall_qty": float(max(Decimal("0"), allocated - projected).quantize(THREE_DP, rounding=ROUND_HALF_UP)),
        "delay_days": max(0, (delivery - required_by).days),
    }


def derive_open_impact_counts(dataset: Mapping[str, pd.DataFrame]) -> dict[str, int]:
    """Compute open impact counts by PO in one indexed pass."""
    orders = {str(r["production_order_id"]): r for r in _records(dataset, "production_orders")}
    counts: dict[str, int] = {}
    for impact in _records(dataset, "production_order_impact"):
        order = orders.get(str(impact.get("production_order_id")))
        if order and str(order.get("status", "")).upper() in {"AT_RISK", "DELAYED"}:
            po_id = str(order.get("po_id"))
            counts[po_id] = counts.get(po_id, 0) + 1
    return counts


def derive_open_impact_count(dataset: Mapping[str, pd.DataFrame], po_id: Any) -> int:
    """Compute the current unresolved downstream-impact count for one PO."""
    return int(derive_open_impact_counts(dataset).get(str(po_id), 0))


def _records(dataset: Mapping[str, pd.DataFrame], key: str) -> list[dict[str, Any]]:
    frame = dataset.get(key)
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        return frame.to_dict(orient="records")
    return [dict(row) for row in frame]


def _same(actual: Any, expected: Any) -> bool:
    if actual is not None:
        try:
            if bool(pd.isna(actual)):
                actual = None
        except (TypeError, ValueError):
            pass
    if expected is not None:
        try:
            if bool(pd.isna(expected)):
                expected = None
        except (TypeError, ValueError):
            pass
    if actual is None or expected is None:
        return actual is None and expected is None
    if isinstance(actual, float) and pd.isna(actual):
        return expected is None
    if isinstance(expected, float) and pd.isna(expected):
        return actual is None
    a, e = decimal(actual), decimal(expected)
    if a is not None and e is not None:
        return abs(a - e) <= Decimal("0.00011")
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) <= 0.00011
    return actual == expected


def reconcile(dataset: Mapping[str, pd.DataFrame], thresholds: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Recompute derived fields and arithmetic invariants without modifying frames.

    Each entity's report contains the number of assertions, failures and at most
    five example mismatches. A non-zero mismatch count is a hard generation failure.
    """
    reports: dict[str, dict[str, Any]] = {}
    def init(name: str) -> None:
        if name not in reports:
            reports[name] = {"checked_count": 0, "mismatch_count": 0, "sample_mismatches": []}
    def check(name: str, key: str, row_id: Any, field: str, actual: Any, expected: Any, detail: str = "") -> None:
        init(name)
        reports[name]["checked_count"] += 1
        if not _same(actual, expected):
            reports[name]["mismatch_count"] += 1
            if len(reports[name]["sample_mismatches"]) < 5:
                mismatch = {"entity": name, "key": str(row_id), "field": field, "actual": _json_safe(actual), "expected": _json_safe(expected)}
                if detail:
                    mismatch["detail"] = detail
                reports[name]["sample_mismatches"].append(mismatch)

    pos = _records(dataset, "purchase_orders")
    lines = _records(dataset, "po_lines")
    line_by_id = {str(r["po_line_id"]): r for r in lines}
    po_by_id = {str(r["po_id"]): r for r in pos}
    lines_by_po: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        lines_by_po.setdefault(str(line["po_id"]), []).append(line)
        check("POLine", "po_lines", line.get("po_line_id"), "line_total",
              line.get("line_total"), float(compute_line_total(line.get("requested_qty"), line.get("unit_price"))))
        if line.get("ack_accepted_qty") is not None and line.get("ack_rejected_qty") is not None:
            accepted = decimal(line.get("ack_accepted_qty")); rejected = decimal(line.get("ack_rejected_qty")); requested = decimal(line.get("requested_qty"))
            if None not in (accepted, rejected, requested) and str(line.get("status")) not in {"DRAFT", "OPEN", "CANCELLED"}:
                check("POLine", "po_lines", line.get("po_line_id"), "accepted_plus_rejected", float(accepted + rejected), float(requested))
    for po in pos:
        expected_total = compute_po_total(row.get("line_total") for row in lines_by_po.get(str(po["po_id"]), []))
        check("PurchaseOrder", "purchase_orders", po.get("po_id"), "total_order_value", po.get("total_order_value"), float(expected_total))

    # Per-line ACK snapshots and per-header lifecycle outcome consistency.
    ack_lines = _records(dataset, "acknowledgement_lines")
    ack_headers = _records(dataset, "acknowledgements")
    promises = _records(dataset, "promise_dates")
    promise_by_ack_line = {(str(r.get("ack_id")), str(r.get("po_line_id"))): r for r in promises}
    ack_by_id = {str(r["ack_id"]): r for r in ack_headers}
    accepted_by_ack: dict[str, Decimal] = {}
    requested_by_ack: dict[str, Decimal] = {}
    for row in ack_lines:
        aid = str(row.get("ack_id")); accepted = decimal(row.get("accepted_qty")); rejected = decimal(row.get("rejected_qty")); requested = decimal(row.get("requested_qty"))
        if None not in (accepted, rejected, requested):
            check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "accepted_plus_rejected", float(accepted + rejected), float(requested))
            accepted_by_ack[aid] = accepted_by_ack.get(aid, Decimal("0")) + accepted
            requested_by_ack[aid] = requested_by_ack.get(aid, Decimal("0")) + requested
            qty_pct = compute_percent_delta(requested, accepted)
            check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "qty_delta_pct", row.get("qty_delta_pct"), float(qty_pct))
        old_price, new_price = decimal(row.get("requested_unit_price")), decimal(row.get("acknowledged_unit_price"))
        if old_price is not None and new_price is not None:
            expected_price = compute_percent_delta(old_price, new_price)
            check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "price_delta_pct", row.get("price_delta_pct"), float(expected_price))
        expected_status = acknowledgement_status_value(row.get("requested_qty"), row.get("accepted_qty"), revised=str(row.get("status")) == "SUPERSEDED")
        check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "status", row.get("status"), expected_status)
        line = line_by_id.get(str(row.get("po_line_id")))
        promise = promise_by_ack_line.get((aid, str(row.get("po_line_id"))))
        if line and promise:
            slip = derive_promise_date(promise.get("promised_date"), line.get("required_date"))["slip_days"]
            check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "date_slip_days", row.get("date_slip_days"), slip)
        elif decimal(row.get("accepted_qty")) == Decimal("0"):
            check("Acknowledgement", "acknowledgement_lines", row.get("acknowledgement_line_id"), "date_slip_days", row.get("date_slip_days"), None)
    ack_lines_by_ack: dict[str, list[dict[str, Any]]] = {}
    for row in ack_lines:
        ack_lines_by_ack.setdefault(str(row.get("ack_id")), []).append(row)
    promises_by_ack: dict[str, list[dict[str, Any]]] = {}
    for promise in promises:
        promises_by_ack.setdefault(str(promise.get("ack_id")), []).append(promise)
    for ack in ack_headers:
        requested = decimal(ack.get("requested_qty"), Decimal("0")) or Decimal("0")
        accepted = decimal(ack.get("ack_accepted_qty"), Decimal("0")) or Decimal("0")
        rejected = decimal(ack.get("ack_rejected_qty"), Decimal("0")) or Decimal("0")
        header_id = str(ack.get("ack_id"))
        snapshots = ack_lines_by_ack.get(header_id, [])
        if snapshots:
            source_requested = sum((decimal(r.get("requested_qty"), Decimal("0")) or Decimal("0") for r in snapshots), Decimal("0"))
            source_accepted = sum((decimal(r.get("accepted_qty"), Decimal("0")) or Decimal("0") for r in snapshots), Decimal("0"))
            source_rejected = sum((decimal(r.get("rejected_qty"), Decimal("0")) or Decimal("0") for r in snapshots), Decimal("0"))
            check("Acknowledgement", "acknowledgements", header_id, "requested_qty", requested, source_requested)
            check("Acknowledgement", "acknowledgements", header_id, "ack_accepted_qty", accepted, source_accepted)
            check("Acknowledgement", "acknowledgements", header_id, "ack_rejected_qty", rejected, source_rejected)
            check("Acknowledgement", "acknowledgements", header_id, "accepted_plus_rejected", float(accepted + rejected), float(requested))
            check("Acknowledgement", "acknowledgements", header_id, "qty_delta_pct", ack.get("qty_delta_pct"), float(compute_percent_delta(source_requested, source_accepted)))
            source_requested_value = decimal(ack.get("requested_value"), Decimal("0")) or Decimal("0")
            quoted_value = sum((
                (decimal(r.get("requested_qty"), Decimal("0")) or Decimal("0"))
                * (decimal(r.get("acknowledged_unit_price"), Decimal("0")) or Decimal("0"))
                for r in snapshots
            ), Decimal("0")).quantize(CENT, rounding=ROUND_HALF_UP)
            check("Acknowledgement", "acknowledgements", header_id, "price_delta_pct", ack.get("price_delta_pct"), float(compute_percent_delta(source_requested_value, quoted_value)))
        if str(ack.get("status")) in {"ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "SUPERSEDED"}:
            expected = acknowledgement_status_value(requested, accepted, revised=str(ack.get("status")) == "SUPERSEDED")
            check("Acknowledgement", "acknowledgements", header_id, "status", ack.get("status"), expected)
        source_slips = []
        for promise in promises_by_ack.get(header_id, []):
            line = line_by_id.get(str(promise.get("po_line_id")))
            if line:
                source_slips.append(derive_promise_date(promise.get("promised_date"), line.get("required_date"))["slip_days"])
        expected_header_slip = max(source_slips) if source_slips else None
        check("Acknowledgement", "acknowledgements", header_id, "date_slip_days", ack.get("date_slip_days"), expected_header_slip)

    # PromiseDate flags against the requested PO-line date.
    ackline_by_key = {(str(r.get("ack_id")), str(r.get("po_line_id"))): r for r in ack_lines}
    for promise in promises:
        line = line_by_id.get(str(promise.get("po_line_id")))
        if line:
            expected_flags = derive_promise_date(promise.get("promised_date"), line.get("required_date"))
            check("PromiseDate", "promise_dates", promise.get("promise_date_id"), "slip_days", promise.get("slip_days"), expected_flags["slip_days"])
            check("PromiseDate", "promise_dates", promise.get("promise_date_id"), "is_late", promise.get("is_late"), expected_flags["is_late"])
            ackline = ackline_by_key.get((str(promise.get("ack_id")), str(promise.get("po_line_id"))))
            if ackline:
                check("PromiseDate", "promise_dates", promise.get("promise_date_id"), "promised_qty", promise.get("promised_qty"), ackline.get("accepted_qty"))

    # ChangeRequest deltas, absolute deltas, percentages and required approver.
    for change in _records(dataset, "change_requests"):
        # The silence request deliberately has equal old/new requested dates and still routes to planner.
        expected = derive_change_fields(change, thresholds)
        for field in ("delta", "delta_abs", "delta_pct", "required_approval_level"):
            check("ChangeRequest", "change_requests", change.get("change_request_id"), field, change.get(field), expected[field])

    # InventoryPlan latest-approved pointer, linkage and promise equality.
    plans = _records(dataset, "inventory_plans")
    plan_by_id = {str(r.get("inventory_plan_id")): r for r in plans}
    latest_plans = latest_approved_plan_versions(dataset)
    changes_by_id = {str(r["change_request_id"]): r for r in _records(dataset, "change_requests")}
    promises_by_line = {}
    for p in promises:
        if str(p.get("status")) == "CURRENT":
            promises_by_line[str(p.get("po_line_id"))] = p
    for plan in plans:
        line_id = str(plan.get("po_line_id")); latest = latest_plans.get(line_id)
        expected_effective = int(latest is not None and str(plan.get("inventory_plan_id")) == str(latest.get("inventory_plan_id")))
        check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "is_effective", plan.get("is_effective"), expected_effective)
        if str(plan.get("source")) == "po_baseline" and int(plan.get("plan_version", 1)) == 1:
            source_line = line_by_id.get(line_id, {})
            check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "baseline_qty_matches_PO", plan.get("projected_qty"), source_line.get("requested_qty"))
            check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "baseline_date_matches_PO", plan.get("projected_delivery_date"), source_line.get("required_date"))
            check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "baseline_has_no_previous_version", plan.get("previous_version_id"), None)
        if int(plan.get("plan_version", 1)) > 1:
            prev = plan_by_id.get(str(plan.get("previous_version_id")))
            if prev:
                check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "previous_version_same_line", prev.get("po_line_id"), line_id)
        if str(plan.get("source")) in {"approved_ack", "approved_change"}:
            promise = promises_by_line.get(line_id)
            if promise and int(plan.get("is_effective", 0)) == 1:
                check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "projected_qty_matches_promise", plan.get("projected_qty"), promise.get("promised_qty"))
                check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "projected_date_matches_promise", plan.get("projected_delivery_date"), promise.get("promised_date"))
            if str(plan.get("source")) == "approved_change":
                change = changes_by_id.get(str(plan.get("change_request_id")), {})
                check("InventoryPlan", "inventory_plans", plan.get("inventory_plan_id"), "approved_change_gate", change.get("status"), "IMPLEMENTED")

    # Production order derived values and allocation invariant.
    bridge = {str(r.get("production_order_id")): r for r in _records(dataset, "production_order_line")}
    plan_by_id = {str(r.get("inventory_plan_id")): r for r in plans}
    for order in _records(dataset, "production_orders"):
        alloc = bridge.get(str(order.get("production_order_id")), {})
        plan = plan_by_id.get(str(order.get("inventory_plan_id")), {})
        expected = derive_production_values(order, alloc.get("allocated_quantity", 0), plan.get("projected_qty", 0), plan.get("projected_delivery_date", order.get("required_by_date")))
        for field in ("at_risk", "shortfall_qty", "delay_days"):
            check("ProductionOrder", "production_orders", order.get("production_order_id"), field, order.get(field), expected[field])
        if decimal(alloc.get("allocated_quantity")) is not None and decimal(plan.get("projected_qty")) is not None:
            shortage = decimal(alloc.get("allocated_quantity")) > decimal(plan.get("projected_qty"))
            if shortage and str(order.get("status")) not in {"AT_RISK", "DELAYED"}:
                check("ProductionOrder", "production_order_line", order.get("production_order_id"), "allocation_requires_risk_status", order.get("status"), "AT_RISK/DELAYED/RESCHEDULED")
            else:
                check("ProductionOrder", "production_order_line", order.get("production_order_id"), "allocation_invariant", True, True)

    # Supplier operational scores are derived from actual PO/ACK/PromiseDate records.
    scores = derive_supplier_scores(dataset)
    for supplier in _records(dataset, "suppliers"):
        for field, expected in scores[str(supplier["supplier_id"])].items():
            check("Supplier", "suppliers", supplier.get("supplier_id"), field, supplier.get(field), expected)

    # Each Notification carries the current unresolved impact count for its PO.
    open_impact_counts = derive_open_impact_counts(dataset)
    for notice in _records(dataset, "notifications"):
        po_id = notice.get("po_id")
        expected = int(open_impact_counts.get(str(po_id), 0)) if po_id is not None else 0
        check("Notification", "notifications", notice.get("notification_id"), "open_impact_count", notice.get("open_impact_count"), expected)

    # Arithmetic invariant: all schema-supported line amounts are derived from source qty*price.
    for line in lines:
        for qty_name, price_name, amount_name in (
            ("ack_accepted_qty", "acknowledged_unit_price", "acknowledged_value"),
            ("promised_qty", "promised_unit_price", "promised_value"),
            ("projected_qty", "projected_unit_price", "projected_value"),
        ):
            if line.get(qty_name) is not None and line.get(price_name) is not None and line.get(amount_name) is not None:
                check("POLine", "po_lines", line.get("po_line_id"), amount_name, line.get(amount_name), float(compute_line_total(line[qty_name], line[price_name])))

    # Event lifecycle state snapshots must use legal status transitions. Non-status
    # events are ignored; events without a state snapshot don't claim a transition.
    for event in _records(dataset, "entity_event"):
        old_raw, new_raw = event.get("previous_state"), event.get("new_state")
        if not old_raw or not new_raw:
            continue
        try:
            old = json.loads(old_raw) if isinstance(old_raw, str) else dict(old_raw)
            new = json.loads(new_raw) if isinstance(new_raw, str) else dict(new_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            check("EntityEvent", "entity_event", event.get("event_id"), "state_json_valid", False, True)
            continue
        old_status, new_status = old.get("status"), new.get("status")
        entity_type = str(event.get("entity_type"))
        if old_status and new_status and old_status != new_status and entity_type in STATUS_TRANSITIONS:
            check("EntityEvent", "entity_event", event.get("event_id"), "legal_status_transition", is_legal_transition(entity_type, str(old_status), str(new_status)), True,
                  f"{old_status} -> {new_status}")

    # Ensure each expected entity has a visible report even when no rows were generated.
    for name in ("Supplier", "PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate", "ChangeRequest", "InventoryPlan", "ProductionOrder", "Notification", "EntityEvent"):
        init(name)
    return reports


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def reconciliation_summary(report: Mapping[str, Mapping[str, Any]]) -> tuple[int, int]:
    """Return aggregate (checked, mismatches) totals for a reconciliation report."""
    return (sum(int(row["checked_count"]) for row in report.values()),
            sum(int(row["mismatch_count"]) for row in report.values()))
