"""Seeded, parameterized synthetic data generation orchestration."""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from numpy.random import Generator, default_rng

from supplier_ack.ids import IDFactory
from supplier_ack.schema import ACKNOWLEDGEMENT_LINE_FIELDS, ENTITIES, validate_dataset
from supplier_ack.generators.acks import generate_acknowledgements_and_promises
from supplier_ack.generators.changes import generate_changes
from supplier_ack.generators.common import active_scale_config, get_config
from supplier_ack.generators.coverage import build_coverage_report, validate_coverage_config
from supplier_ack.generators.po_lines import generate_po_lines
from supplier_ack.generators.purchase_orders import finalize_purchase_order_totals, generate_purchase_orders
from supplier_ack.generators.reference_data import generate_reference_data
from supplier_ack.generators.suppliers import generate_suppliers


def _new_rng(seed: int) -> Generator:
    """The sole construction point for the per-run RNG."""
    return default_rng(seed)


def _config_for_scale(cfg: Mapping[str, Any], scale: str, seed: int) -> dict[str, Any]:
    if scale not in cfg.get("scales", {}):
        raise ValueError(f"unknown scale {scale!r}; expected {tuple(cfg.get('scales', {}))}")
    config = dict(cfg)
    config["active_scale"] = scale
    config["seed"] = seed
    active_scale_config(config)
    return config


def _validate_frames(generated: Mapping[str, pd.DataFrame]) -> None:
    key_to_entity = {spec.table_name: entity_name for entity_name, spec in ENTITIES.items()}
    integer_columns = {
        spec.table_name: {field.name for field in spec.fields if field.sql_type.upper() == "INTEGER"}
        for spec in ENTITIES.values()
    }
    integer_columns["acknowledgement_lines"] = {
        field.name for field in ACKNOWLEDGEMENT_LINE_FIELDS if field.sql_type.upper() == "INTEGER"
    }
    validation_context: dict[str, list[dict[str, Any]]] = {}
    for key, dataframe in generated.items():
        if not isinstance(dataframe, pd.DataFrame) or key in {"coverage_report", "silence_report"}:
            continue
        rows = []
        for source_row in dataframe.to_dict(orient="records"):
            normalized_row: dict[str, Any] = {}
            for field_name, value in source_row.items():
                try:
                    missing_value = bool(pd.isna(value))
                except (TypeError, ValueError):
                    missing_value = False
                if missing_value:
                    normalized_row[field_name] = None
                elif hasattr(value, "item"):
                    normalized_value = value.item()
                    if field_name in integer_columns.get(key, set()) and isinstance(normalized_value, float) and normalized_value.is_integer():
                        normalized_value = int(normalized_value)
                    normalized_row[field_name] = normalized_value
                elif field_name in integer_columns.get(key, set()) and isinstance(value, float) and value.is_integer():
                    normalized_row[field_name] = int(value)
                else:
                    normalized_row[field_name] = value
            rows.append(normalized_row)
        validation_context[key] = rows
        if key in key_to_entity:
            validation_context[key_to_entity[key]] = rows
    errors = validate_dataset(validation_context)
    if errors:
        preview = "\n".join(f"- {err}" for err in errors[:40])
        more = f"\n... and {len(errors) - 40} additional validation errors" if len(errors) > 40 else ""
        raise ValueError(f"generated data failed schema validation ({len(errors)} errors):\n{preview}{more}")


