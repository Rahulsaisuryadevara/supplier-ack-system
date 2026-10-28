from datetime import datetime, timezone
from decimal import Decimal

import pytest

from supplier_ack.schema import (
    ACTOR_ROLES,
    ENTITIES,
    STATUS_ENUMS,
    STATUS_TRANSITIONS,
    is_legal_transition,
    validate_dataset,
    validate_record,
)


def test_all_ten_entities_have_complete_field_specs_and_callable_validators():
    assert set(ENTITIES) == {
        "Supplier", "PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate",
        "ChangeRequest", "Approval", "InventoryPlan", "ProductionOrder", "Notification",
    }
    for entity_name, entity in ENTITIES.items():
        assert len(entity.fields) >= 8, entity_name
        primary_keys = [field for field in entity.fields if field.primary_key]
        assert len(primary_keys) == 1
        assert primary_keys[0].name == entity.primary_key
        for field in entity.fields:
            assert field.name and field.sql_type and field.domain and field.units
            assert isinstance(field.required, bool)
            assert field.uniqueness and field.validation_rule
            assert callable(field.validator)


def test_every_lifecycle_enum_has_a_transition_entry():
    for entity, states in STATUS_ENUMS.items():
        assert set(states) == set(STATUS_TRANSITIONS[entity])
        for current, following in STATUS_TRANSITIONS[entity].items():
            assert set(following).issubset(set(states))
    assert is_legal_transition("PurchaseOrder", "ISSUED", "ACKNOWLEDGED")
    assert not is_legal_transition("PurchaseOrder", "CLOSED", "ISSUED")


def test_poline_line_total_and_decimal_precision_are_machine_checked():
    row = {
        "po_line_id": "PO-2026-000001-L01",
        "po_id": "PO-2026-000001",
        "line_no": 1,
        "item_id": "ITEM-000001",
        "item_description": "Test material",
        "requested_qty": Decimal("5.000"),
        "ack_accepted_qty": Decimal("0.000"),
        "ack_rejected_qty": Decimal("0.000"),
        "promised_qty": Decimal("0.000"),
        "projected_qty": Decimal("0.000"),
        "uom": "EA",
        "currency": "INR",
        "unit_price": Decimal("2.00"),
        "acknowledged_unit_price": None,
        "promised_unit_price": None,
        "projected_unit_price": None,
        "line_total": Decimal("9.99"),
        "acknowledged_value": None,
        "promised_value": None,
        "projected_value": None,
        "required_date": "2026-11-05",
        "status": "OPEN",
        "created_at": "2026-10-28T10:00:00+05:30",
        "updated_at": "2026-10-28T10:00:00+05:30",
        "issue_type": None,
        "ground_truth": None,
    }
    errors = validate_record("POLine", row)
    assert any("line_total" in error and "ROUND_HALF_UP" in error for error in errors)
    row["line_total"] = Decimal("10.00")
    assert not validate_record("POLine", row)
    row["unit_price"] = Decimal("2.001")
    assert any("unit_price" in error and "decimal places" in error for error in validate_record("POLine", row))


def test_acknowledgement_quantity_reconciliation_is_machine_checked():
    row = {
        "ack_id": "ACK-PO-2026-000001-01",
        "po_id": "PO-2026-000001",
        "supplier_id": "SUP-000001",
        "po_line_id": None,
        "revision_no": 1,
        "status": "ACCEPTED",
        "lifecycle_state": "PROCESSED",
        "acknowledged_at": "2026-10-28T10:00:00+05:30",
        "response_due_at": "2026-10-29T10:00:00+05:30",
        "requested_qty": Decimal("10.000"),
        "ack_accepted_qty": Decimal("7.000"),
        "ack_rejected_qty": Decimal("2.000"),
        "qty_delta_pct": Decimal("-30.0000"),
        "price_delta_pct": Decimal("0.0000"),
        "date_slip_days": None,
        "promised_qty": Decimal("7.000"),
        "projected_qty": Decimal("7.000"),
        "requested_value": Decimal("100.00"),
        "acknowledged_value": Decimal("70.00"),
        "promised_value": Decimal("70.00"),
        "projected_value": Decimal("70.00"),
        "supplier_note": None,
        "superseded_by": None,
        "created_at": "2026-10-28T09:00:00+05:30",
        "created_by_role": "supplier",
        "created_by_actor_id": "SUP-000001",
        "issue_type": None,
        "ground_truth": None,
    }
    errors = validate_record("Acknowledgement", row)
    assert any("requested_qty must equal" in error for error in errors)
    row["ack_rejected_qty"] = Decimal("3.000")
    assert not validate_record("Acknowledgement", row)


