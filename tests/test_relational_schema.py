from __future__ import annotations

import sqlite3
import pytest

from supplier_ack.schema import ENTITIES, create_all, create_schema_sql


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    columns = list(row)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [row[column] for column in columns],
    )


def _seed_reference_data(conn: sqlite3.Connection) -> None:
    _insert(conn, "carriers", {
        "carrier_id": "CAR-000001", "carrier_name": "Example Carrier",
        "carrier_code": "CARRIER-1", "is_active": 1,
        "created_at": "2026-10-28T09:00:00Z",
    })
    _insert(conn, "suppliers", {
        "supplier_id": "SUP-000001",
        "supplier_name": "Example Supplier",
        "supplier_code": "EXAMPLE-1",
        "supplier_contact_name": "Sam Supplier",
        "supplier_contact_email": "supplier@example.com",
        "supplier_contact_phone": "+911234567890",
        "supplier_status": "ACTIVE",
        "risk_tier": "LOW",
        "region": "SOUTH",
        "lead_time_days": 10,
        "reliability_score": 0.95,
        "on_time_rate": 0.93,
        "ack_rate": 0.0,
        "on_time_promise_rate": 0.0,
        "avg_slip_days": 0.0,
        "preferred_carrier_id": "CAR-000001",
        "default_currency": "INR",
        "data_owner_role": "supplier",
        "created_at": "2026-10-28T09:00:00Z",
        "updated_at": "2026-10-28T09:00:00Z",
        "issue_type": None,
        "ground_truth": None,
    })
    for actor_id, role, name, email, supplier_id in [
        ("SUP-000001", "supplier", "Sam Supplier", "supplier@example.com", "SUP-000001"),
        ("PLN-000001", "planner", "Pat Planner", "planner@example.com", None),
        ("LOG-000001", "logistics_analyst", "Lee Logistics", "logistics@example.com", None),
    ]:
        _insert(conn, "actors", {
            "actor_id": actor_id,
            "actor_role": role,
            "actor_name": name,
            "email": email,
            "supplier_id": supplier_id,
            "is_active": 1,
            "created_at": "2026-10-28T09:00:00Z",
        })
    _insert(conn, "warehouses", {
        "warehouse_id": "WH-0001", "warehouse_name": "North Warehouse",
        "site_code": "NORTH-01", "timezone": "Asia/Kolkata", "is_active": 1,
        "created_at": "2026-10-28T09:00:00Z",
    })
    _insert(conn, "items", {
        "item_id": "ITEM-000001", "item_name": "Steel Component",
        "default_uom": "EA", "item_status": "ACTIVE",
        "unit_price_min": 1.0, "unit_price_max": 10.0, "price_currency": "INR",
        "created_at": "2026-10-28T09:00:00Z",
    })


def _seed_po_and_line(conn: sqlite3.Connection) -> None:
    _insert(conn, "purchase_orders", {
        "po_id": "PO-2026-000001", "supplier_id": "SUP-000001",
        "planner_actor_id": "PLN-000001", "warehouse_id": "WH-0001",
        "carrier_id": "CAR-000001", "order_date": "2026-10-28",
        "required_delivery_date": "2026-11-10",
        "response_due_at": "2026-10-29T12:00:00Z", "currency": "INR",
        "total_order_value": 10, "status": "ISSUED", "created_by_role": "planner",
        "created_by_actor_id": "PLN-000001", "supplier_contact_email": "supplier@example.com",
        "version_no": 1, "created_at": "2026-10-28T09:00:00Z",
        "updated_at": "2026-10-28T09:00:00Z", "issue_type": None, "ground_truth": None,
    })
    _insert(conn, "po_lines", {
        "po_line_id": "PO-2026-000001-L01", "po_id": "PO-2026-000001",
        "line_no": 1, "item_id": "ITEM-000001", "item_description": "Steel Component",
        "requested_qty": 5, "ack_accepted_qty": 0, "ack_rejected_qty": 0,
        "promised_qty": 0, "projected_qty": 0, "uom": "EA", "currency": "INR",
        "unit_price": 2, "acknowledged_unit_price": None, "promised_unit_price": None,
        "projected_unit_price": None, "line_total": 10, "acknowledged_value": None,
        "promised_value": None, "projected_value": None, "required_date": "2026-11-10",
        "status": "OPEN", "created_at": "2026-10-28T09:00:00Z",
        "updated_at": "2026-10-28T09:00:00Z", "issue_type": None, "ground_truth": None,
    })


