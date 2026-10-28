"""Initial schema and data dictionary definitions.

These definitions are intentionally lightweight and are used by generators,
validation, persistence, and documentation.
"""

TABLE_COLUMNS = {
    "suppliers": ["supplier_id", "supplier_name", "email", "risk_tier", "owner_actor"],
    "purchase_orders": [
        "po_id", "supplier_id", "planner_actor", "warehouse_id", "carrier_id",
        "created_date", "required_date", "ordered_quantity", "unit_price", "currency",
        "status",
    ],
    "acknowledgements": [
        "ack_id", "po_id", "ack_status", "acknowledged_at", "promised_date",
        "confirmed_quantity", "confirmed_unit_price", "supplier_note",
    ],
    "schedule_impacts": [
        "impact_id", "po_id", "original_required_date", "current_promised_date",
        "date_slip_days", "quantity_delta", "impact_level", "decision",
        "planner_actor", "approver_actor",
    ],
    "events": [
        "event_id", "po_id", "event_type", "event_time", "actor_role",
        "actor_id", "before_json", "after_json", "reason",
    ],
    "notifications": [
        "notification_id", "po_id", "event_id", "target_role", "target_id",
        "channel", "status", "created_at",
    ],
}

ACTOR_ROLES = {
    "supplier": "Owns acknowledgement and requests promise/quantity changes.",
    "planner": "Owns the production or replenishment schedule and reviews impacts.",
    "carrier_warehouse_operator": "Confirms dispatch and warehouse receipt milestones.",
    "logistics_analyst": "Assesses transit risk and owns logistics exceptions.",
    "operations_manager": "Approves threshold exceptions and handles escalations.",
}

DATA_DICTIONARY = {
    "ack_status": "Supplier response state: pending, acknowledged, or rejected.",
    "promised_date": "Latest supplier-committed delivery date.",
    "date_slip_days": "Calendar-day difference between promised and required dates.",
    "quantity_delta": "Confirmed quantity minus ordered quantity; negative means short.",
    "impact_level": "Computed schedule risk classification: low, medium, high, critical.",
    "decision": "Workflow decision: accept, review, approve, reject, or escalate.",
    "actor_role": "Role responsible for a recorded event.",
    "before_json": "Serialized state before a change, for traceability.",
    "after_json": "Serialized state after a change, for traceability.",
}
