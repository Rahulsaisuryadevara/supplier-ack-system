from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supplier_ack.generators.framework import generate_dataset, write_generated_data
from supplier_ack.rules.derived import reconciliation_summary
from supplier_ack.rules.thresholds import computed_delta, evaluate_threshold


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def starter(config):
    return generate_dataset(config, "starter", 20261022, validate=True)


def test_configured_edge_case_counts_and_internal_boolean_labels(starter, config):
    truth = starter["ground_truth_records"]
    counts = truth.loc[truth["issue_type"].notna(), "issue_type"].value_counts().to_dict()
    expected = config["anomaly_injection"]["counts"]["starter"]
    assert {key: counts.get(key, 0) for key in expected} == expected
    assert set(truth.loc[truth["issue_type"].notna(), "issue_type"]) == set(expected)
    for key in ("inventory_plans", "acknowledgement_lines", "promise_dates", "change_requests"):
        labelled = starter[key].loc[starter[key]["issue_type"].notna()]
        assert labelled["ground_truth"].eq(True).all()
    assert reconciliation_summary(starter["suppliers"].attrs["reconciliation_report"])[1] == 0


def test_ack_reference_variants_include_cross_po_and_nonexistent(starter):
    anomalies = starter["acknowledgement_lines"].loc[
        starter["acknowledgement_lines"]["issue_type"].eq("ACK_WRONG_PO_LINE")
    ]
    line_to_po = dict(zip(starter["po_lines"]["po_line_id"].astype(str), starter["po_lines"]["po_id"].astype(str)))
    variants = set()
    for row in anomalies.to_dict(orient="records"):
        line_id = str(row["po_line_id"])
        if line_id not in line_to_po:
            variants.add("missing_line")
        elif line_to_po[line_id] != str(row["po_id"]):
            variants.add("cross_po")
    assert variants == {"missing_line", "cross_po"}


def test_unapproved_plan_rows_link_to_changes_without_approval(starter):
    plans = starter["inventory_plans"].loc[
        starter["inventory_plans"]["issue_type"].eq("UNAPPROVED_CHANGE_UPDATES_PLAN")
    ]
    approved_ids = set(starter["approvals"].loc[starter["approvals"]["status"].eq("APPROVED"), "change_request_id"].astype(str))
    assert len(plans) == 5
    assert not set(plans["change_request_id"].astype(str)) & approved_ids
    assert plans["source"].eq("approved_change").all()


def test_valid_boundary_rows_are_exact_thresholds(starter, config):
    truth = starter["ground_truth_records"]
    boundaries = truth.loc[truth["boundary"].eq(True)]
    assert len(boundaries) == 4
    assert (boundaries["record_type"] == "AcknowledgementLine").sum() == 1
    assert (boundaries["record_type"] == "ChangeRequest").sum() == 3
    for row in boundaries.loc[boundaries["record_type"].eq("ChangeRequest")].to_dict(orient="records"):
        change = starter["change_requests"].loc[starter["change_requests"]["change_request_id"].eq(row["record_id"])].iloc[0].to_dict()
        rule = evaluate_threshold(change, config["approval_thresholds"])
        assert rule["required_approval_level"] == "planner"
        if change["change_type"] == "price":
            assert abs(float(computed_delta("price", change["old_value"], change["new_value"]))) == pytest.approx(float(config["approval_thresholds"]["price_change_pct"]))
        else:
            assert float(computed_delta("date", change["old_value"], change["new_value"])) == pytest.approx(float(config["approval_thresholds"]["date_slip_days"]))
    ack_truth = boundaries.loc[boundaries["record_type"].eq("AcknowledgementLine")].iloc[0]
    ack_line = starter["acknowledgement_lines"].loc[starter["acknowledgement_lines"]["acknowledgement_line_id"].eq(ack_truth["record_id"])].iloc[0]
    assert float(ack_line["accepted_qty"]) == float(ack_line["requested_qty"])


def test_seeded_injection_is_deterministic(config, starter):
    again = generate_dataset(config, "starter", 20261022, validate=True)
    cols = ["record_type", "record_id", "issue_type", "expected_decision", "boundary"]
    pd.testing.assert_frame_equal(starter["ground_truth_records"][cols], again["ground_truth_records"][cols])
    for table in ("inventory_plans", "acknowledgement_lines", "promise_dates"):
        labeled = starter[table].loc[starter[table]["issue_type"].notna(), [c for c in starter[table].columns if c in {"issue_type", "ground_truth", "inventory_plan_id", "acknowledgement_line_id", "promise_date_id"}]].reset_index(drop=True)
        labeled_again = again[table].loc[again[table]["issue_type"].notna(), labeled.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(labeled, labeled_again)


def test_ground_truth_files_are_separate_and_no_input_csv_label_leakage(starter, config, tmp_path):
    output = write_generated_data(starter, config, "starter", 20261022, output_dir=tmp_path)
    assert (output / "ground_truth.csv").is_file()
    assert (output / "ground_truth.json").is_file()
    payload = json.loads((output / "ground_truth.json").read_text(encoding="utf-8"))
    assert payload["seed"] == 20261022
    assert len(payload["records"]) == len(starter["ground_truth_records"])
    for path in output.glob("*.csv"):
        if path.name == "ground_truth.csv":
            continue
        columns = pd.read_csv(path, nrows=0).columns
        assert "issue_type" not in columns
        assert "ground_truth" not in columns
        assert "boundary" not in columns
    canonical = ROOT / "data" / "generated"
    assert (canonical / "ground_truth.csv").is_file()
    assert (canonical / "ground_truth.json").is_file()


def test_sparse_promise_revisions_fall_back_to_plan_history_without_losing_labels(config, tmp_path):
    """A seed with fewer promise revision pairs still injects the configured stale rows."""
    from supplier_ack.validation.suite import validate_directory

    seed = 20261023
    frames = generate_dataset(config, "starter", seed, validate=True, inject_anomalies=True)
    stale = frames["ground_truth_records"].loc[
        frames["ground_truth_records"]["issue_type"].eq("STALE_REVISION_OVERWRITE")
    ]
    assert len(stale) == config["anomaly_injection"]["counts"]["starter"]["STALE_REVISION_OVERWRITE"]
    assert set(stale["record_type"]).issubset({"PromiseDate", "InventoryPlan"})
    assert "InventoryPlan" in set(stale["record_type"])

    write_generated_data(frames, config, "starter", seed, output_dir=tmp_path, publish_ground_truth=False)
    result = validate_directory(tmp_path)
    assert result["overall_status"] == "PASS"
