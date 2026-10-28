from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import re

import pytest

from supplier_ack.ids import IDFactory, ID_PATTERNS, matches_id_format


def test_first_ids_match_exact_contract_for_all_ten_entities():
    ids = IDFactory()
    supplier_id = ids.next_supplier_id()
    po_id = ids.next_po_id()
    line_id = ids.next_line_id(po_id)
    ack_id = ids.next_ack_id(po_id)
    promise_date_id = ids.next_promise_date_id(ack_id)
    change_id = ids.next_change_id(po_id)
    approval_id = ids.next_approval_id(change_id)
    notification_id = ids.next_notification_id()
    inventory_plan_id = ids.next_inventory_plan_id(line_id)
    production_order_id = ids.next_production_order_id()

    assert supplier_id == "SUP-000001"
    assert po_id == "PO-2026-000001"
    assert line_id == "PO-2026-000001-L01"
    assert ack_id == "ACK-PO-2026-000001-01"
    assert promise_date_id == "PD-ACK-PO-2026-000001-01-01"
    assert change_id == "CHG-PO-2026-000001-000001"
    assert approval_id == "APR-CHG-PO-2026-000001-000001-01"
    assert notification_id == "NOT-2026-000001"
    assert inventory_plan_id == "IP-PO-2026-000001-L01-01"
    assert production_order_id == "PRO-2026-000001"


def test_1000_ids_of_every_type_are_regex_valid_unique_padded_and_parent_exact():
    factory = IDFactory()
    generated: dict[str, list[str]] = {name: [] for name in ID_PATTERNS}

    for _ in range(1000):
        supplier_id = factory.next_supplier_id()
        po_id = factory.next_po_id()
        line_id = factory.next_line_id(po_id)
        ack_id = factory.next_ack_id(po_id)
        promise_date_id = factory.next_promise_date_id(ack_id)
        change_id = factory.next_change_id(po_id)
        approval_id = factory.next_approval_id(change_id)
        notification_id = factory.next_notification_id()
        inventory_plan_id = factory.next_inventory_plan_id(line_id)
        production_order_id = factory.next_production_order_id()

        generated["Supplier"].append(supplier_id)
        generated["PurchaseOrder"].append(po_id)
        generated["POLine"].append(line_id)
        generated["Acknowledgement"].append(ack_id)
        generated["PromiseDate"].append(promise_date_id)
        generated["ChangeRequest"].append(change_id)
        generated["Approval"].append(approval_id)
        generated["Notification"].append(notification_id)
        generated["InventoryPlan"].append(inventory_plan_id)
        generated["ProductionOrder"].append(production_order_id)

        assert line_id.startswith(po_id + "-L")
        assert ack_id == f"ACK-{po_id}-01"
        assert promise_date_id == f"PD-{ack_id}-01"
        assert change_id == f"CHG-{po_id}-000001"
        assert approval_id == f"APR-{change_id}-01"
        assert inventory_plan_id == f"IP-{line_id}-01"

    for entity_name, values in generated.items():
        assert len(values) == 1000
        assert len(values) == len(set(values)), entity_name
        expression = re.compile(ID_PATTERNS[entity_name])
        assert all(expression.fullmatch(value) for value in values), entity_name
        assert all(matches_id_format(entity_name, value) for value in values), entity_name

    assert generated["Supplier"][0].endswith("000001")
    assert generated["Supplier"][-1].endswith("001000")
    assert generated["PurchaseOrder"][0] == "PO-2026-000001"
    assert generated["PurchaseOrder"][-1] == "PO-2026-001000"
    assert generated["POLine"][0].endswith("-L01")
    assert generated["Acknowledgement"][0].endswith("-01")
    assert generated["PromiseDate"][0].endswith("-01-01")
    assert generated["ChangeRequest"][0].endswith("-000001")
    assert generated["Approval"][0].endswith("-000001-01")
    assert generated["Notification"][-1] == "NOT-2026-001000"
    assert generated["InventoryPlan"][0].endswith("-L01-01")
    assert generated["ProductionOrder"][-1] == "PRO-2026-001000"


def test_global_counters_are_monotonic_and_never_reuse_ids():
    factory = IDFactory()
    values = [factory.next_supplier_id() for _ in range(100)]
    assert values == [f"SUP-{n:06d}" for n in range(1, 101)]
    assert len(values) == len(set(values))


def test_line_counter_is_scoped_to_exact_purchase_order():
    factory = IDFactory()
    first = "PO-2026-000001"
    second = "PO-2026-000002"
    assert [factory.next_line_id(first) for _ in range(3)] == [
        f"{first}-L01", f"{first}-L02", f"{first}-L03"
    ]
    assert factory.next_line_id(second) == f"{second}-L01"


def test_acknowledgement_revisions_increment_per_po():
    factory = IDFactory()
    first = "PO-2026-000001"
    second = "PO-2026-000002"
    assert [factory.next_ack_id(first) for _ in range(3)] == [
        f"ACK-{first}-01", f"ACK-{first}-02", f"ACK-{first}-03"
    ]
    assert factory.next_ack_id(second) == f"ACK-{second}-01"


