"""Configuration validation and empirical coverage reporting for generation step 4."""
from __future__ import annotations

import warnings
from typing import Any, Mapping

import pandas as pd

from supplier_ack.generators.common import active_scale_config, get_config

COVERAGE_CATEGORIES = (
    "partial_acceptance",
    "full_acceptance",
    "full_rejection",
    "date_slips",
    "on_time_promises",
    "price_changes",
    "supplier_silence",
    "multiple_revisions",
)


def _round_count(total: int, proportion: float) -> int:
    return int(total * proportion + 0.5)


def validate_coverage_config(
    cfg: Mapping[str, Any], scale: str | None = None, *, emit_warnings: bool = True
) -> list[str]:
    """Validate proportions and warn when event/PO volumes cannot satisfy targets.

    Warnings are returned to callers and optionally emitted as ``RuntimeWarning``.
    Invalid probability distributions raise ``ValueError`` because a seeded run
    cannot be interpreted when its configured distributions are malformed.
    """
    if scale is not None:
        config = dict(cfg)
        config["active_scale"] = scale
    else:
        config = cfg
    block = active_scale_config(config)
    coverage = get_config(config, "coverage", default={})
    target = coverage.get("target_proportions", {})
    required = set(COVERAGE_CATEGORIES)
    missing = required - set(target)
    if missing:
        raise ValueError(f"coverage.target_proportions is missing {sorted(missing)}")
    for name in COVERAGE_CATEGORIES:
        value = float(target[name])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"coverage.target_proportions.{name} must be in [0, 1]")
    outcome_sum = sum(float(target[name]) for name in ("partial_acceptance", "full_acceptance", "full_rejection"))
    if abs(outcome_sum - 1.0) > 1e-8:
        raise ValueError("partial_acceptance + full_acceptance + full_rejection must sum to 1")
    date_sum = float(target["date_slips"]) + float(target["on_time_promises"])
    if abs(date_sum - 1.0) > 1e-8:
        raise ValueError("date_slips + on_time_promises must sum to 1")

    revision_cfg = coverage.get("acknowledgement_revisions", {})
    count_probs = revision_cfg.get("count_probabilities", {2: 0.5, 3: 0.35, 4: 0.15})
    probabilities = [float(value) for value in count_probs.values()]
    if not probabilities or any(value < 0 or value > 1 for value in probabilities) or abs(sum(probabilities) - 1.0) > 1e-8:
        raise ValueError("coverage.acknowledgement_revisions.count_probabilities must sum to 1")
    min_revision = int(revision_cfg.get("min_revisions", min(int(x) for x in count_probs)))
    max_revision = int(revision_cfg.get("max_revisions", max(int(x) for x in count_probs)))
    if min_revision < 2 or max_revision < min_revision or max_revision > 99:
        raise ValueError("acknowledgement revision range must satisfy 2 <= min <= max <= 99")

    n_po = int(block["po_count"])
    events = int(block["event_count"])
    n_silence = _round_count(n_po, float(target["supplier_silence"]))
    responders = n_po - n_silence
    n_revision_pos = _round_count(n_po, float(target["multiple_revisions"]))
    warnings_out: list[str] = []

    if n_revision_pos > responders:
        warnings_out.append(
            f"{scale or config.get('active_scale', 'selected')} scale multiple-revision target ({n_revision_pos} POs) exceeds responding POs ({responders}); revision target will be clipped"
        )
        n_revision_pos = responders
    min_ack_rows = responders + n_revision_pos * (min_revision - 1)
    if min_ack_rows > events:
        warnings_out.append(
            f"{scale or config.get('active_scale', 'selected')} scale event_count={events} is below the minimum {min_ack_rows} acknowledgement rows required by silence/revision targets; change-request budget will be zero and actual events may exceed target"
        )
    expected_price_changes = _round_count(max(0, int(block["po_count"] * 4)), float(target["price_changes"]))
    # This is a conservative feasibility warning, not a strict expected line count.
    remaining_cr = max(0, events - min_ack_rows)
    if expected_price_changes > remaining_cr:
        warnings_out.append(
            f"{scale or config.get('active_scale', 'selected')} scale may not have enough change-request event budget ({remaining_cr}) to realize the price-change target (~{expected_price_changes} at four lines per PO)"
        )
    for message in warnings_out:
        if emit_warnings:
            warnings.warn(message, RuntimeWarning, stacklevel=2)
    return warnings_out


