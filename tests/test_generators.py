from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re

import pandas as pd
import pytest
import yaml

from supplier_ack.generators.framework import generate_master_data, write_generated_data
from supplier_ack.ids import matches_id_format
from supplier_ack.schema import ENTITIES

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "generator_config.yaml"


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_starter_scale_counts_and_exact_entity_columns(config):
    frames = generate_master_data(config, "starter", 20261022)
    assert len(frames["suppliers"]) == 40
    assert len(frames["purchase_orders"]) == 200
    assert len(frames["items"]) == 50
    assert len(frames["carriers"]) == 10
    assert len(frames["warehouses"]) == 4
    assert len(frames["po_lines"]) >= 200 * 2
    assert len(frames["po_lines"]) <= 200 * 6
    assert len(frames["actors"]) == 40 + 6 + 4 + 3 + 2
    assert frames["suppliers"].columns.tolist() == [f.name for f in ENTITIES["Supplier"].fields]
    assert frames["purchase_orders"].columns.tolist() == [f.name for f in ENTITIES["PurchaseOrder"].fields]
    assert frames["po_lines"].columns.tolist() == [f.name for f in ENTITIES["POLine"].fields]


def test_same_seed_produces_identical_frames(config):
    first = generate_master_data(config, "starter", 20261022)
    second = generate_master_data(config, "starter", 20261022)
    assert list(first) == list(second)
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name], check_dtype=True)


def test_seed_override_changes_stochastic_fields_but_not_scale_counts(config):
    first = generate_master_data(config, "starter", 20261022)
    second = generate_master_data(config, "starter", 20261023)
    assert len(first["purchase_orders"]) == len(second["purchase_orders"]) == 200
    assert first["suppliers"]["reliability_score"].tolist() != second["suppliers"]["reliability_score"].tolist()


def test_supplier_ids_fields_lead_times_and_correlated_reliability(config):
    frames = generate_master_data(config, "starter", 20261022)
    suppliers = frames["suppliers"]
    assert suppliers["supplier_id"].is_unique
    assert all(matches_id_format("Supplier", value) for value in suppliers["supplier_id"])
    assert suppliers["supplier_name"].is_unique
    assert suppliers["lead_time_days"].between(7, 90).all()
    assert (suppliers["lead_time_days"].between(7, 30).mean()) > 0.60
    assert suppliers["reliability_score"].between(0, 1).all()
    assert suppliers["on_time_rate"].between(0, 1).all()
    assert suppliers["reliability_score"].corr(suppliers["on_time_rate"]) > 0.60
    assert set(suppliers["region"]).issubset({"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"})
    carrier_ids = set(frames["carriers"]["carrier_id"])
    assert set(suppliers["preferred_carrier_id"]).issubset(carrier_ids)
    assert suppliers["issue_type"].isna().all() and suppliers["ground_truth"].isna().all()


def test_purchase_orders_have_parent_ids_and_weekday_order_dates(config):
    frames = generate_master_data(config, "starter", 20261022)
    pos = frames["purchase_orders"]
    suppliers = frames["suppliers"].set_index("supplier_id")
    assert pos["po_id"].is_unique
    assert all(matches_id_format("PurchaseOrder", value) for value in pos["po_id"])
    assert set(pos["supplier_id"]).issubset(set(suppliers.index))
    dates = pd.to_datetime(pos["order_date"])
    assert dates.dt.dayofweek.lt(5).all()
    assert dates.min() >= pd.Timestamp("2026-01-01")
    assert dates.max() <= pd.Timestamp("2026-06-30")
    merged = pos.merge(suppliers[["lead_time_days"]], left_on="supplier_id", right_index=True)
    delta = (pd.to_datetime(merged["required_delivery_date"]) - dates).dt.days
    assert (delta >= merged["lead_time_days"] + 2).all()
    actor_roles = frames["actors"].set_index("actor_id")["actor_role"]
    assert all(actor_roles.loc[actor_id] == "planner" for actor_id in pos["planner_actor_id"])
    assert all(actor_roles.loc[actor_id] == role for actor_id, role in zip(pos["created_by_actor_id"], pos["created_by_role"]))


