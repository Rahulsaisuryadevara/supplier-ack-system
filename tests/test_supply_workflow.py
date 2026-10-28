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


def test_notifications_use_po_owner_and_are_traceable(supply_frames):
    frames = supply_frames
    notifications = frames["notifications"]
    recipients = frames["notification_recipient"]
    raised = notifications.loc[notifications["not_type"].eq("CHANGE_RAISED")]
    assert len(raised) == len(frames["change_requests"])
    po_owners = frames["purchase_orders"].set_index("po_id")["planner_actor_id"]
    for notice in raised.to_dict(orient="records"):
        got = recipients.loc[
            recipients["notification_id"].eq(notice["notification_id"])
            & recipients["actor_role"].eq("planner"), "recipient_actor_id"
        ]
        assert got.tolist() == [po_owners.loc[notice["po_id"]]]
        chain = trace(notice["notification_id"], frames)
        assert chain["change"]["change_request_id"] == notice["change_request_id"]
        if chain["acknowledgement"] is None:
            assert chain["trace_status"] == "complete_supplier_silence"
            assert "no supplier acknowledgement" in str(chain["change"]["reason_text"]).lower()
        else:
            assert chain["trace_status"] == "complete"
        assert chain["purchase_order"]["po_id"] == notice["po_id"]
        assert chain["supplier"]["supplier_id"] == chain["purchase_order"]["supplier_id"]

    assert {"CHANGE_RAISED", "APPROVAL_DECISION", "PLAN_UPDATED", "DOWNSTREAM_IMPACT", "SUPPLIER_SILENCE_CHASE", "WEEKLY_SUMMARY"}.issubset(set(notifications["not_type"]))

    def roles_for(notification_id):
        return set(recipients.loc[recipients["notification_id"].eq(notification_id), "actor_role"])

    plan_notices = notifications.loc[notifications["not_type"].eq("PLAN_UPDATED")]
    assert not plan_notices.empty
    for notice in plan_notices.to_dict(orient="records"):
        assert {"planner", "logistics_analyst"}.issubset(roles_for(notice["notification_id"]))
        owner_id = po_owners.loc[notice["po_id"]]
        assert recipients.loc[(recipients["notification_id"].eq(notice["notification_id"])) & recipients["actor_role"].eq("planner"), "recipient_actor_id"].tolist() == [owner_id]

    silence_notices = notifications.loc[notifications["not_type"].eq("SUPPLIER_SILENCE_CHASE")]
    assert len(silence_notices) == 10
    assert all({"planner", "supplier"}.issubset(roles_for(row["notification_id"])) for row in silence_notices.to_dict(orient="records"))

    date_impact_ids = set(frames["production_order_impact"].loc[frames["production_order_impact"]["impact_type"].eq("date_conflict"), "impact_id"])
    impact_notices = notifications.loc[notifications["not_type"].eq("DOWNSTREAM_IMPACT")]
    assert not impact_notices.empty
    assert all({"planner", "carrier_warehouse_operator"}.issubset(roles_for(row["notification_id"])) for row in impact_notices.to_dict(orient="records") if any(impact_id in str(row["body"]) for impact_id in date_impact_ids))
    weekly = notifications.loc[notifications["not_type"].eq("WEEKLY_SUMMARY")]
    assert len(weekly) == frames["actors"]["actor_role"].eq("operations_manager").sum()
    assert all(roles_for(row["notification_id"]) == {"operations_manager"} for row in weekly.to_dict(orient="records"))

    assert {"inventory_plan_updated", "downstream_impact_created", "notification_sent"}.issubset(set(frames["entity_event"]["event_type"]))


def test_impact_severity_worst_of_date_and_quantity_bands():
    assert compute_impact_severity(1, 1.0) == "LOW"
    assert compute_impact_severity(5, 2.0) == "MEDIUM"
    assert compute_impact_severity(12, 12.0) == "HIGH"
    assert compute_impact_severity(30, 4.0) == "CRITICAL"
    assert compute_impact_severity(0, 30.0) == "CRITICAL"
