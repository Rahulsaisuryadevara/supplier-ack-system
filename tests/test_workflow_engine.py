"""Integration tests for transactional live workflow event processing."""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from supplier_ack.workflow.engine import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]
SEED_DB = ROOT / "data/samples/sql/seed.db"
DEMO_EVENTS = ROOT / "data/samples/demo_events.json"


@pytest.fixture(scope="session")
def runtime_db(tmp_path_factory):
    if not SEED_DB.exists():
        pytest.skip("exported seed DB is needed for runtime integration tests")
    path = tmp_path_factory.mktemp("runtime") / "app.db"
    shutil.copy2(SEED_DB, path)
    return path


def test_demo_exercises_all_event_types_and_four_exception_paths(runtime_db):
    engine = WorkflowEngine(runtime_db)
    result = engine.run(DEMO_EVENTS)
    assert result["events_processed"] == 9
    assert result["plans_updated"] == 1
    assert result["exceptions"] >= 4
    exceptions = engine.exceptions()
    rules = {row["rule_id"] for row in exceptions}
    assert {"PROMISE_BEFORE_ORDER_DATE", "APPROVAL_BEFORE_APPLY", "STALE_REVISION_GUARD", "ACK_INVALID_PO_REFERENCE"}.issubset(rules)
    types = {row[0] for row in sqlite3.connect(runtime_db).execute("SELECT event_type FROM runtime_processed_event")}
    assert {"ack_submitted", "ack_revision_received", "promise_updated", "change_requested", "approval_decision", "silence_timeout"}.issubset(types)


def test_pending_change_cannot_update_plan(runtime_db, tmp_path):
    engine = WorkflowEngine(runtime_db)
    conn = sqlite3.connect(runtime_db)
    before = conn.execute("SELECT COUNT(*) FROM inventory_plans WHERE po_line_id='PO-2026-000045-L01'").fetchone()[0]
    conn.close()
    event = {"event_id":"test-pending-plan-gate","event_type":"change_requested","po_id":"PO-2026-000045","po_line_id":"PO-2026-000045-L01","change_type":"date","old_value":"2026-08-01","new_value":"2026-08-04","requested_by_role":"planner","attempt_plan_update":True}
    result = engine.run(_write_event(event, tmp_path))
    conn = sqlite3.connect(runtime_db)
    after = conn.execute("SELECT COUNT(*) FROM inventory_plans WHERE po_line_id='PO-2026-000045-L01'").fetchone()[0]
    conn.close()
    assert result["results"][0]["status"] == "PLAN_UPDATE_REFUSED"
    assert before == after
    assert any(row["rule_id"] == "APPROVAL_BEFORE_APPLY" for row in engine.exceptions())


def test_stale_revision_is_recorded_but_not_inserted(runtime_db, tmp_path):
    engine = WorkflowEngine(runtime_db)
    conn = sqlite3.connect(runtime_db)
    before = conn.execute("SELECT COUNT(*) FROM acknowledgements WHERE po_id='PO-2026-000041'").fetchone()[0]
    conn.close()
    event = {"event_id":"test-stale-revision-guard","event_type":"ack_revision_received","po_id":"PO-2026-000041","revision_no":1,"ack_id":"ACK-PO-2026-000041-01","lines":[{"po_line_id":"PO-2026-000041-L01","accepted_qty":10,"promised_date":"2026-06-05"}]}
    result = engine.run(_write_event(event, tmp_path))
    conn = sqlite3.connect(runtime_db)
    after = conn.execute("SELECT COUNT(*) FROM acknowledgements WHERE po_id='PO-2026-000041'").fetchone()[0]
    conn.close()
    assert result["results"][0]["status"] == "STALE_REVISION_RECORDED"
    assert before == after
    assert any(row["rule_id"] == "STALE_REVISION_GUARD" for row in engine.exceptions())


def _write_event(event, tmp_path):
    # Use pytest's per-test temporary directory on Windows, macOS, and Linux.
    # The engine accepts a JSON file path, matching the public CLI API.
    path = tmp_path / f"{event['event_id']}.json"
    path.write_text(json.dumps([event]), encoding="utf-8")
    return path