def test_promise_date_counter_is_scoped_to_full_ack_id():
    factory = IDFactory()
    ack_one = "ACK-PO-2026-000001-01"
    ack_two = "ACK-PO-2026-000001-02"
    assert [factory.next_promise_date_id(ack_one) for _ in range(2)] == [
        f"PD-{ack_one}-01", f"PD-{ack_one}-02"
    ]
    assert factory.next_promise_date_id(ack_two) == f"PD-{ack_two}-01"


def test_change_request_counter_is_six_digits_and_scoped_to_po():
    factory = IDFactory()
    po_id = "PO-2026-000027"
    assert [factory.next_change_id(po_id) for _ in range(2)] == [
        f"CHG-{po_id}-000001", f"CHG-{po_id}-000002"
    ]
    assert factory.next_change_id("PO-2026-000028") == "CHG-PO-2026-000028-000001"


def test_approval_embeds_full_change_id_and_increments_per_change():
    factory = IDFactory()
    change_id = "CHG-PO-2026-000001-000027"
    other_change_id = "CHG-PO-2026-000001-000028"
    assert factory.next_approval_id(change_id) == f"APR-{change_id}-01"
    assert factory.next_approval_id(change_id) == f"APR-{change_id}-02"
    assert factory.next_approval_id(other_change_id) == f"APR-{other_change_id}-01"


def test_inventory_plan_versions_are_scoped_to_full_po_line_id():
    factory = IDFactory()
    line_one = "PO-2026-000001-L01"
    line_two = "PO-2026-000001-L02"
    assert [factory.next_inventory_plan_id(line_one) for _ in range(3)] == [
        f"IP-{line_one}-01", f"IP-{line_one}-02", f"IP-{line_one}-03"
    ]
    assert factory.next_inventory_plan_id(line_two) == f"IP-{line_two}-01"


def test_ids_are_deterministic_for_the_same_generation_sequence():
    left, right = IDFactory(), IDFactory()
    def sequence(factory: IDFactory) -> list[str]:
        po = factory.next_po_id()
        line = factory.next_line_id(po)
        ack = factory.next_ack_id(po)
        change = factory.next_change_id(po)
        return [factory.next_supplier_id(), po, line, ack,
                factory.next_promise_date_id(ack), change,
                factory.next_approval_id(change), factory.next_notification_id(),
                factory.next_inventory_plan_id(line), factory.next_production_order_id()]
    assert sequence(left) == sequence(right)


def test_json_state_round_trip_resumes_all_counters_without_reuse():
    original = IDFactory()
    original.next_supplier_id()
    po = original.next_po_id()
    line = original.next_line_id(po)
    ack = original.next_ack_id(po)
    original.next_promise_date_id(ack)
    change = original.next_change_id(po)
    original.next_approval_id(change)
    original.next_notification_id()
    original.next_inventory_plan_id(line)
    original.next_production_order_id()

    restored = IDFactory.from_json(original.to_json())
    assert restored.to_dict() == original.to_dict()
    assert restored.next_supplier_id() == "SUP-000002"
    assert restored.next_po_id() == "PO-2026-000002"
    assert restored.next_line_id(po) == f"{po}-L02"
    assert restored.next_ack_id(po) == f"ACK-{po}-02"
    assert restored.next_promise_date_id(ack) == f"PD-{ack}-02"
    assert restored.next_change_id(po) == f"CHG-{po}-000002"
    assert restored.next_approval_id(change) == f"APR-{change}-02"
    assert restored.next_notification_id() == "NOT-2026-000002"
    assert restored.next_inventory_plan_id(line) == f"IP-{line}-02"
    assert restored.next_production_order_id() == "PRO-2026-000002"


def test_dict_snapshot_is_detached_from_internal_counter_state():
    factory = IDFactory()
    po_id = factory.next_po_id()
    factory.next_line_id(po_id)
    snapshot = factory.to_dict()
    snapshot["counters"]["line_by_po"][po_id] = 78
    snapshot["counters"]["purchase_order"] = 999
    assert factory.next_line_id(po_id) == f"{po_id}-L02"
    assert factory.next_po_id() == "PO-2026-000002"


def test_from_dict_rejects_wrong_year_version_and_counter_structure():
    state = IDFactory().to_dict()
    changed = deepcopy(state)
    changed["year"] = 2027
    with pytest.raises(ValueError, match="year"):
        IDFactory.from_dict(changed)
    changed = deepcopy(state)
    changed["schema_version"] = 99
    with pytest.raises(ValueError, match="version"):
        IDFactory.from_dict(changed)
    changed = deepcopy(state)
    del changed["counters"]["supplier"]
    with pytest.raises(ValueError, match="missing or unknown keys"):
        IDFactory.from_dict(changed)