def generate_master_data(
    cfg: Mapping[str, Any],
    scale: str = "starter",
    seed: int | None = None,
    *,
    validate: bool = True,
    rng: Generator | None = None,
    id_factory: IDFactory | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate support masters, Supplier, PurchaseOrder, and POLine.

    ``rng`` and ``id_factory`` can be injected by the end-to-end orchestrator so
    randomness and nomenclature state are continuous across every generation step.
    When called standalone, the function creates its own deterministic objects.
    """
    seed_value = int(seed if seed is not None else cfg.get("seed", 20261022))
    if seed_value < 0:
        raise ValueError("seed must be a non-negative integer")
    config = _config_for_scale(cfg, scale, seed_value)
    rng = rng if rng is not None else _new_rng(seed_value)
    factory = id_factory if id_factory is not None else IDFactory()

    suppliers = generate_suppliers(rng, config, id_factory=factory)
    references = generate_reference_data(rng, config, suppliers)
    purchase_orders = generate_purchase_orders(
        rng, config, suppliers, references["actors"], references["warehouses"],
        references["carriers"], id_factory=factory,
    )
    po_lines = generate_po_lines(rng, config, purchase_orders, references["items"], id_factory=factory)
    purchase_orders = finalize_purchase_order_totals(purchase_orders, po_lines)

    generated: dict[str, pd.DataFrame] = {
        "suppliers": suppliers,
        "purchase_orders": purchase_orders,
        "po_lines": po_lines,
        **references,
    }
    for entity_name, dataframe_key in (
        ("Supplier", "suppliers"), ("PurchaseOrder", "purchase_orders"), ("POLine", "po_lines"),
    ):
        expected = [field.name for field in ENTITIES[entity_name].fields]
        if generated[dataframe_key].columns.tolist() != expected:
            raise RuntimeError(
                f"{entity_name} columns differ from data dictionary: "
                f"{generated[dataframe_key].columns.tolist()!r}"
            )
    if validate:
        _validate_frames(generated)
    return generated


def generate_dataset(
    cfg: Mapping[str, Any],
    scale: str = "starter",
    seed: int | None = None,
    *,
    validate: bool = True,
) -> dict[str, pd.DataFrame]:
    """Generate master data and all configured acknowledgement/change events.

    The RNG and IDFactory are each initialized exactly once and threaded through
    all entity generators. ``event_count`` means acknowledgement revision rows plus
    ChangeRequest rows; Approval rows are decisions on those requests, not events
    for purposes of the requested generation-volume baseline.
    """
    seed_value = int(seed if seed is not None else cfg.get("seed", 20261022))
    config = _config_for_scale(cfg, scale, seed_value)
    validate_coverage_config(config, scale)
    rng = _new_rng(seed_value)
    factory = IDFactory()
    generated = generate_master_data(
        config, scale, seed_value, validate=False, rng=rng, id_factory=factory,
    )
    transaction_frames = generate_acknowledgements_and_promises(
        rng, config, generated["purchase_orders"], generated["po_lines"],
        generated["suppliers"], generated["actors"], id_factory=factory,
        warehouses=generated["warehouses"], carriers=generated["carriers"],
    )
    generated["purchase_orders"] = transaction_frames["purchase_orders"]
    generated["po_lines"] = transaction_frames["po_lines"]
    generated["acknowledgements"] = transaction_frames["acknowledgements"]
    generated["acknowledgement_lines"] = transaction_frames["acknowledgement_lines"]
    generated["promise_dates"] = transaction_frames["promise_dates"]
    generated["entity_event"] = transaction_frames["entity_event"]
    generated["silence_report"] = transaction_frames["silence_report"]

    cr_frames = generate_changes(
        rng, config, generated["purchase_orders"], generated["po_lines"],
        generated["acknowledgements"], generated["acknowledgement_lines"],
        generated["promise_dates"], generated["actors"],
        transaction_frames["price_change_specs"], transaction_frames["change_request_count"],
        id_factory=factory, silence_report=generated["silence_report"],
        existing_events=generated["entity_event"],
    )
    generated.update(cr_frames)

    # The supplier's acknowledged quote is observable immediately, but the projected
    # operational price must not apply a price change that an approval rejected.
    price_decisions = generated["change_requests"].loc[
        generated["change_requests"]["request_type"].eq("PRICE_CHANGE"),
        ["po_line_id", "requested_unit_price", "status"],
    ]
    if not price_decisions.empty:
        line_position = {str(value): position for position, value in enumerate(generated["po_lines"]["po_line_id"])}
        for decision in price_decisions.to_dict(orient="records"):
            line_id = str(decision["po_line_id"])
            row_idx = line_position[line_id]
            if decision["status"] == "REJECTED":
                projected_price = float(generated["po_lines"].iloc[row_idx]["unit_price"])
            else:
                projected_price = float(decision["requested_unit_price"])
            generated["po_lines"].at[row_idx, "projected_unit_price"] = projected_price
            projected_qty = Decimal(str(generated["po_lines"].at[row_idx, "projected_qty"]))
            projected_value = (projected_qty * Decimal(str(projected_price))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            generated["po_lines"].at[row_idx, "projected_value"] = float(projected_value)

    generated["coverage_report"] = build_coverage_report(config, scale, seed_value, generated)

    # Ensure the primary entity frames are always the exact source-of-truth schema columns.
    for entity_name in ("Supplier", "PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate", "ChangeRequest", "Approval"):
        table = ENTITIES[entity_name].table_name
        expected = [field.name for field in ENTITIES[entity_name].fields]
        if generated[table].columns.tolist() != expected:
            raise RuntimeError(f"{entity_name} DataFrame columns differ from schema.py")

    if validate:
        _validate_frames(generated)
        actual_events = len(generated["acknowledgements"]) + len(generated["change_requests"])
        expected_events = int(active_scale_config(config)["event_count"])
        if actual_events != expected_events:
            raise ValueError(f"event volume mismatch: expected {expected_events} ACK+ChangeRequest rows, got {actual_events}")
    return generated


def _distribution_summary(frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    suppliers = frames["suppliers"]
    lines = frames["po_lines"]
    purchase_orders = frames["purchase_orders"]
    po_lines_per_order = purchase_orders["po_id"].map(lines.groupby("po_id").size()).fillna(0)
    quantities = lines["requested_qty"].astype(float)
    leads = suppliers["lead_time_days"].astype(float)

    def stats(series: pd.Series) -> dict[str, float]:
        if series.empty:
            return {"mean": 0.0, "median": 0.0, "p90": 0.0}
        return {
            "mean": round(float(series.mean()), 3),
            "median": round(float(series.median()), 3),
            "p90": round(float(series.quantile(0.90)), 3),
        }

    correlation = float(suppliers["reliability_score"].corr(suppliers["on_time_rate"])) if len(suppliers) > 1 else 1.0
    rows_to_count = {
        name: int(len(frame)) for name, frame in frames.items()
        if name not in {"coverage_report", "silence_report"}
    }
    summary: dict[str, Any] = {
        "row_counts": rows_to_count,
        "distributions": {
            "requested_quantity": stats(quantities),
            "supplier_lead_time_days": stats(leads),
            "lines_per_purchase_order": stats(po_lines_per_order),
            "reliability_on_time_pearson_correlation": round(correlation, 4),
        },
    }
    if "change_requests" in frames and "acknowledgements" in frames:
        summary["event_counts"] = {
            "acknowledgement_rows": int(len(frames["acknowledgements"])),
            "change_request_rows": int(len(frames["change_requests"])),
            "acknowledgement_plus_change_request_rows": int(len(frames["acknowledgements"]) + len(frames["change_requests"])),
        }
    if "change_requests" in frames and "approvals" in frames:
        changes = frames["change_requests"]
        approvals = frames["approvals"]
        summary["change_workflow"] = {
            "change_counts_by_type": {str(key): int(value) for key, value in changes["change_type"].value_counts().sort_index().items()} if "change_type" in changes else {},
            "approval_decision_distribution": {str(key): int(value) for key, value in approvals["status"].value_counts().sort_index().items()} if not approvals.empty else {},
            "escalated_change_count": int(approvals.loc[approvals["status"].eq("ESCALATED"), "change_request_id"].nunique()) if not approvals.empty else 0,
            "operations_manager_review_count": int(approvals.loc[approvals["approval_level"].eq("operations_manager"), "change_request_id"].nunique()) if not approvals.empty else 0,
            "silence_chase_count": int(changes["reason_text"].str.contains("No supplier acknowledgement", case=False, na=False).sum()),
            "escalation_reasons_by_threshold": {str(key): int(value) for key, value in approvals.loc[approvals["status"].eq("ESCALATED"), "threshold_name"].value_counts().sort_index().items()} if not approvals.empty else {},
        }
    if "coverage_report" in frames:
        summary["coverage_report"] = frames["coverage_report"].to_dict(orient="records")
    if "silence_report" in frames:
        summary["supplier_silence_report_rows"] = int(len(frames["silence_report"]))
    # ACK workflow metrics are computed from retained revision history and the
    # current PromiseDate state, with silence kept in the all-PO denominator.
    if {"acknowledgements", "purchase_orders", "promise_dates", "po_lines"}.issubset(frames):
        acknowledgements = frames["acknowledgements"]
        po_count = len(purchase_orders)
        acknowledged_po_count = int(acknowledgements["po_id"].nunique()) if not acknowledgements.empty else 0
        latest_acks = acknowledgements.loc[acknowledgements["status"].ne("SUPERSEDED")] if not acknowledgements.empty else acknowledgements
        partial_count = int(latest_acks["status"].eq("PARTIALLY_ACCEPTED").sum()) if not latest_acks.empty else 0
        current_promises = frames["promise_dates"].loc[frames["promise_dates"]["status"].eq("CURRENT")] if not frames["promise_dates"].empty else frames["promise_dates"]
        required_dates = {str(row["po_line_id"]): str(row["required_date"]) for row in lines.to_dict(orient="records")}
        slips: list[int] = []
        from datetime import date as _date
        for row in current_promises.to_dict(orient="records"):
            line_id = str(row["po_line_id"])
            if line_id in required_dates:
                slips.append((_date.fromisoformat(str(row["promised_date"])) - _date.fromisoformat(required_dates[line_id])).days)
        revision_counts = {str(po_id): int(count) for po_id, count in acknowledgements.groupby("po_id").size().items()} if not acknowledgements.empty else {}
        histogram: dict[str, int] = {}
        for count in range(0, 5):
            histogram[str(count)] = sum(1 for po in purchase_orders["po_id"].astype(str) if revision_counts.get(po, 0) == count)
        summary["acknowledgement_metrics"] = {
            "ack_coverage_pct": round(100.0 * acknowledged_po_count / po_count, 4) if po_count else 0.0,
            "acknowledged_po_count": acknowledged_po_count,
            "purchase_order_count": po_count,
            "partial_acceptance_pct": round(100.0 * partial_count / len(latest_acks), 4) if len(latest_acks) else 0.0,
            "partial_acceptance_count": partial_count,
            "latest_acknowledgement_count": int(len(latest_acks)),
            "average_current_date_slip_days": round(sum(slips) / len(slips), 4) if slips else 0.0,
            "current_promised_line_count": len(slips),
            "revision_count_histogram": histogram,
        }
    return summary


def write_generated_data(
    frames: Mapping[str, pd.DataFrame],
    cfg: Mapping[str, Any],
    scale: str,
    seed: int,
    output_dir: str | Path | None = None,
) -> Path:
    """Write generated tables, silence report, coverage report, and summary JSON."""
    if output_dir is None:
        if scale == "starter":
            output_dir = get_config(cfg, "workflow", "sample_output_dir", default="data/samples")
        else:
            output_dir = get_config(cfg, "workflow", "output_dir", default="data/generated")
    target = Path(output_dir)
    if not target.is_absolute():
        target = Path.cwd() / target
    target.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(target / f"{name}.csv", index=False, encoding="utf-8", lineterminator="\n")
    summary = _distribution_summary(frames)
    summary["scale"] = scale
    summary["seed"] = int(seed)
    summary["config_source"] = "config/generator_config.yaml"
    summary["target_event_count"] = int(active_scale_config(_config_for_scale(cfg, scale, seed))["event_count"])
    (target / "generation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (target / "coverage_report.json").write_text(
        json.dumps(frames.get("coverage_report", pd.DataFrame()).to_dict(orient="records"), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def print_generation_summary(frames: Mapping[str, pd.DataFrame], scale: str, seed: int, output_dir: str | Path) -> None:
    summary = _distribution_summary(frames)
    print(f"Synthetic supplier acknowledgement data generated (selected scale={scale}, seed={seed})")
    print(f"Output directory: {output_dir}")
    print("\nRow counts")
    for name, count in summary["row_counts"].items():
        print(f"  {name:22s} {count:>8,d}")
    if "event_counts" in summary:
        counts = summary["event_counts"]
        print("\nEvent volume (acknowledgement revision rows + change-request rows)")
        print(f"  Acknowledgements       {counts['acknowledgement_rows']:>8,d}")
        print(f"  Change requests        {counts['change_request_rows']:>8,d}")
        print(f"  Total                   {counts['acknowledgement_plus_change_request_rows']:>8,d}")
    print("\nDistribution statistics (mean / median / p90)")
    for name in ("requested_quantity", "supplier_lead_time_days", "lines_per_purchase_order"):
        row = summary["distributions"][name]
        units = " units" if name == "requested_quantity" else " days" if name == "supplier_lead_time_days" else " lines"
        print(f"  {name:30s} {row['mean']:>9,.3f} / {row['median']:>9,.3f} / {row['p90']:>9,.3f}{units}")
    print(f"  {'reliability/on-time correlation':30s} {summary['distributions']['reliability_on_time_pearson_correlation']:.4f}")
    if "coverage_report" in frames:
        print("\nCoverage report (observed count and denominator-relative percentage)")
        for report_scale, group in frames["coverage_report"].groupby("scale", sort=True):
            print(f"  [{report_scale}]")
            for row in group.to_dict(orient="records"):
                print(f"    {row['category']:22s} {row['count']:>7,d} / {row['denominator']:<7,d} = {row['percentage']:>6.2f}% (target {row['target_proportion'] * 100:>5.1f}%)")
    print(f"\nSupplier silence report rows: {len(frames.get('silence_report', pd.DataFrame()))}")
    if "acknowledgement_metrics" in summary:
        metrics = summary["acknowledgement_metrics"]
        print("\nAcknowledgement workflow metrics")
        print(f"  ACK coverage: {metrics['ack_coverage_pct']:.2f}% ({metrics['acknowledged_po_count']:,}/{metrics['purchase_order_count']:,} POs)")
        print(f"  Partial acceptance: {metrics['partial_acceptance_pct']:.2f}% ({metrics['partial_acceptance_count']:,}/{metrics['latest_acknowledgement_count']:,} latest ACKs)")
        print(f"  Average current date slip: {metrics['average_current_date_slip_days']:.2f} days across {metrics['current_promised_line_count']:,} promised lines")
        print("  ACK revision-count histogram (0 includes silence):")
        for revision_count, count in metrics["revision_count_histogram"].items():
            print(f"    {revision_count} revision(s): {count:,} PO(s)")
    if "change_requests" in frames and "approvals" in frames:
        changes = frames["change_requests"]
        approvals = frames["approvals"]
        print("\nChange requests by type")
        for change_type, count in changes["change_type"].value_counts().sort_index().items():
            print(f"  {change_type:22s} {int(count):>8,d}")
        escalated_ids = set(approvals.loc[approvals["status"].eq("ESCALATED"), "change_request_id"].astype(str))
        ops_ids = set(approvals.loc[approvals["approval_level"].eq("operations_manager"), "change_request_id"].astype(str))
        silence_mask = changes["reason_text"].str.contains("No supplier acknowledgement", case=False, na=False)
        pending_silence = int(silence_mask.sum())
        print("\nThreshold routing")
        print(f"  Planner auto/quick route {len(set(changes['change_request_id'].astype(str)) - ops_ids - set(changes.loc[silence_mask, 'change_request_id'].astype(str))):>8,d}")
        print(f"  Operations-manager route {len(ops_ids):>8,d}")
        print(f"  Silence chase pending     {pending_silence:>8,d}")
        print("\nApproval decision distribution")
        for decision, count in approvals["status"].value_counts().sort_index().items():
            print(f"  {decision:22s} {int(count):>8,d}")
        escalations = approvals.loc[approvals["status"].eq("ESCALATED")]
        print("\nEscalation reasons")
        if escalations.empty:
            print("  None in this dataset")
        else:
            for threshold_name, group in escalations.groupby("threshold_name", dropna=False, sort=True):
                example = str(group.iloc[0]["decision_reason"] or "threshold breach")
                print(f"  {threshold_name}: {len(group)} case(s); {example}")


def generate_and_write(
    cfg: Mapping[str, Any], scale: str = "starter", seed: int | None = None,
    output_dir: str | Path | None = None, *, validate: bool = True,
) -> dict[str, pd.DataFrame]:
    """Generate the requested dataset and print actual coverage for both scales."""
    seed_value = int(seed if seed is not None else cfg.get("seed", 20261022))
    frames = generate_dataset(cfg, scale=scale, seed=seed_value, validate=validate)
    other_scale = "full" if scale == "starter" else "starter"
    # Build the second scale with identical generator/config code solely to report observed coverage.
    other_frames = generate_dataset(cfg, scale=other_scale, seed=seed_value, validate=False)
    coverage = pd.concat([frames["coverage_report"], other_frames["coverage_report"]], ignore_index=True)
    frames["coverage_report"] = coverage.sort_values(["scale", "category"]).reset_index(drop=True)
    written_to = write_generated_data(frames, cfg, scale, seed_value, output_dir=output_dir)
    print_generation_summary(frames, scale, seed_value, written_to)
    return frames