def _percentage(count: int, denominator: int) -> float:
    return round(100.0 * count / denominator, 3) if denominator else 0.0


def build_coverage_report(
    cfg: Mapping[str, Any], scale: str, seed: int, frames: Mapping[str, pd.DataFrame]
) -> pd.DataFrame:
    """Build observed count/percentage rows for the required eight coverage groups.

    Each category percentage uses the denominator appropriate to its semantics:
    response outcome is per responding PO; promise timing is per current line promise;
    price change is per line with a positive acknowledged quantity; silence and
    multiple revisions are per total PO count.
    """
    target = get_config(cfg, "coverage", "target_proportions", default={})
    pos = frames["purchase_orders"]
    lines = frames["po_lines"]
    acks = frames.get("acknowledgements", pd.DataFrame())
    promises = frames.get("promise_dates", pd.DataFrame())
    silence = frames.get("silence_report", pd.DataFrame())
    total_pos = len(pos)

    if acks.empty:
        latest_acks = acks.copy()
        revision_counts = pd.Series(dtype=int)
    else:
        revision_counts = acks.groupby("po_id").size()
        latest_acks = acks.loc[~acks["status"].eq("SUPERSEDED")].copy()

    responded = len(latest_acks)
    current_outcomes = {
        "partial_acceptance": int(latest_acks["status"].eq("PARTIALLY_ACCEPTED").sum()) if responded else 0,
        "full_acceptance": int(latest_acks["status"].eq("ACCEPTED").sum()) if responded else 0,
        "full_rejection": int(latest_acks["status"].eq("REJECTED").sum()) if responded else 0,
    }

    if promises.empty:
        current_promises = promises.copy()
        slip_count = on_time_count = 0
    else:
        current_promises = promises.loc[promises["status"].eq("CURRENT")].copy()
        required = lines[["po_line_id", "required_date"]].drop_duplicates("po_line_id")
        current_promises = current_promises.merge(required, on="po_line_id", how="left", validate="many_to_one")
        promised_dates = pd.to_datetime(current_promises["promised_date"], errors="coerce")
        required_dates = pd.to_datetime(current_promises["required_date"], errors="coerce")
        slip_mask = promised_dates.gt(required_dates)
        slip_count = int(slip_mask.sum())
        on_time_count = int((promised_dates.le(required_dates)).sum())

    positive_accepted = lines.loc[pd.to_numeric(lines["ack_accepted_qty"], errors="coerce").fillna(0).gt(0)]
    ack_price = pd.to_numeric(positive_accepted["acknowledged_unit_price"], errors="coerce")
    po_price = pd.to_numeric(positive_accepted["unit_price"], errors="coerce")
    comparable = ack_price.notna() & po_price.notna()
    price_changed_mask = (ack_price.sub(po_price).abs() > 0.005) & comparable
    price_count = int(price_changed_mask.sum())
    price_denominator = int(comparable.sum())
    revision_po_count = int((revision_counts >= 2).sum())

    rows: list[dict[str, Any]] = []
    category_specs = [
        ("partial_acceptance", current_outcomes["partial_acceptance"], responded),
        ("full_acceptance", current_outcomes["full_acceptance"], responded),
        ("full_rejection", current_outcomes["full_rejection"], responded),
        ("date_slips", slip_count, len(current_promises)),
        ("on_time_promises", on_time_count, len(current_promises)),
        ("price_changes", price_count, price_denominator),
        ("supplier_silence", len(silence), total_pos),
        ("multiple_revisions", revision_po_count, total_pos),
    ]
    for category, count, denominator in category_specs:
        rows.append({
            "scale": scale,
            "seed": int(seed),
            "category": category,
            "count": int(count),
            "denominator": int(denominator),
            "percentage": _percentage(int(count), int(denominator)),
            "target_proportion": float(target[category]),
        })
    return pd.DataFrame(rows, columns=["scale", "seed", "category", "count", "denominator", "percentage", "target_proportion"])