def test_create_all_builds_complete_schema_with_foreign_keys_enabled():
    conn = create_all(":memory:")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {spec.table_name for spec in ENTITIES.values()}.issubset(tables)
        assert {"actors", "items", "warehouses", "carriers", "entity_event", "notification_recipient", "production_order_line", "production_order_impact"}.issubset(tables)
        for entity in ENTITIES.values():
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({entity.table_name})")}
            assert columns == {field.name for field in entity.fields}, entity.name
            assert conn.execute(f"PRAGMA foreign_key_list({entity.table_name})").fetchall() or not any(
                field.foreign_key for field in entity.fields
            ), entity.name
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert "CREATE TABLE IF NOT EXISTS notification_recipient" in create_schema_sql
        assert "CREATE TABLE IF NOT EXISTS production_order_line" in create_schema_sql
    finally:
        conn.close()


def test_foreign_keys_composite_joins_and_event_snapshots_are_enforced():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        _seed_po_and_line(conn)

        # A valid insert and subsequent state change each produce a durable event snapshot.
        before = conn.execute(
            "SELECT count(*) FROM entity_event WHERE entity_type='PurchaseOrder' AND entity_id='PO-2026-000001'"
        ).fetchone()[0]
        assert before == 1
        conn.execute("UPDATE purchase_orders SET status='CANCELLED', updated_at='2026-10-28T09:30:00Z' WHERE po_id='PO-2026-000001'")
        events = conn.execute(
            "SELECT event_type, previous_state, new_state FROM entity_event "
            "WHERE entity_type='PurchaseOrder' AND entity_id='PO-2026-000001' ORDER BY rowid"
        ).fetchall()
        assert len(events) == 2
        assert events[1][0] == "PO_STATUS_CHANGED"
        assert conn.execute("SELECT json_extract(?, '$.status')", (events[1][1],)).fetchone()[0] == "ISSUED"
        assert conn.execute("SELECT json_extract(?, '$.status')", (events[1][2],)).fetchone()[0] == "CANCELLED"

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("PO-2026-000002", "SUP-999999", "PLN-000001", "WH-0001", "CAR-000001",
                 "2026-10-28", "2026-11-10", "2026-10-29T12:00:00Z", "INR", 10, "ISSUED",
                 "planner", "PLN-000001", "supplier@example.com", 1, "2026-10-28T09:00:00Z",
                 "2026-10-28T09:00:00Z", None, None),
            )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE entity_event SET event_type='CORRUPTED' WHERE event_id=(SELECT event_id FROM entity_event LIMIT 1)")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM entity_event WHERE event_id=(SELECT event_id FROM entity_event LIMIT 1)")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_notification_bridge_supports_role_fanout_and_system_wide_notices():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        # NULL PO/change links intentionally represent a system-wide notification.
        _insert(conn, "notifications", {
            "notification_id": "NOT-2026-000001", "not_id": "NOT-2026-000001",
            "not_type": "WEEKLY_SUMMARY", "severity": "INFO", "subject": "System maintenance",
            "related_entity_type": "system", "related_entity_id": "maintenance-2026-10-28",
            "read_status": "UNREAD", "po_id": None, "ack_id": None,
            "change_request_id": None, "source_event_id": None, "channel": "IN_APP",
            "status": "QUEUED", "title": "System maintenance", "open_impact_count": 0, "body": "A planned system maintenance window is scheduled.",
            "scheduled_at": "2026-10-28T09:00:00Z", "sent_at": None, "delivered_at": None,
            "retry_count": 0, "last_error": None, "created_at": "2026-10-28T09:00:00Z",
            "issue_type": None, "ground_truth": None,
        })
        conn.execute(
            "INSERT INTO notification_recipient(notification_id,actor_role,recipient_actor_id) VALUES (?,?,?)",
            ("NOT-2026-000001", "planner", "PLN-000001"),
        )
        conn.execute(
            "INSERT INTO notification_recipient(notification_id,actor_role,recipient_actor_id) VALUES (?,?,?)",
            ("NOT-2026-000001", "logistics_analyst", "LOG-000001"),
        )
        assert conn.execute("SELECT count(*) FROM notification_recipient WHERE notification_id='NOT-2026-000001'").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO notification_recipient(notification_id,actor_role) VALUES (?,?)",
                ("NOT-2026-000001", "planner"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO notification_recipient(notification_id,actor_role,recipient_actor_id) VALUES (?,?,?)",
                ("NOT-2026-000001", "planner", "SUP-000001"),
            )
        assert conn.execute(
            "SELECT count(*) FROM entity_event WHERE entity_type='Notification' AND event_type='NOTIFICATION_RECIPIENT_ADDED'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_acknowledgement_revision_payload_cannot_be_overwritten():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        _seed_po_and_line(conn)
        _insert(conn, "acknowledgements", {
            "ack_id": "ACK-PO-2026-000001-01", "po_id": "PO-2026-000001",
            "supplier_id": "SUP-000001", "po_line_id": "PO-2026-000001-L01",
            "revision_no": 1, "status": "SUBMITTED", "lifecycle_state": "SUBMITTED",
            "acknowledged_at": "2026-10-28T09:10:00Z",
            "response_due_at": "2026-10-29T12:00:00Z", "requested_qty": 5,
            "ack_accepted_qty": 0, "ack_rejected_qty": 0,
            "qty_delta_pct": -100.0, "price_delta_pct": -100.0, "date_slip_days": None,
            "promised_qty": 0, "projected_qty": 0, "requested_value": 10, "acknowledged_value": 0,
            "promised_value": 0, "projected_value": 0, "supplier_note": None,
            "superseded_by": None, "created_at": "2026-10-28T09:00:00Z",
            "created_by_role": "supplier", "created_by_actor_id": "SUP-000001",
            "issue_type": None, "ground_truth": None,
        })
        with pytest.raises(sqlite3.IntegrityError, match="payload is immutable"):
            conn.execute("UPDATE acknowledgements SET promised_qty=4 WHERE ack_id='ACK-PO-2026-000001-01'")
        # Lifecycle metadata can progress without rewriting the revision payload.
        conn.execute("UPDATE acknowledgements SET status='UNDER_REVIEW' WHERE ack_id='ACK-PO-2026-000001-01'")
        assert conn.execute(
            "SELECT event_type FROM entity_event WHERE entity_type='Acknowledgement' AND entity_id='ACK-PO-2026-000001-01' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0] == "ACKNOWLEDGEMENT_UPDATED"
    finally:
        conn.close()


def test_inventory_plan_versions_are_append_only():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        _seed_po_and_line(conn)
        _insert(conn, "inventory_plans", {
            "inventory_plan_id": "IP-PO-2026-000001-L01-01",
            "po_id": "PO-2026-000001", "po_line_id": "PO-2026-000001-L01",
            "plan_revision_no": 1, "plan_version": 1, "previous_version_id": None,
            "source": "po_baseline", "is_effective": 1,
            "projected_delivery_date": "2026-11-10", "change_request_id": None,
            "status": "ACTIVE", "demand_qty": 5, "requested_qty": 5,
            "acknowledged_qty": 0, "promised_qty": 0, "projected_qty": 5,
            "on_hand_qty": 0, "reserved_qty": 0, "planned_receipt_qty": 5,
            "projected_available_qty": 5, "projected_shortage_qty": 0,
            "required_date": "2026-11-10", "promised_date": None,
            "plan_start_date": "2026-10-28", "plan_end_date": "2026-11-10",
            "planner_actor_id": "PLN-000001", "approved_by_actor_id": "PLN-000001",
            "effective_date": "2026-10-28", "superseded_by": None,
            "created_at": "2026-10-28T09:00:00Z", "updated_at": "2026-10-28T09:00:00Z",
            "issue_type": None, "ground_truth": None,
        })
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE inventory_plans SET is_effective=0 WHERE inventory_plan_id=?", ("IP-PO-2026-000001-L01-01",))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM inventory_plans WHERE inventory_plan_id=?", ("IP-PO-2026-000001-L01-01",))
        assert conn.execute("SELECT is_effective FROM inventory_plans WHERE inventory_plan_id=?", ("IP-PO-2026-000001-L01-01",)).fetchone()[0] == 1
    finally:
        conn.close()


def test_every_dictionary_foreign_key_is_declared_in_sqlite_ddl():
    conn = create_all(":memory:")
    try:
        for entity in ENTITIES.values():
            declared = {
                (row[3], row[4])
                for row in conn.execute(f"PRAGMA foreign_key_list({entity.table_name})")
            }
            for field in entity.fields:
                if field.foreign_key:
                    target_table, target_column = field.foreign_key.split(".", 1)
                    assert (field.name, target_column) in declared, (
                        entity.name, field.name, field.foreign_key, declared
                    )
    finally:
        conn.close()


def test_date_anomaly_is_labelled_without_disabling_foreign_keys():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        _seed_po_and_line(conn)
        bad_date_line = {
            "po_line_id": "PO-2026-000001-L02", "po_id": "PO-2026-000001",
            "line_no": 2, "item_id": "ITEM-000001", "item_description": "Steel Component anomaly",
            "requested_qty": 2, "ack_accepted_qty": 0, "ack_rejected_qty": 0,
            "promised_qty": 0, "projected_qty": 0, "uom": "EA", "currency": "INR",
            "unit_price": 2, "acknowledged_unit_price": None, "promised_unit_price": None,
            "projected_unit_price": None, "line_total": 4, "acknowledged_value": None,
            "promised_value": None, "projected_value": None, "required_date": "2026-10-20",
            "status": "OPEN", "created_at": "2026-10-28T09:00:00Z",
            "updated_at": "2026-10-28T09:00:00Z", "issue_type": None, "ground_truth": None,
        }
        with pytest.raises(sqlite3.IntegrityError, match="required_date must not predate"):
            _insert(conn, "po_lines", bad_date_line)

        bad_date_line["issue_type"] = "DATE_CONFLICT"
        bad_date_line["ground_truth"] = "DATE_CONFLICT"
        _insert(conn, "po_lines", bad_date_line)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(
            "SELECT issue_type, ground_truth FROM po_lines WHERE po_line_id=?",
            (bad_date_line["po_line_id"],),
        ).fetchone() == ("DATE_CONFLICT", "DATE_CONFLICT")
    finally:
        conn.close()


def test_event_target_fk_cannot_be_made_dangling_by_matching_entity_id_text():
    conn = create_all(":memory:")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO entity_event(
                    entity_type, entity_id, event_type, actor_role, payload_json,
                    target_po_id
                ) VALUES ('PurchaseOrder', 'PO-2026-999999', 'INVALID_TRANSITION',
                          'system', '{"status":"CLOSED"}', 'PO-2026-999999')"""
            )
    finally:
        conn.close()


def test_approval_rows_are_immutable_and_appeals_require_new_rounds():
    conn = create_all(":memory:")
    try:
        _seed_reference_data(conn)
        _seed_po_and_line(conn)
        _insert(conn, "change_requests", {
            "change_request_id": "CHG-PO-2026-000001-000001",
            "po_id": "PO-2026-000001", "supplier_id": "SUP-000001",
            "po_line_id": "PO-2026-000001-L01", "request_type": "PRICE_CHANGE",
            "change_type": "price", "old_value": "2.00", "new_value": "2.10", "delta": 5.0,
            "delta_abs": 5.0, "delta_pct": 5.0, "required_approval_level": "planner",
            "status": "UNDER_REVIEW", "requested_at": "2026-10-28T10:00:00Z",
            "effective_date": "2026-10-29", "response_due_date": "2026-10-30",
            "previous_qty": None, "requested_qty": None,
            "previous_unit_price": 2.0, "requested_unit_price": 2.1,
            "previous_promised_date": None, "requested_promised_date": None,
            "reason_code": "PRICE_CHANGE", "reason_text": "Supplier quote differs by 5 percent.",
            "requested_by_role": "supplier", "requested_by_actor_id": "SUP-000001",
            "created_at": "2026-10-28T10:00:00Z", "updated_at": "2026-10-28T10:00:00Z",
            "issue_type": None, "ground_truth": None,
        })
        _insert(conn, "approvals", {
            "approval_id": "APR-CHG-PO-2026-000001-000001-01",
            "change_request_id": "CHG-PO-2026-000001-000001", "approval_round": 1,
            "approver_role": "planner", "approval_level": "planner",
            "approver_actor_id": "PLN-000001", "status": "PENDING",
            "requested_at": "2026-10-28T10:00:00Z", "due_at": "2026-10-30T17:00:00Z",
            "decided_at": None, "decision_reason": None,
            "comments": "Awaiting planner decision.", "threshold_name": "PRICE_CHANGE_PCT",
            "threshold_value": 5.0, "created_at": "2026-10-28T10:00:00Z",
            "issue_type": None, "ground_truth": None,
        })
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE approvals SET status='APPROVED', decided_at='2026-10-28T11:00:00Z' WHERE approval_id=?",
                ("APR-CHG-PO-2026-000001-000001-01",),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM approvals WHERE approval_id=?", ("APR-CHG-PO-2026-000001-000001-01",))
        assert conn.execute("SELECT status FROM approvals WHERE approval_id=?", ("APR-CHG-PO-2026-000001-000001-01",)).fetchone()[0] == "PENDING"
    finally:
        conn.close()
