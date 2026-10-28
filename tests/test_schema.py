from __future__ import annotations
import sqlite3
import pytest
from supplier_ack.schema import create_all, create_schema_sql

def test_ddl_executes_and_foreign_keys_are_enabled():
    conn = create_all(":memory:")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"suppliers", "purchase_orders", "po_lines", "entity_event", "notification_recipient", "production_order_line"} <= tables
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally: conn.close()

def test_foreign_key_rejects_bad_supplier_reference():
    conn = create_all(":memory:")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO production_order_line (production_order_id, po_line_id, allocated_quantity, allocated_uom, created_at) VALUES (?, ?, ?, ?, ?)", ("PRO-2026-000001", "PO-2026-000001-L01", 1, "EA", "2026-01-01"))
    finally: conn.close()

def test_bridge_tables_have_composite_unique_or_primary_keys():
    sql = create_schema_sql.lower()
    assert "primary key (notification_id, actor_role)" in sql
    assert "primary key (production_order_id, po_line_id)" in sql


def test_bridge_composite_unique_indexes_are_present_in_sqlite():
    conn = create_all(":memory:")
    try:
        for table, expected in (("notification_recipient", {"notification_id", "actor_role"}), ("production_order_line", {"production_order_id", "po_line_id"})):
            indexes = conn.execute(f"PRAGMA index_list({table})").fetchall()
            unique_columns = []
            for index in indexes:
                if index[2]:
                    unique_columns.append({row[2] for row in conn.execute(f"PRAGMA index_info({index[1]})")})
            assert expected in unique_columns
    finally: conn.close()