@pytest.mark.parametrize(
    ("method_name", "bad_parent"),
    [
        ("next_line_id", "PO-2026-1"),
        ("next_ack_id", "PO-2025-000001"),
        ("next_change_id", "PO-2026-000001-L01"),
        ("next_promise_date_id", "ACK-PO-2026-000001-1"),
        ("next_approval_id", "CHG-PO-2026-000001-1"),
        ("next_inventory_plan_id", "PO-2026-000001-L1"),
    ],
)
def test_parent_ids_must_match_exact_documented_format(method_name: str, bad_parent: str):
    factory = IDFactory()
    with pytest.raises(ValueError, match="must match"):
        getattr(factory, method_name)(bad_parent)


def test_scoped_two_digit_counter_exhaustion_does_not_emit_invalid_id():
    state = IDFactory().to_dict()
    po_id = "PO-2026-000001"
    state["counters"]["line_by_po"][po_id] = 99
    factory = IDFactory.from_dict(state)
    with pytest.raises(OverflowError, match="2-digit range"):
        factory.next_line_id(po_id)
    assert factory.to_dict()["counters"]["line_by_po"][po_id] == 99


def test_six_digit_global_counter_exhaustion_does_not_emit_invalid_id():
    state = IDFactory().to_dict()
    state["counters"]["supplier"] = 999999
    factory = IDFactory.from_dict(state)
    with pytest.raises(OverflowError, match="6-digit range"):
        factory.next_supplier_id()
    assert factory.to_dict()["counters"]["supplier"] == 999999


def test_state_restore_rejects_invalid_scoped_parent_and_count():
    state = IDFactory().to_dict()
    state["counters"]["line_by_po"]["PO-2026-1"] = 1
    with pytest.raises(ValueError, match="invalid parent ID"):
        IDFactory.from_dict(state)

    state = IDFactory().to_dict()
    state["counters"]["approval_by_change"]["CHG-PO-2026-000001-000001"] = 100
    with pytest.raises(ValueError, match="must be an integer"):
        IDFactory.from_dict(state)


def test_factory_is_safe_for_concurrent_global_issuance():
    factory = IDFactory()
    with ThreadPoolExecutor(max_workers=12) as pool:
        issued = list(pool.map(lambda _: factory.next_notification_id(), range(2000)))
    assert len(issued) == len(set(issued)) == 2000
    assert set(issued) == {f"NOT-2026-{n:06d}" for n in range(1, 2001)}


def test_generic_helpers_remain_backward_compatible():
    from datetime import date
    from supplier_ack.ids import dated_id, make_id

    assert make_id("PO", 123) == "PO-000123"
    assert dated_id("EVT", 4, date(2026, 10, 28)) == "EVT-20261028-000004"


def test_unknown_entity_name_does_not_match_an_id_format():
    assert not matches_id_format("Unknown", "PO-2026-000001")
    assert not matches_id_format("PurchaseOrder", "PO-2026-1")


def test_every_factory_id_is_accepted_by_its_entity_schema_validator():
    from supplier_ack.schema import ENTITIES

    factory = IDFactory()
    po_id = factory.next_po_id()
    line_id = factory.next_line_id(po_id)
    ack_id = factory.next_ack_id(po_id)
    change_id = factory.next_change_id(po_id)
    issued = {
        "Supplier": factory.next_supplier_id(),
        "PurchaseOrder": po_id,
        "POLine": line_id,
        "Acknowledgement": ack_id,
        "PromiseDate": factory.next_promise_date_id(ack_id),
        "ChangeRequest": change_id,
        "Approval": factory.next_approval_id(change_id),
        "Notification": factory.next_notification_id(),
        "InventoryPlan": factory.next_inventory_plan_id(line_id),
        "ProductionOrder": factory.next_production_order_id(),
    }
    for entity_name, identifier in issued.items():
        entity = ENTITIES[entity_name]
        field = next(field for field in entity.fields if field.name == entity.primary_key)
        assert field.validator(identifier, {field.name: identifier}, {}, field) is None, entity_name


def test_all_ten_entity_id_patterns_are_explicit_and_non_overlapping():
    expected = {
        "Supplier", "PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate",
        "ChangeRequest", "Approval", "Notification", "InventoryPlan", "ProductionOrder",
    }
    assert set(ID_PATTERNS) == expected
    examples = {
        "Supplier": "SUP-000001", "PurchaseOrder": "PO-2026-000001",
        "POLine": "PO-2026-000001-L01", "Acknowledgement": "ACK-PO-2026-000001-01",
        "PromiseDate": "PD-ACK-PO-2026-000001-01-01",
        "ChangeRequest": "CHG-PO-2026-000001-000001",
        "Approval": "APR-CHG-PO-2026-000001-000001-01",
        "Notification": "NOT-2026-000001", "InventoryPlan": "IP-PO-2026-000001-L01-01",
        "ProductionOrder": "PRO-2026-000001",
    }
    for entity, value in examples.items():
        assert matches_id_format(entity, value)
        assert not matches_id_format(entity, value + "X")
