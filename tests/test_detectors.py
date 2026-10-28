from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from supplier_ack.metrics.detectors import (
    detect_boundary_cases,
    detect_impossible_promise_dates,
    detect_stale_revision_effective,
    detect_unapproved_plan_updates,
    detect_wrong_line_refs,
    evaluate_detections,
)

ROOT = Path(__file__).resolve().parents[1]


def test_starter_detection_has_perfect_precision_and_recall(tmp_path):
    result = evaluate_detections(ROOT / "data" / "samples", tmp_path / "detection_report.md")
    assert result["overall_pass"] is True
    assert result["ground_truth_anomaly_count"] == 20
    for cls in result["classes"]:
        assert cls["tp"] == 5
        assert cls["fp"] == 0
        assert cls["fn"] == 0
        assert cls["precision"] == cls["recall"] == cls["f1"] == 1.0
    assert (tmp_path / "detection_report.csv").exists()


def test_detectors_reject_label_columns():
    with pytest.raises(ValueError, match="forbidden label columns"):
        detect_wrong_line_refs({"acknowledgement_lines": pd.DataFrame({"issue_type": ["wrong"], "po_id": ["PO-1"]})})


def test_pure_detectors_detect_one_violation_each():
    unapproved = detect_unapproved_plan_updates({
        "inventory_plans": pd.DataFrame([{"inventory_plan_id": "IP-1", "source": "approved_change", "change_request_id": "CHG-1", "po_id": "PO-1", "po_line_id": "L1"}]),
        "change_requests": pd.DataFrame([{"change_request_id": "CHG-1", "change_type": "price", "old_value": 100, "new_value": 120, "status": "PENDING_APPROVAL"}]),
        "approvals": pd.DataFrame([{"change_request_id": "CHG-1", "approval_level": "operations_manager", "status": "PENDING", "approval_round": 1}]),
    })
    assert len(unapproved) == 1
    wrong = detect_wrong_line_refs({
        "acknowledgement_lines": pd.DataFrame([{"acknowledgement_line_id": "AL1", "po_id": "PO1", "po_line_id": "L2"}]),
        "po_lines": pd.DataFrame([{"po_line_id": "L2", "po_id": "PO2"}]),
    })
    assert len(wrong) == 1
    impossible = detect_impossible_promise_dates({
        "promise_dates": pd.DataFrame([{"promise_date_id": "PD1", "po_id": "PO1", "po_line_id": "L1", "promised_date": "2026-01-01"}]),
        "purchase_orders": pd.DataFrame([{"po_id": "PO1", "order_date": "2026-01-02"}]),
    })
    assert len(impossible) == 1
    stale = detect_stale_revision_effective({
        "promise_dates": pd.DataFrame([{"promise_date_id": "PD1", "po_line_id": "L1", "revision_no": 1, "status": "CURRENT"}, {"promise_date_id": "PD2", "po_line_id": "L1", "revision_no": 2, "status": "SUPERSEDED"}]),
        "inventory_plans": pd.DataFrame(),
    })
    assert len(stale) == 1


def test_boundary_report_is_not_anomaly_prediction():
    rows = detect_boundary_cases({"change_requests": pd.DataFrame([{"change_request_id": "CHG1", "change_type": "price", "old_value": 100, "new_value": 105}])})
    assert len(rows) == 1
    assert rows.iloc[0]["boundary_type"] == "price_threshold"
