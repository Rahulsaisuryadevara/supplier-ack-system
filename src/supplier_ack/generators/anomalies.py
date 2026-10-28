"""Post-baseline labelled anomaly injection and separated ground-truth generation.

This module deliberately runs only AFTER the clean baseline has passed schema and
reconciliation gates. Injected records retain internal labels but those label fields
are removed by the export writer so they cannot leak into model/input features.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd
from numpy.random import Generator

from supplier_ack.rules.thresholds import evaluate_threshold, computed_delta

EDGE_TYPES = (
    "UNAPPROVED_CHANGE_UPDATES_PLAN",
    "ACK_WRONG_PO_LINE",
    "PROMISE_DATE_BEFORE_ORDER_DATE",
    "STALE_REVISION_OVERWRITE",
)

GT_COLUMNS = [
    "record_type", "record_id", "issue_type", "expected_decision",
    "related_entity_ids", "expected_severity", "notes", "boundary",
]


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return value is None


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.to_dict(orient="records") if isinstance(frame, pd.DataFrame) else []


def _idx_by_value(frame: pd.DataFrame, column: str, value: Any) -> Any | None:
    matches = frame.index[frame[column].astype(str).eq(str(value))]
    return matches[0] if len(matches) else None


def _set_internal_label(frame: pd.DataFrame, index: Any, issue_type: str) -> None:
    frame.at[index, "issue_type"] = issue_type
    frame.at[index, "ground_truth"] = True


def _gt(record_type: str, record_id: Any, issue_type: str | None, expected: str,
        related: Mapping[str, Any], severity: str, notes: str, boundary: bool = False) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "record_id": str(record_id),
        "issue_type": issue_type,
        "expected_decision": expected,
        "related_entity_ids": json.dumps(dict(related), sort_keys=True, separators=(",", ":")),
        "expected_severity": severity,
        "notes": notes,
        "boundary": bool(boundary),
    }


def _mark_boundaries(frames: dict[str, pd.DataFrame], config: Mapping[str, Any], rng: Generator,
                     ground_truth: list[dict[str, Any]]) -> None:
    """Materialize exact threshold examples in existing source-value rows.

    The boundary rows are not anomalies: issue_type stays NULL and ground_truth
    stays False. Their boundary=True label is kept only in internal state and the
    separate ground-truth file.
    """
    thresholds = config.get("approval_thresholds", {})
    wanted = config.get("anomaly_injection", {}).get("boundary_cases", {})

    # Exact quantity boundary: full acceptance, accepted_qty == requested_qty.
    ack_lines = frames["acknowledgement_lines"]
    exact_qty = ack_lines.loc[
        (pd.to_numeric(ack_lines["accepted_qty"], errors="coerce") - pd.to_numeric(ack_lines["requested_qty"], errors="coerce")).abs() < 0.0005
    ]
    qty_count = int(wanted.get("accepted_qty_equals_requested", 1))
    if qty_count and not exact_qty.empty:
        candidates = exact_qty.iloc[rng.permutation(len(exact_qty))[:qty_count]]
        for row in candidates.to_dict(orient="records"):
            ground_truth.append(_gt(
                "AcknowledgementLine", row["acknowledgement_line_id"], None,
                "accept acknowledgement line as full acceptance; accepted quantity equals requested quantity",
                {"ack_id": row["ack_id"], "po_id": row["po_id"], "po_line_id": row["po_line_id"]},
                "NONE", "Boundary case: accepted_qty equals requested_qty exactly.", True,
            ))

    changes = frames["change_requests"]
    approvals = frames["approvals"]
    approvals_by_change: dict[str, list[dict[str, Any]]] = {}
    for approval in _records(approvals):
        approvals_by_change.setdefault(str(approval.get("change_request_id")), []).append(approval)

    def planner_approved_candidates(kind: str) -> list[dict[str, Any]]:
        result = []
        for row in _records(changes.loc[changes["change_type"].astype(str).str.lower().eq(kind)]):
            relevant = approvals_by_change.get(str(row["change_request_id"]), [])
            planner_ok = any(str(a.get("approval_level")) == "planner" and str(a.get("status")) == "APPROVED" for a in relevant)
            if row.get("required_approval_level") == "planner" and planner_ok:
                result.append(row)
        return result

    # Exact positive/negative price thresholds. Source old/new fields are adjusted
    # together and all delta/routing fields are recomputed using the shared rule.
    price_count_pos = int(wanted.get("price_delta_plus_threshold", 1))
    price_count_neg = int(wanted.get("price_delta_minus_threshold", 1))
    price_candidates = planner_approved_candidates("price")
    if len(price_candidates) < price_count_pos + price_count_neg:
        raise ValueError("not enough planner-approved price changes to build exact +/- threshold boundary rows")
    permuted_price = [price_candidates[i] for i in rng.permutation(len(price_candidates))]
    price_targets = [(row, 1) for row in permuted_price[:price_count_pos]] + [
        (row, -1) for row in permuted_price[price_count_pos:price_count_pos + price_count_neg]
    ]
    for row, sign in price_targets:
        idx = _idx_by_value(changes, "change_request_id", row["change_request_id"])
        if idx is None:
            continue
        old_value = 100.0
        new_value = old_value * (1.0 + sign * float(thresholds.get("price_change_pct", 5.0)) / 100.0)
        # Two-decimal prices at 100 make both +/- 5% exact.
        change = changes.loc[idx].to_dict()
        change.update({"old_value": f"{old_value:.2f}", "new_value": f"{new_value:.2f}"})
        delta = computed_delta("price", change["old_value"], change["new_value"])
        changes.at[idx, "old_value"] = change["old_value"]
        changes.at[idx, "new_value"] = change["new_value"]
        changes.at[idx, "previous_unit_price"] = old_value
        changes.at[idx, "requested_unit_price"] = new_value
        changes.at[idx, "delta"] = delta
        changes.at[idx, "delta_abs"] = abs(delta)
        changes.at[idx, "delta_pct"] = delta
        changes.at[idx, "required_approval_level"] = evaluate_threshold(change, thresholds)["required_approval_level"]
        # The approval history remains a valid planner approval because the threshold
        # is inclusive (|delta| <= configured threshold).
        ground_truth.append(_gt(
            "ChangeRequest", row["change_request_id"], None,
            f"planner approval is sufficient at the exact {'+' if sign > 0 else '-'}{float(thresholds.get('price_change_pct', 5.0)):g}% price threshold",
            {"po_id": row["po_id"], "po_line_id": row.get("po_line_id"), "change_request_id": row["change_request_id"]},
            "NONE", "Boundary case: signed price delta is exactly at the inclusive threshold.", True,
        ))

    # Exact date threshold: the ChangeRequest's source dates yield the configured day count.
    date_count = int(wanted.get("slip_days_equals_threshold", 1))
    date_candidates = planner_approved_candidates("date")
    if date_count and not date_candidates:
        raise ValueError("not enough planner-approved date changes to build exact date threshold boundary row")
    for row in [date_candidates[i] for i in rng.permutation(len(date_candidates))[:date_count]]:
        idx = _idx_by_value(changes, "change_request_id", row["change_request_id"])
        if idx is None:
            continue
        po_line = _records(frames["po_lines"].loc[frames["po_lines"]["po_line_id"].astype(str).eq(str(row.get("po_line_id")))])
        baseline_date = str(po_line[0]["required_date"])[:10] if po_line else str(row.get("previous_promised_date"))[:10]
        new_date = (date.fromisoformat(baseline_date) + timedelta(days=int(float(thresholds.get("date_slip_days", 7))))).isoformat()
        changes.at[idx, "old_value"] = baseline_date
        changes.at[idx, "new_value"] = new_date
        changes.at[idx, "previous_promised_date"] = baseline_date
        changes.at[idx, "requested_promised_date"] = new_date
        changes.at[idx, "delta"] = float(thresholds.get("date_slip_days", 7))
        changes.at[idx, "delta_abs"] = abs(float(thresholds.get("date_slip_days", 7)))
        changes.at[idx, "delta_pct"] = np.nan
        changes.at[idx, "required_approval_level"] = evaluate_threshold(changes.loc[idx].to_dict(), thresholds)["required_approval_level"]
        ground_truth.append(_gt(
            "ChangeRequest", row["change_request_id"], None,
            "planner approval is sufficient at the exact inclusive date-slip threshold",
            {"po_id": row["po_id"], "po_line_id": row.get("po_line_id"), "change_request_id": row["change_request_id"]},
            "NONE", f"Boundary case: date slip is exactly {int(float(thresholds.get('date_slip_days', 7)))} days.", True,
        ))


def _inject_unapproved_plan_updates(frames: dict[str, pd.DataFrame], count: int, rng: Generator,
                                    ground_truth: list[dict[str, Any]]) -> int:
    changes, approvals, plans, lines = (frames[k] for k in ("change_requests", "approvals", "inventory_plans", "po_lines"))
    approved_ids = set(approvals.loc[approvals["status"].astype(str).eq("APPROVED"), "change_request_id"].astype(str))
    candidates = changes.loc[~changes["change_request_id"].astype(str).isin(approved_ids)]
    pairs: list[tuple[dict[str, Any], str]] = []
    line_rows = _records(lines)
    line_by_id = {str(line["po_line_id"]): line for line in line_rows}
    line_ids_by_po: dict[str, list[str]] = {}
    for line in line_rows:
        line_ids_by_po.setdefault(str(line["po_id"]), []).append(str(line["po_line_id"]))
    for change in _records(candidates):
        own_line = change.get("po_line_id")
        possible = [str(own_line)] if not _is_missing(own_line) and str(own_line) in line_by_id else line_ids_by_po.get(str(change["po_id"]), [])
        for line_id in possible:
            pairs.append((change, line_id))
    # one injected request per line prevents unrelated version rows from being rewritten
    rng_order = rng.permutation(len(pairs)) if pairs else []
    used_lines: set[str] = set()
    chosen: list[tuple[dict[str, Any], str]] = []
    used_changes: set[str] = set()
    for pos in rng_order:
        change, line_id = pairs[int(pos)]
        if line_id in used_lines or str(change["change_request_id"]) in used_changes:
            continue
        chosen.append((change, line_id)); used_lines.add(line_id); used_changes.add(str(change["change_request_id"]))
        if len(chosen) >= count:
            break
    if len(chosen) != count:
        raise ValueError(f"configured UNAPPROVED_CHANGE_UPDATES_PLAN count={count}, only {len(chosen)} eligible line/change pairs")

    rows_to_append = []
    for n, (change, line_id) in enumerate(chosen, 1):
        line = _records(lines.loc[lines["po_line_id"].astype(str).eq(line_id)])[0]
        versions = plans.loc[plans["po_line_id"].astype(str).eq(line_id)].sort_values("plan_version")
        current = versions.iloc[-1].to_dict()
        current_idx = versions.index[-1]
        version = int(current["plan_version"]) + 1
        new_id = f"IP-{line_id}-{version:02d}"
        plans.at[current_idx, "is_effective"] = 0
        plans.at[current_idx, "status"] = "SUPERSEDED"
        plans.at[current_idx, "superseded_by"] = new_id
        row = dict(current)
        row.update({
            "inventory_plan_id": new_id, "plan_revision_no": version, "plan_version": version,
            "previous_version_id": current["inventory_plan_id"], "source": "approved_change",
            "is_effective": 1, "change_request_id": change["change_request_id"], "status": "ACTIVE",
            "superseded_by": None, "created_at": str(change.get("updated_at") or current["created_at"]),
            "updated_at": str(change.get("updated_at") or current["updated_at"]),
            "issue_type": "UNAPPROVED_CHANGE_UPDATES_PLAN", "ground_truth": True,
        })
        # Apply the unapproved requested value to make the defect concrete.
        if str(change.get("change_type")).lower() == "quantity" and not _is_missing(change.get("requested_qty")):
            row["projected_qty"] = float(change["requested_qty"])
            row["promised_qty"] = float(change["requested_qty"])
        if str(change.get("change_type")).lower() == "date" and not _is_missing(change.get("requested_promised_date")):
            row["projected_delivery_date"] = str(change["requested_promised_date"])
            row["promised_date"] = str(change["requested_promised_date"])
        rows_to_append.append(row)
        ground_truth.append(_gt(
            "InventoryPlan", new_id, "UNAPPROVED_CHANGE_UPDATES_PLAN",
            "plan version must be reverted; only retain the prior approved effective version",
            {"inventory_plan_id": new_id, "previous_version_id": current["inventory_plan_id"],
             "change_request_id": change["change_request_id"], "po_id": line["po_id"], "po_line_id": line_id},
            "CRITICAL", "A new approved_change projection was created without any Approval row with status APPROVED.",
        ))
    frames["inventory_plans"] = pd.concat([plans, pd.DataFrame(rows_to_append)], ignore_index=True)
    return len(rows_to_append)


def _inject_wrong_ack_lines(frames: dict[str, pd.DataFrame], count: int, rng: Generator,
                            seed: int, ground_truth: list[dict[str, Any]]) -> int:
    ack_lines, lines = frames["acknowledgement_lines"], frames["po_lines"]
    base_rows, all_lines = _records(ack_lines), _records(lines)
    if count and not base_rows:
        raise ValueError("cannot inject ACK_WRONG_PO_LINE because acknowledgement_lines is empty")
    indexes = list(map(int, rng.permutation(len(base_rows))[:min(count, len(base_rows))]))
    additions = []
    for n in range(count):
        base = dict(base_rows[indexes[n % len(indexes)]])
        parent_po = str(base["po_id"])
        mode = "cross_po" if n % 2 == 0 else "missing_line"
        if mode == "cross_po":
            foreign = [line for line in all_lines if str(line["po_id"]) != parent_po]
            if not foreign:
                mode = "missing_line"
            else:
                other = foreign[int(rng.integers(0, len(foreign)))]
                base["po_line_id"] = str(other["po_line_id"])
        if mode == "missing_line":
            base["po_line_id"] = "PO-2026-999999-L99"
        record_id = f"AL-EDGE-{seed:010d}-{n + 1:06d}"
        base["acknowledgement_line_id"] = record_id
        base["issue_type"] = "ACK_WRONG_PO_LINE"
        base["ground_truth"] = True
        additions.append(base)
        expected = "reject acknowledgement line as invalid reference; do not repair by silently changing the PO"
        notes = "Cross-PO line reference: referenced PO line belongs to a different purchase order." if mode == "cross_po" else "Non-existent PO-line reference: target line ID is absent from POLine."
        ground_truth.append(_gt(
            "AcknowledgementLine", record_id, "ACK_WRONG_PO_LINE", expected,
            {"ack_id": base["ack_id"], "po_id": base["po_id"], "po_line_id": base["po_line_id"], "reference_variant": mode},
            "HIGH", notes,
        ))
    frames["acknowledgement_lines"] = pd.concat([ack_lines, pd.DataFrame(additions)], ignore_index=True)
    return len(additions)


def _inject_promise_before_order(frames: dict[str, pd.DataFrame], count: int, rng: Generator,
                                 seed: int, ground_truth: list[dict[str, Any]]) -> int:
    promises, pos = frames["promise_dates"], frames["purchase_orders"]
    po_order = {str(r["po_id"]): str(r["order_date"])[:10] for r in _records(pos)}
    line_required = {str(r["po_line_id"]): str(r["required_date"])[:10] for r in _records(frames["po_lines"])}
    base = _records(promises)
    if count and not base:
        raise ValueError("cannot inject PROMISE_DATE_BEFORE_ORDER_DATE because PromiseDate is empty")
    indexes = list(map(int, rng.permutation(len(base))[:min(count, len(base))]))
    additions = []
    for n in range(count):
        row = dict(base[indexes[n % len(indexes)]])
        order_day = date.fromisoformat(po_order[str(row["po_id"])])
        invalid_day = order_day - timedelta(days=1 + (n % 5))
        row["promise_date_id"] = f"PD-EDGE-{seed:010d}-{n + 1:06d}"
        row["sequence_no"] = int(row.get("sequence_no") or 1) + 1000 + n
        row["promised_date"] = invalid_day.isoformat()
        row["slip_days"] = (invalid_day - date.fromisoformat(line_required[str(row["po_line_id"])] )).days
        row["is_late"] = bool(row["slip_days"] > 0)
        row["status"] = "PROPOSED"
        row["superseded_by"] = None
        row["issue_type"] = "PROMISE_DATE_BEFORE_ORDER_DATE"
        row["ground_truth"] = True
        additions.append(row)
        ground_truth.append(_gt(
            "PromiseDate", row["promise_date_id"], "PROMISE_DATE_BEFORE_ORDER_DATE",
            "flag promise date invalid and reject the promise until a date on/after PO order_date is supplied",
            {"promise_date_id": row["promise_date_id"], "ack_id": row["ack_id"], "po_id": row["po_id"],
             "po_line_id": row["po_line_id"], "order_date": po_order[str(row["po_id"])], "promised_date": invalid_day.isoformat()},
            "HIGH", "The promised delivery date occurs before its parent PO was ordered.",
        ))
    frames["promise_dates"] = pd.concat([promises, pd.DataFrame(additions)], ignore_index=True)
    return len(additions)


def _inject_stale_revisions(frames: dict[str, pd.DataFrame], count: int, rng: Generator,
                            ground_truth: list[dict[str, Any]]) -> int:
    promises = frames["promise_dates"]
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for line_id, group in promises.loc[~promises["promise_date_id"].astype(str).str.startswith("PD-EDGE-")].groupby("po_line_id", sort=True):
        if group["revision_no"].nunique() < 2:
            continue
        ordered = group.sort_values(["revision_no", "created_at"])
        older, newer = ordered.iloc[0].to_dict(), ordered.iloc[-1].to_dict()
        if int(older["revision_no"]) >= int(newer["revision_no"]):
            continue
        candidates.append((str(line_id), older, newer))
    if len(candidates) < count:
        raise ValueError(f"configured STALE_REVISION_OVERWRITE count={count}, only {len(candidates)} multi-revision PO lines exist")
    order = rng.permutation(len(candidates))[:count]
    for n in order:
        line_id, older, newer = candidates[int(n)]
        old_idx = _idx_by_value(promises, "promise_date_id", older["promise_date_id"])
        new_idx = _idx_by_value(promises, "promise_date_id", newer["promise_date_id"])
        promises.at[old_idx, "status"] = "CURRENT"
        promises.at[old_idx, "superseded_by"] = None
        promises.at[old_idx, "issue_type"] = "STALE_REVISION_OVERWRITE"
        promises.at[old_idx, "ground_truth"] = True
        promises.at[new_idx, "status"] = "SUPERSEDED"
        promises.at[new_idx, "superseded_by"] = older["promise_date_id"]
        ground_truth.append(_gt(
            "PromiseDate", older["promise_date_id"], "STALE_REVISION_OVERWRITE",
            "newer revision must win; restore the highest revision_no as CURRENT and supersede the older revision",
            {"po_id": older["po_id"], "po_line_id": line_id, "effective_promise_date_id": older["promise_date_id"],
             "stale_revision_no": int(older["revision_no"]), "newer_promise_date_id": newer["promise_date_id"],
             "newer_revision_no": int(newer["revision_no"])},
            "HIGH", "An earlier timestamp/lower revision is incorrectly marked CURRENT while a newer revision exists.",
        ))
    frames["promise_dates"] = promises
    return int(count)


def _append_expected_decisions(frames: Mapping[str, pd.DataFrame], thresholds: Mapping[str, Any],
                               ground_truth: list[dict[str, Any]]) -> None:
    approvals = frames["approvals"]
    approvals_by_change: dict[str, list[dict[str, Any]]] = {}
    for approval in _records(approvals):
        approvals_by_change.setdefault(str(approval.get("change_request_id")), []).append(approval)
    for change in _records(frames["change_requests"]):
        try:
            rule = evaluate_threshold(change, thresholds)
        except (ValueError, TypeError, KeyError):
            rule = {"required_approval_level": change.get("required_approval_level", "planner"), "hard_limit_breach": False, "within_threshold": True}
        rows = approvals_by_change.get(str(change["change_request_id"]), [])
        required = str(rule["required_approval_level"])
        level_rows = [r for r in rows if str(r.get("approval_level")) == required]
        latest = max(level_rows, key=lambda r: (int(r.get("approval_round") or 0), str(r.get("decided_at") or ""))) if level_rows else None
        if rule.get("hard_limit_breach"):
            expected, severity = "reject change under hard policy limit", "CRITICAL"
        elif latest and str(latest.get("status")) == "REJECTED":
            expected, severity = "reject change; do not update projected supply", "HIGH"
        elif latest and str(latest.get("status")) == "APPROVED":
            expected, severity = "approve at required level and permit application", "LOW"
        elif latest and str(latest.get("status")) in {"ESCALATED", "PENDING"}:
            expected, severity = ("escalate to operations_manager" if required == "operations_manager" else "await planner decision"), "MEDIUM"
        else:
            expected, severity = ("escalate to operations_manager" if required == "operations_manager" else "await planner decision"), "MEDIUM"
        ground_truth.append(_gt(
            "ChangeRequest", change["change_request_id"], None, expected,
            {"change_request_id": change["change_request_id"], "po_id": change["po_id"],
             "po_line_id": None if _is_missing(change.get("po_line_id")) else change.get("po_line_id"),
             "required_approval_level": required, "computed_delta": rule.get("delta")},
            severity, f"Normal ground-truth decision derived from thresholds: required level={required}; hard_limit_breach={rule.get('hard_limit_breach', False)}.",
        ))

    if "production_order_impact" not in frames or frames["production_order_impact"].empty:
        return
    impacts_by_order = frames["production_order_impact"].groupby("production_order_id")
    orders = frames["production_orders"]
    for production_order_id, group in impacts_by_order:
        matches = orders.loc[orders["production_order_id"].astype(str).eq(str(production_order_id))]
        if matches.empty:
            continue
        order = matches.iloc[0].to_dict()
        severities = sorted(set(group["severity"].astype(str)))
        ground_truth.append(_gt(
            "ProductionOrder", production_order_id, None,
            f"production order status should be {str(order['status']).lower()}",
            {"production_order_id": production_order_id, "po_id": order["po_id"], "po_line_id": order["po_line_id"],
             "change_request_ids": sorted(set(group["change_request_id"].astype(str)))},
            ",".join(severities) if severities else "NONE",
            "Expected downstream status is derived from the recorded date-conflict/quantity-shortfall impacts.",
        ))


def inject_labelled_edge_cases(frames: dict[str, pd.DataFrame], cfg: Mapping[str, Any], scale: str,
                               rng: Generator, seed: int) -> dict[str, pd.DataFrame]:
    """Inject the configured, labelled edge-case cohorts after baseline validation.

    Mutation is deterministic for a fixed seed. The passed RNG is the same seeded
    generator used by baseline generation, continuing its stream without reseeding.
    """
    config = cfg.get("anomaly_injection", {})
    if not config.get("enabled", True):
        frames["ground_truth_records"] = pd.DataFrame(columns=GT_COLUMNS)
        return frames
    counts = config.get("counts", {}).get(scale, {})
    for issue_type in EDGE_TYPES:
        if issue_type not in counts:
            raise ValueError(f"anomaly_injection.counts.{scale} missing {issue_type}")
    # Clear legacy labels created by pre-existing generator internals: only the new,
    # explicit pipeline stage is allowed to label anomaly rows. JSON event snapshots
    # are scrubbed as well to prevent label leakage via payload/state columns.
    for key, frame in list(frames.items()):
        if not isinstance(frame, pd.DataFrame):
            continue
        if "issue_type" in frame.columns:
            frame["issue_type"] = None
        if "ground_truth" in frame.columns:
            frame["ground_truth"] = False
        if key == "entity_event":
            for col in ("payload_json", "previous_state", "new_state"):
                if col not in frame.columns:
                    continue
                def scrub(raw: Any) -> Any:
                    if _is_missing(raw):
                        return raw
                    try:
                        data = json.loads(str(raw))
                    except (ValueError, TypeError):
                        return raw
                    def walk(obj: Any) -> Any:
                        if isinstance(obj, dict):
                            return {k: walk(v) for k, v in obj.items() if k not in {"issue_type", "ground_truth"}}
                        if isinstance(obj, list):
                            return [walk(v) for v in obj]
                        return obj
                    return json.dumps(walk(data), sort_keys=True, separators=(",", ":"))
                frame[col] = frame[col].map(scrub)
            frame.attrs["label_keys_scrubbed"] = True

    ground_truth: list[dict[str, Any]] = []
    _mark_boundaries(frames, cfg, rng, ground_truth)
    injected = {
        EDGE_TYPES[0]: _inject_unapproved_plan_updates(frames, int(counts[EDGE_TYPES[0]]), rng, ground_truth),
        EDGE_TYPES[1]: _inject_wrong_ack_lines(frames, int(counts[EDGE_TYPES[1]]), rng, seed, ground_truth),
        EDGE_TYPES[2]: _inject_promise_before_order(frames, int(counts[EDGE_TYPES[2]]), rng, seed, ground_truth),
        EDGE_TYPES[3]: _inject_stale_revisions(frames, int(counts[EDGE_TYPES[3]]), rng, ground_truth),
    }
    _append_expected_decisions(frames, cfg.get("approval_thresholds", {}), ground_truth)
    frames["ground_truth_records"] = pd.DataFrame(ground_truth, columns=GT_COLUMNS)
    frames["injection_summary"] = pd.DataFrame([
        {"issue_type": issue_type, "injected_count": count, "scale": scale, "seed": seed}
        for issue_type, count in injected.items()
    ])
    return frames
