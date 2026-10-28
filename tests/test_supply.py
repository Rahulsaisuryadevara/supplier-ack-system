from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from supplier_ack.generators.framework import generate_dataset
from supplier_ack.generators.supply import trace
from supplier_ack.rules.impact import compute_impact_severity

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def supply_frames():
    config = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))
    return generate_dataset(config, "starter", 20261022, validate=True, inject_anomalies=False)


def test_every_po_line_has_an_immutable_baseline_and_one_effective_plan(supply_frames):
    frames = supply_frames
    plans = frames["inventory_plans"]
    assert plans.loc[plans["plan_version"].eq(1), "po_line_id"].nunique() == len(frames["po_lines"])
    assert plans.loc[plans["source"].eq("po_baseline"), "projected_qty"].equals(
        plans.loc[plans["plan_version"].eq(1), "projected_qty"]
    )
    assert plans.groupby("po_line_id")["plan_version"].apply(lambda values: sorted(values.tolist()) == list(range(1, len(values) + 1))).all()
    assert plans.groupby("po_line_id")["is_effective"].sum().eq(1).all()
    for row in plans.loc[plans["plan_version"].gt(1)].to_dict(orient="records"):
        previous = plans.loc[plans["inventory_plan_id"].eq(row["previous_version_id"])].iloc[0]
        assert previous["po_line_id"] == row["po_line_id"]
        assert previous["superseded_by"] == row["inventory_plan_id"]


def test_pending_or_rejected_change_hard_blocks_new_plan_versions(supply_frames):
    frames = supply_frames
    plans = frames["inventory_plans"]
    changes = frames["change_requests"]
    for line_id, group in changes.loc[changes["po_line_id"].notna()].groupby("po_line_id"):
        line_changes = group
        has_blocking_change = line_changes["status"].ne("IMPLEMENTED").any()
        versions = plans.loc[plans["po_line_id"].astype(str).eq(str(line_id))]
        if has_blocking_change:
            assert versions["plan_version"].max() == 1, f"blocked change moved projection for {line_id}"
        else:
            assert versions["source"].isin(["po_baseline", "approved_ack", "approved_change"]).all()
    changed_versions = plans.loc[plans["source"].eq("approved_change")]
    status_by_id = changes.set_index("change_request_id")["status"]
    assert not changed_versions.empty
    assert changed_versions["change_request_id"].map(status_by_id).eq("IMPLEMENTED").all()


def test_impacts_are_only_from_implemented_changes_and_severity_is_computed(supply_frames):
    frames = supply_frames
    impacts = frames["production_order_impact"]
    assert not impacts.empty
    change_status = frames["change_requests"].set_index("change_request_id")["status"]
    assert impacts["change_request_id"].map(change_status).eq("IMPLEMENTED").all()
    for impact in impacts.to_dict(orient="records"):
        assert impact["severity"] == compute_impact_severity(impact["slip_days"], impact["shortfall_pct"])
    assert {"date_conflict", "quantity_shortfall"}.issubset(set(impacts["impact_type"]))
    events = frames["entity_event"]
    assert "downstream_impact_created" in set(events["event_type"])
    changed = events.loc[events["event_type"].eq("production_order_status_changed")]
    assert not changed.empty
    assert set(changed["actor_role"]).issubset({"planner", "operations_manager"})


def test_impact_severity_worst_of_date_and_quantity_bands():
    assert compute_impact_severity(1, 1.0) == "LOW"
    assert compute_impact_severity(5, 2.0) == "MEDIUM"
    assert compute_impact_severity(12, 12.0) == "HIGH"
    assert compute_impact_severity(30, 4.0) == "CRITICAL"
    assert compute_impact_severity(0, 30.0) == "CRITICAL"
