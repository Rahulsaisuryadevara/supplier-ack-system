from __future__ import annotations

import pytest

from supplier_ack.rules.thresholds import can_apply, computed_delta, evaluate_threshold, required_approval_level


THRESHOLDS = {
    "price_change_pct": 5.0,
    "date_slip_days": 7,
    "quantity_change_pct": 10.0,
    "max_price_change_pct": 15.0,
    "max_date_slip_days": 30,
    "max_quantity_change_pct": 50.0,
}


@pytest.mark.parametrize(
    ("kind", "old", "new", "expected"),
    [
        ("price", "100.00", "105.00", 5.0),
        ("price", "100.00", "106.00", 6.0),
        ("quantity", "100", "90", -10.0),
        ("quantity", "100", "75", -25.0),
        ("date", "2026-10-01", "2026-10-08", 7.0),
    ],
)
def test_delta_is_computed_from_source_values(kind, old, new, expected):
    assert computed_delta(kind, old, new) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kind", "old", "new", "level", "downstream"),
    [
        ("price", "100", "105", "planner", False),
        ("price", "100", "106", "operations_manager", False),
        ("date", "2026-10-01", "2026-10-08", "planner", False),
        ("date", "2026-10-01", "2026-10-09", "operations_manager", True),
        ("quantity", "100", "90", "planner", False),
        ("quantity", "100", "89", "operations_manager", False),
    ],
)
def test_threshold_routing_is_config_driven(kind, old, new, level, downstream):
    change = {"change_type": kind, "old_value": old, "new_value": new}
    result = evaluate_threshold(change, THRESHOLDS)
    assert required_approval_level(change, THRESHOLDS) == level
    assert result["required_approval_level"] == level
    assert result["downstream_impact_flag"] is downstream


def test_can_apply_requires_approval_at_the_required_level():
    change = {
        "change_request_id": "CHG-PO-2026-000001-000001",
        "change_type": "price", "old_value": "100", "new_value": "110",
    }
    planner_only = [{
        "change_request_id": change["change_request_id"], "approval_round": 1,
        "approval_level": "planner", "status": "APPROVED",
    }]
    allowed, reason = can_apply(change, [])
    assert allowed is False and "no approval record" in reason
    allowed, reason = can_apply(change, planner_only, THRESHOLDS)
    assert allowed is False and "operations_manager" in reason
    approved = planner_only + [{
        "change_request_id": change["change_request_id"], "approval_round": 2,
        "approval_level": "operations_manager", "status": "APPROVED",
    }]
    assert can_apply(change, approved, THRESHOLDS)[0] is True


def test_latest_append_only_appeal_round_controls_application():
    change = {
        "change_request_id": "CHG-PO-2026-000001-000002",
        "change_type": "price", "old_value": "100", "new_value": "104",
    }
    approvals = [
        {"change_request_id": change["change_request_id"], "approval_round": 1,
         "approval_level": "planner", "status": "REJECTED"},
        {"change_request_id": change["change_request_id"], "approval_round": 2,
         "approval_level": "planner", "status": "APPROVED"},
    ]
    assert can_apply(change, approvals, THRESHOLDS)[0] is True
    assert [row["status"] for row in approvals] == ["REJECTED", "APPROVED"]
    approvals.append({
        "change_request_id": change["change_request_id"], "approval_round": 3,
        "approval_level": "planner", "status": "REJECTED",
    })
    allowed, reason = can_apply(change, approvals, THRESHOLDS)
    assert allowed is False and "latest 'planner' decision is REJECTED" in reason


def test_hard_policy_limits_are_deterministic_rejections():
    result = evaluate_threshold({"change_type": "quantity", "old_value": "100", "new_value": "40"}, THRESHOLDS)
    assert result["required_approval_level"] == "operations_manager"
    assert result["hard_limit_breach"] is True
    assert "Hard policy limit" in result["escalation_reason"]


def test_threshold_metadata_reports_configured_value_separately_from_measured_delta():
    result = evaluate_threshold({"change_type": "price", "old_value": "100", "new_value": "108"}, THRESHOLDS)
    assert result["threshold_value"] == 5.0
    assert result["configured_threshold"] == 5.0
    assert result["measured_delta"] == 8.0


def test_already_implemented_change_cannot_be_applied_again():
    change = {"change_request_id": "CHG-PO-2026-000001-000003", "change_type": "price",
              "old_value": "100", "new_value": "104", "status": "IMPLEMENTED"}
    approvals = [{"change_request_id": change["change_request_id"], "approval_round": 1,
                  "approval_level": "planner", "status": "APPROVED"}]
    allowed, reason = can_apply(change, approvals, THRESHOLDS)
    assert allowed is False and "IMPLEMENTED" in reason


def test_threshold_decision_recomputes_delta_from_old_and_new_values():
    change = {"change_type": "price", "old_value": "100", "new_value": "107", "delta": 1.0}
    result = evaluate_threshold(change, THRESHOLDS)
    assert result["delta"] == 7.0
    assert result["required_approval_level"] == "operations_manager"


def test_required_level_cannot_be_overridden_by_stale_route_metadata():
    change = {"change_request_id": "CHG-PO-2026-000001-000004", "change_type": "price",
              "old_value": "100", "new_value": "110", "required_approval_level": "planner"}
    planner_approval = [{"change_request_id": change["change_request_id"], "approval_round": 1,
                         "approval_level": "planner", "status": "APPROVED"}]
    allowed, reason = can_apply(change, planner_approval, THRESHOLDS)
    assert allowed is False and "operations_manager" in reason
