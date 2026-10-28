"""Purchase-order line generation; financial totals are computed from quantity × price."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

import pandas as pd
from numpy.random import Generator

from supplier_ack.ids import IDFactory
from supplier_ack.generators.common import active_scale_config, frame_for_entity, get_config, require_rng

_CENTS = Decimal("0.01")


def _money_product(quantity: Any, unit_price: Any) -> float:
    amount = Decimal(str(quantity)) * Decimal(str(unit_price))
    return float(amount.quantize(_CENTS, rounding=ROUND_HALF_UP))


def generate_po_lines(
    rng: Generator,
    cfg: Mapping[str, Any],
    purchase_orders: pd.DataFrame,
    items: pd.DataFrame,
    id_factory: IDFactory | None = None,
) -> pd.DataFrame:
    """Create 2–6 POLines per PO, sampling prices inside each item's configured band."""
    require_rng(rng)
    if purchase_orders.empty or items.empty:
        raise ValueError("purchase orders and item master must be non-empty before generating PO lines")
    factory = id_factory or IDFactory()
    line_cfg = get_config(cfg, "distributions", "po_lines", default={})
    minimum_lines = int(line_cfg.get("min_lines_per_po", 2))
    maximum_lines = int(line_cfg.get("max_lines_per_po", 6))
    if minimum_lines < 1 or maximum_lines < minimum_lines or maximum_lines > 99:
        raise ValueError("line-count range must satisfy 1 <= min <= max <= 99")
    qty_min = float(line_cfg.get("quantity_min", 10))
    qty_max = float(line_cfg.get("quantity_max", 5000))
    if qty_min <= 0 or qty_max < qty_min:
        raise ValueError("quantity bounds must satisfy 0 < min <= max")
    lognormal_mean = float(line_cfg.get("quantity_lognormal_mean", 5.8))
    lognormal_sigma = float(line_cfg.get("quantity_lognormal_sigma", 0.85))
    if lognormal_sigma <= 0:
        raise ValueError("quantity_lognormal_sigma must be > 0")

    item_rows = items.to_dict(orient="records")
    item_ids = [row["item_id"] for row in item_rows]
    item_map = {row["item_id"]: row for row in item_rows}
    records: list[dict[str, Any]] = []
    for po in purchase_orders.to_dict(orient="records"):
        line_count = int(rng.integers(minimum_lines, maximum_lines + 1))
        selected_items = rng.choice(item_ids, size=line_count, replace=True)
        for item_id in selected_items:
            item = item_map[str(item_id)]
            quantity = round(min(qty_max, max(qty_min, float(rng.lognormal(lognormal_mean, lognormal_sigma)))), 3)
            low, high = float(item["unit_price_min"]), float(item["unit_price_max"])
            if high < low or low < 0:
                raise ValueError(f"item {item_id} has invalid price band [{low}, {high}]")
            unit_price = round(float(rng.uniform(low, high)), 2)
            unit_price = min(high, max(low, unit_price))
            line_id = factory.next_line_id(str(po["po_id"]))
            line_no = int(line_id.rsplit("L", 1)[1])
            line_total = _money_product(quantity, unit_price)
            records.append({
                "po_line_id": line_id,
                "po_id": po["po_id"],
                "line_no": line_no,
                "item_id": str(item_id),
                "item_description": item["item_name"],
                "requested_qty": quantity,
                "ack_accepted_qty": 0.0,
                "ack_rejected_qty": 0.0,
                "promised_qty": 0.0,
                "projected_qty": 0.0,
                "uom": item["default_uom"],
                "currency": po["currency"],
                "unit_price": unit_price,
                "acknowledged_unit_price": None,
                "promised_unit_price": None,
                "projected_unit_price": None,
                "line_total": line_total,
                "acknowledged_value": None,
                "promised_value": None,
                "projected_value": None,
                "required_date": po["required_delivery_date"],
                "status": "DRAFT",
                "created_at": po["created_at"],
                "updated_at": po["created_at"],
                "issue_type": None,
                "ground_truth": None,
            })
    return frame_for_entity("POLine", records)
