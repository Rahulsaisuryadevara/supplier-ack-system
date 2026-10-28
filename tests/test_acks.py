from __future__ import annotations

from datetime import date
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import pytest
import yaml

from supplier_ack.generators.framework import generate_dataset

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def starter_frames():
    cfg = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text(encoding="utf-8"))
    return generate_dataset(cfg, "starter", 20261022, validate=True)


def test_each_ack_line_snapshot_reconciles_to_source_po_line(starter_frames):
    frames = starter_frames
    snapshots = frames["acknowledgement_lines"]
    source_lines = frames["po_lines"].set_index("po_line_id")
    assert not snapshots.empty
    for row in snapshots.to_dict(orient="records"):
        source = source_lines.loc[row["po_line_id"]]
        assert row["po_id"] == source["po_id"]
        assert Decimal(str(row["requested_qty"])).quantize(Decimal("0.001")) == Decimal(str(source["requested_qty"])).quantize(Decimal("0.001"))
        assert Decimal(str(row["accepted_qty"])).quantize(Decimal("0.001")) + Decimal(str(row["rejected_qty"])).quantize(Decimal("0.001")) == Decimal(str(row["requested_qty"])).quantize(Decimal("0.001"))
        if row["rejected_qty"] > 0:
            assert row["rejected_reason"] in {"capacity", "price", "stock", "logistics"}
        else:
            assert pd.isna(row["rejected_reason"])


