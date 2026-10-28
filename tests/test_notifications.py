from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from supplier_ack.generators.framework import generate_dataset
from supplier_ack.generators.supply import trace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def supply_frames():
    config = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))
    return generate_dataset(config, "starter", 20261022, validate=True, inject_anomalies=False)


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
