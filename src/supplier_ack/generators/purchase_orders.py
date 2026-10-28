"""Purchase-order header generation with weighted supplier assignment."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

import pandas as pd
from numpy.random import Generator

from supplier_ack.ids import IDFactory
from supplier_ack.generators.common import (
    active_scale_config, at_utc, assert_probability_distribution, frame_for_entity, get_config,
    require_rng,
)


def generate_purchase_orders(
    rng: Generator,
    cfg: Mapping[str, Any],
    suppliers: pd.DataFrame,
    actors: pd.DataFrame,
    warehouses: pd.DataFrame,
    carriers: pd.DataFrame,
    id_factory: IDFactory | None = None,
) -> pd.DataFrame:
    """Generate PO headers. `total_order_value` is staged at zero then aggregated from lines."""
    require_rng(rng)
    count = int(active_scale_config(cfg)["po_count"])
    if count < 1:
        raise ValueError("po_count must be >= 1")
    if suppliers.empty or warehouses.empty or carriers.empty:
        raise ValueError("supplier, warehouse, and carrier masters must be generated before purchase orders")
    factory = id_factory or IDFactory()
    order_cfg = get_config(cfg, "distributions", "order_calendar", default={})
    sampling_cfg = get_config(cfg, "distributions", "supplier_sampling", default={})
    carrier_cfg = get_config(cfg, "distributions", "preferred_carrier", default={})
    start, end = date.fromisoformat(str(order_cfg.get("start_date", "2026-01-01"))), date.fromisoformat(str(order_cfg.get("end_date", "2026-06-30")))
    if end < start:
        raise ValueError("order_calendar.end_date must be >= start_date")
    business_days = pd.bdate_range(start=start.isoformat(), end=end.isoformat(), freq="B")
    if len(business_days) == 0:
        raise ValueError("order calendar contains no weekdays")

    # Assign latent supplier weights after a random permutation of Pareto ranks. This
    # creates a long-tail concentration while avoiding a fixed supplier-ID advantage.
    supplier_count = len(suppliers)
    alpha = float(sampling_cfg.get("pareto_alpha", 1.15))
    if alpha <= 0:
        raise ValueError("supplier_sampling.pareto_alpha must be > 0")
    supplier_weights = rng.permutation([float(rank) ** (-alpha) for rank in range(1, supplier_count + 1)])
    supplier_probabilities = supplier_weights / sum(supplier_weights)
    supplier_rows = suppliers.to_dict(orient="records")
    supplier_ids = [row["supplier_id"] for row in supplier_rows]
    supplier_map = {row["supplier_id"]: row for row in supplier_rows}
    chosen_supplier_ids = rng.choice(supplier_ids, size=count, p=supplier_probabilities)
    chosen_days = rng.choice(business_days.to_numpy(), size=count, replace=True)

    planner_ids = actors.loc[actors["actor_role"] == "planner", "actor_id"].tolist()
    operations_ids = actors.loc[actors["actor_role"] == "operations_manager", "actor_id"].tolist()
    if not planner_ids or not operations_ids:
        raise ValueError("actor roster must include planner and operations_manager roles")
    warehouse_ids = warehouses["warehouse_id"].tolist()
    carrier_ids = carriers["carrier_id"].tolist()
    currency_fallback = str(get_config(cfg, "distributions", "default_currency", default="INR"))
    min_buffer = int(order_cfg.get("min_delivery_buffer_days", 2))
    max_buffer = int(order_cfg.get("max_delivery_buffer_days", 7))
    if min_buffer < 0 or max_buffer < min_buffer:
        raise ValueError("delivery buffer configuration is invalid")
    response_days = int(order_cfg.get("supplier_response_due_days", 2))
    created_hour = int(order_cfg.get("created_hour_utc", 9))
    due_hour = int(order_cfg.get("due_hour_utc", 17))
    if not (0 <= created_hour <= 23 and 0 <= due_hour <= 23):
        raise ValueError("configured UTC hours must be within 0–23")
    preferred_probability = float(carrier_cfg.get("preferred_probability", 0.78))
    if not 0 <= preferred_probability <= 1:
        raise ValueError("preferred_carrier.preferred_probability must be in [0, 1]")

    records: list[dict[str, Any]] = []
    for index in range(count):
        supplier = supplier_map[str(chosen_supplier_ids[index])]
        order_day = pd.Timestamp(chosen_days[index]).date()
        buffer_days = int(rng.integers(min_buffer, max_buffer + 1))
        required_day = order_day + timedelta(days=int(supplier["lead_time_days"]) + buffer_days)
        planner_actor_id = str(rng.choice(planner_ids))
        if float(rng.uniform(0.0, 1.0)) < 0.92:
            created_by_role = "planner"
            created_by_actor_id = planner_actor_id
        else:
            created_by_role = "operations_manager"
            created_by_actor_id = str(rng.choice(operations_ids))
        if float(rng.uniform(0.0, 1.0)) < preferred_probability:
            carrier_id = str(supplier["preferred_carrier_id"])
        else:
            carrier_id = str(rng.choice(carrier_ids))
        created_at = at_utc(order_day, created_hour)
        due_at = at_utc(order_day + timedelta(days=response_days), due_hour)
        records.append({
            "po_id": factory.next_po_id(),
            "supplier_id": supplier["supplier_id"],
            "planner_actor_id": planner_actor_id,
            "warehouse_id": str(rng.choice(warehouse_ids)),
            "carrier_id": carrier_id,
            "order_date": order_day.isoformat(),
            "required_delivery_date": required_day.isoformat(),
            "response_due_at": due_at,
            "currency": str(supplier.get("default_currency") or currency_fallback),
            # Staging sentinel only; framework replaces this with exact line aggregation after POLines exist.
            "total_order_value": 0.0,
            "status": "DRAFT",
            "created_by_role": created_by_role,
            "created_by_actor_id": created_by_actor_id,
            "supplier_contact_email": supplier["supplier_contact_email"],
            "version_no": 1,
            "created_at": created_at,
            "updated_at": created_at,
            "issue_type": None,
            "ground_truth": None,
        })
    return frame_for_entity("PurchaseOrder", records)


def finalize_purchase_order_totals(purchase_orders: pd.DataFrame, po_lines: pd.DataFrame) -> pd.DataFrame:
    """Derive header totals from computed line totals; never generate them independently."""
    updated = purchase_orders.copy(deep=True)
    totals: dict[str, Decimal] = {}
    for row in po_lines[["po_id", "line_total"]].to_dict(orient="records"):
        po_id = str(row["po_id"])
        value = Decimal(str(row["line_total"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        totals[po_id] = totals.get(po_id, Decimal("0.00")) + value
    updated["total_order_value"] = [float(totals.get(str(po_id), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for po_id in updated["po_id"]]
    return updated
