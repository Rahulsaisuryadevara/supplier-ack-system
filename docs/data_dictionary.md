# Data dictionary

| Field | Meaning |
|---|---|
| `po_id` | Stable purchase-order identifier. |
| `supplier_id` | Supplier responsible for the acknowledgement. |
| `ack_status` | `pending`, `acknowledged`, or `rejected`. |
| `promised_date` | Latest supplier-committed delivery date. |
| `date_slip_days` | Promised date minus required date in calendar days. |
| `quantity_delta` | Confirmed quantity minus ordered quantity; negative means short. |
| `impact_level` | Schedule-risk classification (`low`, `medium`, `high`, `critical`). |
| `decision` | Workflow disposition (`accept`, `review`, `approve`, `reject`, `escalate`). |
| `actor_role` | Role responsible for the event or decision. |
| `before_json` / `after_json` | State snapshots retained for traceability. |
| `target_role` / `target_id` | Notification recipient role and identity. |

## Actor ownership

- **Supplier:** acknowledgement owner and requester of promise/quantity changes.
- **Planner:** schedule owner and schedule-impact reviewer.
- **Carrier/Warehouse Operator:** dispatch and receipt confirmation.
- **Logistics Analyst:** transit-risk analysis and logistics exception owner.
- **Operations Manager:** exception approver and escalation owner.
