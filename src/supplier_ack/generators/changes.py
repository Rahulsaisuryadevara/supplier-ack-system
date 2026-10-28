"""Rule-driven ChangeRequest, Approval, event, and silence-chase generation."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd
from numpy.random import Generator

from supplier_ack.generators.common import at_utc, frame_for_entity, get_config, require_rng
from supplier_ack.ids import IDFactory
from supplier_ack.rules.thresholds import can_apply, computed_delta, evaluate_threshold
from supplier_ack.rules.derived import derive_change_fields

_EVENT_COLUMNS = [
    "event_id", "entity_type", "entity_id", "event_type", "event_timestamp",
    "actor_role", "actor_id", "payload_json", "previous_state", "new_state",
    "issue_type", "ground_truth", "target_supplier_id", "target_po_id",
    "target_po_line_id", "target_ack_id", "target_promise_date_id",
    "target_change_request_id", "target_approval_id", "target_inventory_plan_id",
    "target_production_order_id", "target_notification_id",
]


def _day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _money(value: Any) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _qty(value: Any) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP):.3f}"


def _pct(old_value: Any, new_value: Any) -> float:
    return computed_delta("quantity", old_value, new_value)


def _decision_time(requested_at: str, role: str, round_no: int) -> str:
    requested = datetime.fromisoformat(str(requested_at).replace("Z", "+00:00"))
    # Fixed, rule-based review latency avoids outcome randomness and remains seeded-data stable.
    hours = 12 if role == "planner" else 24 + 6 * max(0, round_no - 1)
    return (requested + timedelta(hours=hours)).isoformat(timespec="seconds")


def _sample_ordered(candidates: list[dict[str, Any]], count: int, rng: Generator, thresholds: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pick candidates from both threshold bands where possible to exercise each route."""
    if count <= 0:
        return []
    within, outside = [], []
    for candidate in candidates:
        target = within if evaluate_threshold(candidate, thresholds)["within_threshold"] else outside
        target.append(candidate)
    if len(within) > 1:
        within = [within[i] for i in rng.permutation(len(within))]
    if len(outside) > 1:
        outside = [outside[i] for i in rng.permutation(len(outside))]
    # Ensure above- and within-threshold examples enter the starter cohort whenever available.
    outside_goal = min(len(outside), max(1, count // 2)) if outside and within and count > 1 else min(len(outside), count)
    within_goal = min(len(within), count - outside_goal)
    chosen = within[:within_goal] + outside[:outside_goal]
    if len(chosen) < count:
        selected_ids = {id(row) for row in chosen}
        rest = [row for row in within[within_goal:] + outside[outside_goal:] if id(row) not in selected_ids]
        chosen.extend(rest[:count - len(chosen)])
    return chosen[:count]


def _event(
    event_id: str, entity_type: str, entity_id: str, event_type: str, timestamp: str,
    actor_role: str, actor_id: str | None, payload: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None, new_state: Mapping[str, Any] | None,
    target_column: str, target_id: str, *, issue_type: str | None = None,
) -> dict[str, Any]:
    row = {column: None for column in _EVENT_COLUMNS}
    row.update({
        "event_id": event_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "event_timestamp": timestamp,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload_json": json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str),
        "previous_state": json.dumps(dict(previous_state), sort_keys=True, separators=(",", ":"), default=str) if previous_state is not None else None,
        "new_state": json.dumps(dict(new_state), sort_keys=True, separators=(",", ":"), default=str) if new_state is not None else None,
        "issue_type": issue_type,
        "ground_truth": issue_type,
        target_column: target_id,
    })
    return row


def generate_changes(
    rng: Generator,
    cfg: Mapping[str, Any],
    purchase_orders: pd.DataFrame,
    po_lines: pd.DataFrame,
    acknowledgements: pd.DataFrame,
    acknowledgement_lines: pd.DataFrame,
    promise_dates: pd.DataFrame,
    actors: pd.DataFrame,
    price_change_specs: list[dict[str, Any]],
    target_count: int,
    id_factory: IDFactory | None = None,
    *,
    silence_report: pd.DataFrame | None = None,
    existing_events: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Create auditable change requests and append-only decisions from source deltas.

    Price deltas originate in the supplier's acknowledged line-price snapshots;
    quantity deltas originate in the latest acknowledgement-line snapshots; date
    deltas originate in current PromiseDate rows. Silence cases are explicitly kept
    as planner-owned, pending date-type chase requests and emit email notifications.
    Approval decisions are deterministic policy outcomes, never random coin flips.
    """
    require_rng(rng)
    if target_count < 0:
        raise ValueError("target_count must be non-negative")
    factory = id_factory or IDFactory()
    thresholds = get_config(cfg, "approval_thresholds", default={})
    full_thresholds = dict(thresholds)
    full_thresholds.setdefault("max_price_change_pct", float(get_config(cfg, "coverage", "price_changes", "magnitude_max_pct", default=15.0)))
    full_thresholds.setdefault("max_date_slip_days", float(thresholds.get("max_date_slip_days", 30)))
    full_thresholds.setdefault("max_quantity_change_pct", float(thresholds.get("max_quantity_change_pct", 50)))
    change_cfg = get_config(cfg, "coverage", "change_requests", default={})
    weights = change_cfg.get("non_price_type_weights", {"QUANTITY_CHANGE": 0.5, "DATE_CHANGE": 0.5})
    names = list(weights)
    probs = np.asarray([float(weights[name]) for name in names], dtype=float)
    if not names or np.any(probs < 0) or abs(float(probs.sum()) - 1.0) > 1e-8:
        raise ValueError("coverage.change_requests.non_price_type_weights must be nonnegative and sum to 1")
    if set(names) - {"QUANTITY_CHANGE", "DATE_CHANGE"}:
        raise ValueError("change generation supports only QUANTITY_CHANGE and DATE_CHANGE residuals")

    pos = {str(r["po_id"]): r for r in purchase_orders.to_dict(orient="records")}
    lines = {str(r["po_line_id"]): r for r in po_lines.to_dict(orient="records")}
    actor_rows = actors.to_dict(orient="records")
    role_ids: dict[str, list[str]] = {}
    for actor in actor_rows:
        role_ids.setdefault(str(actor["actor_role"]), []).append(str(actor["actor_id"]))
    planners = role_ids.get("planner", [])
    ops_managers = role_ids.get("operations_manager", [])
    if not planners or not ops_managers:
        raise ValueError("actor roster must contain planner and operations_manager actors")
    supplier_for_po = {po_id: str(row["supplier_id"]) for po_id, row in pos.items()}
    ack_rows = acknowledgements.to_dict(orient="records")
    latest_ack = {}
    for row in ack_rows:
        if row.get("po_id") not in latest_ack or int(row["revision_no"]) > int(latest_ack[row["po_id"]]["revision_no"]):
            latest_ack[str(row["po_id"])] = row

    request_specs: list[dict[str, Any]] = []
    # 1. Price-change requests map one-to-one to actual supplier-quoted price deltas.
    for source in price_change_specs:
        po_id, line_id = str(source["po_id"]), str(source["po_line_id"])
        old = _money(source["previous_unit_price"])
        new = _money(source["requested_unit_price"])
        delta = computed_delta("price", old, new)
        ack = latest_ack.get(po_id)
        request_specs.append({
            "po": pos[po_id], "line": lines[line_id], "request_type": "PRICE_CHANGE", "change_type": "price",
            "old_value": old, "new_value": new, "delta": delta,
            "previous_unit_price": float(old), "requested_unit_price": float(new),
            "previous_qty": None, "requested_qty": None,
            "previous_promised_date": None, "requested_promised_date": None,
            "threshold_name": "PRICE_CHANGE_PCT", "created_at": str(ack["acknowledged_at"] if ack else pos[po_id]["created_at"]),
            "requested_by_role": "supplier", "requested_by_actor_id": supplier_for_po[po_id],
            "reason_code": "PRICE_CHANGE", "reason_text": f"Supplier acknowledgement quotes {new} versus requested unit price {old} ({delta:+.2f}%).",
            "is_silence": False,
        })

    if len(request_specs) > target_count:
        raise ValueError(f"price-change requests ({len(request_specs)}) exceed change-request budget ({target_count})")

    # 2. One request per silent PO while budget allows; it remains pending with the planner.
    silence_rows = (silence_report.to_dict(orient="records") if silence_report is not None else [])
    remaining_for_silence = max(0, target_count - len(request_specs))
    for silence in silence_rows[:remaining_for_silence]:
        po_id = str(silence["po_id"])
        po = pos[po_id]
        due_day = _day(silence["response_due_at"])
        as_of_day = _day(silence.get("as_of_date", due_day + timedelta(days=1)))
        request_day = max(as_of_day, due_day)
        requested_at = at_utc(request_day, 12)
        requested_date = str(po["required_delivery_date"])
        # The same date is intentional: no supplier commitment exists to justify inventing a new promise.
        request_specs.append({
            "po": po, "line": None, "request_type": "DATE_CHANGE", "change_type": "date",
            "old_value": requested_date, "new_value": requested_date, "delta": 0.0,
            "previous_promised_date": requested_date, "requested_promised_date": requested_date,
            "previous_qty": None, "requested_qty": None, "previous_unit_price": None, "requested_unit_price": None,
            "threshold_name": "DATE_SLIP_DAYS", "created_at": requested_at,
            "requested_by_role": "planner", "requested_by_actor_id": str(po["planner_actor_id"]),
            "reason_code": "OTHER", "reason_text": f"No supplier acknowledgement by response_due_date {str(silence['response_due_at'])}; planner chase escalation required. No promise date is fabricated.",
            "is_silence": True, "silence_due_at": str(silence["response_due_at"]),
        })

    # 3. Source-traceable quantity candidates from the latest ACK line revision.
    latest_ack_ids = {str(row["ack_id"]) for row in latest_ack.values()}
    quantity_candidates: list[dict[str, Any]] = []
    for row in acknowledgement_lines.to_dict(orient="records"):
        if str(row["ack_id"]) not in latest_ack_ids:
            continue
        requested = Decimal(str(row["requested_qty"]))
        accepted = Decimal(str(row["accepted_qty"]))
        if accepted <= 0 or accepted >= requested:
            continue
        po_id, line_id = str(row["po_id"]), str(row["po_line_id"])
        old, new = _qty(requested), _qty(accepted)
        delta = _pct(old, new)
        quantity_candidates.append({
            "po": pos[po_id], "line": lines[line_id], "request_type": "QUANTITY_CHANGE", "change_type": "quantity",
            "old_value": old, "new_value": new, "delta": delta,
            "previous_qty": float(old), "requested_qty": float(new),
            "previous_unit_price": None, "requested_unit_price": None,
            "previous_promised_date": None, "requested_promised_date": None,
            "threshold_name": "QUANTITY_CHANGE_PCT", "created_at": str(row["response_timestamp"]),
            "requested_by_role": "supplier", "requested_by_actor_id": supplier_for_po[po_id],
            "reason_code": "SUPPLIER_CAPACITY" if row.get("rejected_reason") == "capacity" else "MATERIAL_SHORTAGE",
            "reason_text": f"Supplier ACK line accepted {new} of requested {old}; computed quantity delta {delta:+.2f}%.",
            "is_silence": False,
        })

    # 4. Source-traceable date candidates from actual current promise dates.
    current_promise = promise_dates.loc[promise_dates["status"].eq("CURRENT")] if not promise_dates.empty else promise_dates
    date_candidates: list[dict[str, Any]] = []
    for row in current_promise.to_dict(orient="records"):
        line_id = str(row["po_line_id"])
        line = lines[line_id]
        required_day = _day(line["required_date"])
        promised_day = _day(row["promised_date"])
        slip = (promised_day - required_day).days
        if slip <= 0:
            continue
        po_id = str(row["po_id"])
        date_candidates.append({
            "po": pos[po_id], "line": line, "request_type": "DATE_CHANGE", "change_type": "date",
            "old_value": required_day.isoformat(), "new_value": promised_day.isoformat(), "delta": float(slip),
            "previous_qty": None, "requested_qty": None, "previous_unit_price": None, "requested_unit_price": None,
            "previous_promised_date": required_day.isoformat(), "requested_promised_date": promised_day.isoformat(),
            "threshold_name": "DATE_SLIP_DAYS", "created_at": str(row["created_at"]),
            "requested_by_role": "supplier", "requested_by_actor_id": supplier_for_po[po_id],
            "reason_code": "TRANSPORT_DELAY", "reason_text": f"Current supplier promise is {slip} calendar days later than the requested line date.",
            "is_silence": False,
        })

    other_count = max(0, target_count - len(request_specs))
    # Allocate residual volume to quantity/date requests in config proportions, preserving both types.
    counts = {name: int(np.floor(other_count * probs[i])) for i, name in enumerate(names)}
    for name in names[:other_count - sum(counts.values())]:
        counts[name] += 1
    if other_count >= 2 and len(names) == 2:
        for name in names:
            if counts[name] == 0:
                other = names[1] if name == names[0] else names[0]
                counts[other] -= 1
                counts[name] += 1
    picked_qty = _sample_ordered(quantity_candidates, counts.get("QUANTITY_CHANGE", 0), rng, full_thresholds)
    picked_date = _sample_ordered(date_candidates, counts.get("DATE_CHANGE", 0), rng, full_thresholds)
    if len(picked_qty) < counts.get("QUANTITY_CHANGE", 0) or len(picked_date) < counts.get("DATE_CHANGE", 0):
        raise ValueError(
            "not enough source changes to fill configured event budget: "
            f"quantity candidates={len(quantity_candidates)}, requested={counts.get('QUANTITY_CHANGE', 0)}; "
            f"date candidates={len(date_candidates)}, requested={counts.get('DATE_CHANGE', 0)}"
        )
    request_specs.extend(picked_qty)
    request_specs.extend(picked_date)
    if len(request_specs) != target_count:
        raise RuntimeError(f"change request generator emitted {len(request_specs)} rows, expected {target_count}")

    change_rows: list[dict[str, Any]] = []
    approval_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    sequence = 0

    for spec in request_specs:
        sequence += 1
        po = spec["po"]
        line = spec.get("line")
        po_id = str(po["po_id"])
        change_id = factory.next_change_id(po_id)
        requested_at = str(spec["created_at"])
        created_dt = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        effective_date = (created_dt.date() + timedelta(days=1)).isoformat()
        response_due_date = (created_dt.date() + timedelta(days=2)).isoformat()
        # The rule evaluator computes the required role from the actual source delta.
        rule = evaluate_threshold(spec, full_thresholds)
        required_level = str(rule["required_approval_level"])
        status = "SUBMITTED"
        request_event_id = f"EVT-CHG-{sequence:06d}"
        issue_type = "DATE_SLIP_REQUIRES_APPROVAL" if rule["downstream_impact_flag"] else None
        ground_truth = issue_type
        derived_change = derive_change_fields({
            "change_type": spec["change_type"], "old_value": spec["old_value"], "new_value": spec["new_value"],
        }, full_thresholds)
        request_row: dict[str, Any] = {
            "change_request_id": change_id,
            "po_id": po_id,
            "supplier_id": supplier_for_po[po_id],
            "po_line_id": str(line["po_line_id"]) if line is not None else None,
            "request_type": str(spec["request_type"]),
            "change_type": str(spec["change_type"]),
            "old_value": str(spec["old_value"]),
            "new_value": str(spec["new_value"]),
            "delta": derived_change["delta"],
            "delta_abs": derived_change["delta_abs"],
            "delta_pct": derived_change["delta_pct"],
            "required_approval_level": derived_change["required_approval_level"],
            "status": status,
            "requested_at": requested_at,
            "effective_date": effective_date,
            "response_due_date": response_due_date,
            "previous_qty": spec.get("previous_qty"),
            "requested_qty": spec.get("requested_qty"),
            "previous_unit_price": spec.get("previous_unit_price"),
            "requested_unit_price": spec.get("requested_unit_price"),
            "previous_promised_date": spec.get("previous_promised_date"),
            "requested_promised_date": spec.get("requested_promised_date"),
            "reason_code": str(spec["reason_code"]),
            "reason_text": str(spec["reason_text"])[:2000],
            "requested_by_role": str(spec["requested_by_role"]),
            "requested_by_actor_id": str(spec["requested_by_actor_id"]),
            "created_at": requested_at,
            "updated_at": requested_at,
            "issue_type": issue_type,
            "ground_truth": ground_truth,
        }
        # Required level is passed explicitly to can_apply for this decision pass.
        gate_change = dict(request_row)
        gate_change["required_approval_level"] = required_level
        event_rows.append(_event(
            request_event_id, "ChangeRequest", change_id, "change_requested", requested_at,
            str(spec["requested_by_role"]), str(spec["requested_by_actor_id"]),
            {"change_type": spec["change_type"], "delta": spec["delta"], "threshold_name": rule["threshold_name"],
             "threshold_value": rule["threshold_value"], "required_approval_level": required_level,
             "downstream_impact_flag": rule["downstream_impact_flag"], "silence_escalation": bool(spec["is_silence"])},
            None, {"status": "SUBMITTED", "change_request_id": change_id},
            "target_change_request_id", change_id, issue_type=issue_type,
        ))
        event_rows.append(_event(
            f"EVT-CHG-{sequence:06d}-P", "ChangeRequest", change_id, "change_status_changed", requested_at,
            str(spec["requested_by_role"]), str(spec["requested_by_actor_id"]),
            {"reason": "change routed for review"}, {"status": "SUBMITTED"}, {"status": "UNDER_REVIEW"},
            "target_change_request_id", change_id, issue_type=issue_type,
        ))

        if spec["is_silence"]:
            planner_id = str(spec["requested_by_actor_id"])
            round_no = 1
            approval_id = factory.next_approval_id(change_id)
            approval_rows.append({
                "approval_id": approval_id, "change_request_id": change_id, "approval_round": round_no,
                "approver_role": "planner", "approval_level": "planner", "approver_actor_id": planner_id,
                "status": "PENDING", "requested_at": requested_at,
                "due_at": at_utc(created_dt.date() + timedelta(days=2), 17), "decided_at": None,
                "decision_reason": "Supplier response is overdue; chase supplier and review manually.",
                "comments": "Supplier response is overdue; chase supplier and review manually.",
                "threshold_name": "DATE_SLIP_DAYS", "threshold_value": 0.0,
                "created_at": requested_at, "issue_type": None, "ground_truth": None,
            })
            event_rows.append(_event(
                f"EVT-APR-{len(approval_rows):06d}", "Approval", approval_id, "approval_requested", requested_at,
                "planner", planner_id, {"status": "PENDING", "reason": "supplier silence chase"}, None,
                {"status": "PENDING", "change_request_id": change_id}, "target_approval_id", approval_id,
            ))
            request_row["status"] = "UNDER_REVIEW"
            request_row["updated_at"] = requested_at
            notification_id = factory.next_notification_id()
            notification_event_id = f"EVT-NOT-{len(notifications) + 1:06d}"
            notifications.append({
                "notification_id": notification_id, "not_id": notification_id,
                "not_type": "SUPPLIER_SILENCE_CHASE", "severity": "HIGH",
                "subject": "Supplier acknowledgement overdue — chase required",
                "related_entity_type": "ChangeRequest", "related_entity_id": change_id,
                "read_status": "UNREAD", "po_id": po_id, "open_impact_count": 0, "ack_id": None,
                "change_request_id": change_id, "source_event_id": request_event_id,
                "channel": "EMAIL", "status": "SENT",
                "title": "Supplier acknowledgement overdue — chase required",
                "body": f"Notification {notification_id}: change {change_id}, PO {po_id}, supplier {supplier_for_po[po_id]} did not acknowledge by {spec['silence_due_at']}. Planner {po['planner_actor_id']} must chase the supplier and record the response.",
                "scheduled_at": requested_at, "sent_at": requested_at, "delivered_at": None,
                "retry_count": 0, "last_error": None, "created_at": requested_at,
                "issue_type": None, "ground_truth": None,
            })
            event_rows.append(_event(
                notification_event_id, "Notification", notification_id, "chase_notification_sent", requested_at,
                "system", None, {"notification_id": notification_id, "change_request_id": change_id, "channel": "EMAIL"},
                None, {"status": "SENT"}, "target_notification_id", notification_id,
            ))
            change_rows.append(request_row)
            continue

        # Normal changes are approved/rejected by policy, not a sampled probability.
        review_rows: list[dict[str, Any]] = []
        roles = ["planner"] if required_level == "planner" else ["planner", "operations_manager"]
        final_decision = "APPROVED" if not rule["hard_limit_breach"] else "REJECTED"
        for round_no, role in enumerate(roles, start=1):
            approver_pool = planners if role == "planner" else ops_managers
            approver_id = str(approver_pool[(sequence + round_no - 2) % len(approver_pool)])
            if role == "planner" and required_level == "operations_manager":
                decision = "ESCALATED"
                comments = str(rule["escalation_reason"] or "Threshold breach requires operations-manager review.")
            else:
                decision = final_decision
                if decision == "APPROVED":
                    comments = f"Approved at {role} level under configured policy; measured delta {rule['measured_delta']:.4f}."
                else:
                    comments = f"Rejected at {role} level because measured delta {rule['measured_delta']:.4f} exceeds hard policy limit {rule['hard_limit']:g}."
            decided_at = _decision_time(requested_at, role, round_no)
            approval_id = factory.next_approval_id(change_id)
            approval = {
                "approval_id": approval_id, "change_request_id": change_id, "approval_round": round_no,
                "approver_role": role, "approval_level": role, "approver_actor_id": approver_id,
                "status": decision, "requested_at": requested_at,
                "due_at": at_utc(created_dt.date() + timedelta(days=2), 17), "decided_at": decided_at,
                "decision_reason": comments,
                "comments": comments,
                "threshold_name": str(rule["threshold_name"]), "threshold_value": round(float(rule["threshold_value"]), 3),
                "created_at": requested_at, "issue_type": None, "ground_truth": None,
            }
            approval_rows.append(approval)
            review_rows.append(approval)
            event_rows.append(_event(
                f"EVT-APR-{len(approval_rows):06d}", "Approval", approval_id, "approval_decided", decided_at,
                role, approver_id,
                {"decision": decision, "approval_level": role, "change_request_id": change_id,
                 "threshold_name": rule["threshold_name"], "threshold_value": rule["threshold_value"],
                 "downstream_impact_flag": rule["downstream_impact_flag"]},
                {"status": "PENDING"}, {"status": decision, "approval_id": approval_id},
                "target_approval_id", approval_id,
            ))
            if decision == "REJECTED":
                break
        approved, reason = can_apply(gate_change, review_rows, full_thresholds)
        if approved:
            request_row["status"] = "IMPLEMENTED"
            request_row["updated_at"] = str(review_rows[-1]["decided_at"])
            event_rows.append(_event(
                f"EVT-CHG-APPLIED-{sequence:06d}", "ChangeRequest", change_id, "change_status_changed",
                str(review_rows[-1]["decided_at"]), str(review_rows[-1]["approver_role"]), str(review_rows[-1]["approver_actor_id"]),
                {"reason": "required approval obtained"}, {"status": "UNDER_REVIEW"}, {"status": "APPROVED"},
                "target_change_request_id", change_id, issue_type=issue_type,
            ))
            event_rows.append(_event(
                f"EVT-CHG-DONE-{sequence:06d}", "ChangeRequest", change_id, "change_applied",
                str(review_rows[-1]["decided_at"]), str(review_rows[-1]["approver_role"]), str(review_rows[-1]["approver_actor_id"]),
                {"applied": True, "approval_gate_reason": reason,
                 "downstream_impact_flag": rule["downstream_impact_flag"]},
                {"status": "APPROVED"}, {"status": "IMPLEMENTED"},
                "target_change_request_id", change_id, issue_type=issue_type,
            ))
        else:
            request_row["status"] = "REJECTED"
            request_row["updated_at"] = str(review_rows[-1]["decided_at"])
            event_rows.append(_event(
                f"EVT-CHG-REJECT-{sequence:06d}", "ChangeRequest", change_id, "change_status_changed",
                str(review_rows[-1]["decided_at"]), str(review_rows[-1]["approver_role"]), str(review_rows[-1]["approver_actor_id"]),
                {"reason": reason}, {"status": "UNDER_REVIEW"}, {"status": "REJECTED"},
                "target_change_request_id", change_id, issue_type=issue_type,
            ))
        change_rows.append(request_row)

    # Every generated change has a request event; approvals are inserted as immutable rows.
    change_df = frame_for_entity("ChangeRequest", change_rows)
    approval_df = frame_for_entity("Approval", approval_rows)
    notification_df = frame_for_entity("Notification", notifications)
    added_events = pd.DataFrame(event_rows, columns=_EVENT_COLUMNS)
    if existing_events is not None and not existing_events.empty:
        entity_events = pd.concat([existing_events, added_events], ignore_index=True)
    else:
        entity_events = added_events
    return {
        "change_requests": change_df,
        "approvals": approval_df,
        "notifications": notification_df,
        "entity_event": entity_events,
    }