def test_line_deltas_are_computed_from_source_values(starter_frames):
    frames = starter_frames
    snapshots = frames["acknowledgement_lines"]
    source_lines = frames["po_lines"].set_index("po_line_id")
    promises = frames["promise_dates"].set_index(["ack_id", "po_line_id"])
    for row in snapshots.to_dict(orient="records"):
        requested = Decimal(str(row["requested_qty"]))
        accepted = Decimal(str(row["accepted_qty"]))
        requested_price = Decimal(str(row["requested_unit_price"]))
        quote = Decimal(str(row["acknowledged_unit_price"]))
        expected_qty_delta = (Decimal("100") * (accepted - requested) / requested).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        expected_price_delta = (Decimal("100") * (quote - requested_price) / requested_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if requested_price else Decimal("0")
        assert Decimal(str(row["qty_delta_pct"])).quantize(Decimal("0.0001")) == expected_qty_delta
        assert Decimal(str(row["price_delta_pct"])).quantize(Decimal("0.0001")) == expected_price_delta
        key = (row["ack_id"], row["po_line_id"])
        if row["accepted_qty"] > 0:
            promise = promises.loc[key]
            required = date.fromisoformat(str(source_lines.loc[row["po_line_id"], "required_date"]))
            expected_slip = (date.fromisoformat(str(promise["promised_date"])) - required).days
            assert int(row["date_slip_days"]) == expected_slip
        else:
            assert pd.isna(row["date_slip_days"])


def test_response_timestamps_and_deadlines_match_parent_po_exactly(starter_frames):
    frames = starter_frames
    po_by_id = frames["purchase_orders"].set_index("po_id")
    acks = frames["acknowledgements"]
    line_snapshots = frames["acknowledgement_lines"]
    for ack in acks.to_dict(orient="records"):
        po = po_by_id.loc[ack["po_id"]]
        assert ack["po_id"] == str(po.name)
        assert ack["response_due_at"] == po["response_due_at"]
        assert pd.Timestamp(ack["acknowledged_at"]).date() >= date.fromisoformat(str(po["order_date"]))
        matching = line_snapshots.loc[line_snapshots["ack_id"].eq(ack["ack_id"])]
        assert matching["response_timestamp"].eq(ack["acknowledged_at"]).all()
        assert matching["po_id"].eq(ack["po_id"]).all()


def test_promise_qty_and_logistics_references_match_ack_line_and_masters(starter_frames):
    frames = starter_frames
    snapshots = frames["acknowledgement_lines"].set_index(["ack_id", "po_line_id"])
    warehouses = frames["warehouses"].set_index("warehouse_id")
    carriers = frames["carriers"].set_index("carrier_id")
    actors = frames["actors"].set_index("actor_id")
    po_by_id = frames["purchase_orders"].set_index("po_id")
    for promise in frames["promise_dates"].to_dict(orient="records"):
        line = snapshots.loc[(promise["ack_id"], promise["po_line_id"])]
        assert Decimal(str(promise["promised_qty"])).quantize(Decimal("0.001")) == Decimal(str(line["accepted_qty"])).quantize(Decimal("0.001"))
        assert promise["po_id"] == po_by_id.loc[promise["po_id"]].name
        assert promise["ship_from_location"] == warehouses.loc[promise["ship_from_warehouse_id"], "warehouse_name"]
        assert promise["carrier_reference"] == carriers.loc[promise["carrier_id"], "carrier_code"]
        assert actors.loc[promise["carrier_operator_actor_id"], "actor_role"] == "carrier_warehouse_operator"
        assert promise["created_by_role"] == "supplier"
        assert promise["created_by_actor_id"] == po_by_id.loc[promise["po_id"], "supplier_id"]
        assert date.fromisoformat(str(promise["promised_date"])) >= date.fromisoformat(str(po_by_id.loc[promise["po_id"], "order_date"]))
        assert date.fromisoformat(str(promise["effective_date"])) >= date.fromisoformat(str(promise["created_at"])[:10])
        assert date.fromisoformat(str(promise["response_due_date"])) >= date.fromisoformat(str(promise["effective_date"]))


def test_one_supplier_event_exists_for_every_ack_revision(starter_frames):
    frames = starter_frames
    acks = frames["acknowledgements"].set_index("ack_id")
    events = frames["entity_event"]
    ack_events = events.loc[events["entity_type"].eq("Acknowledgement")]
    assert len(ack_events) == len(acks)
    assert ack_events["entity_id"].is_unique
    assert set(ack_events["entity_id"]) == set(acks.index)
    for event in ack_events.to_dict(orient="records"):
        ack = acks.loc[event["entity_id"]]
        expected_type = "ack_submitted" if int(ack["revision_no"]) == 1 else "ack_revised"
        assert event["event_type"] == expected_type
        assert event["actor_role"] == "supplier"
        assert event["actor_id"] == ack["supplier_id"]
        assert event["target_ack_id"] == event["entity_id"]


def test_revision_rows_are_full_snapshots_and_superseded_pointers_resolve(starter_frames):
    frames = starter_frames
    acks = frames["acknowledgements"]
    by_id = acks.set_index("ack_id")
    for po_id, group in acks.groupby("po_id"):
        ordered = group.sort_values("revision_no")
        assert ordered["revision_no"].tolist() == list(range(1, len(ordered) + 1))
        for prior, later in zip(ordered.iloc[:-1].to_dict("records"), ordered.iloc[1:].to_dict("records")):
            assert prior["status"] == "SUPERSEDED"
            assert prior["superseded_by"] == later["ack_id"]
            assert by_id.loc[prior["superseded_by"], "po_id"] == po_id
        assert pd.isna(ordered.iloc[-1]["superseded_by"])
    for po_id in set(frames["purchase_orders"]["po_id"]) - set(acks["po_id"]):
        assert po_id in set(frames["silence_report"]["po_id"])


def test_starter_ack_and_promise_csvs_are_emitted(starter_frames):
    for name in ("acknowledgements", "acknowledgement_lines", "promise_dates", "entity_event"):
        path = ROOT / "data" / "samples" / f"{name}.csv"
        assert path.exists(), f"missing sample export: {path}"
        frame = pd.read_csv(path)
        assert not frame.empty
        assert frame.columns.tolist() == starter_frames[name].columns.tolist()
