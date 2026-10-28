from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
import os
import subprocess
import sys

import pandas as pd
import pytest
import yaml

from supplier_ack.generators.coverage import COVERAGE_CATEGORIES, build_coverage_report, validate_coverage_config
from supplier_ack.generators.framework import generate_dataset, print_generation_summary
from supplier_ack.schema import ENTITIES

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "generator_config.yaml"


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def starter(config):
    return generate_dataset(config, "starter", 20261022, validate=True)


@pytest.fixture(scope="module")
def full(config):
    return generate_dataset(config, "full", 20261022, validate=False)


def _current_acknowledgements(frames):
    return frames["acknowledgements"].loc[~frames["acknowledgements"]["status"].eq("SUPERSEDED")]


def _category(report, category):
    return report.loc[report["category"].eq(category)].iloc[0]


def test_default_seed_volumes_and_event_semantics(config):
    assert config["seed"] == 20261022
    assert config["scales"]["starter"]["po_count"] == 200
    assert config["scales"]["starter"]["event_count"] == 300
    assert config["scales"]["full"]["po_count"] == 10000
    assert config["scales"]["full"]["event_count"] == 15000


def test_starter_and_full_have_exact_ack_plus_change_request_event_counts(starter, full):
    assert len(starter["purchase_orders"]) == 200
    assert len(starter["acknowledgements"]) + len(starter["change_requests"]) == 300
    assert len(full["purchase_orders"]) == 10000
    assert len(full["acknowledgements"]) + len(full["change_requests"]) == 15000
    assert len(full["suppliers"]) == 200


def test_every_required_coverage_category_is_configured_and_reported(config, starter, full):
    assert set(config["coverage"]["target_proportions"]) == set(COVERAGE_CATEGORIES)
    for frames in (starter, full):
        report = frames["coverage_report"]
        assert report["category"].tolist() == list(COVERAGE_CATEGORIES)
        assert report["count"].ge(0).all()
        assert report["denominator"].ge(0).all()
        assert report["percentage"].between(0, 100).all()
        assert report["target_proportion"].between(0, 1).all()


def test_ack_outcome_coverage_hits_configured_mix(starter, full, config):
    for scale, frames in (("starter", starter), ("full", full)):
        current = _current_acknowledgements(frames)
        denominator = len(current)
        for status, category in (
            ("PARTIALLY_ACCEPTED", "partial_acceptance"),
            ("ACCEPTED", "full_acceptance"),
            ("REJECTED", "full_rejection"),
        ):
            observed = int(current["status"].eq(status).sum())
            row = _category(frames["coverage_report"], category)
            assert row["count"] == observed
            assert row["denominator"] == denominator
            assert abs(observed / denominator - config["coverage"]["target_proportions"][category]) <= 1 / denominator + 1e-12


def test_all_acknowledgements_reconcile_quantities_and_reason_rules(starter, full):
    for frames in (starter, full):
        acks = frames["acknowledgements"]
        assert ((acks["requested_qty"] - acks["ack_accepted_qty"] - acks["ack_rejected_qty"]).abs() < 0.001).all()
        partial_or_rejected = acks["status"].isin(["PARTIALLY_ACCEPTED", "REJECTED"])
        assert acks.loc[partial_or_rejected, "rejection_reason"].isin(["capacity", "price", "stock", "logistics"]).all()
        current = _current_acknowledgements(frames)
        assert current.loc[current["status"].eq("ACCEPTED"), "rejection_reason"].isna().all()


def test_silence_rows_have_no_ack_and_response_due_is_past(starter, full, config):
    expected = {"starter": 10, "full": 500}
    for scale, frames in (("starter", starter), ("full", full)):
        silence = frames["silence_report"]
        assert len(silence) == expected[scale]
        assert silence["issue_type"].eq("MISSING_ACK").all()
        assert silence["ground_truth"].eq("MISSING_ACK").all()
        assert set(silence["po_id"]).isdisjoint(set(frames["acknowledgements"]["po_id"]))
        assert pd.to_datetime(silence["response_due_at"]).dt.date.lt(date.fromisoformat(config["coverage"]["as_of_date"])).all()
        row = _category(frames["coverage_report"], "supplier_silence")
        assert row["count"] == len(silence)
        assert row["denominator"] == len(frames["purchase_orders"])


