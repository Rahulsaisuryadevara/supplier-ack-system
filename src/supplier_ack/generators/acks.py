"""Seeded supplier acknowledgement, promise-date, revision, and silence generation."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import warnings
from typing import Any, Mapping

import numpy as np
import pandas as pd
from numpy.random import Generator

from supplier_ack.generators.common import active_scale_config, at_utc, frame_for_entity, get_config, require_rng
from supplier_ack.ids import IDFactory
from supplier_ack.rules.derived import acknowledgement_status_value, compute_percent_delta, derive_promise_date
from supplier_ack.schema import ACKNOWLEDGEMENT_LINE_FIELDS

_CENT = Decimal("0.01")
_QTY = Decimal("0.001")
_REJECTION_REASONS = ("capacity", "price", "stock", "logistics")


def _decimal(value: Any, quantum: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _money(quantity: Any, unit_price: Any) -> float:
    return float((_decimal(quantity, _QTY) * _decimal(unit_price, _CENT)).quantize(_CENT, rounding=ROUND_HALF_UP))


def _rounded_count(total: int, proportion: float) -> int:
    return int(np.floor(total * proportion + 0.5))


def _business_day_on_or_after(day: date) -> date:
    """Round a calendar date forward to Monday-Friday."""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _business_day_on_or_before(day: date) -> date:
    """Round a calendar date backward to Monday-Friday."""
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _sample_response_day(
    rng: Generator,
    po: Mapping[str, Any],
    supplier: Mapping[str, Any],
    response_cfg: Mapping[str, Any],
) -> date:
    """Sample a supplier-profile-driven response date, including late responses."""
    order_day = date.fromisoformat(str(po["order_date"]))
    due_day = datetime.fromisoformat(str(po["response_due_at"]).replace("Z", "+00:00")).date()
    required_day = date.fromisoformat(str(po["required_delivery_date"]))
    reliability = float(supplier["reliability_score"])
    fast_threshold = float(response_cfg.get("fast_supplier_reliability_threshold", 0.75))
    late_base = float(response_cfg.get("late_probability_base", 0.10))
    late_effect = float(response_cfg.get("late_probability_reliability_effect", 0.30))
    late_probability = _clamp(late_base + late_effect * (1.0 - reliability), 0.0, 0.85)

    if float(rng.random()) < late_probability:
        minimum = int(response_cfg.get("late_min_days_after_due", 1))
        maximum = int(response_cfg.get("late_max_days_after_due", 5))
        if minimum < 1 or maximum < minimum:
            raise ValueError("supplier_response late-day range must satisfy 1 <= min <= max")
        sampled = due_day + timedelta(days=int(rng.integers(minimum, maximum + 1)))
        candidate = _business_day_on_or_after(sampled)
    elif reliability >= fast_threshold:
        minimum = int(response_cfg.get("fast_delay_min_days", 1))
        maximum = int(response_cfg.get("fast_delay_max_days", 3))
        alpha = float(response_cfg.get("fast_delay_beta_alpha", 2.2))
        beta = float(response_cfg.get("fast_delay_beta_beta", 2.0))
        if minimum < 1 or maximum < minimum or alpha <= 0 or beta <= 0:
            raise ValueError("supplier_response fast-delay distribution is invalid")
        delay = minimum + int(round(float(rng.beta(alpha, beta)) * (maximum - minimum)))
        candidate = _business_day_on_or_after(order_day + timedelta(days=delay))
    else:
        mean = float(response_cfg.get("slow_delay_lognormal_mean", 0.55))
        sigma = float(response_cfg.get("slow_delay_lognormal_sigma", 0.35))
        if mean < 0 or sigma <= 0:
            raise ValueError("supplier_response slow-delay lognormal parameters are invalid")
        days_before_due = max(0, int(round(float(rng.lognormal(mean, sigma)))) - 1)
        gap = max(1, (due_day - order_day).days)
        days_before_due = min(days_before_due, gap - 1)
        candidate = _business_day_on_or_before(due_day - timedelta(days=days_before_due))

    # A supplier response cannot occur on/after the requested delivery day in the
    # clean baseline. Such a case would be a separate labelled anomaly scenario.
    response_cap = _business_day_on_or_before(required_day - timedelta(days=1))
    if response_cap < order_day:
        response_cap = _business_day_on_or_after(order_day + timedelta(days=1))
    return min(max(candidate, _business_day_on_or_after(order_day + timedelta(days=1))), response_cap)


def _signed_percent(numerator_delta: Decimal, denominator: Decimal) -> float:
    if denominator == 0:
        return 0.0
    return float((Decimal("100") * numerator_delta / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


_EVENT_COLUMNS = [
    "event_id", "entity_type", "entity_id", "event_type", "event_timestamp",
    "actor_role", "actor_id", "payload_json", "previous_state", "new_state",
    "issue_type", "ground_truth", "target_supplier_id", "target_po_id",
    "target_po_line_id", "target_ack_id", "target_promise_date_id",
    "target_change_request_id", "target_approval_id", "target_inventory_plan_id",
    "target_production_order_id", "target_notification_id",
]


def _weighted_rank(
    rng: Generator,
    records: list[dict[str, Any]],
    target_count: int,
    score_function,
) -> list[dict[str, Any]]:
    if target_count <= 0 or not records:
        return []
    scores = [(float(score_function(row)) + float(rng.normal(0.0, 1e-9)), index, row) for index, row in enumerate(records)]
    scores.sort(key=lambda item: item[0], reverse=True)
    chosen_indices = {index for _, index, _ in scores[:min(target_count, len(scores))]}
    return [row for index, row in enumerate(records) if index in chosen_indices]


def generate_acknowledgements_and_promises(
    rng: Generator,
    cfg: Mapping[str, Any],
    purchase_orders: pd.DataFrame,
    po_lines: pd.DataFrame,
    suppliers: pd.DataFrame,
    actors: pd.DataFrame,
    id_factory: IDFactory | None = None,
    *,
    warehouses: pd.DataFrame | None = None,
    carriers: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Generate every ACK revision, line-level PromiseDate revision, and silence report.

    Outcomes are targeted by configured proportions while ranking supplier/PO risk so
    low-reliability suppliers and large quantities are more likely to be partial or late.
    The input frames are not mutated; updated current-state PO and line frames are returned.
    """
    require_rng(rng)
    if purchase_orders.empty or po_lines.empty or suppliers.empty:
        raise ValueError("suppliers, purchase_orders, and po_lines must be generated first")
    factory = id_factory or IDFactory()
    coverage_cfg = get_config(cfg, "coverage", default={})
    target_cfg = coverage_cfg.get("target_proportions", {})
    outcome_cfg = coverage_cfg.get("acknowledgement_outcomes", {})
    revision_cfg = coverage_cfg.get("acknowledgement_revisions", {})
    promise_cfg = coverage_cfg.get("promise_dates", {})
    price_cfg = coverage_cfg.get("price_changes", {})
    order_cfg = get_config(cfg, "distributions", "order_calendar", default={})
    response_cfg = get_config(cfg, "distributions", "supplier_response", default={})
    as_of = date.fromisoformat(str(coverage_cfg.get("as_of_date", "2026-10-28")))

    po_rows = purchase_orders.to_dict(orient="records")
    po_by_id = {str(row["po_id"]): row for row in po_rows}
    line_rows = po_lines.to_dict(orient="records")
    supplier_map = {str(row["supplier_id"]): row for row in suppliers.to_dict(orient="records")}
    warehouse_rows = warehouses.to_dict(orient="records") if warehouses is not None else []
    carrier_rows = carriers.to_dict(orient="records") if carriers is not None else []
    warehouse_by_id = {str(row["warehouse_id"]): row for row in warehouse_rows}
    carrier_by_id = {str(row["carrier_id"]): row for row in carrier_rows}
    carrier_operators = [row for row in actors.to_dict(orient="records") if row.get("actor_role") == "carrier_warehouse_operator"]
    if not warehouse_rows or not carrier_rows or not carrier_operators:
        raise ValueError("promise generation requires warehouse, carrier, and carrier_warehouse_operator master rows")
    lines_by_po: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_line in line_rows:
        line = dict(source_line)
        line["requested_qty"] = float(line["requested_qty"])
        line["unit_price"] = float(line["unit_price"])
        lines_by_po[str(line["po_id"])].append(line)

    po_total_qty: dict[str, float] = {
        po_id: sum(float(line["requested_qty"]) for line in rows)
        for po_id, rows in lines_by_po.items()
    }
    log_qtys = [float(np.log1p(po_total_qty.get(str(po["po_id"]), 0.0))) for po in po_rows]
    log_center = float(np.mean(log_qtys)) if log_qtys else 0.0
    log_sd = float(np.std(log_qtys)) if len(log_qtys) > 1 else 1.0
    log_sd = log_sd if log_sd > 1e-12 else 1.0

    po_risk: dict[str, float] = {}
    for po, log_qty in zip(po_rows, log_qtys):
        supplier = supplier_map[str(po["supplier_id"])]
        reliability = float(supplier["reliability_score"])
        size_z = (log_qty - log_center) / log_sd
        po_risk[str(po["po_id"])] = (
            0.76 * (1.0 - reliability)
            + 0.20 * size_z
            + float(rng.normal(0.0, float(outcome_cfg.get("risk_noise_sd", 0.12))))
        )

    # The reporting date makes silence an observable overdue exception, not a fake ACK.
    silence_prop = float(target_cfg.get("supplier_silence", 0.05))
    silence_count = min(len(po_rows), _rounded_count(len(po_rows), silence_prop))
    ranked_po = sorted(po_rows, key=lambda row: po_risk[str(row["po_id"])], reverse=True)
    silence_ids = {str(row["po_id"]) for row in ranked_po[:silence_count]}
    responding_pos = [row for row in po_rows if str(row["po_id"]) not in silence_ids]

    # Assign 2–4 total ACK rows (including the first) to a configured share of all POs.
    revision_prop = float(target_cfg.get("multiple_revisions", 0.08))
    revision_po_target = _rounded_count(len(po_rows), revision_prop)
    if revision_po_target > len(responding_pos):
        warnings.warn(
            f"multiple-revision target ({revision_po_target} POs) exceeds responding POs ({len(responding_pos)}); clipping to feasible population",
            RuntimeWarning,
            stacklevel=2,
        )
        revision_po_target = len(responding_pos)
    revision_candidates = sorted(responding_pos, key=lambda row: po_risk[str(row["po_id"])], reverse=True)
    revision_po_order = [str(row["po_id"]) for row in revision_candidates[:revision_po_target]]
    revision_po_ids = set(revision_po_order)
    revision_prob_cfg = revision_cfg.get("count_probabilities", {2: 0.50, 3: 0.35, 4: 0.15})
    revision_values = [int(key) for key in revision_prob_cfg]
    revision_probs = np.asarray([float(revision_prob_cfg[key]) for key in revision_prob_cfg], dtype=float)
    if not len(revision_values) or np.any(revision_probs < 0) or abs(float(revision_probs.sum()) - 1.0) > 1e-8:
        raise ValueError("coverage.acknowledgement_revisions.count_probabilities must be nonnegative and sum to 1")
    revisions_by_po: dict[str, int] = {str(po["po_id"]): 1 for po in responding_pos}
    min_revs = int(revision_cfg.get("min_revisions", min(revision_values)))
    max_revs = int(revision_cfg.get("max_revisions", max(revision_values)))
    if min_revs < 2 or max_revs > 99 or min_revs > max_revs:
        raise ValueError("acknowledgement revision range must satisfy 2 <= min <= max <= 99")
    # RNG consumption follows a stable PO order; iterating revision_po_ids itself
    # would make output depend on the process-randomized hash seed.
    for po_id in revision_po_order:
        sampled = int(rng.choice(revision_values, p=revision_probs))
        revisions_by_po[po_id] = min(max(sampled, min_revs), max_revs)

    # Outcome shares are conditional on POs that actually received a response.
    n_response = len(responding_pos)
    outcome_props = [
        float(target_cfg.get("partial_acceptance", 0.22)),
        float(target_cfg.get("full_acceptance", 0.70)),
        float(target_cfg.get("full_rejection", 0.08)),
    ]
    if any(value < 0 or value > 1 for value in outcome_props):
        raise ValueError("acknowledgement outcome proportions must be in [0, 1]")
    prop_sum = sum(outcome_props)
    if abs(prop_sum - 1.0) > 1e-8:
        raise ValueError("partial_acceptance + full_acceptance + full_rejection proportions must sum to 1")
    partial_count = _rounded_count(n_response, outcome_props[0])
    reject_count = _rounded_count(n_response, outcome_props[2])
    if partial_count + reject_count > n_response:
        reject_count = n_response - partial_count
    full_count = n_response - partial_count - reject_count

    # Exact outcome counts with risk-ranked assignment rather than independent labels.
    ranked_response = sorted(responding_pos, key=lambda row: po_risk[str(row["po_id"])], reverse=True)
    outcome_by_po: dict[str, str] = {}
    for idx, po in enumerate(ranked_response):
        po_id = str(po["po_id"])
        if idx < reject_count:
            outcome_by_po[po_id] = "REJECTED"
        elif idx < reject_count + partial_count:
            outcome_by_po[po_id] = "PARTIALLY_ACCEPTED"
        else:
            outcome_by_po[po_id] = "ACCEPTED"

    reason_weights = outcome_cfg.get("rejection_reason_weights", {"capacity": .34, "price": .14, "stock": .34, "logistics": .18})
    reason_labels = list(reason_weights)
    reason_probs = np.asarray([float(reason_weights[key]) for key in reason_labels], dtype=float)
    if set(reason_labels) - set(_REJECTION_REASONS) or np.any(reason_probs < 0) or abs(float(reason_probs.sum()) - 1.0) > 1e-8:
        raise ValueError("rejection_reason_weights must use capacity/price/stock/logistics and sum to 1")

    # Decide line quantities. The partial acceptance ratio is beta-distributed and
    # falls as reliability worsens or quantity grows.
    accepted_by_line: dict[str, float] = {}
    rejected_by_line: dict[str, float] = {}
    reason_by_po: dict[str, str | None] = {}
    line_qty_log = {str(line["po_line_id"]): float(np.log1p(float(line["requested_qty"]))) for line in line_rows}
    log_line_values = list(line_qty_log.values())
    line_log_mean = float(np.mean(log_line_values)) if log_line_values else 0.0
    line_log_sd = float(np.std(log_line_values)) if len(log_line_values) > 1 else 1.0
    line_log_sd = line_log_sd if line_log_sd > 1e-12 else 1.0
    concentration = float(outcome_cfg.get("partial_acceptance_beta_concentration", 10.0))
    if concentration <= 0:
        raise ValueError("partial_acceptance_beta_concentration must be > 0")
    reliability_effect = float(outcome_cfg.get("reliability_effect", 0.25))
    large_effect = float(outcome_cfg.get("large_quantity_effect", 0.08))
    for po in po_rows:
        po_id = str(po["po_id"])
        requested_lines = lines_by_po[po_id]
        outcome = outcome_by_po.get(po_id)
        if outcome is None:
            reason_by_po[po_id] = None
            for line in requested_lines:
                accepted_by_line[str(line["po_line_id"])] = 0.0
                rejected_by_line[str(line["po_line_id"])] = 0.0  # silence is not a rejection
            continue
        rejection_reason = None if outcome == "ACCEPTED" else str(rng.choice(reason_labels, p=reason_probs))
        reason_by_po[po_id] = rejection_reason
        supplier = supplier_map[str(po["supplier_id"])]
        reliability = float(supplier["reliability_score"])
        for line in requested_lines:
            line_id = str(line["po_line_id"])
            requested = _decimal(line["requested_qty"], _QTY)
            if outcome == "ACCEPTED":
                accepted = requested
            elif outcome == "REJECTED":
                accepted = Decimal("0.000")
            else:
                z_qty = (line_qty_log[line_id] - line_log_mean) / line_log_sd
                mean_share = min(0.96, max(0.20, 0.80 + reliability_effect * (reliability - 0.65) - large_effect * z_qty))
                alpha = max(0.1, mean_share * concentration)
                beta = max(0.1, (1.0 - mean_share) * concentration)
                share = float(rng.beta(alpha, beta))
                accepted = (requested * Decimal(str(share))).quantize(_QTY, rounding=ROUND_HALF_UP)
                if accepted <= 0:
                    accepted = _QTY
                if accepted >= requested:
                    accepted = requested - _QTY
            rejected = (requested - accepted).quantize(_QTY, rounding=ROUND_HALF_UP)
            accepted_by_line[line_id] = float(accepted)
            rejected_by_line[line_id] = float(rejected)

    # Price changes are selected by weighted risk among lines with nonzero accepted quantity.
    accepted_lines = [line for line in line_rows if accepted_by_line[str(line["po_line_id"])] > 0.0]
    price_prop = float(target_cfg.get("price_changes", 0.06))
    price_target = min(len(accepted_lines), _rounded_count(len(accepted_lines), price_prop))
    total_ack_rows = sum(revisions_by_po.values())
    requested_events = int(active_scale_config(cfg)["event_count"])
    change_request_budget = requested_events - total_ack_rows
    if change_request_budget < 0:
        warnings.warn(
            f"event_count={requested_events} cannot contain {total_ack_rows} acknowledgement revision rows; generated event total will exceed target unless revision coverage is reduced",
            RuntimeWarning,
            stacklevel=2,
        )
        change_request_budget = 0
    if price_target > change_request_budget:
        warnings.warn(
            f"price-change target ({price_target} lines) exceeds change-request budget ({change_request_budget}); clipping price changes to event budget",
            RuntimeWarning,
            stacklevel=2,
        )
        price_target = change_request_budget
    def price_score(line: dict[str, Any]) -> float:
        po = po_by_id[str(line["po_id"])]
        supplier = supplier_map[str(po["supplier_id"])]
        z_qty = (line_qty_log[str(line["po_line_id"])] - line_log_mean) / line_log_sd
        return 0.58 * z_qty + 0.32 * (1.0 - float(supplier["reliability_score"])) + float(rng.normal(0.0, float(price_cfg.get("risk_noise_sd", 0.10))))

    price_changed = _weighted_rank(rng, accepted_lines, price_target, price_score)
    price_change_specs: list[dict[str, Any]] = []
    price_by_line: dict[str, float] = {}
    increase_probability = float(price_cfg.get("increase_probability", 0.78))
    min_pct = float(price_cfg.get("magnitude_min_pct", 0.5))
    max_pct = float(price_cfg.get("magnitude_max_pct", 15.0))
    beta_a = float(price_cfg.get("magnitude_beta_alpha", 2.0))
    beta_b = float(price_cfg.get("magnitude_beta_beta", 3.5))
    if not (0.0 <= increase_probability <= 1.0 and 0.0 < min_pct <= max_pct <= 15.0 and beta_a > 0 and beta_b > 0):
        raise ValueError("price change configuration is invalid")
    for line in line_rows:
        line_id = str(line["po_line_id"])
        price_by_line[line_id] = float(line["unit_price"])
    for line in price_changed:
        line_id = str(line["po_line_id"])
        base = _decimal(line["unit_price"], _CENT)
        magnitude = min_pct + (max_pct - min_pct) * float(rng.beta(beta_a, beta_b))
        sign = 1 if float(rng.random()) < increase_probability else -1
        candidate = (base * (Decimal("1") + Decimal(str(sign * magnitude / 100.0)))).quantize(_CENT, rounding=ROUND_HALF_UP)
        if candidate == base or abs(float((candidate - base) / base * Decimal("100"))) < min_pct:
            adjusted_magnitude = Decimal(str(min_pct / 100.0))
            candidate = (base * (Decimal("1") + Decimal(sign) * adjusted_magnitude)).quantize(_CENT, rounding=ROUND_HALF_UP)
            if candidate == base:
                candidate = base + Decimal("0.01") * sign
        if candidate <= 0:
            candidate = Decimal("0.01")
        price_by_line[line_id] = float(candidate)
        price_change_specs.append({
            "po_line_id": line_id,
            "po_id": str(line["po_id"]),
            "previous_unit_price": float(base),
            "requested_unit_price": float(candidate),
            "change_pct": round(float((candidate - base) / base * Decimal("100")), 4),
        })

    # Generate revision IDs before rows so every earlier row can point forward to its successor.
    ack_ids_by_po: dict[str, list[str]] = {}
    response_day_by_ack: dict[str, date] = {}
    revision_step_min = int(revision_cfg.get("revision_step_min_days", 1))
    revision_step_max = int(revision_cfg.get("revision_step_max_days", 2))
    if revision_step_min < 1 or revision_step_max < revision_step_min:
        raise ValueError("revision step days must satisfy 1 <= min <= max")
    for po in responding_pos:
        po_id = str(po["po_id"])
        ids = [factory.next_ack_id(po_id) for _ in range(revisions_by_po[po_id])]
        ack_ids_by_po[po_id] = ids
        response_day = _sample_response_day(rng, po, supplier_map[str(po["supplier_id"])], response_cfg)
        response_day_by_ack[ids[0]] = response_day
        required_day = date.fromisoformat(str(po["required_delivery_date"]))
        response_cap = _business_day_on_or_before(required_day - timedelta(days=1))
        for ack_id in ids[1:]:
            proposed = _business_day_on_or_after(
                response_day + timedelta(days=int(rng.integers(revision_step_min, revision_step_max + 1)))
            )
            if proposed > response_cap:
                proposed = response_cap
            if proposed < response_day:
                proposed = response_day
            response_day = proposed
            response_day_by_ack[ack_id] = response_day

    # Build all ACK records, keeping each revision as its own row. Payload quantities
    # remain immutable; only lifecycle status and the forward superseded_by pointer change.
    acknowledgement_rows: list[dict[str, Any]] = []
    ack_index: dict[tuple[str, int], dict[str, Any]] = {}
    for po in responding_pos:
        po_id = str(po["po_id"])
        po_lines_here = lines_by_po[po_id]
        supplier_id = str(po["supplier_id"])
        ids = ack_ids_by_po[po_id]
        outcome = outcome_by_po[po_id]
        req_qty = sum((_decimal(line["requested_qty"], _QTY) for line in po_lines_here), Decimal("0.000"))
        accepted_qty = sum((_decimal(accepted_by_line[str(line["po_line_id"])], _QTY) for line in po_lines_here), Decimal("0.000"))
        rejected_qty = (req_qty - accepted_qty).quantize(_QTY, rounding=ROUND_HALF_UP)
        requested_value = sum((_decimal(line["line_total"], _CENT) for line in po_lines_here), Decimal("0.00"))
        reason = reason_by_po[po_id]
        for revision_no, ack_id in enumerate(ids, start=1):
            response_day = response_day_by_ack[ack_id]
            created_at = at_utc(response_day, min(8 + revision_no, 11))
            acknowledged_at = at_utc(response_day, min(9 + revision_no, 13))
            # Keep the authoritative deadline byte-identical to the PO's value.
            response_due_at = str(po["response_due_at"])
            acknowledged_dt = datetime.fromisoformat(acknowledged_at.replace("Z", "+00:00"))
            due_dt = datetime.fromisoformat(response_due_at.replace("Z", "+00:00"))
            lifecycle_state = "EXCEPTION" if acknowledged_dt > due_dt else "PROCESSED"
            revision_price_map = {
                str(line["po_line_id"]): (price_by_line[str(line["po_line_id"])] if revision_no == len(ids) else float(line["unit_price"]))
                for line in po_lines_here
            }
            acknowledged_value = sum((
                _decimal(accepted_by_line[str(line["po_line_id"])], _QTY) * _decimal(revision_price_map[str(line["po_line_id"])], _CENT)
                for line in po_lines_here
            ), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP)
            quoted_value = sum((
                _decimal(line["requested_qty"], _QTY) * _decimal(revision_price_map[str(line["po_line_id"])], _CENT)
                for line in po_lines_here
            ), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP)
            derived_header_status = acknowledgement_status_value(req_qty, accepted_qty)
            if derived_header_status != outcome:
                raise RuntimeError(f"acknowledgement status is not reconciled for {po_id}: {outcome} vs {derived_header_status}")
            qty_delta_pct = float(compute_percent_delta(req_qty, accepted_qty))
            price_delta_pct = float(compute_percent_delta(requested_value, quoted_value))
            row = {
                "ack_id": ack_id,
                "po_id": po_id,
                "supplier_id": supplier_id,
                "po_line_id": None,
                "revision_no": revision_no,
                "status": derived_header_status,
                "lifecycle_state": lifecycle_state,
                "acknowledged_at": acknowledged_at,
                "response_due_at": response_due_at,
                "requested_qty": float(req_qty),
                "ack_accepted_qty": float(accepted_qty),
                "ack_rejected_qty": float(rejected_qty),
                "rejection_reason": reason,
                "promised_qty": float(accepted_qty),
                "projected_qty": float(accepted_qty),
                "requested_value": float(requested_value),
                "acknowledged_value": float(acknowledged_value),
                "promised_value": float(acknowledged_value),
                "projected_value": float(acknowledged_value),
                "qty_delta_pct": qty_delta_pct,
                "price_delta_pct": price_delta_pct,
                "date_slip_days": None,
                "supplier_note": {
                    "ACCEPTED": "Purchase order accepted in full.",
                    "PARTIALLY_ACCEPTED": f"Partial acceptance; rejected quantity reason: {reason}.",
                    "REJECTED": f"Purchase order rejected; reason: {reason}.",
                }[outcome],
                "superseded_by": ids[revision_no] if revision_no < len(ids) else None,
                "created_at": created_at,
                "created_by_role": "supplier",
                "created_by_actor_id": supplier_id,
                "issue_type": "LATE_ACKNOWLEDGEMENT" if lifecycle_state == "EXCEPTION" else None,
                "ground_truth": "LATE_ACKNOWLEDGEMENT" if lifecycle_state == "EXCEPTION" else None,
            }
            if revision_no < len(ids):
                row["status"] = "SUPERSEDED"
            acknowledgement_rows.append(row)
            ack_index[(po_id, revision_no)] = row

    # Current promised dates are targeted by exact counts among lines with positive accepted supply.
    promise_line_records = [line for line in line_rows if accepted_by_line[str(line["po_line_id"])] > 0.0]
    date_slip_prop = float(target_cfg.get("date_slips", 0.30))
    on_time_prop = float(target_cfg.get("on_time_promises", 0.70))
    if date_slip_prop < 0 or on_time_prop < 0 or abs(date_slip_prop + on_time_prop - 1.0) > 1e-8:
        raise ValueError("date_slips and on_time_promises proportions must be nonnegative and sum to 1")
    slip_target = _rounded_count(len(promise_line_records), date_slip_prop)
    promise_risk_noise = float(promise_cfg.get("slip_risk_noise_sd", 0.15))
    po_by_id = {str(row["po_id"]): row for row in po_rows}

    def promise_slip_score(line: dict[str, Any]) -> float:
        po = po_by_id[str(line["po_id"])]
        reliability = float(supplier_map[str(po["supplier_id"])]["reliability_score"])
        z_qty = (line_qty_log[str(line["po_line_id"])] - line_log_mean) / line_log_sd
        return 0.78 * (1.0 - reliability) + 0.10 * z_qty + float(rng.normal(0.0, promise_risk_noise))

    slip_lines = _weighted_rank(rng, promise_line_records, slip_target, promise_slip_score)
    slip_line_ids = {str(line["po_line_id"]) for line in slip_lines}
    final_promised_date_by_line: dict[str, date] = {}
    slip_days_by_line: dict[str, int] = {}
    slip_mean = float(promise_cfg.get("slip_days_lognormal_mean", 1.90))
    slip_sigma = float(promise_cfg.get("slip_days_lognormal_sigma", 0.60))
    slip_min = int(promise_cfg.get("min_slip_days", 3))
    slip_max = int(promise_cfg.get("max_slip_days", 60))
    if slip_sigma <= 0 or slip_min < 3 or slip_max < slip_min or slip_max > 60:
        raise ValueError("promise slip distribution must have sigma > 0 and bounds in [3, 60]")
    for line in promise_line_records:
        line_id = str(line["po_line_id"])
        required_date = date.fromisoformat(str(line["required_date"]))
        po_id = str(line["po_id"])
        latest_ack_id = ack_ids_by_po[po_id][-1]
        latest_effective_date = response_day_by_ack[latest_ack_id]
        if line_id in slip_line_ids:
            slip_days = int(round(float(rng.lognormal(slip_mean, slip_sigma))))
            slip_days = min(slip_max, max(slip_min, slip_days))
            target_date = required_date + timedelta(days=slip_days)
            slip_days_by_line[line_id] = slip_days
        else:
            alpha = float(promise_cfg.get("on_time_early_days_beta_alpha", 2.0))
            beta = float(promise_cfg.get("on_time_early_days_beta_beta", 5.0))
            max_early = int(promise_cfg.get("max_early_days", 5))
            if alpha <= 0 or beta <= 0 or max_early < 0:
                raise ValueError("on-time promise Beta distribution parameters must be positive and max_early_days >= 0")
            early_days = int(round(float(rng.beta(alpha, beta)) * max_early))
            target_date = required_date - timedelta(days=early_days)
            slip_days_by_line[line_id] = 0
        final_promised_date_by_line[line_id] = max(target_date, latest_effective_date)

    # Emit line-level promises for each ACK revision; every old promise remains in history.
    promise_rows: list[dict[str, Any]] = []
    promise_index: dict[tuple[str, str, int], dict[str, Any]] = {}
    promise_sources = list(promise_cfg.get("sources", {"SUPPLIER_PORTAL": .55, "EMAIL": .20, "EDI": .15, "API": .07, "MANUAL": .03}))
    promise_source_probs = np.asarray([float(promise_cfg.get("sources", {}).get(key, 0)) for key in promise_sources], dtype=float)
    if not promise_sources or np.any(promise_source_probs < 0) or abs(float(promise_source_probs.sum()) - 1.0) > 1e-8:
        raise ValueError("promise_dates.sources weights must be nonnegative and sum to 1")
    prior_date_by_line: dict[str, date] = {}
    logistics_by_po: dict[str, dict[str, str]] = {}
    for po_index, po in enumerate(po_rows):
        po_id = str(po["po_id"])
        warehouse = warehouse_by_id.get(str(po.get("warehouse_id"))) or warehouse_rows[po_index % len(warehouse_rows)]
        carrier = carrier_by_id.get(str(po.get("carrier_id"))) or carrier_rows[po_index % len(carrier_rows)]
        # Use the PO's planned ship-from/carrier where present, with stable fallback.
        operator = carrier_operators[po_index % len(carrier_operators)]
        logistics_by_po[po_id] = {
            "ship_from_warehouse_id": str(warehouse["warehouse_id"]),
            "ship_from_location": str(warehouse["warehouse_name"]),
            "carrier_id": str(carrier["carrier_id"]),
            "carrier_reference": str(carrier["carrier_code"]),
            "carrier_operator_actor_id": str(operator["actor_id"]),
        }

    confidence_noise_sd = float(response_cfg.get("promise_confidence_noise_sd", 0.10))
    high_confidence_threshold = float(response_cfg.get("high_confidence_threshold", 0.78))
    medium_confidence_threshold = float(response_cfg.get("medium_confidence_threshold", 0.55))
    if confidence_noise_sd < 0 or not (0 <= medium_confidence_threshold <= high_confidence_threshold <= 1):
        raise ValueError("supplier_response confidence thresholds are invalid")

    for po in responding_pos:
        po_id = str(po["po_id"])
        ids = ack_ids_by_po[po_id]
        supplier = supplier_map[str(po["supplier_id"])]
        logistics = logistics_by_po[po_id]
        for revision_no, ack_id in enumerate(ids, start=1):
            ack_row = ack_index[(po_id, revision_no)]
            ack_created_dt = datetime.fromisoformat(str(ack_row["acknowledged_at"]).replace("Z", "+00:00"))
            effective_day = ack_created_dt.date()
            promise_sequence = 0
            for line in lines_by_po[po_id]:
                line_id = str(line["po_line_id"])
                accepted_qty = _decimal(accepted_by_line[line_id], _QTY)
                if accepted_qty <= 0:
                    continue
                promise_sequence += 1
                sequence_no = promise_sequence
                latest_day = final_promised_date_by_line[line_id]
                revision_gap = len(ids) - revision_no
                proposed_day = latest_day - timedelta(days=revision_gap * 2)
                promise_day = _business_day_on_or_after(max(proposed_day, effective_day))
                # Keep the generated on-time class on or before required date where possible.
                required_day = date.fromisoformat(str(line["required_date"]))
                if line_id not in slip_line_ids and promise_day > required_day:
                    promise_day = _business_day_on_or_before(required_day)
                if promise_day < effective_day:
                    promise_day = _business_day_on_or_after(effective_day)
                promise_id = factory.next_promise_date_id(ack_id)
                prior = prior_date_by_line.get(line_id) if revision_no > 1 else None
                reliability = float(supplier["reliability_score"])
                confidence_score = _clamp(reliability + float(rng.normal(0.0, confidence_noise_sd)), 0.0, 1.0)
                confidence = "HIGH" if confidence_score >= high_confidence_threshold else "MEDIUM" if confidence_score >= medium_confidence_threshold else "LOW"
                issue_type = "DATE_SLIP_REQUIRES_APPROVAL" if (promise_day - required_day).days > int(get_config(cfg, "approval_thresholds", "date_slip_days", default=3)) and revision_no == len(ids) else None
                row = {
                    "promise_date_id": promise_id,
                    "ack_id": ack_id,
                    "po_id": po_id,
                    "po_line_id": line_id,
                    "sequence_no": sequence_no,
                    "revision_no": revision_no,
                    "promised_date": promise_day.isoformat(),
                    "slip_days": derive_promise_date(promise_day.isoformat(), required_day.isoformat())["slip_days"],
                    "is_late": derive_promise_date(promise_day.isoformat(), required_day.isoformat())["is_late"],
                    "promised_qty": float(accepted_qty),
                    "promise_confidence": confidence,
                    "ship_from_location": logistics["ship_from_location"],
                    "ship_from_warehouse_id": logistics["ship_from_warehouse_id"],
                    "carrier_id": logistics["carrier_id"],
                    "carrier_reference": logistics["carrier_reference"],
                    "carrier_operator_actor_id": logistics["carrier_operator_actor_id"],
                    "prior_promised_date": prior.isoformat() if prior else None,
                    "effective_date": effective_day.isoformat(),
                    "response_due_date": (effective_day + timedelta(days=1)).isoformat(),
                    "status": "CURRENT" if revision_no == len(ids) else "SUPERSEDED",
                    "superseded_by": None,
                    "source": str(rng.choice(promise_sources, p=promise_source_probs)),
                    "created_at": str(ack_row["acknowledged_at"]),
                    "created_by_role": "supplier",
                    "created_by_actor_id": str(po["supplier_id"]),
                    "issue_type": issue_type,
                    "ground_truth": issue_type,
                }
                promise_rows.append(row)
                promise_index[(po_id, line_id, revision_no)] = row
                prior_date_by_line[line_id] = promise_day

    # The prior_promised_date chain is revision-ordered; fill superseded_by after IDs exist.
    for po in responding_pos:
        po_id = str(po["po_id"])
        ids = ack_ids_by_po[po_id]
        candidate_lines = [line for line in lines_by_po[po_id] if accepted_by_line[str(line["po_line_id"])] > 0.0]
        for revision_no in range(1, len(ids)):
            for line in candidate_lines:
                earlier = promise_index[(po_id, str(line["po_line_id"]), revision_no)]
                later = promise_index[(po_id, str(line["po_line_id"]), revision_no + 1)]
                earlier["superseded_by"] = later["promise_date_id"]

    # Update only current-state snapshots on PO and POLine; historical ACK and promise rows remain intact.
    po_updated = purchase_orders.copy(deep=True)
    po_status_map: dict[str, str] = {}
    latest_ack_time: dict[str, str] = {}
    for po in responding_pos:
        po_id = str(po["po_id"])
        outcome = outcome_by_po[po_id]
        po_status_map[po_id] = {
            "ACCEPTED": "ACKNOWLEDGED",
            "PARTIALLY_ACCEPTED": "PARTIALLY_ACKNOWLEDGED",
            "REJECTED": "CHANGE_PENDING",
        }[outcome]
        latest_ack_time[po_id] = str(ack_index[(po_id, len(ack_ids_by_po[po_id]))]["acknowledged_at"])
    for idx, row in po_updated.iterrows():
        po_id = str(row["po_id"])
        if po_id in silence_ids:
            po_updated.at[idx, "status"] = "ISSUED"
            po_updated.at[idx, "issue_type"] = "MISSING_ACK"
            po_updated.at[idx, "ground_truth"] = "MISSING_ACK"
            continue
        po_updated.at[idx, "status"] = po_status_map[po_id]
        po_updated.at[idx, "updated_at"] = latest_ack_time[po_id]

    lines_updated = po_lines.copy(deep=True)
    for idx, row in lines_updated.iterrows():
        line_id = str(row["po_line_id"])
        po_id = str(row["po_id"])
        if po_id in silence_ids:
            # Silence is not a rejection or acknowledgement: leave acknowledgement snapshots unresolved.
            lines_updated.at[idx, "status"] = "OPEN"
            continue
        accepted = _decimal(accepted_by_line[line_id], _QTY)
        rejected = _decimal(rejected_by_line[line_id], _QTY)
        acknowledged_price = _decimal(price_by_line[line_id], _CENT)
        promised_qty = accepted
        lines_updated.at[idx, "ack_accepted_qty"] = float(accepted)
        lines_updated.at[idx, "ack_rejected_qty"] = float(rejected)
        lines_updated.at[idx, "promised_qty"] = float(promised_qty)
        lines_updated.at[idx, "projected_qty"] = float(promised_qty)
        lines_updated.at[idx, "acknowledged_unit_price"] = float(acknowledged_price)
        lines_updated.at[idx, "promised_unit_price"] = float(acknowledged_price)
        lines_updated.at[idx, "projected_unit_price"] = float(acknowledged_price)
        lines_updated.at[idx, "acknowledged_value"] = _money(accepted, acknowledged_price)
        lines_updated.at[idx, "promised_value"] = _money(promised_qty, acknowledged_price)
        lines_updated.at[idx, "projected_value"] = _money(promised_qty, acknowledged_price)
        if accepted == 0:
            lines_updated.at[idx, "status"] = "OPEN"
        elif rejected == 0:
            lines_updated.at[idx, "status"] = "ACKNOWLEDGED"
        else:
            lines_updated.at[idx, "status"] = "PARTIALLY_ACKNOWLEDGED"
        lines_updated.at[idx, "updated_at"] = latest_ack_time[po_id]

    # Build a full immutable line snapshot for each ACK revision. Quantities,
    # deltas, and date slips are derived from their source records, never sampled
    # independently. A fully rejected line intentionally has no PromiseDate row.
    promise_by_ack_line = {
        (str(row["ack_id"]), str(row["po_line_id"])): row for row in promise_rows
    }
    line_by_id = {str(row["po_line_id"]): row for row in line_rows}
    acknowledgement_line_rows: list[dict[str, Any]] = []
    for ack_row in acknowledgement_rows:
        po_id = str(ack_row["po_id"])
        ack_id = str(ack_row["ack_id"])
        revision_no = int(ack_row["revision_no"])
        supplier_id = str(ack_row["supplier_id"])
        ack_is_superseded = str(ack_row["status"]) == "SUPERSEDED"
        # For a prior revision, supplier prices revert to the original request;
        # a changed quote is part of the latest revision snapshot.
        for line in lines_by_po[po_id]:
            line_id = str(line["po_line_id"])
            requested = _decimal(line["requested_qty"], _QTY)
            accepted = _decimal(accepted_by_line[line_id], _QTY)
            rejected = (requested - accepted).quantize(_QTY, rounding=ROUND_HALF_UP)
            requested_price = _decimal(line["unit_price"], _CENT)
            final_revision_no = len(ack_ids_by_po[po_id])
            acknowledged_price = _decimal(
                price_by_line[line_id] if revision_no == final_revision_no else line["unit_price"],
                _CENT,
            )
            promise = promise_by_ack_line.get((ack_id, line_id))
            if promise is not None:
                date_values = derive_promise_date(promise["promised_date"], line["required_date"])
                date_slip = date_values["slip_days"]
            else:
                date_slip = None
            outcome_status = "REJECTED" if accepted == 0 else "PARTIALLY_ACCEPTED" if rejected > 0 else "ACCEPTED"
            issue_type = ack_row.get("issue_type")
            acknowledgement_line_rows.append({
                "acknowledgement_line_id": f"AL-{ack_id}-{line_id}",
                "ack_id": ack_id,
                "po_id": po_id,
                "po_line_id": line_id,
                "revision_no": revision_no,
                "status": "SUPERSEDED" if ack_is_superseded else outcome_status,
                "requested_qty": float(requested),
                "accepted_qty": float(accepted),
                "rejected_qty": float(rejected),
                "rejected_reason": reason_by_po[po_id] if rejected > 0 else None,
                "requested_unit_price": float(requested_price),
                "acknowledged_unit_price": float(acknowledged_price),
                "qty_delta_pct": float(compute_percent_delta(requested, accepted)),
                "price_delta_pct": float(compute_percent_delta(requested_price, acknowledged_price)),
                "date_slip_days": date_slip,
                "response_timestamp": str(ack_row["acknowledged_at"]),
                "created_at": str(ack_row["created_at"]),
                "created_by_role": "supplier",
                "created_by_actor_id": supplier_id,
                "issue_type": issue_type,
                "ground_truth": ack_row.get("ground_truth"),
            })

    # Set date_slip_days on the header from the actual emitted promise rows.
    max_slip_by_ack: dict[str, int] = {}
    for promise in promise_rows:
        line = line_by_id[str(promise["po_line_id"])]
        slip = (date.fromisoformat(str(promise["promised_date"])) - date.fromisoformat(str(line["required_date"]))).days
        max_slip_by_ack[str(promise["ack_id"])] = max(max_slip_by_ack.get(str(promise["ack_id"]), slip), slip)
    for ack_row in acknowledgement_rows:
        ack_row["date_slip_days"] = max_slip_by_ack.get(str(ack_row["ack_id"]))

    # Persist one event per submitted ACK/revision. JSON state snapshots make the
    # events independently useful even if downstream current-state rows evolve.
    event_rows: list[dict[str, Any]] = []
    event_sequence = 0
    previous_ack_by_po: dict[str, dict[str, Any]] = {}
    for ack_row in acknowledgement_rows:
        event_sequence += 1
        ack_id = str(ack_row["ack_id"])
        po_id = str(ack_row["po_id"])
        previous = previous_ack_by_po.get(po_id)
        event_rows.append({
            "event_id": f"EVT-ACK-{event_sequence:06d}",
            "entity_type": "Acknowledgement",
            "entity_id": ack_id,
            "event_type": "ack_submitted" if int(ack_row["revision_no"]) == 1 else "ack_revised",
            "event_timestamp": str(ack_row["acknowledged_at"]),
            "actor_role": "supplier",
            "actor_id": str(ack_row["supplier_id"]),
            "payload_json": json.dumps({
                "po_id": po_id,
                "revision_no": int(ack_row["revision_no"]),
                "status": str(ack_row["status"]),
                "lifecycle_state": str(ack_row["lifecycle_state"]),
                "late_response": str(ack_row["lifecycle_state"]) == "EXCEPTION",
                "line_count": len(lines_by_po[po_id]),
            }, sort_keys=True, separators=(",", ":")),
            # Every ack_id is a distinct immutable revision entity. Its own lifecycle
            # begins at SUBMITTED; do not compare it to the preceding revision's status.
            "previous_state": json.dumps({"status": "SUBMITTED"}, sort_keys=True, separators=(",", ":")),
            "new_state": json.dumps(ack_row, sort_keys=True, default=str, separators=(",", ":")),
            "issue_type": ack_row.get("issue_type"),
            "ground_truth": ack_row.get("ground_truth"),
            "target_supplier_id": None,
            "target_po_id": None,
            "target_po_line_id": None,
            "target_ack_id": ack_id,
            "target_promise_date_id": None,
            "target_change_request_id": None,
            "target_approval_id": None,
            "target_inventory_plan_id": None,
            "target_production_order_id": None,
            "target_notification_id": None,
        })
        previous_ack_by_po[po_id] = dict(ack_row)

    ack_df = frame_for_entity("Acknowledgement", acknowledgement_rows)
    promise_df = frame_for_entity("PromiseDate", promise_rows)
    acknowledgement_lines_df = pd.DataFrame(
        acknowledgement_line_rows,
        columns=[field.name for field in ACKNOWLEDGEMENT_LINE_FIELDS],
    )
    entity_event_df = pd.DataFrame(event_rows, columns=_EVENT_COLUMNS)

    silence_rows: list[dict[str, Any]] = []
    for po in po_rows:
        po_id = str(po["po_id"])
        if po_id not in silence_ids:
            continue
        supplier = supplier_map[str(po["supplier_id"])]
        due_at = datetime.fromisoformat(str(po["response_due_at"]))
        due_day = due_at.date()
        silence_rows.append({
            "po_id": po_id,
            "supplier_id": str(po["supplier_id"]),
            "supplier_name": str(supplier["supplier_name"]),
            "order_date": str(po["order_date"]),
            "requested_delivery_date": str(po["required_delivery_date"]),
            "response_due_at": str(po["response_due_at"]),
            "as_of_date": as_of.isoformat(),
            "days_overdue": max(0, (as_of - due_day).days),
            "lead_time_days": int(supplier["lead_time_days"]),
            "reliability_score": float(supplier["reliability_score"]),
            "issue_type": "MISSING_ACK",
            "ground_truth": "MISSING_ACK",
        })
    silence_df = pd.DataFrame(silence_rows, columns=[
        "po_id", "supplier_id", "supplier_name", "order_date", "requested_delivery_date",
        "response_due_at", "as_of_date", "days_overdue", "lead_time_days", "reliability_score",
        "issue_type", "ground_truth",
    ])

    return {
        "acknowledgements": ack_df,
        "acknowledgement_lines": acknowledgement_lines_df,
        "promise_dates": promise_df,
        "entity_event": entity_event_df,
        "purchase_orders": po_updated,
        "po_lines": lines_updated,
        "silence_report": silence_df,
        "price_change_specs": price_change_specs,
        "silence_ids": silence_ids,
        "revision_po_ids": revision_po_ids,
        "revisions_by_po": revisions_by_po,
        "outcome_by_po": outcome_by_po,
        "accepted_by_line": accepted_by_line,
        "rejected_by_line": rejected_by_line,
        "price_change_target": price_target,
        "change_request_count": change_request_budget,
        "event_count_target": requested_events,
        "response_due_at_by_po": {str(row["po_id"]): row["response_due_at"] for row in po_rows},
    }
