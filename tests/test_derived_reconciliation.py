from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from supplier_ack.generators.framework import generate_dataset
from supplier_ack.rules.derived import (
    compute_line_total,
    compute_percent_delta,
    derive_ack_status,
    reconcile,
    reconciliation_summary,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("requested", "accepted", "expected"),
    [
        (10, 0, "full_reject"),
        (10, 10, "full_accept"),
        (10, 4, "partial_accept"),
        (10, 10, "revised"),
        (1.0004, 1.0000, "full_accept"),  # compares persisted 3dp quantities
        (1, 0.0004, "full_reject"),
        (1, 0.5, "partial_accept"),
    ],
)
def test_ack_status_boundaries_and_business_rounding(requested, accepted, expected):
    assert derive_ack_status(requested, accepted, revised=(expected == "revised")) == expected


def test_derived_arithmetic_uses_explicit_money_and_percent_rounding():
    assert compute_line_total("1.005", "1") == Decimal("1.01")
    assert compute_percent_delta(3, 2) == Decimal("-33.3333")


@pytest.fixture(scope="module")
def generated_dataset():
    config = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))
    return generate_dataset(config, "starter", 20261022, validate=True, inject_anomalies=False)


def test_clean_starter_reconciles_every_derived_field_and_invariant(generated_dataset):
    # Reconcile the clean baseline before Step 7 injection.
    report = reconcile(generated_dataset)
    checked, mismatches = reconciliation_summary(report)
    assert checked >= 10_000
    assert mismatches == 0
    assert all(row["mismatch_count"] == 0 for row in report.values())
    for required in ("POLine", "PurchaseOrder", "Acknowledgement", "PromiseDate", "ChangeRequest",
                     "InventoryPlan", "ProductionOrder", "Supplier", "Notification", "EntityEvent"):
        assert required in report
        assert report[required]["checked_count"] > 0


def test_reconciler_reports_tampered_source_amount():
    config = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))
    original = generate_dataset(config, "starter", 20261022, validate=True, inject_anomalies=False)
    broken = {key: frame.copy(deep=True) if isinstance(frame, pd.DataFrame) else deepcopy(frame)
              for key, frame in original.items()}
    broken["po_lines"].loc[broken["po_lines"].index[0], "line_total"] += 1.0
    report = reconcile(broken)
    assert report["POLine"]["mismatch_count"] >= 1
    assert any(row["field"] == "line_total" for row in report["POLine"]["sample_mismatches"])


def test_generation_stores_zero_mismatch_report(generated_dataset):
    stored = generated_dataset["suppliers"].attrs["reconciliation_report"]
    assert reconciliation_summary(stored)[1] == 0


def test_reconciler_detects_corrupted_values_in_each_invariant_group(generated_dataset):
    import json

    from supplier_ack.schema import STATUS_TRANSITIONS

    broken = {key: frame.copy(deep=True) if isinstance(frame, pd.DataFrame) else deepcopy(frame)
              for key, frame in generated_dataset.items()}
    broken["po_lines"].loc[0, "line_total"] += 1.0
    broken["acknowledgement_lines"].loc[0, "accepted_qty"] += 1.0
    broken["promise_dates"].loc[0, "slip_days"] += 1
    broken["change_requests"].loc[0, "delta_abs"] += 1.0
    broken["inventory_plans"].loc[broken["inventory_plans"]["is_effective"].eq(1).idxmax(), "projected_qty"] += 1.0
    broken["production_orders"].loc[0, "delay_days"] += 1
    current_rate = float(broken["suppliers"].loc[0, "ack_rate"])
    broken["suppliers"].loc[0, "ack_rate"] = 0.1234 if abs(current_rate - 0.1234) > 1e-8 else 0.9876
    broken["notifications"].loc[0, "open_impact_count"] += 1

    events = broken["entity_event"]
    for index, row in events.iterrows():
        entity_type = str(row.get("entity_type"))
        if entity_type not in STATUS_TRANSITIONS or pd.isna(row.get("previous_state")) or pd.isna(row.get("new_state")):
            continue
        try:
            old_state = json.loads(row["previous_state"])
            new_state = json.loads(row["new_state"])
        except (TypeError, ValueError):
            continue
        if old_state.get("status") and new_state.get("status"):
            new_state["status"] = "INVALID_STATUS"
            events.at[index, "new_state"] = json.dumps(new_state)
            break

    report = reconcile(broken)
    assert report["POLine"]["mismatch_count"] > 0
    assert report["Acknowledgement"]["mismatch_count"] > 0
    assert report["PromiseDate"]["mismatch_count"] > 0
    assert report["ChangeRequest"]["mismatch_count"] > 0
    assert report["InventoryPlan"]["mismatch_count"] > 0
    assert report["ProductionOrder"]["mismatch_count"] > 0
    assert report["Supplier"]["mismatch_count"] > 0
    assert report["Notification"]["mismatch_count"] > 0
    assert report["EntityEvent"]["mismatch_count"] > 0