def test_multiple_revisions_are_retained_and_link_forward(starter, full, config):
    expected_target = {"starter": 16, "full": 800}
    for scale, frames in (("starter", starter), ("full", full)):
        acks = frames["acknowledgements"]
        counts = acks.groupby("po_id").size()
        revision_pos = counts[counts >= 2]
        assert len(revision_pos) == expected_target[scale]
        assert revision_pos.between(2, 4).all()
        by_id = acks.set_index("ack_id")
        for po_id in revision_pos.index:
            ordered = acks.loc[acks["po_id"].eq(po_id)].sort_values("revision_no")
            assert ordered["revision_no"].tolist() == list(range(1, len(ordered) + 1))
            for prior, later in zip(ordered.iloc[:-1].to_dict("records"), ordered.iloc[1:].to_dict("records")):
                assert prior["status"] == "SUPERSEDED"
                assert prior["superseded_by"] == later["ack_id"]
                assert by_id.loc[prior["superseded_by"], "po_id"] == po_id
            assert ordered.iloc[-1]["status"] != "SUPERSEDED"
            assert pd.isna(ordered.iloc[-1]["superseded_by"])
        row = _category(frames["coverage_report"], "multiple_revisions")
        assert row["count"] == expected_target[scale]
        assert row["denominator"] == len(frames["purchase_orders"])


def test_promise_date_revisions_preserve_chain_and_current_snapshot(starter, full):
    for frames in (starter, full):
        promises = frames["promise_dates"]
        by_id = promises.set_index("promise_date_id")
        assert promises["promise_date_id"].is_unique
        group_sizes = promises.groupby("po_line_id").size()
        revision_line_ids = group_sizes[group_sizes.gt(1)].index
        assert promises.groupby("po_line_id")["status"].apply(lambda col: int(col.eq("CURRENT").sum())).eq(1).all()
        for line_id in revision_line_ids:
            ordered = promises.loc[promises["po_line_id"].eq(line_id)].sort_values("revision_no")
            assert ordered["status"].eq("SUPERSEDED").sum() == len(ordered) - 1
            assert ordered.iloc[-1]["status"] == "CURRENT"
            for prior, later in zip(ordered.iloc[:-1].to_dict("records"), ordered.iloc[1:].to_dict("records")):
                assert prior["superseded_by"] == later["promise_date_id"]
                assert by_id.loc[prior["superseded_by"], "po_line_id"] == prior["po_line_id"]
                assert prior["promised_date"] == later["prior_promised_date"]
        assert (promises.loc[promises["revision_no"].eq(1), "prior_promised_date"].isna()).all()


def test_date_slip_mix_and_realistic_slip_range(starter, full, config):
    for frames in (starter, full):
        current = frames["promise_dates"].loc[frames["promise_dates"]["status"].eq("CURRENT")].merge(
            frames["po_lines"][["po_line_id", "required_date"]], on="po_line_id", validate="many_to_one"
        )
        promised = pd.to_datetime(current["promised_date"])
        required = pd.to_datetime(current["required_date"])
        slip_days = (promised - required).dt.days
        slipped = int(slip_days.gt(0).sum())
        on_time = int(slip_days.le(0).sum())
        assert slipped + on_time == len(current)
        assert slip_days.loc[slip_days.gt(0)].between(3, 60).all()
        assert abs(slipped / len(current) - config["coverage"]["target_proportions"]["date_slips"]) <= 1 / len(current) + 1e-12
        assert abs(on_time / len(current) - config["coverage"]["target_proportions"]["on_time_promises"]) <= 1 / len(current) + 1e-12


