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
from supplier_ack.generators.anomalies import inject_labelled_edge_cases
from supplier_ack.generators.changes import generate_changes
from supplier_ack.generators.supply import generate_supply_workflow, trace as trace_notification
from supplier_ack.generators.common import active_scale_config, get_config
from supplier_ack.generators.coverage import build_coverage_report, validate_coverage_config
from supplier_ack.generators.po_lines import generate_po_lines
from supplier_ack.generators.purchase_orders import finalize_purchase_order_totals, generate_purchase_orders
from supplier_ack.generators.reference_data import generate_reference_data
from supplier_ack.generators.suppliers import generate_suppliers
from supplier_ack.rules.derived import derive_supplier_scores, reconcile, reconciliation_summary


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
    inject_anomalies: bool = True,
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

    supply_frames = generate_supply_workflow(
        rng, config, generated["purchase_orders"], generated["po_lines"], generated["suppliers"],
        generated["actors"], generated["acknowledgements"], generated["acknowledgement_lines"],
        generated["promise_dates"], generated["change_requests"], generated["approvals"],
        generated["notifications"], generated["entity_event"], id_factory=factory,
    )
    generated.update(supply_frames)

    # Supplier operational scores are derived from the actual transaction rows, not
    # sampled master attributes. The same library recomputes them during reconciliation.
    score_map = derive_supplier_scores(generated)
    generated["suppliers"] = generated["suppliers"].copy(deep=True)
    for field in ("ack_rate", "on_time_promise_rate", "avg_slip_days"):
        generated["suppliers"][field] = generated["suppliers"]["supplier_id"].map(
            {supplier_id: values[field] for supplier_id, values in score_map.items()}
        )

    # Hard clean-data gate: this runs even when schema validation is skipped. Store
    # the report in DataFrame attrs so the CLI can print it without re-running work.
    reconciliation = reconcile(generated, config.get("approval_thresholds", {}))
    checked, mismatches = reconciliation_summary(reconciliation)
    generated["suppliers"].attrs["reconciliation_report"] = reconciliation
    if mismatches:
        samples = [sample for entity in reconciliation.values() for sample in entity["sample_mismatches"]]
        preview = "\n".join(f"- {item}" for item in samples[:20])
        raise ValueError(
            f"derived-value reconciliation failed: {mismatches} mismatch(es) across {checked} checks\n{preview}"
        )

    generated["coverage_report"] = build_coverage_report(config, scale, seed_value, generated)

    # Ensure the primary entity frames are always the exact source-of-truth schema columns.
    for entity_name in ("Supplier", "PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate", "ChangeRequest", "Approval", "InventoryPlan", "ProductionOrder", "Notification"):
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

    # Generation Step 7 is a distinct, post-validation stage. The reconciliation
    # report above is the clean-baseline report; injected rows intentionally violate
    # documented rules and are labelled internally plus in the separate target file.
    if inject_anomalies:
        generated = inject_labelled_edge_cases(generated, config, scale, rng, seed_value)
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
        if name not in {"coverage_report", "silence_report", "ground_truth_records", "injection_summary"}
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
    if "injection_summary" in frames:
        summary["anomaly_injection"] = {
            str(row["issue_type"]): int(row["injected_count"])
            for row in frames["injection_summary"].to_dict(orient="records")
        }
        summary["ground_truth_row_count"] = int(len(frames.get("ground_truth_records", pd.DataFrame())))
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
    if "inventory_plans" in frames:
        plans = frames["inventory_plans"]
        summary["projected_supply"] = {
            "baseline_plan_versions": int(plans["plan_version"].eq(1).sum()),
            "approved_ack_versions": int(plans["source"].eq("approved_ack").sum()),
            "approved_change_versions": int(plans["source"].eq("approved_change").sum()),
            "effective_versions": int(plans["is_effective"].eq(1).sum()),
            "lines_held_at_baseline": int(plans.loc[plans["is_effective"].eq(1), "source"].eq("po_baseline").sum()),
        }
    if "production_orders" in frames:
        summary["downstream_schedule"] = {
            "production_orders": int(len(frames["production_orders"])),
            "orders_at_risk": int(frames["production_orders"]["status"].eq("AT_RISK").sum()),
            "orders_rescheduled": int(frames["production_orders"]["status"].eq("RESCHEDULED").sum()),
            "impact_counts_by_type": {str(k): int(v) for k, v in frames.get("production_order_impact", pd.DataFrame()).get("impact_type", pd.Series(dtype=str)).value_counts().sort_index().items()},
            "impact_severity_distribution": {str(k): int(v) for k, v in frames.get("production_order_impact", pd.DataFrame()).get("severity", pd.Series(dtype=str)).value_counts().sort_index().items()},
        }
    if "notifications" in frames:
        notifications = frames["notifications"]
        summary["notification_workflow"] = {
            "notification_count": int(len(notifications)),
            "counts_by_type": {str(k): int(v) for k, v in notifications["not_type"].value_counts().sort_index().items()},
            "recipient_links": int(len(frames.get("notification_recipient", pd.DataFrame()))),
            "notifications_with_change_trace": int(notifications["change_request_id"].notna().sum()),
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
    label_columns = ["issue_type", "ground_truth", "boundary"]
    json_state_columns = ("payload_json", "previous_state", "new_state")
    freshly_written: set[str] = set()

    def strip_label_keys(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip_label_keys(item) for key, item in value.items()
                    if key not in {"issue_type", "ground_truth", "boundary"}}
        if isinstance(value, list):
            return [strip_label_keys(item) for item in value]
        return value

    for name, frame in frames.items():
        if name in {"ground_truth_records", "injection_summary"}:
            continue
        export_frame = frame.drop(columns=label_columns, errors="ignore").copy()
        if name == "entity_event" and not frame.attrs.get("label_keys_scrubbed", False):
            for json_col in json_state_columns:
                if json_col not in export_frame.columns:
                    continue
                def clean_json(raw: Any) -> Any:
                    if pd.isna(raw):
                        return raw
                    try:
                        payload = json.loads(str(raw))
                    except (ValueError, TypeError):
                        return raw
                    return json.dumps(strip_label_keys(payload), sort_keys=True, separators=(",", ":"))
                export_frame[json_col] = export_frame[json_col].map(clean_json)
        filename = f"{name}.csv"
        export_frame.to_csv(target / filename, index=False, encoding="utf-8", lineterminator="\n")
        freshly_written.add(filename)

    # Ground-truth labels are target-only artifacts, never input features. Publish
    # them beside the chosen output and at the canonical data/generated path.
    truth = frames.get("ground_truth_records", pd.DataFrame())
    truth_records = truth.to_dict(orient="records") if isinstance(truth, pd.DataFrame) else []
    truth_json = json.dumps({"scale": scale, "seed": int(seed), "records": truth_records}, indent=2, sort_keys=True, default=str) + "\n"
    truth.to_csv(target / "ground_truth.csv", index=False, encoding="utf-8", lineterminator="\n")
    (target / "ground_truth.json").write_text(truth_json, encoding="utf-8")
    canonical_truth_dir = Path.cwd() / "data" / "generated"
    canonical_truth_dir.mkdir(parents=True, exist_ok=True)
    # The canonical target file represents the full-scale evaluation labels.
    # Starter exports and tests writing to temporary directories must never replace it.
    if canonical_truth_dir.resolve() != target.resolve() and scale == "full":
        truth.to_csv(canonical_truth_dir / "ground_truth.csv", index=False, encoding="utf-8", lineterminator="\n")
        (canonical_truth_dir / "ground_truth.json").write_text(truth_json, encoding="utf-8")

    # Migrate legacy exports produced by older revisions, then fail closed. Files
    # emitted during this call already had label columns removed and JSON payloads
    # scrubbed in memory, so they need only a cheap header check.
    def strip_and_check_export(directory: Path, fresh_files: set[str]) -> None:
        for csv_path in directory.glob("*.csv"):
            if csv_path.name == "ground_truth.csv":
                continue
            header = pd.read_csv(csv_path, nrows=0).columns
            leaked = set(header).intersection(label_columns)
            needs_json_scrub = bool(set(header).intersection(json_state_columns)) and csv_path.name not in fresh_files
            if leaked or needs_json_scrub:
                legacy = pd.read_csv(csv_path, low_memory=False)
                legacy.drop(columns=list(leaked), inplace=True, errors="ignore")
                for json_col in json_state_columns:
                    if json_col not in legacy.columns or not needs_json_scrub:
                        continue
                    def scrub_state(raw: Any) -> Any:
                        if pd.isna(raw):
                            return raw
                        try:
                            payload = json.loads(str(raw))
                        except (ValueError, TypeError):
                            return raw
                        return json.dumps(strip_label_keys(payload), sort_keys=True, separators=(",", ":"))
                    legacy[json_col] = legacy[json_col].map(scrub_state)
                legacy.to_csv(csv_path, index=False, encoding="utf-8", lineterminator="\n")
            header = pd.read_csv(csv_path, nrows=0).columns
            leaked = set(header).intersection(label_columns)
            if leaked:
                raise ValueError(f"export leakage check failed for {csv_path.name}: {sorted(leaked)}")
    strip_and_check_export(target, freshly_written)

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
    if "projected_supply" in summary:
        metrics = summary["projected_supply"]
        print("\nProjected supply / InventoryPlan versioning")
        for metric, value in metrics.items():
            print(f"  {metric.replace('_', ' '):34s} {value:>8,d}")
    if "downstream_schedule" in summary:
        metrics = summary["downstream_schedule"]
        print("\nDownstream production schedule")
        for metric in ("production_orders", "orders_at_risk", "orders_rescheduled"):
            print(f"  {metric.replace('_', ' '):34s} {metrics[metric]:>8,d}")
        print("  Impact counts by type:")
        for impact_type, count in metrics["impact_counts_by_type"].items():
            print(f"    {impact_type:30s} {count:>8,d}")
        print("  Impact severity distribution:")
        for severity, count in metrics["impact_severity_distribution"].items():
            print(f"    {severity:30s} {count:>8,d}")
    if "notification_workflow" in summary:
        metrics = summary["notification_workflow"]
        print("\nNotification workflow")
        for metric in ("notification_count", "recipient_links", "notifications_with_change_trace"):
            print(f"  {metric.replace('_', ' '):34s} {metrics[metric]:>8,d}")
        for notice_type, count in metrics["counts_by_type"].items():
            print(f"  {notice_type:34s} {count:>8,d}")
        print("\nThree example notification traces (notification → change when present → ACK → PO → supplier)")
        examples = []
        for wanted_type in ("CHANGE_RAISED", "APPROVAL_DECISION", "DOWNSTREAM_IMPACT"):
            candidates = frames["notifications"].loc[frames["notifications"]["not_type"].eq(wanted_type)]
            if not candidates.empty:
                examples.append(candidates.iloc[0])
        if len(examples) < 3:
            for _, candidate in frames["notifications"].iterrows():
                if len(examples) >= 3:
                    break
                if all(str(candidate["notification_id"]) != str(row["notification_id"]) for row in examples):
                    examples.append(candidate)
        for index, row in enumerate(examples[:3], start=1):
            chain = trace_notification(str(row["notification_id"]), frames)
            notice = chain["notification"]
            change = chain["change"]
            ack = chain["acknowledgement"]
            po = chain["purchase_order"]
            supplier = chain["supplier"]
            print(f"  {index}. {notice['notification_id']} ({notice['not_type']})")
            print(f"     change={change.get('change_request_id') if change else 'none (ACK-only)'}; ACK={ack.get('ack_id') if ack else 'unavailable'}; PO={po.get('po_id') if po else 'unavailable'}; supplier={supplier.get('supplier_id') if supplier else 'unavailable'}; trace={chain['trace_status']}")
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
    if "injection_summary" in frames:
        print("\nControlled anomaly injection (post-baseline; labels excluded from input CSVs)")
        for row in frames["injection_summary"].to_dict(orient="records"):
            print(f"  {row['issue_type']:38s} {int(row['injected_count']):>6,d}")
        print(f"  Ground-truth rows (including boundary and decision labels): {len(frames.get('ground_truth_records', pd.DataFrame())):,}")
    report = frames.get("suppliers", pd.DataFrame()).attrs.get("reconciliation_report", {})
    if report:
        checked, mismatches = reconciliation_summary(report)
        print(f"\nDerived-value reconciliation (checked={checked}, mismatches={mismatches})")
        for entity_name, values in report.items():
            print(f"  {entity_name:22s} checked={int(values['checked_count']):>6,d}  mismatches={int(values['mismatch_count']):>3,d}")
            for sample in values["sample_mismatches"]:
                print(f"    mismatch: {sample}")


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