def test_date_ordering_and_id_nomenclature_are_enforced():
    row = {
        "supplier_id": "SUP-000001",
        "supplier_name": "Valid Supplier",
        "supplier_code": "SUPPLIER-1",
        "supplier_contact_name": "Supplier Contact",
        "supplier_contact_email": "contact@example.com",
        "supplier_contact_phone": "+911234567890",
        "supplier_status": "ACTIVE",
        "risk_tier": "LOW",
        "lead_time_days": 10,
        "default_currency": "INR",
        "data_owner_role": "supplier",
        "created_at": "2026-10-28T10:00:00+05:30",
        "updated_at": "2026-10-27T10:00:00+05:30",
        "issue_type": None,
        "ground_truth": None,
    }
    assert any("updated_at must be >= created_at" in error for error in validate_record("Supplier", row))
    row["supplier_id"] = "SUP-1"
    assert any("supplier_id" in error and "SUP-\\d{6}" in error for error in validate_record("Supplier", row))


def test_dataset_checks_foreign_keys_and_parent_consistency():
    supplier = {"supplier_id": "SUP-000001"}
    po = {"po_id": "PO-2026-000001", "supplier_id": "SUP-000001", "order_date": "2026-10-20", "total_order_value": Decimal("10.00")}
    line = {"po_line_id": "PO-2026-000001-L01", "po_id": "PO-2026-000001", "line_total": Decimal("10.00"), "currency": "USD"}
    errors = validate_dataset({"Supplier": [supplier], "PurchaseOrder": [po], "POLine": [line]})
    assert any("currency must match parent PurchaseOrder.currency" in error for error in errors)


def test_actor_roles_are_explicitly_defined():
    assert set(ACTOR_ROLES) == {
        "supplier", "planner", "carrier_warehouse_operator", "logistics_analyst", "operations_manager"
    }


def test_markdown_document_is_generated_from_same_schema_source():
    from pathlib import Path
    from supplier_ack.schema import render_markdown_dictionary, validate_schema_contract

    repo_root = Path(__file__).resolve().parents[1]
    document = (repo_root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    assert document == render_markdown_dictionary()
    assert validate_schema_contract() == []
    for entity_name, entity in ENTITIES.items():
        assert f"## {entity_name}\n" in document
        assert f"| `{entity.primary_key}` |" in document
        for field in entity.fields:
            assert f"| `{field.name}` | `{field.sql_type}` |" in document


def test_validation_collects_errors_instead_of_crashing_on_bad_types():
    from supplier_ack.schema import validate_record
    errors = validate_record("Acknowledgement", {
        "ack_id": 123,
        "po_id": [],
        "revision_no": "not-an-integer",
        "status": "NOT_A_STATUS",
        "ack_accepted_qty": "bad",
    })
    assert errors
    assert any("ack_id" in error for error in errors)
    assert any("revision_no" in error for error in errors)


def test_documented_field_tables_parse_to_schema_fields():
    """Every field row documented in Markdown must exist in the schema source."""
    import re
    from pathlib import Path
    from supplier_ack.schema import ENTITIES

    dictionary = Path(__file__).resolve().parents[1] / "docs" / "data_dictionary.md"
    text = dictionary.read_text(encoding="utf-8")
    current_entity = None
    documented = {}
    for line in text.splitlines():
        heading = re.fullmatch(r"#{2,6}\s+(.+?)\s*", line)
        if heading:
            name = heading.group(1)
            current_entity = name if name in ENTITIES else None
            if current_entity:
                documented.setdefault(current_entity, set())
            continue
        if current_entity and line.startswith("|") and not re.match(r"^\|\s*:?-{3,}", line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"`[a-z][a-z0-9_]*`", cells[0]):
                documented[current_entity].add(cells[0].strip("`"))

    assert set(documented) == set(ENTITIES)
    for entity_name, entity in ENTITIES.items():
        expected = {field.name for field in entity.fields}
        assert documented[entity_name] == expected, (
            entity_name, sorted(expected - documented[entity_name]),
            sorted(documented[entity_name] - expected)
        )
