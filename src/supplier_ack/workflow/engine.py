"""Transactional SQLite runtime for live supplier acknowledgement workflow events.

Threshold and derived-value decisions are delegated to the same pure rule functions
used by the offline generator. Runtime-only audit tables are append-only.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from supplier_ack.rules.thresholds import evaluate_threshold, required_approval_level, can_apply, computed_delta
from supplier_ack.rules.derived import derive_ack_status, derive_promise_date

EVENT_TYPES = {"ack_submitted", "ack_revision_received", "promise_updated", "change_requested", "approval_decision", "silence_timeout"}

RUNTIME_DDL = """
CREATE TABLE IF NOT EXISTS runtime_exception (
 exception_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, rule_id TEXT NOT NULL,
 severity TEXT NOT NULL, entity_type TEXT, entity_id TEXT, entity_trace TEXT NOT NULL,
 message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_decision (
 decision_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, change_request_id TEXT,
 decision TEXT NOT NULL, rule_id TEXT NOT NULL, values_compared TEXT NOT NULL,
 required_approval_level TEXT, approver_actor_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_processed_event (
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 outcome_json TEXT NOT NULL, processed_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    # Runtime audit time is intentionally wall-clock; generated business data is not changed.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def open_database(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Convenient first-run path: copy the generator's validated seed DB to app.db.
        project_root = Path(__file__).resolve().parents[3]
        candidates = [path.parent / "sql" / "seed.db", path.parent / "seed.db",
                      project_root / "data" / "samples" / "sql" / "seed.db"]
        seed = next((candidate for candidate in candidates if candidate.is_file()), None)
        if seed is None:
            raise FileNotFoundError(f"database {path} does not exist and no sibling seed.db was found")
        shutil.copy2(seed, path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if int(enabled) != 1:
            raise sqlite3.OperationalError(
                "SQLite foreign-key enforcement could not be enabled; use a SQLite build with FK support"
            )
        required = {"purchase_orders", "po_lines", "acknowledgements", "inventory_plans"}
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(required - existing)
        if missing:
            raise sqlite3.DatabaseError(
                f"database schema is incomplete (missing tables: {', '.join(missing)}); "
                "create it using `supplier-ack export --formats csv,json,sql`"
            )
        # SQLite's FK enforcement setting is connection-local. Enable it above and
        # also reject a hand-built schema that omitted the foreign-key declarations.
        missing_fk = [table for table in ("purchase_orders", "po_lines")
                      if not conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()]
        if missing_fk:
            raise sqlite3.DatabaseError(
                f"database schema has no declared foreign keys for {', '.join(missing_fk)}; "
                "regenerate the SQLite seed with `supplier-ack export --formats csv,json,sql`"
            )
        conn.executescript(RUNTIME_DDL)
        return conn
    except Exception:
        conn.close()
        raise


def _row(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> dict[str, Any] | None:
    value = conn.execute(sql, tuple(args)).fetchone()
    return dict(value) if value else None


def _rows(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _insert(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    columns = [c for c in values if c in _columns(conn, table)]
    if not columns:
        return
    sql = f'INSERT INTO "{table}" ({", ".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({", ".join("?" for _ in columns)})'
    conn.execute(sql, [values[c] for c in columns])


def _update(conn: sqlite3.Connection, table: str, pk: str, pk_value: Any, values: Mapping[str, Any]) -> None:
    columns = [c for c in values if c in _columns(conn, table)]
    if columns:
        conn.execute(f'UPDATE "{table}" SET '+", ".join(f'"{c}"=?' for c in columns)+f' WHERE "{pk}"=?', [values[c] for c in columns]+[pk_value])


def _next_id(conn: sqlite3.Connection, table: str, column: str, prefix: str, width: int = 6) -> str:
    rows = conn.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" LIKE ?', (prefix+"%",)).fetchall()
    nums = []
    for r in rows:
        match = re.search(r'(\d+)$', str(r[0] or ""))
        if match: nums.append(int(match.group(1)))
    return f"{prefix}{max(nums, default=0)+1:0{width}d}"


def _exception(conn: sqlite3.Connection, event_id: str, rule_id: str, severity: str,
               entity_type: str | None, entity_id: str | None, trace: Mapping[str, Any], message: str) -> None:
    _insert(conn, "runtime_exception", {"event_id": event_id, "rule_id": rule_id, "severity": severity,
        "entity_type": entity_type, "entity_id": entity_id, "entity_trace": _json(trace), "message": message, "created_at": utc_now()})


def _decision(conn: sqlite3.Connection, event_id: str, change_id: str | None, decision: str,
              rule_id: str, values: Mapping[str, Any], level: str | None, actor_id: str | None) -> None:
    _insert(conn, "runtime_decision", {"event_id": event_id, "change_request_id": change_id, "decision": decision,
        "rule_id": rule_id, "values_compared": _json(values), "required_approval_level": level,
        "approver_actor_id": actor_id, "created_at": utc_now()})


def _event_log(conn: sqlite3.Connection, event_id: str, event_type: str, entity_type: str, entity_id: str,
               actor_role: str, actor_id: str | None, old: Mapping[str, Any] | None, new: Mapping[str, Any] | None,
               targets: Mapping[str, Any] | None = None) -> None:
    payload = {"runtime": True, "source_event_id": event_id}
    base_id = "EVR-" + re.sub(r"[^A-Za-z0-9_-]", "-", event_id) + "-" + re.sub(r"[^A-Za-z0-9_-]", "-", event_type)
    event_log_id = base_id
    suffix = 1
    while conn.execute("SELECT 1 FROM entity_event WHERE event_id=?", (event_log_id,)).fetchone():
        event_log_id = f"{base_id}-{suffix:02d}"; suffix += 1
    _insert(conn, "entity_event", {"event_id": event_log_id, "entity_type": entity_type, "entity_id": entity_id,
        "event_type": event_type, "event_timestamp": utc_now(), "actor_role": actor_role, "actor_id": actor_id,
        "payload_json": _json(payload), "previous_state": _json(old) if old is not None else None,
        "new_state": _json(new) if new is not None else None, **(targets or {})})


def _notification(conn: sqlite3.Connection, event_id: str, po: Mapping[str, Any], subject: str, body: str,
                  severity: str = "MEDIUM", change_id: str | None = None, ack_id: str | None = None,
                  recipient_roles: Iterable[str] = ("planner",), po_line_id: str | None = None) -> str:
    nid = _next_id(conn, "notifications", "notification_id", "NOT-2026-", 6)
    now = utc_now()
    _insert(conn, "notifications", {"notification_id": nid, "not_id": nid, "not_type": "runtime_workflow",
        "severity": severity, "subject": subject, "title": subject, "body": body,
        "related_entity_type": "ChangeRequest" if change_id else "PurchaseOrder", "related_entity_id": change_id or po["po_id"],
        "read_status": "UNREAD", "po_id": po["po_id"], "ack_id": ack_id, "change_request_id": change_id,
        "source_event_id": event_id, "channel": "in_app", "status": "SENT", "scheduled_at": now,
        "sent_at": now, "created_at": now, "retry_count": 0})
    for role in recipient_roles:
        actor_id = None
        if role == "planner": actor_id = po.get("planner_actor_id")
        elif role == "supplier":
            found = _row(conn, "SELECT actor_id FROM actors WHERE supplier_id=? AND LOWER(actor_role)='supplier' LIMIT 1", (po.get("supplier_id"),))
            actor_id = found.get("actor_id") if found else None
        elif role == "carrier_warehouse_operator" and po_line_id:
            found = _row(conn, "SELECT carrier_operator_actor_id FROM promise_dates WHERE po_line_id=? ORDER BY revision_no DESC LIMIT 1", (po_line_id,))
            actor_id = found.get("carrier_operator_actor_id") if found else None
        else:
            found = _row(conn, "SELECT actor_id FROM actors WHERE LOWER(actor_role)=? LIMIT 1", (role,))
            actor_id = found.get("actor_id") if found else None
        _insert(conn, "notification_recipient", {"notification_id": nid, "actor_role": role, "recipient_actor_id": actor_id, "created_at": now})
    _event_log(conn, event_id, "notification_created", "Notification", nid, "system", None, None,
               {"status": "SENT", "subject": subject}, {"target_notification_id": nid, "target_po_id": po["po_id"]})
    return nid


def _create_change(conn: sqlite3.Connection, event_id: str, po: Mapping[str, Any], line: Mapping[str, Any],
                   kind: str, old: Any, new: Any, requested_by_role: str, requested_by_actor_id: str | None,
                   thresholds: Mapping[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    change_id = _next_id(conn, "change_requests", "change_request_id", f"CHG-{po['po_id']}-", 6)
    delta = computed_delta(kind, old, new)
    change = {"change_request_id": change_id, "po_id": po["po_id"], "supplier_id": po["supplier_id"],
        "po_line_id": line["po_line_id"], "change_type": kind, "request_type": kind.upper()+"_CHANGE",
        "old_value": str(old), "new_value": str(new), "delta": delta, "status": "SUBMITTED",
        "requested_by_role": requested_by_role, "requested_by_actor_id": requested_by_actor_id,
        "created_at": utc_now(), "requested_at": utc_now(), "updated_at": utc_now()}
    rule = evaluate_threshold(change, thresholds)
    change.update({"delta_abs": abs(delta), "delta_pct": delta if kind in {"price", "quantity"} else None,
                   "required_approval_level": rule["required_approval_level"]})
    if rule["hard_limit_breach"]:
        change["status"] = "REJECTED"
    _insert(conn, "change_requests", change)
    _event_log(conn, event_id, "change_requested", "ChangeRequest", change_id, requested_by_role,
               requested_by_actor_id, None, {"status": change["status"], "change_type": kind, "delta": delta},
               {"target_change_request_id": change_id, "target_po_id": po["po_id"], "target_po_line_id": line["po_line_id"]})
    _notification(conn, event_id, po, f"Change request {change_id} raised", f"A {kind} change for {line['po_line_id']} requires workflow review.", "HIGH" if not rule["within_threshold"] else "MEDIUM", change_id)
    decision = "REJECTED" if rule["hard_limit_breach"] else ("ROUTE_PLANNER" if rule["within_threshold"] else "ESCALATE")
    _decision(conn, event_id, change_id, decision, f"THRESHOLD_{rule['threshold_name']}",
              {"old_value": old, "new_value": new, "delta": delta, "threshold": rule["threshold_value"], "hard_limit": rule["hard_limit"]},
              rule["required_approval_level"], None)
    if not rule["hard_limit_breach"]:
        _insert(conn, "approvals", {"approval_id": _next_id(conn, "approvals", "approval_id", f"APR-{change_id}-", 2),
            "change_request_id": change_id, "approval_round": 1, "approver_role": rule["required_approval_level"],
            "approval_level": rule["required_approval_level"], "status": "PENDING", "requested_at": utc_now(),
            "threshold_name": rule["threshold_name"], "threshold_value": rule["threshold_value"], "created_at": utc_now()})
    return change_id, rule


def _apply_plan(conn: sqlite3.Connection, event_id: str, change: Mapping[str, Any], approval_level: str,
                actor_id: str | None) -> str:
    # Recalculate gate from the canonical rules; never trust event-provided approval level.
    approvals = _rows(conn, "SELECT * FROM approvals WHERE change_request_id=?", (change["change_request_id"],))
    ok, reason = can_apply(change, approvals)
    if not ok:
        _exception(conn, event_id, "APPROVAL_BEFORE_APPLY", "HIGH", "ChangeRequest", str(change["change_request_id"]),
                   {"change_request_id": change["change_request_id"], "po_id": change["po_id"]}, "Plan update refused: "+reason)
        _event_log(conn, event_id, "plan_update_refused", "ChangeRequest", str(change["change_request_id"]), "system", None,
                   {"status": change.get("status")}, {"status": "REFUSED", "reason": reason},
                   {"target_change_request_id": change["change_request_id"], "target_po_id": change["po_id"]})
        return "refused"
    po = _row(conn, "SELECT * FROM purchase_orders WHERE po_id=?", (change["po_id"],))
    line = _row(conn, "SELECT * FROM po_lines WHERE po_line_id=?", (change.get("po_line_id"),))
    if not po or not line:
        raise ValueError("approved change references missing PO or PO line")
    latest = _row(conn, "SELECT * FROM inventory_plans WHERE po_line_id=? AND COALESCE(is_effective,0)=1 ORDER BY plan_version DESC LIMIT 1", (line["po_line_id"],))
    if latest is None:
        latest = _row(conn, "SELECT * FROM inventory_plans WHERE po_line_id=? ORDER BY plan_version DESC LIMIT 1", (line["po_line_id"],))
    version = int(latest["plan_version"] if latest else 0) + 1
    plan_id = _next_id(conn, "inventory_plans", "inventory_plan_id", f"IP-{line['po_line_id']}-", 2)
    qty = float(latest["projected_qty"] if latest else line.get("requested_qty") or 0)
    promised_date = str(change.get("new_value")) if change.get("change_type") == "date" else str(latest.get("projected_delivery_date") if latest else line.get("required_date"))
    if change.get("change_type") == "quantity": qty = max(0.0, float(change.get("new_value") or 0))
    # Supersede current version without deleting historical rows.
    if latest:
        _update(conn, "inventory_plans", "inventory_plan_id", latest["inventory_plan_id"], {"is_effective": 0, "status": "SUPERSEDED", "superseded_by": plan_id, "updated_at": utc_now()})
        _event_log(conn,event_id,"inventory_plan_superseded","InventoryPlan",latest["inventory_plan_id"],"planner",po.get("planner_actor_id"),{"status":latest.get("status"),"is_effective":latest.get("is_effective")},{"status":"SUPERSEDED","is_effective":0,"superseded_by":plan_id},{"target_inventory_plan_id":latest["inventory_plan_id"],"target_po_id":po["po_id"],"target_po_line_id":line["po_line_id"]})
    _insert(conn, "inventory_plans", {"inventory_plan_id": plan_id, "po_id": po["po_id"], "po_line_id": line["po_line_id"],
        "plan_version": version, "plan_revision_no": version, "previous_version_id": latest.get("inventory_plan_id") if latest else None,
        "source": "approved_change", "is_effective": 1, "projected_delivery_date": promised_date,
        "change_request_id": change["change_request_id"], "status": "ACTIVE", "projected_qty": qty,
        "promised_qty": qty, "requested_qty": line.get("requested_qty"), "required_date": line.get("required_date"),
        "promised_date": promised_date, "plan_start_date": po.get("order_date"), "plan_end_date": promised_date,
        "planner_actor_id": po.get("planner_actor_id"), "approved_by_actor_id": actor_id,
        "effective_date": utc_now(), "created_at": utc_now(), "updated_at": utc_now()})
    _update(conn, "change_requests", "change_request_id", change["change_request_id"], {"status": "IMPLEMENTED", "updated_at": utc_now()})
    _event_log(conn, event_id, "change_applied", "ChangeRequest", str(change["change_request_id"]), "system", None,
               {"status": change.get("status")}, {"status": "IMPLEMENTED", "inventory_plan_id": plan_id},
               {"target_change_request_id": change["change_request_id"], "target_inventory_plan_id": plan_id, "target_po_id": po["po_id"], "target_po_line_id": line["po_line_id"]})
    # Compute conflicts against allocations, update production orders, and emit impacts.
    allocs = _rows(conn, "SELECT pol.*, pro.* FROM production_order_line pol JOIN production_orders pro USING(production_order_id) WHERE pol.po_line_id=?", (line["po_line_id"],))
    impacts = 0
    for order in allocs:
        allocated = float(order.get("allocated_quantity") or 0)
        shortfall = max(0.0, allocated-qty)
        delay = max(0, (date.fromisoformat(promised_date[:10])-date.fromisoformat(str(order.get("required_by_date"))[:10])).days)
        if shortfall <= 0 and delay <= 0: continue
        status = "AT_RISK" if shortfall > 0 else "RESCHEDULED"
        start = max(date.fromisoformat(str(order.get("planned_start_date"))[:10]), date.fromisoformat(promised_date[:10]))
        _update(conn, "production_orders", "production_order_id", order["production_order_id"], {"status": status, "at_risk": int(shortfall > 0), "shortfall_qty": shortfall, "delay_days": delay, "planned_start_date": start.isoformat(), "current_start_date": start.isoformat(), "updated_at": utc_now()})
        impact_id = _next_id(conn, "production_order_impact", "impact_id", "IMP-2026-", 6)
        _insert(conn, "production_order_impact", {"impact_id": impact_id, "production_order_id": order["production_order_id"], "change_request_id": change["change_request_id"], "po_line_id": line["po_line_id"], "impact_type": "quantity_shortfall" if shortfall > 0 else "date_conflict", "severity": "HIGH" if shortfall > 0 or delay > 7 else "MEDIUM", "slip_days": delay, "shortfall_pct": round(shortfall/max(allocated,1)*100,4), "old_projected_delivery_date": latest.get("projected_delivery_date") if latest else None, "new_projected_delivery_date": promised_date, "old_projected_qty": latest.get("projected_qty") if latest else None, "new_projected_qty": qty, "rescheduled_planned_start_date": start.isoformat(), "created_at": utc_now()})
        _event_log(conn, event_id, "production_order_status_changed", "ProductionOrder", order["production_order_id"], "planner", po.get("planner_actor_id"), {"status": order.get("status")}, {"status": status}, {"target_production_order_id": order["production_order_id"], "target_po_id": po["po_id"]})
        _notification(conn, event_id, po, f"Production order {order['production_order_id']} impacted", f"Change {change['change_request_id']} projected delivery/quantity affects production order {order['production_order_id']}.", "HIGH", str(change["change_request_id"]))
        impacts += 1
    _notification(conn, event_id, po, f"Approved change {change['change_request_id']} applied", f"Inventory plan {plan_id} is now effective for {line['po_line_id']}.", "MEDIUM", str(change["change_request_id"]))
    return f"applied:{plan_id}:impacts={impacts}"


class WorkflowEngine:
    def __init__(self, db_path: str | Path, thresholds: Mapping[str, Any] | None = None):
        self.db_path = Path(db_path)
        if thresholds is None:
            # Use the same checked-in configuration as the offline generator.
            import yaml
            config_path = Path(__file__).resolve().parents[3] / "config" / "generator_config.yaml"
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except OSError:
                config = {}
            thresholds = config.get("approval_thresholds", {})
        self.thresholds = thresholds

    def _connect(self) -> sqlite3.Connection:
        return open_database(self.db_path)

    def run(self, events_path: str | Path) -> dict[str, Any]:
        events = json.loads(Path(events_path).read_text(encoding="utf-8"))
        if isinstance(events, dict): events = events.get("events", [])
        if not isinstance(events, list): raise ValueError("event file must be a JSON array or {events: [...]}")
        summary = {"events_processed": 0, "changes_raised": 0, "approvals_routed": 0, "plans_updated": 0, "impacts": 0, "notifications": 0, "exceptions": 0, "results": []}
        conn = self._connect()
        try:
            for index, event in enumerate(events, 1):
                event_id = str(event.get("event_id") or f"EVR-IN-{index:06d}")
                event_type = str(event.get("event_type") or "")
                if event_type not in EVENT_TYPES: raise ValueError(f"unsupported event_type {event_type!r}; expected {sorted(EVENT_TYPES)}")
                if conn.execute("SELECT 1 FROM runtime_processed_event WHERE event_id=?", (event_id,)).fetchone():
                    summary["results"].append({"event_id": event_id, "status": "DUPLICATE_IGNORED"}); continue
                before = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in ("change_requests","approvals","inventory_plans","production_order_impact","notifications","runtime_exception")}
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    outcome = self._process(conn, event_id, event_type, event)
                    conn.execute("INSERT INTO runtime_processed_event(event_id,event_type,payload_json,outcome_json,processed_at) VALUES(?,?,?,?,?)", (event_id,event_type,_json(event),_json(outcome),utc_now()))
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    # Persist an exception even when the business transaction rolls back.
                    conn.execute("BEGIN IMMEDIATE")
                    _exception(conn, event_id, "RUNTIME_EVENT_FAILURE", "HIGH", None, None, {"event_type": event_type}, str(exc))
                    conn.execute("INSERT OR REPLACE INTO runtime_processed_event(event_id,event_type,payload_json,outcome_json,processed_at) VALUES(?,?,?,?,?)", (event_id,event_type,_json(event),_json({"status":"EXCEPTION","error":str(exc)}),utc_now()))
                    conn.commit(); outcome={"status":"EXCEPTION","error":str(exc)}
                after = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before}
                summary["events_processed"] += 1
                summary["changes_raised"] += max(0,after["change_requests"]-before["change_requests"])
                summary["approvals_routed"] += max(0,after["approvals"]-before["approvals"])
                summary["plans_updated"] += max(0,after["inventory_plans"]-before["inventory_plans"])
                summary["impacts"] += max(0,after["production_order_impact"]-before["production_order_impact"])
                summary["notifications"] += max(0,after["notifications"]-before["notifications"])
                summary["exceptions"] += max(0,after["runtime_exception"]-before["runtime_exception"])
                summary["results"].append({"event_id":event_id, **outcome})
        finally: conn.close()
        return summary

    def _process(self, conn: sqlite3.Connection, event_id: str, kind: str, event: Mapping[str, Any]) -> dict[str, Any]:
        if kind in {"ack_submitted", "ack_revision_received"}: outcome = self._ack(conn,event_id,event)
        elif kind == "promise_updated": outcome = self._promise(conn,event_id,event)
        elif kind == "change_requested": outcome = self._change(conn,event_id,event)
        elif kind == "approval_decision": outcome = self._approval(conn,event_id,event)
        elif kind == "silence_timeout": outcome = self._silence(conn,event_id,event)
        else: raise ValueError(kind)
        _event_log(conn,"RECEIPT-"+event_id,"runtime_event_processed","RuntimeEvent",event_id,"system",None,None,
                   {"status": outcome.get("status", "PROCESSED"), "event_type": kind},None)
        return outcome

    def _ack(self, conn: sqlite3.Connection, event_id: str, e: Mapping[str, Any]) -> dict[str, Any]:
        po_id=str(e.get("po_id") or ""); po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(po_id,))
        if not po:
            _exception(conn,event_id,"ACK_INVALID_PO_REFERENCE","HIGH","PurchaseOrder",po_id,{"po_id":po_id},"Acknowledgement references an unknown PO")
            return {"status":"REJECTED_INVALID_REFERENCE"}
        revision=int(e.get("revision_no") or 1)
        latest=_row(conn,"SELECT * FROM acknowledgements WHERE po_id=? ORDER BY revision_no DESC LIMIT 1",(po_id,))
        ack_id=str(e.get("ack_id") or f"ACK-{po_id}-{revision:02d}")
        if latest and revision <= int(latest["revision_no"]):
            _exception(conn,event_id,"STALE_REVISION_GUARD","HIGH","Acknowledgement",ack_id,{"po_id":po_id,"current_ack_id":latest["ack_id"]},f"Refused to make revision {revision} effective; latest revision is {latest['revision_no']}")
            _event_log(conn,event_id,"stale_ack_revision_recorded","Acknowledgement",ack_id,"supplier",e.get("actor_id"),None,{"revision_no":revision,"effective":False},{"target_po_id":po_id,"target_ack_id":latest["ack_id"]})
            return {"status":"STALE_REVISION_RECORDED","effective":False}
        lines=e.get("lines") or []
        if not lines: raise ValueError("ack_submitted requires non-empty lines")
        for item in lines:
            line_id = str(item.get("po_line_id") or "")
            if not _row(conn, "SELECT po_line_id FROM po_lines WHERE po_line_id=? AND po_id=?", (line_id, po_id)):
                _exception(conn,event_id,"ACK_INVALID_PO_LINE_REFERENCE","HIGH","Acknowledgement",ack_id,{"po_id":po_id,"po_line_id":line_id},"Acknowledgement line does not belong to referenced PO")
                return {"status":"REJECTED_INVALID_REFERENCE"}
        for line_index, item in enumerate(lines):
            line_id=str(item.get("po_line_id") or "")
            line=_row(conn,"SELECT * FROM po_lines WHERE po_line_id=? AND po_id=?",(line_id,po_id))
            if not line:
                _exception(conn,event_id,"ACK_INVALID_PO_LINE_REFERENCE","HIGH","Acknowledgement",ack_id,{"po_id":po_id,"po_line_id":line_id},"Acknowledgement line does not belong to referenced PO")
                return {"status":"REJECTED_INVALID_REFERENCE"}
            requested=float(item.get("requested_qty",line["requested_qty"])); accepted=float(item.get("accepted_qty",requested)); rejected=round(requested-accepted,3)
            status={"full_accept":"ACCEPTED","partial_accept":"PARTIALLY_ACCEPTED","full_reject":"REJECTED"}[derive_ack_status(requested,accepted)]
            now=utc_now()
            if line_index == 0:
                if latest:
                    _update(conn,"acknowledgements","ack_id",latest["ack_id"],{"status":"SUPERSEDED","superseded_by":ack_id})
                    _event_log(conn,event_id,"acknowledgement_superseded","Acknowledgement",latest["ack_id"],"supplier",e.get("actor_id"),{"status":latest.get("status")},{"status":"SUPERSEDED","superseded_by":ack_id},{"target_ack_id":latest["ack_id"],"target_po_id":po_id})
                _insert(conn,"acknowledgements",{"ack_id":ack_id,"po_id":po_id,"supplier_id":po["supplier_id"],"po_line_id":line_id,"revision_no":revision,"status":status,"lifecycle_state":"PROCESSED","acknowledged_at":e.get("response_timestamp") or now,"response_due_at":po.get("response_due_at"),"requested_qty":requested,"ack_accepted_qty":accepted,"ack_rejected_qty":rejected,"promised_qty":accepted,"projected_qty":accepted,"requested_value":float(line["requested_qty"])*float(line["unit_price"]),"acknowledged_value":accepted*float(item.get("unit_price",line["unit_price"])),"promised_value":accepted*float(item.get("unit_price",line["unit_price"])),"qty_delta_pct":computed_delta("quantity",requested,accepted),"price_delta_pct":computed_delta("price",line["unit_price"],item.get("unit_price",line["unit_price"])),"created_at":now,"created_by_role":"supplier","created_by_actor_id":e.get("actor_id")})
            _insert(conn,"acknowledgement_lines",{"acknowledgement_line_id":f"{ack_id}-L{int(line.get('line_no') or 1):02d}","ack_id":ack_id,"po_id":po_id,"po_line_id":line_id,"revision_no":revision,"status":status,"requested_qty":requested,"accepted_qty":accepted,"rejected_qty":rejected,"requested_unit_price":line["unit_price"],"acknowledged_unit_price":item.get("unit_price",line["unit_price"]),"qty_delta_pct":computed_delta("quantity",requested,accepted),"price_delta_pct":computed_delta("price",line["unit_price"],item.get("unit_price",line["unit_price"])),"response_timestamp":now,"created_at":now,"created_by_role":"supplier"})
            promised_date = str(item.get("promised_date") or (date.fromisoformat(str(line["required_date"])[:10]) + timedelta(days=int(item.get("promised_offset_days", 0)))).isoformat())
            self._promise_row(conn,event_id,po,line,ack_id,revision,accepted,promised_date,e.get("actor_id"))
            for typ,old,new in (("quantity",line["requested_qty"],accepted),("price",line["unit_price"],item.get("unit_price",line["unit_price"])),("date",line["required_date"],promised_date)):
                delta= computed_delta(typ,old,new)
                rule=evaluate_threshold({"change_type":typ,"old_value":old,"new_value":new},self.thresholds)
                if abs(delta)>0 and (not rule["within_threshold"] or rule["hard_limit_breach"]):
                    _, _ = _create_change(conn,event_id,po,line,typ,old,new,"supplier",e.get("actor_id"),self.thresholds)
        _event_log(conn,event_id,"ack_submitted","Acknowledgement",ack_id,"supplier",e.get("actor_id"),None,{"status":"PROCESSED","revision_no":revision},{"target_po_id":po_id,"target_ack_id":ack_id})
        _notification(conn,event_id,po,f"Acknowledgement {ack_id} processed",f"Acknowledgement {ack_id} for {po_id} was processed.","LOW",ack_id=ack_id)
        return {"status":"PROCESSED","ack_id":ack_id,"revision_no":revision}

    def _promise_row(self,conn:sqlite3.Connection,event_id:str,po:Mapping[str,Any],line:Mapping[str,Any],ack_id:str,revision:int,qty:float,promised_date:str,actor_id:str|None)->None:
        order_date=str(po["order_date"])
        if promised_date[:10] < order_date[:10]:
            _exception(conn,event_id,"PROMISE_BEFORE_ORDER_DATE","HIGH","PromiseDate",None,{"po_id":po["po_id"],"po_line_id":line["po_line_id"],"ack_id":ack_id},"Promise date is earlier than PO order date")
            _update(conn,"acknowledgements","ack_id",ack_id,{"lifecycle_state":"EXCEPTION","status":"REJECTED"})
            _notification(conn,event_id,po,"Invalid promise date rejected",f"Promise {promised_date} precedes order date {order_date}; acknowledgement {ack_id} was rejected.","HIGH",ack_id=ack_id)
            return
        prior=_row(conn,"SELECT * FROM promise_dates WHERE po_line_id=? AND status='CURRENT' ORDER BY revision_no DESC LIMIT 1",(line["po_line_id"],))
        promise_derived = derive_promise_date(promised_date, line["required_date"])
        pid=_next_id(conn,"promise_dates","promise_date_id",f"PD-{ack_id}-",2)
        if prior:
            _update(conn,"promise_dates","promise_date_id",prior["promise_date_id"],{"status":"SUPERSEDED","superseded_by":pid})
            _event_log(conn,event_id,"promise_superseded","PromiseDate",prior["promise_date_id"],"supplier",actor_id,{"status":prior.get("status")},{"status":"SUPERSEDED","superseded_by":pid},{"target_promise_date_id":prior["promise_date_id"],"target_po_id":po["po_id"]})
        _insert(conn,"promise_dates",{"promise_date_id":pid,"ack_id":ack_id,"po_id":po["po_id"],"po_line_id":line["po_line_id"],"sequence_no":revision,"revision_no":revision,"promised_date":promised_date,"slip_days":promise_derived["slip_days"],"is_late":int(promise_derived["is_late"]),"promised_qty":qty,"promise_confidence":"MEDIUM","ship_from_warehouse_id":po.get("warehouse_id"),"carrier_id":po.get("carrier_id"),"effective_date":utc_now(),"response_due_date":po.get("response_due_at"),"status":"CURRENT","source":"runtime","prior_promised_date":prior.get("promised_date") if prior else None,"created_at":utc_now(),"created_by_role":"supplier","created_by_actor_id":actor_id})

    def _promise(self,conn:sqlite3.Connection,event_id:str,e:Mapping[str,Any])->dict[str,Any]:
        po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(e.get("po_id"),)); line=_row(conn,"SELECT * FROM po_lines WHERE po_line_id=? AND po_id=?",(e.get("po_line_id"),e.get("po_id")))
        if not po or not line:
            _exception(conn,event_id,"PROMISE_INVALID_REFERENCE","HIGH","PromiseDate",str(e.get("po_line_id")),{"po_id":e.get("po_id"),"po_line_id":e.get("po_line_id")},"Promise update references invalid PO/line")
            return {"status":"REJECTED_INVALID_REFERENCE"}
        ack_id=str(e.get("ack_id") or "")
        ack=_row(conn,"SELECT * FROM acknowledgements WHERE ack_id=? AND po_id=?",(ack_id,po["po_id"])) if ack_id else _row(conn,"SELECT * FROM acknowledgements WHERE po_id=? ORDER BY revision_no DESC LIMIT 1",(po["po_id"],))
        if not ack: raise ValueError("promise_updated requires an existing acknowledgement")
        promised=str(e.get("promised_date") or "")
        before=promised[:10] < str(po["order_date"])[:10]
        if before:
            _update(conn,"acknowledgements","ack_id",ack["ack_id"],{"lifecycle_state":"EXCEPTION","status":"REJECTED"})
            _exception(conn,event_id,"PROMISE_BEFORE_ORDER_DATE","CRITICAL","PromiseDate",None,{"po_id":po["po_id"],"ack_id":ack["ack_id"],"po_line_id":line["po_line_id"]},f"Promise date {promised} precedes order date {po['order_date']}")
            _notification(conn,event_id,po,"Impossible promise date rejected",f"Promise {promised} is before order date {po['order_date']}; planner action required.","CRITICAL",ack_id=ack["ack_id"])
            _event_log(conn,event_id,"promise_rejected_impossible_date","Acknowledgement",ack["ack_id"],"system",None,{"lifecycle_state":ack["lifecycle_state"]},{"lifecycle_state":"EXCEPTION"},{"target_ack_id":ack["ack_id"],"target_po_id":po["po_id"]})
            return {"status":"REJECTED_IMPOSSIBLE_DATE"}
        self._promise_row(conn,event_id,po,line,ack["ack_id"],int(ack["revision_no"]),float(e.get("promised_qty",ack.get("promised_qty") or line["requested_qty"])),promised,e.get("actor_id"))
        return {"status":"PROMISE_UPDATED","ack_id":ack["ack_id"]}

    def _change(self,conn:sqlite3.Connection,event_id:str,e:Mapping[str,Any])->dict[str,Any]:
        po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(e.get("po_id"),)); line=_row(conn,"SELECT * FROM po_lines WHERE po_line_id=? AND po_id=?",(e.get("po_line_id"),e.get("po_id")))
        if not po or not line:
            _exception(conn,event_id,"CHANGE_INVALID_REFERENCE","HIGH","ChangeRequest",None,{"po_id":e.get("po_id"),"po_line_id":e.get("po_line_id")},"Change request references unknown PO/line")
            return {"status":"REJECTED_INVALID_REFERENCE"}
        kind = str(e.get("change_type") or "").lower()
        source_old = {"date": line.get("required_date"), "price": line.get("unit_price"), "quantity": line.get("requested_qty")}.get(kind)
        old_value = e.get("old_value", source_old)
        new_value = e.get("new_value")
        if new_value is None and kind == "date" and e.get("offset_days") is not None:
            new_value = (date.fromisoformat(str(old_value)[:10]) + timedelta(days=int(e["offset_days"]))).isoformat()
        elif new_value is None and kind in {"price", "quantity"} and e.get("multiplier") is not None:
            new_value = float(old_value) * float(e["multiplier"])
        if new_value is None:
            raise ValueError("change_requested requires new_value, or offset_days/multiplier for a derived proposal")
        cid,rule=_create_change(conn,event_id,po,line,kind,old_value,new_value,str(e.get("requested_by_role") or "planner"),e.get("requested_by_actor_id"),self.thresholds)
        if e.get("attempt_plan_update"):
            change=_row(conn,"SELECT * FROM change_requests WHERE change_request_id=?",(cid,))
            result=_apply_plan(conn,event_id,change,"",None)
            return {"status":"PLAN_UPDATE_REFUSED" if result=="refused" else result,"change_request_id":cid}
        return {"status":"CHANGE_RAISED","change_request_id":cid,"required_approval_level":rule["required_approval_level"]}

    def _approval(self,conn:sqlite3.Connection,event_id:str,e:Mapping[str,Any])->dict[str,Any]:
        change=_row(conn,"SELECT * FROM change_requests WHERE change_request_id=?",(e.get("change_request_id"),))
        if not change:
            _exception(conn,event_id,"APPROVAL_UNKNOWN_CHANGE","HIGH","ChangeRequest",str(e.get("change_request_id")),{"change_request_id":e.get("change_request_id")},"Approval references unknown change")
            return {"status":"REJECTED_INVALID_REFERENCE"}
        level=str(e.get("approval_level") or e.get("approver_role") or "").lower(); required=required_approval_level(change,self.thresholds); decision=str(e.get("decision") or "").upper()
        if decision not in {"APPROVED","REJECTED"}: raise ValueError("decision must be approved or rejected")
        if decision=="APPROVED" and level!=required:
            _exception(conn,event_id,"APPROVAL_WRONG_LEVEL","HIGH","ChangeRequest",change["change_request_id"],{"required":required,"provided":level},f"Approval at {level} cannot satisfy required level {required}")
            decision="REJECTED"
        approval_id=_next_id(conn,"approvals","approval_id",f"APR-{change['change_request_id']}-",2)
        _insert(conn,"approvals",{"approval_id":approval_id,"change_request_id":change["change_request_id"],"approval_round":int(e.get("approval_round") or 1),"approver_role":level,"approval_level":level,"approver_actor_id":e.get("approver_actor_id"),"status":decision,"decided_at":utc_now(),"decision_reason":e.get("comments"),"comments":e.get("comments"),"created_at":utc_now()})
        _event_log(conn,event_id,"approval_decided","Approval",approval_id,level,e.get("approver_actor_id"),{"status":"PENDING"},{"status":decision},{"target_approval_id":approval_id,"target_change_request_id":change["change_request_id"],"target_po_id":change["po_id"]})
        _decision(conn,event_id,change["change_request_id"],decision,"APPROVAL_DECISION_LEVEL_CHECK",{"provided_level":level,"required_level":required},required,e.get("approver_actor_id"))
        po_for_notice = _row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(change["po_id"],))
        if po_for_notice:
            requester_role = str(change.get("requested_by_role") or "planner").lower()
            _notification(conn,event_id,po_for_notice,f"Approval decision for {change['change_request_id']}",f"Change {change['change_request_id']} decision: {decision} at {level} level.","HIGH" if decision=="REJECTED" else "MEDIUM",str(change["change_request_id"]),recipient_roles=(requester_role,))
        if decision=="REJECTED":
            _update(conn,"change_requests","change_request_id",change["change_request_id"],{"status":"REJECTED","updated_at":utc_now()})
            po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(change["po_id"],)); _notification(conn,event_id,po,"Change rejected",f"Change {change['change_request_id']} was rejected.","HIGH",change["change_request_id"])
            return {"status":"REJECTED","approval_id":approval_id}
        _update(conn,"change_requests","change_request_id",change["change_request_id"],{"status":"APPROVED","updated_at":utc_now()})
        change=_row(conn,"SELECT * FROM change_requests WHERE change_request_id=?",(change["change_request_id"],))
        applied=_apply_plan(conn,event_id,change,level,e.get("approver_actor_id"))
        return {"status":"APPROVED","approval_id":approval_id,"plan_result":applied}

    def _silence(self,conn:sqlite3.Connection,event_id:str,e:Mapping[str,Any])->dict[str,Any]:
        po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(e.get("po_id"),))
        if not po:
            _exception(conn,event_id,"SILENCE_UNKNOWN_PO","HIGH","PurchaseOrder",str(e.get("po_id")),{"po_id":e.get("po_id")},"Silence timeout references unknown PO")
            return {"status":"REJECTED_INVALID_REFERENCE"}
        line=_row(conn,"SELECT * FROM po_lines WHERE po_id=? ORDER BY line_no LIMIT 1",(po["po_id"],))
        if not line: raise ValueError("silence_timeout PO has no lines")
        cid,rule=_create_change(conn,event_id,po,line,"date",line["required_date"],e.get("requested_promised_date") or line["required_date"],"planner",po.get("planner_actor_id"),self.thresholds)
        _notification(conn,event_id,po,"Supplier response overdue — chase required",f"Supplier has not acknowledged {po['po_id']} by response due date {po.get('response_due_at')}. Change {cid} routed to planner.","HIGH",cid,recipient_roles=("planner", "supplier"))
        return {"status":"SILENCE_ESCALATED","change_request_id":cid,"required_approval_level":rule["required_approval_level"]}

    def status(self, po_id: str) -> dict[str, Any]:
        conn=self._connect()
        try:
            po=_row(conn,"SELECT * FROM purchase_orders WHERE po_id=?",(po_id,))
            if not po: raise KeyError(f"PO {po_id} not found")
            ack=_row(conn,"SELECT * FROM acknowledgements WHERE po_id=? ORDER BY revision_no DESC LIMIT 1",(po_id,))
            promises=_rows(conn,"SELECT * FROM promise_dates WHERE po_id=? AND status='CURRENT' ORDER BY promised_date",(po_id,))
            changes=_rows(conn,"SELECT * FROM change_requests WHERE po_id=? AND status NOT IN ('IMPLEMENTED','REJECTED','CLOSED','CANCELLED') ORDER BY created_at",(po_id,))
            plans=_rows(conn,"SELECT * FROM inventory_plans WHERE po_id=? ORDER BY po_line_id,plan_version",(po_id,))
            impacts=_rows(conn,"SELECT i.* FROM production_order_impact i JOIN production_orders p USING(production_order_id) WHERE p.po_id=? ORDER BY i.created_at",(po_id,))
            notifications=_rows(conn,"SELECT * FROM notifications WHERE po_id=? ORDER BY created_at",(po_id,))
            events=_rows(conn,"SELECT * FROM entity_event WHERE target_po_id=? OR entity_id=? ORDER BY event_timestamp,event_id",(po_id,po_id))
            return {"purchase_order":po,"current_acknowledgement":ack,"effective_promises":promises,"open_changes":changes,"plan_versions":plans,"impacts":impacts,"notifications":notifications,"event_timeline":events}
        finally: conn.close()

    def exceptions(self) -> list[dict[str, Any]]:
        conn=self._connect()
        try: return _rows(conn,"SELECT * FROM runtime_exception ORDER BY exception_id")
        finally: conn.close()

    def decisions(self) -> list[dict[str, Any]]:
        conn=self._connect()
        try: return _rows(conn,"SELECT * FROM runtime_decision ORDER BY decision_id")
        finally: conn.close()