def test_price_change_coverage_has_auditable_change_request_and_bounded_magnitude(starter, full, config):
    for frames in (starter, full):
        lines = frames["po_lines"]
        eligible = lines.loc[lines["ack_accepted_qty"].gt(0)]
        changed = eligible.loc[(eligible["acknowledged_unit_price"] - eligible["unit_price"]).abs().gt(0.005)]
        price_requests = frames["change_requests"].loc[frames["change_requests"]["request_type"].eq("PRICE_CHANGE")]
        assert len(changed) == len(price_requests)
        assert len(changed) / len(eligible) == pytest.approx(config["coverage"]["target_proportions"]["price_changes"], abs=1 / len(eligible) + 1e-12)
        assert (price_requests["requested_unit_price"] != price_requests["previous_unit_price"]).all()
        pct = (price_requests["requested_unit_price"] - price_requests["previous_unit_price"]).abs() / price_requests["previous_unit_price"] * 100
        assert pct.between(0.5, 15.0).all()
        assert (price_requests["requested_unit_price"] > price_requests["previous_unit_price"]).mean() > 0.65
        price_match = price_requests[["po_line_id", "requested_unit_price"]].merge(
            lines[["po_line_id", "acknowledged_unit_price"]], on="po_line_id", how="left", validate="one_to_one"
        )
        assert (pd.to_numeric(price_match["acknowledged_unit_price"]).to_numpy() == pd.to_numeric(price_match["requested_unit_price"]).to_numpy()).all()
        line_projection = lines[["po_line_id", "unit_price", "projected_unit_price"]]
        projected_match = price_requests[["po_line_id", "requested_unit_price", "status"]].merge(
            line_projection, on="po_line_id", how="left", validate="one_to_one"
        )
        rejected = projected_match["status"].eq("REJECTED")
        assert (projected_match.loc[rejected, "projected_unit_price"].astype(float).to_numpy() == projected_match.loc[rejected, "unit_price"].astype(float).to_numpy()).all()
        assert (projected_match.loc[~rejected, "projected_unit_price"].astype(float).to_numpy() == projected_match.loc[~rejected, "requested_unit_price"].astype(float).to_numpy()).all()


def test_change_request_and_approval_foreign_keys_resolve(starter, full):
    for frames in (starter, full):
        po_ids = set(frames["purchase_orders"]["po_id"])
        ack_ids = set(frames["acknowledgements"]["ack_id"])
        line_ids = set(frames["po_lines"]["po_line_id"])
        cr = frames["change_requests"]
        assert set(cr["po_id"]).issubset(po_ids)
        assert set(cr["po_line_id"].dropna()).issubset(line_ids)
        approvals = frames["approvals"]
        assert set(approvals["change_request_id"]).issubset(set(cr["change_request_id"]))
        assert approvals["approval_id"].is_unique
        assert approvals["approval_id"].str.startswith("APR-CHG-").all()
        assert set(frames["promise_dates"]["ack_id"]).issubset(ack_ids)


def test_each_entity_dataframe_matches_dictionary_columns(starter, full):
    table_to_entity = {spec.table_name: name for name, spec in ENTITIES.items()}
    for frames in (starter, full):
        for table, entity_name in table_to_entity.items():
            if table in frames:
                assert frames[table].columns.tolist() == [field.name for field in ENTITIES[entity_name].fields]


def test_coverage_config_warns_for_impossible_revision_and_event_volume(config):
    impossible = deepcopy(config)
    impossible["scales"]["starter"]["event_count"] = 10
    impossible["coverage"]["target_proportions"]["supplier_silence"] = 0.20
    impossible["coverage"]["target_proportions"]["multiple_revisions"] = 0.90
    messages = validate_coverage_config(impossible, "starter", emit_warnings=False)
    assert any("multiple-revision target" in message for message in messages)
    assert any("below the minimum" in message for message in messages)


def test_coverage_config_rejects_invalid_probability_sums(config):
    invalid = deepcopy(config)
    invalid["coverage"]["target_proportions"]["full_acceptance"] = 0.60
    with pytest.raises(ValueError, match="must sum to 1"):
        validate_coverage_config(invalid, "starter", emit_warnings=False)


def test_same_seed_reproduces_transactions_and_coverage(config):
    first = generate_dataset(config, "starter", 20261022, validate=False)
    second = generate_dataset(config, "starter", 20261022, validate=False)
    for table in ("acknowledgements", "promise_dates", "change_requests", "approvals", "coverage_report"):
        pd.testing.assert_frame_equal(first[table], second[table])


def test_print_summary_includes_both_scale_coverage_reports(config, starter, full, capsys, tmp_path):
    frames = dict(starter)
    frames["coverage_report"] = pd.concat([starter["coverage_report"], full["coverage_report"]], ignore_index=True)
    print_generation_summary(frames, "starter", 20261022, tmp_path)
    output = capsys.readouterr().out
    assert "[starter]" in output and "[full]" in output
    for category in COVERAGE_CATEGORIES:
        assert category in output