def test_lines_have_parent_consistency_and_exact_computed_totals(config):
    frames = generate_master_data(config, "starter", 20261022)
    pos = frames["purchase_orders"].set_index("po_id")
    lines = frames["po_lines"]
    assert lines["po_line_id"].is_unique
    assert all(matches_id_format("POLine", value) for value in lines["po_line_id"])
    assert set(lines["po_id"]).issubset(set(pos.index))
    assert lines["requested_qty"].between(10, 5000).all()
    assert lines["unit_price"].ge(0).all()
    for row in lines[["requested_qty", "unit_price", "line_total"]].to_dict(orient="records"):
        exact = (Decimal(str(row["requested_qty"])) * Decimal(str(row["unit_price"]))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert Decimal(str(row["line_total"])).quantize(Decimal("0.01")) == exact
    assert (lines["po_line_id"].str.rsplit("-L", n=1).str[0] == lines["po_id"]).all()
    counts = lines.groupby("po_id").size()
    assert counts.between(2, 6).all()
    assert lines["status"].eq("DRAFT").all()
    assert lines["issue_type"].isna().all() and lines["ground_truth"].isna().all()
    line_sums = lines.groupby("po_id")["line_total"].sum().round(2)
    for po_id, amount in line_sums.items():
        assert round(float(pos.loc[po_id, "total_order_value"]), 2) == round(float(amount), 2)


def test_item_prices_stay_within_configured_item_bands(config):
    frames = generate_master_data(config, "starter", 20261022)
    item_prices = frames["items"].set_index("item_id")
    lines = frames["po_lines"]
    for row in lines[["item_id", "unit_price"]].to_dict(orient="records"):
        item = item_prices.loc[row["item_id"]]
        assert item["unit_price_min"] <= row["unit_price"] <= item["unit_price_max"]
        assert item["price_currency"] == "INR"


def test_master_reference_roster_contains_all_five_actor_roles(config):
    frames = generate_master_data(config, "starter", 20261022)
    assert set(frames["actors"]["actor_role"]) == {
        "supplier", "planner", "carrier_warehouse_operator", "logistics_analyst", "operations_manager"
    }
    supplier_actors = frames["actors"].loc[frames["actors"]["actor_role"] == "supplier"]
    assert supplier_actors["supplier_id"].equals(supplier_actors["actor_id"])


def test_line_totals_are_header_aggregates_not_independent_random_values(config):
    frames = generate_master_data(config, "starter", 20261022)
    expected = frames["po_lines"].groupby("po_id")["line_total"].sum().round(2)
    actual = frames["purchase_orders"].set_index("po_id")["total_order_value"].round(2)
    pd.testing.assert_series_equal(actual.sort_index(), expected.sort_index(), check_names=False)


def test_full_scale_counts_use_same_generator_code_path(config):
    frames = generate_master_data(config, "full", 20261022, validate=True)
    assert len(frames["suppliers"]) == 200
    assert len(frames["purchase_orders"]) == 10000
    assert len(frames["items"]) == 50
    assert len(frames["po_lines"]) >= 20000
    assert len(frames["po_lines"]) <= 60000
    assert frames["po_lines"].groupby("po_id").size().between(2, 6).all()


def test_csv_export_writes_tables_and_summary_with_readable_columns(config, tmp_path):
    frames = generate_master_data(config, "starter", 20261022)
    output = write_generated_data(frames, config, "starter", 20261022, tmp_path)
    assert (output / "generation_summary.json").exists()
    for name, frame in frames.items():
        loaded = pd.read_csv(output / f"{name}.csv")
        assert loaded.columns.tolist() == frame.columns.tolist()
        assert len(loaded) == len(frame)


def test_generator_modules_never_construct_or_use_global_rngs():
    generator_dir = ROOT / "src" / "supplier_ack" / "generators"
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in generator_dir.glob("*.py"))
    assert "np.random." not in all_text
    assert re.search(r"^\s*(?:import\s+random|from\s+random\s+import)\b", all_text, re.MULTILINE) is None
    # Only the single orchestrator creates the RNG. Entity modules accept it as an argument.
    assert all("default_rng(" not in path.read_text(encoding="utf-8") for path in generator_dir.glob("*.py") if path.name != "framework.py")
    framework_source = (generator_dir / "framework.py").read_text(encoding="utf-8")
    assert framework_source.count("default_rng(") == 1
