"""Projected supply, production schedule impact propagation, and traceable notifications."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from numpy.random import Generator

from supplier_ack.generators.common import at_utc, frame_for_entity, get_config, require_rng
from supplier_ack.ids import IDFactory
from supplier_ack.rules.impact import compute_impact_severity
from supplier_ack.rules.derived import derive_open_impact_counts, derive_production_values

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


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: date) -> str:
    return value.isoformat()


def _qty(value: Any) -> float:
    return round(float(value), 3)


def _event(
    event_id: str, entity_type: str, entity_id: str, event_type: str,
    timestamp: str, actor_role: str, actor_id: str | None,
    payload: Mapping[str, Any], old: Mapping[str, Any] | None,
    new: Mapping[str, Any] | None, target_column: str, target_id: str,
) -> dict[str, Any]:
    row = {column: None for column in _EVENT_COLUMNS}
    row.update({
        "event_id": event_id, "entity_type": entity_type, "entity_id": entity_id,
        "event_type": event_type, "event_timestamp": timestamp,
        "actor_role": actor_role, "actor_id": actor_id,
        "payload_json": json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str),
        "previous_state": json.dumps(dict(old), sort_keys=True, separators=(",", ":"), default=str) if old is not None else None,
        "new_state": json.dumps(dict(new), sort_keys=True, separators=(",", ":"), default=str) if new is not None else None,
        target_column: target_id,
    })
    return row


def _latest_ack_rows(acknowledgements: pd.DataFrame) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in acknowledgements.to_dict(orient="records"):
        po_id = str(row["po_id"])
        if po_id not in latest or int(row["revision_no"]) > int(latest[po_id]["revision_no"]):
            latest[po_id] = row
    return latest


def _plan_record(
    *, factory: IDFactory, line: Mapping[str, Any], po: Mapping[str, Any],
    planner_id: str, revision: int, previous_id: str | None,
    projected_qty: float, projected_date: str, source: str,
    created_at: str, effective_date: str, approved_by: str,
    change_id: str | None, demand_qty: float, acknowledged_qty: float,
    promised_qty: float, status: str, superseded_by: str | None,
    is_effective: int,
) -> dict[str, Any]:
    inventory_plan_id = factory.next_inventory_plan_id(str(line["po_line_id"]))
    on_hand, reserved = 0.0, 0.0
    planned_receipt = _qty(projected_qty)
    available = _qty(on_hand - reserved + planned_receipt)
    shortage = _qty(max(0.0, demand_qty - available))
    start_day = _day(po["order_date"])
    end_day = max(start_day, _day(projected_date))
    return {
        "inventory_plan_id": inventory_plan_id,
        "po_id": str(line["po_id"]), "po_line_id": str(line["po_line_id"]),
        "plan_revision_no": revision, "plan_version": revision,
        "previous_version_id": previous_id, "source": source,
        "is_effective": int(is_effective), "projected_delivery_date": projected_date,
        "change_request_id": change_id, "status": status,
        "demand_qty": _qty(demand_qty), "requested_qty": _qty(line["requested_qty"]),
        "acknowledged_qty": _qty(acknowledged_qty), "promised_qty": _qty(promised_qty),
        "projected_qty": _qty(projected_qty), "on_hand_qty": on_hand,
        "reserved_qty": reserved, "planned_receipt_qty": planned_receipt,
        "projected_available_qty": available, "projected_shortage_qty": shortage,
        "required_date": str(line["required_date"]),
        "promised_date": projected_date if source != "po_baseline" else None,
        "plan_start_date": _iso(start_day), "plan_end_date": _iso(end_day),
        "planner_actor_id": planner_id, "approved_by_actor_id": approved_by,
        "effective_date": effective_date, "superseded_by": superseded_by,
        "created_at": created_at, "updated_at": created_at,
        "issue_type": None, "ground_truth": None,
    }


def trace(not_id: str, frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    """Resolve a Notification into its source change (when present), ACK, PO, and supplier.

    ACK-only plan notifications correctly report ``change=None`` because no ChangeRequest
    exists for an acknowledgement that changes no requested business value. All traced
    records are resolved from IDs in the supplied generated data; the function invents no IDs.
    """
    notification_frame = frames.get("notifications", pd.DataFrame())
    if notification_frame.empty:
        raise KeyError(f"notification {not_id!r} not found: notifications table is empty")
    found = notification_frame.loc[
        notification_frame.get("notification_id", pd.Series(dtype=str)).astype(str).eq(str(not_id))
        | notification_frame.get("not_id", pd.Series(dtype=str)).astype(str).eq(str(not_id))
    ]
    if found.empty:
        raise KeyError(f"notification {not_id!r} was not found")
    notification = found.iloc[0].to_dict()
    changes = frames.get("change_requests", pd.DataFrame())
    change = None
    change_id = notification.get("change_request_id")
    if change_id is None and notification.get("related_entity_type") == "ChangeRequest":
        change_id = notification.get("related_entity_id")
    if change_id is not None and not changes.empty:
        rows = changes.loc[changes["change_request_id"].astype(str).eq(str(change_id))]
        if not rows.empty:
            change = rows.iloc[0].to_dict()
    acknowledgements = frames.get("acknowledgements", pd.DataFrame())
    po_id = (change or {}).get("po_id") or notification.get("po_id")
    ack_id = notification.get("ack_id")
    ack = None
    if not acknowledgements.empty:
        if ack_id is not None:
            matches = acknowledgements.loc[acknowledgements["ack_id"].astype(str).eq(str(ack_id))]
        else:
            matches = acknowledgements.loc[acknowledgements["po_id"].astype(str).eq(str(po_id))]
            if change and change.get("po_line_id") and "acknowledgement_lines" in frames:
                line_rows = frames["acknowledgement_lines"]
                candidate_ack_ids = set(line_rows.loc[
                    line_rows["po_line_id"].astype(str).eq(str(change["po_line_id"])), "ack_id"
                ].astype(str))
                line_matches = matches.loc[matches["ack_id"].astype(str).isin(candidate_ack_ids)]
                if not line_matches.empty:
                    matches = line_matches
            if not matches.empty:
                matches = matches.sort_values("revision_no")
        if not matches.empty:
            ack = matches.iloc[-1].to_dict()
    if ack and po_id is None:
        po_id = ack.get("po_id")
    purchase_orders = frames.get("purchase_orders", pd.DataFrame())
    po = None
    if po_id is not None and not purchase_orders.empty:
        matches = purchase_orders.loc[purchase_orders["po_id"].astype(str).eq(str(po_id))]
        if not matches.empty:
            po = matches.iloc[0].to_dict()
    suppliers = frames.get("suppliers", pd.DataFrame())
    supplier = None
    supplier_id = (po or {}).get("supplier_id") or (change or {}).get("supplier_id")
    if supplier_id is not None and not suppliers.empty:
        matches = suppliers.loc[suppliers["supplier_id"].astype(str).eq(str(supplier_id))]
        if not matches.empty:
            supplier = matches.iloc[0].to_dict()
    silent_change = bool(
        change
        and "no supplier acknowledgement" in str(change.get("reason_text", "")).lower()
        and ack is None
    )
    if all((change, ack, po, supplier)):
        trace_status = "complete"
    elif silent_change and all((change, po, supplier)):
        # Silence is itself the traceable outcome; never synthesize an ACK to fill the gap.
        trace_status = "complete_supplier_silence"
    elif change is None and all((ack, po, supplier)):
        trace_status = "acknowledgement-only"
    else:
        trace_status = "partial"
    return {
        "notification": notification,
        "change": change,
        "acknowledgement": ack,
        "purchase_order": po,
        "supplier": supplier,
        "trace_status": trace_status,
    }


def generate_supply_workflow(
    rng: Generator,
    cfg: Mapping[str, Any],
    purchase_orders: pd.DataFrame,
    po_lines: pd.DataFrame,
    suppliers: pd.DataFrame,
    actors: pd.DataFrame,
    acknowledgements: pd.DataFrame,
    acknowledgement_lines: pd.DataFrame,
    promise_dates: pd.DataFrame,
    change_requests: pd.DataFrame,
    approvals: pd.DataFrame,
    existing_notifications: pd.DataFrame,
    existing_events: pd.DataFrame,
    id_factory: IDFactory | None = None,
) -> dict[str, pd.DataFrame]:
    """Create immutable InventoryPlan versions, downstream ProductionOrders, impacts and notices."""
    require_rng(rng)
    factory = id_factory or IDFactory()
    scale = str(cfg.get("active_scale", "starter"))
    scale_cfg = cfg.get("scales", {}).get(scale, {})
    thresholds = get_config(cfg, "downstream_impact_tolerances", default={})
    date_grace = int(thresholds.get("date_conflict_grace_days", 0))
    qty_tolerance = float(thresholds.get("quantity_shortfall_pct", 0.0))

    po_rows = {str(row["po_id"]): row for row in purchase_orders.to_dict(orient="records")}
    line_rows = {str(row["po_line_id"]): row for row in po_lines.to_dict(orient="records")}
    suppliers_by_id = {str(row["supplier_id"]): row for row in suppliers.to_dict(orient="records")}
    actor_rows = actors.to_dict(orient="records")
    role_actor_ids: dict[str, list[str]] = {}
    actor_by_id = {}
    for actor in actor_rows:
        actor_id = str(actor["actor_id"])
        actor_by_id[actor_id] = actor
        role_actor_ids.setdefault(str(actor["actor_role"]), []).append(actor_id)
    planners = role_actor_ids.get("planner", [])
    logistics = role_actor_ids.get("logistics_analyst", [])
    operators = role_actor_ids.get("carrier_warehouse_operator", [])
    ops_managers = role_actor_ids.get("operations_manager", [])
    if not planners or not logistics or not operators or not ops_managers:
        raise ValueError("actor roster must include planner, logistics_analyst, carrier_warehouse_operator and operations_manager roles")

    po_by_line = {line_id: po_rows[str(line["po_id"])] for line_id, line in line_rows.items()}
    planner_by_po = {po_id: str(po["planner_actor_id"]) for po_id, po in po_rows.items()}
    latest_ack = _latest_ack_rows(acknowledgements)
    ack_by_id = {str(row["ack_id"]): row for row in acknowledgements.to_dict(orient="records")}
    ack_line_rows = acknowledgement_lines.to_dict(orient="records")
    current_promises = promise_dates.loc[promise_dates["status"].eq("CURRENT")] if not promise_dates.empty else promise_dates
    promise_by_line: dict[str, dict[str, Any]] = {}
    for row in current_promises.to_dict(orient="records"):
        line_id = str(row["po_line_id"])
        ack = latest_ack.get(str(row["po_id"]))
        if ack and str(row["ack_id"]) == str(ack["ack_id"]):
            promise_by_line[line_id] = row
    latest_ack_line = {}
    latest_ack_ids = {str(row["ack_id"]) for row in latest_ack.values()}
    for row in ack_line_rows:
        if str(row["ack_id"]) in latest_ack_ids:
            latest_ack_line[str(row["po_line_id"])] = row

    change_rows = change_requests.to_dict(orient="records")
    change_by_id = {str(row["change_request_id"]): row for row in change_rows}
    changes_by_line: dict[str, list[dict[str, Any]]] = {}
    for row in change_rows:
        line_id = row.get("po_line_id")
        if line_id is not None:
            changes_by_line.setdefault(str(line_id), []).append(row)
    approval_rows = approvals.to_dict(orient="records")
    approvals_by_change: dict[str, list[dict[str, Any]]] = {}
    for row in approval_rows:
        approvals_by_change.setdefault(str(row["change_request_id"]), []).append(row)

    # 1) InventoryPlan: version 1 is the original PO line projection, never a supplier promise.
    plan_rows: list[dict[str, Any]] = []
    plan_events: list[dict[str, Any]] = []
    new_version_change_for_line: dict[str, str | None] = {}
    new_version_lines: set[str] = set()
    for line_id, line in line_rows.items():
        po = po_by_line[line_id]
        planner_id = planner_by_po[str(po["po_id"])]
        baseline_qty = _qty(line["requested_qty"])
        baseline_date = str(line["required_date"])
        baseline_time = str(po["created_at"])
        related_changes = sorted(changes_by_line.get(line_id, []), key=lambda row: str(row["requested_at"]))
        ack = latest_ack.get(str(po["po_id"]))
        promise = promise_by_line.get(line_id)
        ack_line = latest_ack_line.get(line_id)
        processed = bool(
            ack and str(ack.get("lifecycle_state", "PROCESSED")) == "PROCESSED"
            and promise and ack_line and str(promise.get("ack_id")) == str(ack["ack_id"])
            and float(promise.get("promised_qty", 0) or 0) > 0
        )
        # Hard approval gate: any related pending/rejected change holds projection at baseline.
        can_update = processed and not any(str(change["status"]) != "IMPLEMENTED" for change in related_changes)
        effective_change = next((row for row in related_changes if str(row["status"]) == "IMPLEMENTED"), None) if can_update else None
        plan_version_will_exist = bool(can_update)
        baseline_id = f"IP-{line_id}-01"
        baseline_record = _plan_record(
            factory=factory, line=line, po=po, planner_id=planner_id, revision=1,
            previous_id=None, projected_qty=baseline_qty, projected_date=baseline_date,
            source="po_baseline", created_at=baseline_time, effective_date=str(po["order_date"]),
            approved_by=planner_id, change_id=None, demand_qty=baseline_qty,
            acknowledged_qty=0.0, promised_qty=0.0,
            status="SUPERSEDED" if plan_version_will_exist else "ACTIVE",
            superseded_by=(f"IP-{line_id}-02" if plan_version_will_exist else None),
            is_effective=0 if plan_version_will_exist else 1,
        )
        if baseline_record["inventory_plan_id"] != baseline_id:
            raise RuntimeError(f"inventory plan IDs out of sequence for {line_id}: {baseline_record['inventory_plan_id']} != {baseline_id}")
        plan_rows.append(baseline_record)
        new_version_change_for_line[line_id] = str(effective_change["change_request_id"]) if effective_change else None
        if can_update:
            source = "approved_change" if effective_change else "approved_ack"
            approved_actor = planner_id
            if effective_change:
                approvals_for_source = approvals_by_change.get(str(effective_change["change_request_id"]), [])
                approved = [a for a in approvals_for_source if str(a["status"]) == "APPROVED"]
                if approved:
                    approved_actor = str(sorted(approved, key=lambda a: int(a["approval_round"]))[-1]["approver_actor_id"])
            new_version = _plan_record(
                factory=factory, line=line, po=po, planner_id=planner_id, revision=2,
                previous_id=baseline_record["inventory_plan_id"], projected_qty=_qty(promise["promised_qty"]),
                projected_date=str(promise["promised_date"]), source=source,
                created_at=str(promise["created_at"]), effective_date=str(promise["effective_date"]),
                approved_by=approved_actor,
                change_id=str(effective_change["change_request_id"]) if effective_change else None,
                demand_qty=baseline_qty, acknowledged_qty=_qty(ack_line["accepted_qty"]),
                promised_qty=_qty(promise["promised_qty"]), status="ACTIVE", superseded_by=None,
                is_effective=1,
            )
            plan_rows.append(new_version)
            new_version_lines.add(line_id)

    inventory_plans = frame_for_entity("InventoryPlan", plan_rows)
    plan_by_id = {str(row["inventory_plan_id"]): row for row in plan_rows}
    current_plan_by_line = {
        str(row["po_line_id"]): row for row in plan_rows if int(row["is_effective"]) == 1
    }
    for index, row in enumerate(plan_rows, start=1):
        is_new = int(row["plan_version"]) > 1
        event_type = "inventory_plan_updated" if is_new else "inventory_plan_created"
        event_id = f"EVT-PLAN-{index:06d}"
        actor_role = "planner" if is_new else "system"
        actor_id = str(row["planner_actor_id"]) if is_new else None
        plan_events.append(_event(
            event_id, "InventoryPlan", str(row["inventory_plan_id"]), event_type,
            str(row["created_at"]), actor_role, actor_id,
            {"plan_version": row["plan_version"], "source": row["source"], "projected_qty": row["projected_qty"],
             "projected_delivery_date": row["projected_delivery_date"], "is_effective": row["is_effective"],
             "change_request_id": row["change_request_id"]},
            None if not is_new else {"previous_version_id": row["previous_version_id"]},
            {"inventory_plan_id": row["inventory_plan_id"], "plan_version": row["plan_version"], "is_effective": row["is_effective"]},
            "target_inventory_plan_id", str(row["inventory_plan_id"]),
        ))

    # 2) Production orders and their material allocation bridge. Prioritize lines whose
    # approved changes are capable of generating a true downstream conflict/shortfall.
    target_orders = int(scale_cfg.get("production_order_count", 100 if scale == "starter" else 5000))
    quantity_changed_lines = {
        str(row["po_line_id"]) for row in change_rows
        if row.get("po_line_id") is not None and row.get("change_type") == "quantity" and row.get("status") == "IMPLEMENTED"
    }
    date_changed_lines = {
        str(row["po_line_id"]) for row in change_rows
        if row.get("po_line_id") is not None and row.get("change_type") == "date" and row.get("status") == "IMPLEMENTED"
    }
    impact_candidate_lines = [
        line_id for line_id in line_rows
        if line_id in new_version_lines and (line_id in quantity_changed_lines or line_id in date_changed_lines)
    ]
    impact_candidate_line_set = set(impact_candidate_lines)
    remaining_lines = [line_id for line_id in line_rows if line_id not in impact_candidate_line_set]
    if len(remaining_lines) > 1:
        remaining_lines = [remaining_lines[int(i)] for i in rng.permutation(len(remaining_lines))]
    selected_lines = (impact_candidate_lines + remaining_lines)[:min(target_orders, len(line_rows))]
    if len(selected_lines) < min(target_orders, len(line_rows)):
        raise RuntimeError("could not fill configured production-order cohort")

    production_orders: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []
    allocation_by_order: dict[str, dict[str, Any]] = {}
    production_events: list[dict[str, Any]] = []
    duration_days_by_order: dict[str, int] = {}
    order_by_line: dict[str, dict[str, Any]] = {}
    promise_for_line = promise_by_line
    for seq, line_id in enumerate(selected_lines, start=1):
        line, po = line_rows[line_id], po_by_line[line_id]
        current_plan = current_plan_by_line[line_id]
        requested = _qty(line["requested_qty"])
        projected = _qty(current_plan["projected_qty"])
        if line_id in quantity_changed_lines and projected < requested:
            allocated = min(requested, projected + max(0.001, (requested - projected) * 0.80))
        else:
            # Baseline/ACK-only rows may not allocate more than available projected
            # supply. A deliberate shortfall is generated only for approved quantity
            # changes, which must propagate an AT_RISK production-order state.
            allocated = min(projected, max(0.001, projected * float(rng.uniform(0.35, 0.82))))
        allocated = _qty(allocated)
        promise = promise_for_line.get(line_id)
        if line_id in date_changed_lines and promise:
            new_day = _day(promise["promised_date"])
            req_by = new_day - timedelta(days=max(1, min(5, max(1, (_day(promise["promised_date"]) - _day(line["required_date"])).days // 2))))
        else:
            req_by = _day(line["required_date"]) + timedelta(days=int(rng.integers(-10, 11)))
        duration = 14
        planned_start = req_by - timedelta(days=duration)
        end_day = planned_start + timedelta(days=duration)
        owner_role = "planner"
        owner_id = str(po["planner_actor_id"])
        production_id = factory.next_production_order_id()
        planned_qty = _qty(max(1.0, allocated * 0.5))
        row = {
            "production_order_id": production_id,
            "inventory_plan_id": str(current_plan["inventory_plan_id"]),
            "po_id": str(po["po_id"]), "po_line_id": line_id,
            "required_by_date": _iso(req_by), "planned_start_date": _iso(planned_start),
            "status": "PLANNED", "at_risk": False,
            "shortfall_qty": _qty(max(0.0, allocated - projected)),
            "delay_days": max(0, (_day(current_plan["projected_delivery_date"]) - req_by).days),
            "planned_qty": planned_qty, "released_qty": 0.0,
            "completed_qty": 0.0, "affected_material_qty": allocated,
            "priority": "HIGH" if line_id in impact_candidate_lines else str(rng.choice(["LOW", "NORMAL", "HIGH"], p=[0.2, 0.55, 0.25])),
            "original_start_date": _iso(planned_start), "current_start_date": _iso(planned_start),
            "scheduled_end_date": _iso(end_day), "actual_start_date": None, "actual_end_date": None,
            "schedule_shift_days": 0, "owner_role": owner_role, "owner_actor_id": owner_id,
            "created_at": str(po["created_at"]), "updated_at": str(po["created_at"]),
            "issue_type": None, "ground_truth": None,
        }
        production_orders.append(row)
        allocation = {
            "production_order_id": production_id, "po_line_id": line_id,
            "allocated_quantity": allocated, "allocated_uom": str(line["uom"]),
            "created_at": str(po["created_at"]),
        }
        allocation_rows.append(allocation)
        allocation_by_order[production_id] = allocation
        duration_days_by_order[production_id] = duration
        order_by_line[line_id] = row
        production_events.append(_event(
            f"EVT-PRO-{seq:06d}", "ProductionOrder", production_id, "production_order_created",
            str(po["created_at"]), "planner", owner_id,
            {"po_id": po["po_id"], "po_line_id": line_id, "allocated_quantity": allocated,
             "required_by_date": _iso(req_by), "planned_start_date": _iso(planned_start)},
            None, {"status": "PLANNED", "planned_start_date": _iso(planned_start)},
            "target_production_order_id", production_id,
        ))

    # 3) Propagate approved changes only. The current plan must explicitly point to an
    # approved_change source; pending/rejected requests cannot create impacts.
    impact_records: list[dict[str, Any]] = []
    impact_events: list[dict[str, Any]] = []
    transition_seq = 0
    impact_changes = [row for row in change_rows if str(row["status"]) == "IMPLEMENTED" and row.get("po_line_id")]
    for change in impact_changes:
        line_id = str(change["po_line_id"])
        plan = current_plan_by_line.get(line_id)
        order = order_by_line.get(line_id)
        if plan is None or order is None or str(plan["source"]) != "approved_change":
            continue
        if str(plan.get("change_request_id")) not in {None, str(change["change_request_id"])}:
            # Another approved change on the same line may have supplied the current projection;
            # its source values still govern the impact, and the original change remains auditable.
            pass
        previous_plan = plan_by_id.get(str(plan.get("previous_version_id")), plan)
        old_date = _day(previous_plan["projected_delivery_date"])
        new_date = _day(plan["projected_delivery_date"])
        old_qty = float(previous_plan["projected_qty"])
        new_qty = float(plan["projected_qty"])
        allocation = allocation_by_order[str(order["production_order_id"])]
        allocated_qty = float(allocation["allocated_quantity"])
        required_by = _day(order["required_by_date"])
        slip_days = max(0, (new_date - required_by).days)
        shortfall_pct = max(0.0, (allocated_qty - new_qty) / allocated_qty * 100.0) if allocated_qty > 0 else 0.0
        candidates: list[tuple[str, int, float]] = []
        if str(change["change_type"]) == "date" and new_date > old_date and slip_days > date_grace:
            candidates.append(("date_conflict", slip_days, 0.0))
        if (str(change["change_type"]) == "quantity" or new_qty < old_qty) and allocated_qty > new_qty and shortfall_pct > qty_tolerance:
            candidates.append(("quantity_shortfall", 0, shortfall_pct))
        for impact_type, impact_slip, impact_shortfall in candidates:
            severity = compute_impact_severity(impact_slip, impact_shortfall)
            impact_id = f"IMP-2026-{len(impact_records) + 1:06d}"
            new_start = _day(order["planned_start_date"])
            if impact_type == "date_conflict":
                # The new start is tied to observed projected receipt, plus one calendar day.
                new_start = min(max(new_start, new_date + timedelta(days=1)), required_by)
            old_state = {
                "status": order["status"], "planned_start_date": order["planned_start_date"],
                "projected_qty": old_qty, "projected_delivery_date": _iso(old_date),
            }
            previous_status = str(order["status"])
            if impact_type == "date_conflict":
                order["status"] = "RESCHEDULED"
                order["planned_start_date"] = _iso(new_start)
                order["current_start_date"] = _iso(new_start)
                order["schedule_shift_days"] = (_day(order["current_start_date"]) - _day(order["original_start_date"])).days
                order["scheduled_end_date"] = _iso(new_start + timedelta(days=duration_days_by_order[order["production_order_id"]]))
            else:
                # A material shortfall always leaves the order visibly at risk even
                # when a date conflict had previously rescheduled the same order.
                order["status"] = "AT_RISK"
            order["updated_at"] = max(str(order["updated_at"]), str(change["updated_at"]))
            new_state = {
                "status": order["status"], "planned_start_date": order["planned_start_date"],
                "projected_qty": new_qty, "projected_delivery_date": _iso(new_date),
            }
            impact_records.append({
                "impact_id": impact_id, "production_order_id": str(order["production_order_id"]),
                "change_request_id": str(change["change_request_id"]), "po_line_id": line_id,
                "impact_type": impact_type, "severity": severity,
                "slip_days": int(impact_slip), "shortfall_pct": round(float(impact_shortfall), 4),
                "old_projected_delivery_date": _iso(old_date), "new_projected_delivery_date": _iso(new_date),
                "old_projected_qty": _qty(old_qty), "new_projected_qty": _qty(new_qty),
                "rescheduled_planned_start_date": str(order["planned_start_date"]),
                "created_at": str(change["updated_at"]),
            })
            transition_seq += 1
            actor_role = "operations_manager" if severity in {"HIGH", "CRITICAL"} else "planner"
            actor_pool = ops_managers if actor_role == "operations_manager" else planners
            actor_id = str(actor_pool[transition_seq % len(actor_pool)])
            impact_events.append(_event(
                f"EVT-IMPACT-{transition_seq:06d}", "ProductionOrder", str(order["production_order_id"]),
                "downstream_impact_created", str(change["updated_at"]), actor_role, actor_id,
                {"impact_id": impact_id, "change_request_id": change["change_request_id"],
                 "impact_type": impact_type, "severity": severity}, old_state, new_state,
                "target_production_order_id", str(order["production_order_id"]),
            ))
            if previous_status != str(order["status"]):
                impact_events.append(_event(
                    f"EVT-PRO-STATE-{transition_seq:06d}", "ProductionOrder", str(order["production_order_id"]),
                    "production_order_status_changed", str(change["updated_at"]), actor_role, actor_id,
                    {"change_request_id": change["change_request_id"], "impact_id": impact_id},
                    {"status": previous_status, "planned_start_date": old_state["planned_start_date"]},
                    {"status": order["status"], "planned_start_date": order["planned_start_date"]},
                    "target_production_order_id", str(order["production_order_id"]),
                ))

    for order in production_orders:
        line_id = str(order["po_line_id"])
        plan = current_plan_by_line[line_id]
        allocation = allocation_by_order[str(order["production_order_id"])]
        order.update(derive_production_values(
            order, allocation["allocated_quantity"], plan["projected_qty"], plan["projected_delivery_date"]
        ))

    production_df = frame_for_entity("ProductionOrder", production_orders)
    impacts_df = pd.DataFrame(impact_records, columns=[
        "impact_id", "production_order_id", "change_request_id", "po_line_id", "impact_type", "severity",
        "slip_days", "shortfall_pct", "old_projected_delivery_date", "new_projected_delivery_date",
        "old_projected_qty", "new_projected_qty", "rescheduled_planned_start_date", "created_at",
    ])
    allocation_df = pd.DataFrame(allocation_rows, columns=[
        "production_order_id", "po_line_id", "allocated_quantity", "allocated_uom", "created_at",
    ])

    # 4) Notifications and recipient fan-out. Every recipient is resolved from the
    # PO's buyer/planner or the explicit actor role, never chosen as a random planner.
    notification_rows = existing_notifications.to_dict(orient="records") if not existing_notifications.empty else []
    recipient_rows: list[dict[str, Any]] = []
    notice_events: list[dict[str, Any]] = []
    notice_counter = 0
    existing_notice_ids = {str(row["notification_id"]) for row in notification_rows}
    # Reuse the central derivation helper for every row's PO-level open impact count.
    open_impact_by_po = derive_open_impact_counts({
        "production_orders": pd.DataFrame(production_orders),
        "production_order_impact": pd.DataFrame(impact_records),
    })
    for existing_notice in notification_rows:
        existing_notice["open_impact_count"] = int(open_impact_by_po.get(str(existing_notice.get("po_id") or ""), 0))

    def add_recipients(notification_id: str, recipients: Sequence[tuple[str, str | None]]) -> None:
        seen: set[str] = set()
        for role, actor_id in recipients:
            if role in seen:
                continue
            seen.add(role)
            recipient_rows.append({
                "notification_id": notification_id, "actor_role": role,
                "recipient_actor_id": actor_id,
            })

    for notice in notification_rows:
        change_id = notice.get("change_request_id")
        change = change_by_id.get(str(change_id)) if change_id is not None else None
        po_id = str(notice.get("po_id") or (change or {}).get("po_id") or "")
        if po_id in po_rows:
            po = po_rows[po_id]
            supplier_id = str(po["supplier_id"])
            add_recipients(str(notice["notification_id"]), [
                ("planner", planner_by_po[po_id]), ("supplier", supplier_id),
            ])

    def create_notification(
        not_type: str, severity: str, subject: str, body: str, po_id: str,
        recipients: Sequence[tuple[str, str | None]], timestamp: str,
        *, change_id: str | None = None, ack_id: str | None = None,
        related_entity_type: str | None = None, related_entity_id: str | None = None,
        source_event_id: str | None = None,
    ) -> str:
        nonlocal notice_counter
        notice_counter += 1
        notification_id = factory.next_notification_id()
        if notification_id in existing_notice_ids:
            raise RuntimeError(f"duplicate notification ID generated: {notification_id}")
        existing_notice_ids.add(notification_id)
        related_type = related_entity_type or ("ChangeRequest" if change_id else "Acknowledgement")
        related_id = related_entity_id or (change_id or ack_id)
        if not related_id:
            raise ValueError(f"notification {not_type} requires traceable related entity")
        event_id = source_event_id or f"EVT-NOTIF-{notice_counter:06d}"
        notice = {
            "notification_id": notification_id, "not_id": notification_id,
            "not_type": not_type, "severity": severity, "subject": subject,
            "related_entity_type": related_type, "related_entity_id": str(related_id),
            "read_status": "UNREAD", "po_id": po_id or None,
            "open_impact_count": int(open_impact_by_po.get(str(po_id), 0)), "ack_id": ack_id,
            "change_request_id": change_id, "source_event_id": event_id,
            "channel": "IN_APP", "status": "SENT", "title": subject,
            "body": body[:8000], "scheduled_at": timestamp, "sent_at": timestamp,
            "delivered_at": None, "retry_count": 0, "last_error": None,
            "created_at": timestamp, "issue_type": None, "ground_truth": None,
        }
        notification_rows.append(notice)
        add_recipients(notification_id, recipients)
        notice_events.append(_event(
            event_id, "Notification", notification_id, "notification_sent", timestamp,
            "system", None,
            {"not_type": not_type, "severity": severity, "related_entity_type": related_type,
             "related_entity_id": related_id, "recipient_roles": [role for role, _ in recipients]},
            None, {"status": "SENT", "notification_id": notification_id},
            "target_notification_id", notification_id,
        ))
        return notification_id

    # Change raised -> owning planner.
    for change in change_rows:
        po_id = str(change["po_id"])
        planner_id = planner_by_po[po_id]
        ack = latest_ack.get(po_id)
        create_notification(
            "CHANGE_RAISED", "MEDIUM", f"Change request raised: {change['change_request_id']}",
            f"Change {change['change_request_id']} ({change['change_type']}) for PO {po_id}, line {change.get('po_line_id') or 'PO-wide'}; status={change['status']}, delta={change['delta']}. Planner={planner_id}; supplier={change['supplier_id']}.",
            po_id, [("planner", planner_id)], str(change["requested_at"]),
            change_id=str(change["change_request_id"]), ack_id=str(ack["ack_id"]) if ack else None,
            related_entity_type="ChangeRequest", related_entity_id=str(change["change_request_id"]),
        )

    # Approval decisions -> original requester. Escalation rows are decisions too.
    for approval in approval_rows:
        if str(approval["status"]) == "PENDING":
            continue
        change = change_by_id[str(approval["change_request_id"])]
        po_id = str(change["po_id"])
        ack = latest_ack.get(po_id)
        requested_role = str(change["requested_by_role"])
        requested_actor = str(change["requested_by_actor_id"])
        status = str(approval["status"])
        severity = "HIGH" if status == "REJECTED" else "MEDIUM" if status == "ESCALATED" else "INFO"
        create_notification(
            "APPROVAL_DECISION", severity, f"Approval {status.lower()}: {change['change_request_id']}",
            f"Approval {approval['approval_id']} decided {status} at {approval['approval_level']} level for change {change['change_request_id']} (PO {po_id}). Requester={requested_role}:{requested_actor}.",
            po_id, [(requested_role, requested_actor)], str(approval["decided_at"] or approval["requested_at"]),
            change_id=str(change["change_request_id"]), ack_id=str(ack["ack_id"]) if ack else None,
            related_entity_type="ChangeRequest", related_entity_id=str(change["change_request_id"]),
        )

    # Every new effective projection gets a planner + logistics analyst notice.
    for plan in plan_rows:
        if int(plan["plan_version"]) <= 1:
            continue
        po_id, line_id = str(plan["po_id"]), str(plan["po_line_id"])
        ack = latest_ack.get(po_id)
        change_id = str(plan["change_request_id"]) if plan.get("change_request_id") else None
        related_type = "ChangeRequest" if change_id else "Acknowledgement"
        related_id = change_id or (str(ack["ack_id"]) if ack else None)
        if related_id is None:
            continue
        logistics_id = str(logistics[(int(str(line_rows[line_id]["line_no"])) - 1) % len(logistics)])
        create_notification(
            "PLAN_UPDATED", "INFO", f"Projected supply updated for {line_id}",
            f"InventoryPlan {plan['inventory_plan_id']} version {plan['plan_version']} is effective for PO {po_id}, line {line_id}: projected_qty={plan['projected_qty']}, projected_delivery_date={plan['projected_delivery_date']}, source={plan['source']}, change={change_id or 'ACK-only'}.",
            po_id, [("planner", planner_by_po[po_id]), ("logistics_analyst", logistics_id)],
            str(plan["created_at"]), change_id=change_id, ack_id=str(ack["ack_id"]) if ack else None,
            related_entity_type=related_type, related_entity_id=related_id,
        )

    # Downstream impact notifications go to planner, and carrier/warehouse operator
    # whenever a delivery slot moves (date conflict).
    for impact in impact_records:
        change = change_by_id[str(impact["change_request_id"])]
        po_id, line_id = str(change["po_id"]), str(impact["po_line_id"])
        ack = latest_ack.get(po_id)
        recipients: list[tuple[str, str | None]] = [("planner", planner_by_po[po_id])]
        if str(impact["impact_type"]) == "date_conflict":
            promise = promise_by_line.get(line_id)
            operator_id = str(promise["carrier_operator_actor_id"]) if promise else str(operators[0])
            recipients.append(("carrier_warehouse_operator", operator_id))
        create_notification(
            "DOWNSTREAM_IMPACT", str(impact["severity"]),
            f"Production order impact {impact['impact_id']}: {impact['impact_type']}",
            f"Impact {impact['impact_id']} on production order {impact['production_order_id']} was computed from approved change {change['change_request_id']}; type={impact['impact_type']}, severity={impact['severity']}, slip_days={impact['slip_days']}, shortfall_pct={impact['shortfall_pct']}. PO={po_id}, line={line_id}.",
            po_id, recipients, str(impact["created_at"]), change_id=str(change["change_request_id"]),
            ack_id=str(ack["ack_id"]) if ack else None,
            related_entity_type="ChangeRequest", related_entity_id=str(change["change_request_id"]),
        )

    # Weekly summary: one traceable message per operations manager, anchored to a
    # real change so recipients can inspect a concrete source chain from the notice.
    if change_rows:
        representative = sorted(change_rows, key=lambda row: (str(row["requested_at"]), str(row["change_request_id"])))[-1]
        po_id = str(representative["po_id"])
        ack = latest_ack.get(po_id)
        summary_body = (
            f"Weekly supplier workflow summary: {len(change_rows)} changes, {len(approval_rows)} approval steps, "
            f"{len(plan_rows)} projected-supply versions, {len(impact_records)} downstream impacts. "
            f"Trace anchor change={representative['change_request_id']}, PO={po_id}, supplier={representative['supplier_id']}."
        )
        for manager_id in ops_managers:
            create_notification(
                "WEEKLY_SUMMARY", "INFO", "Weekly supplier acknowledgement workflow summary",
                summary_body, po_id, [("operations_manager", str(manager_id))],
                at_utc(_day(get_config(cfg, "coverage", "as_of_date", default="2026-10-28")), 17),
                change_id=str(representative["change_request_id"]), ack_id=str(ack["ack_id"]) if ack else None,
                related_entity_type="ChangeRequest", related_entity_id=str(representative["change_request_id"]),
            )

    # Keep old and new events together; every plan/update/impact/notification has a ledger row.
    new_events = pd.DataFrame(plan_events + production_events + impact_events + notice_events, columns=_EVENT_COLUMNS)
    if existing_events is not None and not existing_events.empty:
        events_df = pd.concat([existing_events, new_events], ignore_index=True)
    else:
        events_df = new_events
    notifications_df = frame_for_entity("Notification", notification_rows)
    return {
        "inventory_plans": inventory_plans,
        "production_orders": production_df,
        "production_order_line": allocation_df,
        "production_order_impact": impacts_df,
        "notifications": notifications_df,
        "notification_recipient": pd.DataFrame(recipient_rows, columns=["notification_id", "actor_role", "recipient_actor_id"]),
        "entity_event": events_df,
    }