def test_same_seed_is_stable_across_python_processes():
    source = r"""
import hashlib
import yaml
from supplier_ack.generators.framework import generate_dataset
with open('config/generator_config.yaml', encoding='utf-8') as handle:
    config = yaml.safe_load(handle)
frames = generate_dataset(config, 'starter', 20261022, validate=False)
payload = ''.join(frames[name].to_csv(index=False) for name in (
    'suppliers', 'purchase_orders', 'po_lines', 'acknowledgements',
    'promise_dates', 'change_requests', 'approvals', 'coverage_report'
))
print(hashlib.sha256(payload.encode('utf-8')).hexdigest())
"""
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    first = subprocess.run([sys.executable, '-c', source], cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=30)
    second = subprocess.run([sys.executable, '-c', source], cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=30)
    assert first.stdout.strip() == second.stdout.strip()


def test_change_types_use_computed_deltas_and_rule_based_approval_routing(starter, full, config):
    from supplier_ack.rules.thresholds import computed_delta, evaluate_threshold

    threshold_config = config["approval_thresholds"]
    for frames in (starter, full):
        changes = frames["change_requests"]
        approvals = frames["approvals"]
        assert set(changes["change_type"]) == {"price", "date", "quantity"}
        assert changes["change_request_id"].is_unique
        assert changes["delta"].notna().all()

        approval_by_change = {
            change_id: group.sort_values("approval_round").to_dict("records")
            for change_id, group in approvals.groupby("change_request_id", sort=False)
        }
        for change in changes.to_dict("records"):
            kind = str(change["change_type"])
            expected_delta = computed_delta(kind, change["old_value"], change["new_value"])
            assert float(change["delta"]) == pytest.approx(expected_delta, abs=0.00011)
            history = approval_by_change[change["change_request_id"]]
            assert history, f"no approval history for {change['change_request_id']}"
            is_silence = "No supplier acknowledgement" in str(change["reason_text"])
            if is_silence:
                assert change["status"] == "UNDER_REVIEW"
                assert len(history) == 1
                assert history[0]["approval_level"] == "planner"
                assert history[0]["status"] == "PENDING"
                continue

            rule = evaluate_threshold(change, threshold_config)
            if rule["required_approval_level"] == "planner":
                assert len(history) == 1
                assert history[0]["approval_level"] == "planner"
                assert history[0]["status"] == ("REJECTED" if rule["hard_limit_breach"] else "APPROVED")
            else:
                assert len(history) == 2
                assert history[0]["approval_level"] == "planner"
                assert history[0]["status"] == "ESCALATED"
                assert history[1]["approval_level"] == "operations_manager"
                assert history[1]["status"] == ("REJECTED" if rule["hard_limit_breach"] else "APPROVED")
            assert change["status"] == ("REJECTED" if rule["hard_limit_breach"] else "IMPLEMENTED")
            if kind == "date" and rule["downstream_impact_flag"]:
                assert change["issue_type"] == "DATE_SLIP_REQUIRES_APPROVAL"
                related_events = frames["entity_event"].loc[
                    frames["entity_event"]["target_change_request_id"].eq(change["change_request_id"])
                ]
                assert related_events["payload_json"].str.contains('"downstream_impact_flag":true').any()


def test_approval_workflow_is_append_only_audited_and_silence_sends_chase(starter):
    frames = starter
    changes = frames["change_requests"]
    approvals = frames["approvals"]
    events = frames["entity_event"]
    notifications = frames["notifications"]

    assert approvals["approval_id"].is_unique
    assert set(approvals["approval_level"]) == {"planner", "operations_manager"}
    assert events["event_id"].is_unique
    assert {"change_requested", "approval_decided", "change_applied"}.issubset(set(events["event_type"]))
    assert notifications["status"].eq("SENT").all()
    assert notifications["title"].str.contains("overdue", case=False).all()
    assert set(notifications["source_event_id"]).issubset(set(events["event_id"]))
    assert set(notifications["change_request_id"]).issubset(set(changes["change_request_id"]))
    silence = changes.loc[changes["reason_text"].str.contains("No supplier acknowledgement", case=False, na=False)]
    assert len(silence) == 10
    assert silence["requested_by_role"].eq("planner").all()
    assert silence["status"].eq("UNDER_REVIEW").all()
    assert notifications["change_request_id"].nunique() == len(silence)
    assert approvals["status"].isin(["APPROVED", "REJECTED", "PENDING", "ESCALATED"]).all()
