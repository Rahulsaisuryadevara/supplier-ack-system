# Complete data dictionary — Generation Step 1

This is the schema contract for synthetic data generation, persistence, workflow rules, validation, and metrics. The machine-readable source is `src/supplier_ack/schema.py`; this Markdown is generated from the same `ENTITIES` specs.

## Conventions and validation semantics

- `Required` means a stored value must be non-NULL; optional values may be NULL. ISO datetimes must include an explicit UTC offset; UTC is recommended.
- Primary keys follow the ID formats in their field rows. Number suffixes are zero-padded; references embedded in IDs must match their FK fields.
- Foreign keys naming support tables (`actors`, `items`, `warehouses`, `carriers`, `events`) refer to supporting operational/master tables outside the ten core entities. Actor role values are `supplier`, `planner`, `carrier_warehouse_operator`, `logistics_analyst`, and `operations_manager`.
- On `Acknowledgement`, a header-level row has `po_line_id = NULL`; when a line is the focus of an exception, it may be populated and must belong to `po_id`. Per-line commitments are persisted in `PromiseDate` and `POLine`.
- `issue_type` and `ground_truth` are both `NULL` for intentionally normal rows. Labelled anomaly rows populate both from `ANOMALY_TYPES`. This supports auditable synthetic anomaly cohorts.
- `line_total` is `ROUND_HALF_UP(requested_qty * unit_price, 2)`. On final acknowledgement states, `requested_qty = ack_accepted_qty + ack_rejected_qty`; pending/submitted acknowledgements can have no resolved quantity split yet.
- Cross-table FK checks and ownership consistency checks run with `validate_dataset(...)`; row-level rules run with `validate_record(...)`. `is_legal_transition(...)` validates lifecycle transitions.

## Entity volume summary

Counts are baseline generation targets, before revision/event-driven uplift and before optional multi-recipient notification fan-out. The starter and full scales use the same generator rules; only configured scale counts differ.

| Entity | Primary key | Foreign keys | Baseline rows (starter / full) | Generation step |
|---|---|---|---:|---|
| Supplier | `supplier_id` | — | 120 / 120 | Step 2 — supplier/master-data generation |
| PurchaseOrder | `po_id` | `supplier_id` → `suppliers.supplier_id`; `planner_actor_id` → `actors.actor_id`; `warehouse_id` → `warehouses.warehouse_id`; `carrier_id` → `carriers.carrier_id`; `created_by_actor_id` → `actors.actor_id` | 200 / 10,000 | Step 3 — purchase-order header generation |
| POLine | `po_line_id` | `po_id` → `purchase_orders.po_id`; `item_id` → `items.item_id` | 600 (3 per PO) / 30,000 (3 per PO) | Step 3 — purchase-order line generation |
| Acknowledgement | `ack_id` | `po_id` → `purchase_orders.po_id`; `supplier_id` → `suppliers.supplier_id`; `po_line_id` → `po_lines.po_line_id`; `superseded_by` → `acknowledgements.ack_id`; `created_by_actor_id` → `actors.actor_id` | 200 initial rows; + amendment revisions / 10,000 initial rows; + amendment revisions | Step 4 — acknowledgement/revision generation |
| PromiseDate | `promise_date_id` | `ack_id` → `acknowledgements.ack_id`; `po_id` → `purchase_orders.po_id`; `po_line_id` → `po_lines.po_line_id`; `superseded_by` → `promise_dates.promise_date_id`; `created_by_actor_id` → `actors.actor_id` | 600 initial line promises; additional revisions / 30,000 initial line promises; additional revisions | Step 4 — line-level promise-date generation |
| ChangeRequest | `change_request_id` | `po_id` → `purchase_orders.po_id`; `supplier_id` → `suppliers.supplier_id`; `po_line_id` → `po_lines.po_line_id`; `requested_by_actor_id` → `actors.actor_id` | 72 baseline (24% of 300 events; amendments may add rows) / 3,600 baseline (24% of 15,000 events; amendments may add rows) | Step 5 — change-request generation |
| Approval | `approval_id` | `change_request_id` → `change_requests.change_request_id`; `approver_actor_id` → `actors.actor_id` | 36 baseline (50% of baseline change requests; rule-dependent) / 1,800 baseline (50% of baseline change requests; rule-dependent) | Step 5 — approval/decision generation |
| InventoryPlan | `inventory_plan_id` | `po_id` → `purchase_orders.po_id`; `po_line_id` → `po_lines.po_line_id`; `planner_actor_id` → `actors.actor_id`; `approved_by_actor_id` → `actors.actor_id`; `superseded_by` → `inventory_plans.inventory_plan_id` | 600 initial plans (1 per PO line) / 30,000 initial plans (1 per PO line) | Step 6 — inventory-plan generation |
| ProductionOrder | `production_order_id` | `inventory_plan_id` → `inventory_plans.inventory_plan_id`; `po_id` → `purchase_orders.po_id`; `po_line_id` → `po_lines.po_line_id`; `owner_actor_id` → `actors.actor_id` | 100 initial production orders / 5,000 initial production orders (configurable planning slice) | Step 6 — downstream production-order generation |
| Notification | `notification_id` | `po_id` → `purchase_orders.po_id`; `ack_id` → `acknowledgements.ack_id`; `change_request_id` → `change_requests.change_request_id`; `source_event_id` → `events.event_id`; `target_actor_id` → `actors.actor_id` | 300 initial notifications (one per generated event; recipient fan-out may add rows) / 15,000 initial notifications (one per generated event; recipient fan-out may add rows) | Step 7 — event-driven notification generation |

## Entity lifecycle transitions

### PurchaseOrder

| Current state | Legal next states |
|---|---|
| `DRAFT` | `ISSUED`, `CANCELLED` |
| `ISSUED` | `PARTIALLY_ACKNOWLEDGED`, `ACKNOWLEDGED`, `CHANGE_PENDING`, `IN_FULFILLMENT`, `CANCELLED`, `CLOSED` |
| `PARTIALLY_ACKNOWLEDGED` | `ACKNOWLEDGED`, `CHANGE_PENDING`, `IN_FULFILLMENT`, `CANCELLED` |
| `ACKNOWLEDGED` | `CHANGE_PENDING`, `IN_FULFILLMENT`, `CANCELLED` |
| `CHANGE_PENDING` | `ISSUED`, `PARTIALLY_ACKNOWLEDGED`, `ACKNOWLEDGED`, `CANCELLED` |
| `IN_FULFILLMENT` | `PARTIALLY_RECEIVED`, `RECEIVED`, `CLOSED` |
| `PARTIALLY_RECEIVED` | `RECEIVED`, `CLOSED` |
| `RECEIVED` | `CLOSED` |
| `CANCELLED` | Terminal; no outgoing transition |
| `CLOSED` | Terminal; no outgoing transition |

### POLine

| Current state | Legal next states |
|---|---|
| `DRAFT` | `OPEN`, `CANCELLED` |
| `OPEN` | `PARTIALLY_ACKNOWLEDGED`, `ACKNOWLEDGED`, `CHANGE_PENDING`, `CANCELLED` |
| `PARTIALLY_ACKNOWLEDGED` | `ACKNOWLEDGED`, `CHANGE_PENDING`, `CANCELLED` |
| `ACKNOWLEDGED` | `CHANGE_PENDING`, `IN_FULFILLMENT`, `CANCELLED` |
| `CHANGE_PENDING` | `OPEN`, `PARTIALLY_ACKNOWLEDGED`, `ACKNOWLEDGED`, `CANCELLED` |
| `IN_FULFILLMENT` | `PARTIALLY_RECEIVED`, `RECEIVED` |
| `PARTIALLY_RECEIVED` | `RECEIVED` |
| `RECEIVED` | `CLOSED` |
| `CANCELLED` | `CLOSED` |
| `CLOSED` | Terminal; no outgoing transition |

### Acknowledgement

| Current state | Legal next states |
|---|---|
| `DRAFT` | `SUBMITTED`, `WITHDRAWN` |
| `SUBMITTED` | `UNDER_REVIEW`, `ACCEPTED`, `PARTIALLY_ACCEPTED`, `REJECTED`, `SUPERSEDED`, `WITHDRAWN` |
| `UNDER_REVIEW` | `ACCEPTED`, `PARTIALLY_ACCEPTED`, `REJECTED`, `SUPERSEDED`, `WITHDRAWN` |
| `ACCEPTED` | `SUPERSEDED` |
| `PARTIALLY_ACCEPTED` | `SUPERSEDED` |
| `REJECTED` | `SUPERSEDED` |
| `SUPERSEDED` | Terminal; no outgoing transition |
| `WITHDRAWN` | Terminal; no outgoing transition |

### PromiseDate

| Current state | Legal next states |
|---|---|
| `PROPOSED` | `CURRENT`, `CANCELLED` |
| `CURRENT` | `SUPERSEDED`, `CANCELLED` |
| `SUPERSEDED` | Terminal; no outgoing transition |
| `CANCELLED` | Terminal; no outgoing transition |

### ChangeRequest

| Current state | Legal next states |
|---|---|
| `DRAFT` | `SUBMITTED`, `WITHDRAWN` |
| `SUBMITTED` | `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `CANCELLED`, `WITHDRAWN` |
| `UNDER_REVIEW` | `APPROVED`, `REJECTED`, `CANCELLED`, `WITHDRAWN` |
| `APPROVED` | `IMPLEMENTED`, `CANCELLED` |
| `REJECTED` | `CLOSED` |
| `IMPLEMENTED` | `CLOSED` |
| `CANCELLED` | `CLOSED` |
| `WITHDRAWN` | `CLOSED` |
| `CLOSED` | Terminal; no outgoing transition |

### Approval

| Current state | Legal next states |
|---|---|
| `PENDING` | `APPROVED`, `REJECTED`, `ESCALATED`, `WITHDRAWN` |
| `APPROVED` | Terminal; no outgoing transition |
| `REJECTED` | Terminal; no outgoing transition |
| `ESCALATED` | `APPROVED`, `REJECTED`, `WITHDRAWN` |
| `WITHDRAWN` | Terminal; no outgoing transition |

### InventoryPlan

| Current state | Legal next states |
|---|---|
| `DRAFT` | `PROPOSED`, `ACTIVE`, `CANCELLED` |
| `PROPOSED` | `APPROVED`, `REJECTED`, `CANCELLED` |
| `APPROVED` | `ACTIVE`, `SUPERSEDED`, `CANCELLED` |
| `REJECTED` | `DRAFT`, `CLOSED` |
| `ACTIVE` | `AT_RISK`, `PARTIALLY_FULFILLED`, `FULFILLED`, `SUPERSEDED`, `CANCELLED` |
| `AT_RISK` | `ACTIVE`, `PARTIALLY_FULFILLED`, `FULFILLED`, `SUPERSEDED`, `CANCELLED` |
| `PARTIALLY_FULFILLED` | `FULFILLED`, `SUPERSEDED` |
| `FULFILLED` | `CLOSED` |
| `SUPERSEDED` | Terminal; no outgoing transition |
| `CANCELLED` | Terminal; no outgoing transition |
| `CLOSED` | Terminal; no outgoing transition |

### ProductionOrder

| Current state | Legal next states |
|---|---|
| `DRAFT` | `RELEASED`, `CANCELLED` |
| `RELEASED` | `SCHEDULED`, `ON_HOLD`, `CANCELLED` |
| `SCHEDULED` | `IN_PROGRESS`, `ON_HOLD`, `CANCELLED` |
| `IN_PROGRESS` | `PARTIALLY_COMPLETED`, `COMPLETED`, `ON_HOLD` |
| `PARTIALLY_COMPLETED` | `IN_PROGRESS`, `COMPLETED`, `ON_HOLD` |
| `ON_HOLD` | `SCHEDULED`, `IN_PROGRESS`, `CANCELLED` |
| `COMPLETED` | `CLOSED` |
| `CANCELLED` | `CLOSED` |
| `CLOSED` | Terminal; no outgoing transition |

### Notification

| Current state | Legal next states |
|---|---|
| `QUEUED` | `SENT`, `RETRY_PENDING`, `FAILED`, `CANCELLED` |
| `SENT` | `DELIVERED`, `BOUNCED`, `RETRY_PENDING`, `FAILED` |
| `DELIVERED` | Terminal; no outgoing transition |
| `BOUNCED` | `RETRY_PENDING`, `FAILED` |
| `RETRY_PENDING` | `SENT`, `FAILED`, `CANCELLED` |
| `FAILED` | `RETRY_PENDING`, `CANCELLED` |
| `CANCELLED` | Terminal; no outgoing transition |

## Supplier

Supplier master and contact/ownership data.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `supplier_id` | `VARCHAR(10)` | Required | SUP- followed by exactly 6 digits | none | Primary key; globally unique; **PK** | fullmatch ^SUP-\d{6}$ |
| `supplier_name` | `VARCHAR(160)` | Required | 1–160 printable characters; trimmed | none | Not unique | non-empty after trim; max 160 chars |
| `supplier_code` | `VARCHAR(40)` | Required | Uppercase letters, digits, hyphens; 2–40 chars | none | Unique globally | fullmatch ^[A-Z0-9][A-Z0-9-]{1,39}$ |
| `supplier_contact_name` | `VARCHAR(120)` | Required | 1–120 trimmed characters | none | Not unique | non-empty after trim; max 120 chars |
| `supplier_contact_email` | `VARCHAR(254)` | Required | RFC-like address local@domain.tld | none | Not unique; contact lookup index recommended | must contain one @ and a domain suffix |
| `supplier_contact_phone` | `VARCHAR(24)` | Optional | Optional phone digits; spaces, +, parentheses, hyphen allowed | E.164 preferred | Not unique | 7–24 characters matching phone-format whitelist |
| `supplier_status` | `ENUM` | Required | ACTIVE, ON_HOLD, BLOCKED, INACTIVE | none | Not unique | value in supplier_status enum |
| `risk_tier` | `ENUM` | Required | LOW, MEDIUM, HIGH, CRITICAL | none | Not unique | value in risk_tier enum |
| `lead_time_days` | `INTEGER` | Required | 0–365 inclusive | calendar days | Not unique | integer in [0,365] |
| `default_currency` | `CHAR(3)` | Required | INR, USD, EUR, GBP, SGD, JPY, AUD, CAD | ISO-4217 alphabetic code | Not unique | must be in supported currency list |
| `data_owner_role` | `ENUM` | Required | supplier, planner, carrier_warehouse_operator, logistics_analyst, operations_manager | none | Not unique | must identify an owning actor role |
| `created_at` | `DATETIME` | Required | ISO-8601 datetime with timezone | UTC recommended | Not unique | parseable timezone-aware datetime |
| `updated_at` | `DATETIME` | Required | ISO-8601 datetime with timezone | UTC recommended | Not unique | must be >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise one of: MISSING_ACK, DATE_CONFLICT, DATE_SLIP_REQUIRES_APPROVAL, QUANTITY_MISMATCH, OVER_ACKNOWLEDGEMENT, PRICE_SPIKE, PRICE_MISMATCH, INVALID_TRANSITION, DUPLICATE_REVISION, MISSING_APPROVAL, LATE_ACKNOWLEDGEMENT, LEAD_TIME_BREACH, FOREIGN_KEY_MISMATCH, LINE_TOTAL_MISMATCH, NOTIFICATION_FAILURE, PROJECTED_SHORTAGE, PROMISE_BEFORE_ORDER, STATUS_DATE_MISMATCH | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

## PurchaseOrder

Purchase order header, supplier relationship, key dates, owner and value.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `po_id` | `VARCHAR(16)` | Required | PO-YYYY- followed by exactly 6 digits, e.g. PO-2026-000001 | none | Primary key; globally unique; **PK** | fullmatch ^PO-\d{4}-\d{6}$ |
| `supplier_id` | `VARCHAR(10)` | Required | Existing Supplier.supplier_id | none | Foreign key to suppliers.supplier_id; **FK** `suppliers.supplier_id` | must reference an existing supplier |
| `planner_actor_id` | `VARCHAR(10)` | Required | Actor ID with PLN- prefix | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must identify an actor whose role is planner |
| `warehouse_id` | `VARCHAR(7)` | Required | WH- followed by exactly 4 digits | none | Foreign key to warehouses.warehouse_id; **FK** `warehouses.warehouse_id` | fullmatch ^WH-\d{4}$ and existing warehouse |
| `carrier_id` | `VARCHAR(10)` | Required | CAR- followed by exactly 6 digits | none | Foreign key to carriers.carrier_id; **FK** `carriers.carrier_id` | fullmatch ^CAR-\d{6}$ and existing carrier |
| `order_date` | `DATE` | Required | Valid calendar date YYYY-MM-DD | calendar date | Not unique | valid ISO date |
| `required_delivery_date` | `DATE` | Required | Valid calendar date; >= order_date | calendar date | Not unique | required_delivery_date >= order_date |
| `response_due_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | response_due_at >= created_at |
| `currency` | `CHAR(3)` | Required | INR, USD, EUR, GBP, SGD, JPY, AUD, CAD | ISO-4217 alphabetic code | Not unique | must be in supported currency list |
| `total_order_value` | `DECIMAL(14,2)` | Required | 0.00–999999999999.99 | currency per PO | Not unique | finite non-negative amount; equals sum POLine.line_total |
| `status` | `ENUM` | Required | DRAFT, ISSUED, PARTIALLY_ACKNOWLEDGED, ACKNOWLEDGED, CHANGE_PENDING, IN_FULFILLMENT, PARTIALLY_RECEIVED, RECEIVED, CANCELLED, CLOSED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.PurchaseOrder |
| `created_by_role` | `ENUM` | Required | planner or operations_manager | none | Not unique | value in approved creating roles |
| `created_by_actor_id` | `VARCHAR(10)` | Required | PLN-###### or OPS-###### actor ID | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor matching created_by_role |
| `supplier_contact_email` | `VARCHAR(254)` | Required | Snapshot email in syntactically valid form | none | Not unique | valid email; snapshot may differ from current Supplier master |
| `version_no` | `INTEGER` | Required | Integer >= 1 | revision number | Not unique | integer >= 1; increment on material PO mutation |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime; >= order_date at date precision |
| `updated_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | updated_at >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## POLine

Purchase order line quantities and values at requested, acknowledged, promised and projected stages.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `po_line_id` | `VARCHAR(25)` | Required | <PO-id>-L followed by 2-digit line number, e.g. PO-2026-000001-L01 | none | Primary key; globally unique; **PK** | fullmatch ^PO-\d{4}-\d{6}-L\d{2}$ |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; unique with line_no; **FK** `purchase_orders.po_id` | must reference an existing PO |
| `line_no` | `INTEGER` | Required | Integer 1–99 | line ordinal per PO | Unique per po_id | integer [1,99]; PO line ID suffix equals line_no |
| `item_id` | `VARCHAR(11)` | Required | ITEM- followed by 6 digits | none | Foreign key to items.item_id; **FK** `items.item_id` | fullmatch ^ITEM-\d{6}$ and existing item |
| `item_description` | `VARCHAR(240)` | Required | 1–240 trimmed characters | none | Not unique | non-empty after trim; max 240 chars |
| `requested_qty` | `DECIMAL(12,3)` | Required | 0.001–999999999.999 | quantity in uom | Not unique | finite decimal > 0 |
| `ack_accepted_qty` | `DECIMAL(12,3)` | Required | 0–999999999.999 | quantity in uom | Not unique | finite decimal >= 0; final line statuses reconcile |
| `ack_rejected_qty` | `DECIMAL(12,3)` | Required | 0–999999999.999 | quantity in uom | Not unique | finite decimal >= 0; final line statuses reconcile |
| `promised_qty` | `DECIMAL(12,3)` | Required | 0–999999999.999 | quantity in uom | Not unique | finite decimal >= 0; valid promise cannot exceed requested quantity |
| `projected_qty` | `DECIMAL(12,3)` | Required | 0–999999999.999 | quantity in uom | Not unique | finite decimal >= 0; derived from accepted/promise and plan policy |
| `uom` | `ENUM` | Required | EA, BOX, KG, G, L, ML, M, CM, M2, M3, PALLET, SET | unit of measure | Not unique | value in UOM list |
| `currency` | `CHAR(3)` | Required | INR, USD, EUR, GBP, SGD, JPY, AUD, CAD | ISO-4217 alphabetic code inherited/snapshotted from PO | Not unique | must match parent PurchaseOrder.currency |
| `unit_price` | `DECIMAL(12,2)` | Required | 0.00–9999999999.99 | currency per uom | Not unique | finite decimal >= 0 |
| `acknowledged_unit_price` | `DECIMAL(12,2)` | Optional | 0.00–9999999999.99 or NULL until acknowledged | currency per uom | Not unique | NULL or finite decimal >= 0 |
| `promised_unit_price` | `DECIMAL(12,2)` | Optional | 0.00–9999999999.99 or NULL until promise confirmed | currency per uom | Not unique | NULL or finite decimal >= 0 |
| `projected_unit_price` | `DECIMAL(12,2)` | Optional | 0.00–9999999999.99 or NULL until projection exists | currency per uom | Not unique | NULL or finite decimal >= 0 |
| `line_total` | `DECIMAL(14,2)` | Required | 0.00–999999999999.99 | currency | Not unique | line_total = ROUND_HALF_UP(requested_qty × unit_price, 2) |
| `acknowledged_value` | `DECIMAL(14,2)` | Optional | 0.00–999999999999.99 or NULL | currency | Not unique | NULL or ROUND_HALF_UP(ack_accepted_qty × acknowledged_unit_price, 2) |
| `promised_value` | `DECIMAL(14,2)` | Optional | 0.00–999999999999.99 or NULL | currency | Not unique | NULL or ROUND_HALF_UP(promised_qty × promised_unit_price, 2) |
| `projected_value` | `DECIMAL(14,2)` | Optional | 0.00–999999999999.99 or NULL | currency | Not unique | NULL or ROUND_HALF_UP(projected_qty × projected_unit_price, 2) |
| `required_date` | `DATE` | Required | Valid date >= parent PO order_date | calendar date | Not unique | required_date >= purchase_orders.order_date |
| `status` | `ENUM` | Required | DRAFT, OPEN, PARTIALLY_ACKNOWLEDGED, ACKNOWLEDGED, CHANGE_PENDING, IN_FULFILLMENT, PARTIALLY_RECEIVED, RECEIVED, CANCELLED, CLOSED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.POLine |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid timezone-aware datetime |
| `updated_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | updated_at >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## Acknowledgement

PO-level supplier response revision; line-specific quantities are also captured on POLine.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `ack_id` | `VARCHAR(30)` | Required | ACK-<PO-id>-NN, e.g. ACK-PO-2026-000001-01 | none | Primary key; unique per PO revision; **PK** | ID PO portion equals po_id and suffix equals revision_no |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must reference an existing PO |
| `supplier_id` | `VARCHAR(10)` | Required | Existing Supplier.supplier_id and same supplier as parent PO | none | Foreign key to suppliers.supplier_id; **FK** `suppliers.supplier_id` | must equal parent PO supplier_id |
| `po_line_id` | `VARCHAR(25)` | Optional | Existing PO line belonging to po_id; NULL for header-level acknowledgement | none | Optional foreign key to po_lines.po_line_id; **FK** `po_lines.po_line_id` | if supplied, line must belong to same po_id |
| `revision_no` | `INTEGER` | Required | Integer >= 1; formatted as 2 digits in ack_id | revision number per PO | Unique per po_id | integer >= 1; ack_id suffix equals revision_no |
| `status` | `ENUM` | Required | DRAFT, SUBMITTED, UNDER_REVIEW, ACCEPTED, PARTIALLY_ACCEPTED, REJECTED, SUPERSEDED, WITHDRAWN | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.Acknowledgement |
| `acknowledged_at` | `DATETIME` | Optional | Timezone-aware ISO datetime; NULL before supplier response | UTC recommended | Not unique | NULL or >= created_at |
| `response_due_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | response_due_at >= created_at |
| `requested_qty` | `DECIMAL(14,3)` | Required | 0.001–99999999999.999; sum of PO line requested_qty | quantity across PO lines or scoped line | Not unique | finite decimal > 0; reconciles when final |
| `ack_accepted_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity | Not unique | finite decimal >= 0; requested = accepted + rejected for final status |
| `ack_rejected_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity | Not unique | finite decimal >= 0; requested = accepted + rejected for final status |
| `promised_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity | Not unique | finite decimal >= 0; promised_qty <= ack_accepted_qty for final status |
| `projected_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity | Not unique | finite decimal >= 0; same UOM basis as requested_qty |
| `requested_value` | `DECIMAL(16,2)` | Required | 0.00–99999999999999.99 | PO currency | Not unique | must equal sum of PO line_total for header acknowledgements |
| `acknowledged_value` | `DECIMAL(16,2)` | Required | 0.00–99999999999999.99 | PO currency | Not unique | finite non-negative amount; based on accepted quantities and acknowledged prices |
| `promised_value` | `DECIMAL(16,2)` | Required | 0.00–99999999999999.99 | PO currency | Not unique | finite non-negative amount; based on promised quantities/prices |
| `projected_value` | `DECIMAL(16,2)` | Required | 0.00–99999999999999.99 | PO currency | Not unique | finite non-negative amount; based on downstream projected quantities/prices |
| `supplier_note` | `TEXT` | Optional | Free text up to application limit of 4,000 characters | none | Not unique | string or NULL; maximum 4,000 characters |
| `superseded_by` | `VARCHAR(30)` | Optional | ACK id of a later revision for the same PO; NULL if current/non-superseded | none | Self foreign key to acknowledgements.ack_id; **FK** `acknowledgements.ack_id` | SUPERSEDED requires a later same-PO acknowledgement; non-SUPERSEDED has NULL |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime; <= acknowledged_at when acknowledged_at is set |
| `created_by_role` | `ENUM` | Required | supplier, planner, carrier_warehouse_operator, logistics_analyst, operations_manager | none | Not unique | value in ACTOR_ROLES |
| `created_by_actor_id` | `VARCHAR(10)` | Required | Actor ID associated with created_by_role | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor and role must match |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## PromiseDate

Line-specific promised dates, independently versioned and traceable to acknowledgement and PO line.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `promise_date_id` | `VARCHAR(40)` | Required | PD-<ACK-id>-NN, e.g. PD-ACK-PO-2026-000001-01-01 | none | Primary key; sequence unique within acknowledgement; **PK** | ID embeds ack_id and a 2–4 digit sequence; suffix is unique under ack_id |
| `ack_id` | `VARCHAR(30)` | Required | Existing Acknowledgement.ack_id | none | Foreign key to acknowledgements.ack_id; **FK** `acknowledgements.ack_id` | must reference existing acknowledgement |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id; same as acknowledgement PO | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must equal referenced acknowledgement.po_id |
| `po_line_id` | `VARCHAR(25)` | Required | Existing PO line belonging to po_id | none | Foreign key to po_lines.po_line_id; **FK** `po_lines.po_line_id` | must reference a line belonging to same po_id |
| `sequence_no` | `INTEGER` | Required | Integer 1–9999 per ack_id; 2 digits minimum in ID | sequence under ACK | Unique per ack_id | integer [1,9999]; suffix embedded in promise_date_id |
| `revision_no` | `INTEGER` | Required | Integer >= 1 per po_line_id | promise revision | Unique per (ack_id, po_line_id, revision_no) | integer >= 1 and increments when line promise changes |
| `promised_date` | `DATE` | Required | Valid date >= PO order_date | calendar date | Not unique | promised_date >= purchase_orders.order_date; no invalid pre-order promise |
| `prior_promised_date` | `DATE` | Optional | Prior valid promised date or NULL for first revision | calendar date | Not unique | NULL for first revision; otherwise prior to or different from promised_date |
| `effective_date` | `DATE` | Required | Valid date >= record creation date for new forward-effective promises | calendar date | Not unique | effective_date >= DATE(created_at) for newly created promises |
| `response_due_date` | `DATE` | Required | Valid date >= effective_date | calendar date | Not unique | response_due_date >= effective_date |
| `status` | `ENUM` | Required | PROPOSED, CURRENT, SUPERSEDED, CANCELLED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.PromiseDate |
| `superseded_by` | `VARCHAR(40)` | Optional | PromiseDate ID of next revision or NULL | none | Self foreign key to promise_dates.promise_date_id; **FK** `promise_dates.promise_date_id` | SUPERSEDED rows require next revision; otherwise NULL |
| `source` | `ENUM` | Required | SUPPLIER_PORTAL, EMAIL, EDI, API, MANUAL | none | Not unique | value in promise source enum |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime; effective_date is not before its date |
| `created_by_role` | `ENUM` | Required | supplier, planner, carrier_warehouse_operator, logistics_analyst, operations_manager | none | Not unique | value in ACTOR_ROLES |
| `created_by_actor_id` | `VARCHAR(10)` | Required | Actor ID associated with created_by_role | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor and role must match |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## ChangeRequest

Supplier/planner change requests with before/after business values and a review lifecycle.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `change_request_id` | `VARCHAR(40)` | Required | CHG-<PO-id>- followed by 6 digits, e.g. CHG-PO-2026-000001-000001 | none | Primary key; globally unique; **PK** | fullmatch ^CHG-PO-YYYY-NNNNNN-NNNNNN$ |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must reference an existing PO |
| `supplier_id` | `VARCHAR(10)` | Required | Existing Supplier.supplier_id; same as parent PO | none | Foreign key to suppliers.supplier_id; **FK** `suppliers.supplier_id` | must equal parent PO supplier_id |
| `po_line_id` | `VARCHAR(25)` | Optional | Existing PO line belonging to po_id; NULL for PO-wide change | none | Optional foreign key to po_lines.po_line_id; **FK** `po_lines.po_line_id` | if supplied, line must belong to same PO |
| `request_type` | `ENUM` | Required | QUANTITY_CHANGE, DATE_CHANGE, PRICE_CHANGE, CANCEL_LINE, CANCEL_PO | none | Not unique | value in request_type enum |
| `status` | `ENUM` | Required | DRAFT, SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED, IMPLEMENTED, CANCELLED, WITHDRAWN, CLOSED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.ChangeRequest |
| `requested_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime |
| `effective_date` | `DATE` | Required | Valid date >= request date | calendar date | Not unique | effective_date >= DATE(requested_at) |
| `response_due_date` | `DATE` | Required | Valid date >= request date | calendar date | Not unique | response_due_date >= DATE(requested_at) |
| `previous_qty` | `DECIMAL(12,3)` | Optional | 0–999999999.999 or NULL when not a quantity change | quantity in line UOM | Not unique | NULL or finite decimal >= 0 |
| `requested_qty` | `DECIMAL(12,3)` | Optional | 0–999999999.999 or NULL when not a quantity change | quantity in line UOM | Not unique | QUANTITY_CHANGE requires requested_qty > 0 and previous_qty set |
| `previous_unit_price` | `DECIMAL(12,2)` | Optional | 0.00–9999999999.99 or NULL | currency per UOM | Not unique | NULL or finite decimal >= 0 |
| `requested_unit_price` | `DECIMAL(12,2)` | Optional | 0.00–9999999999.99 or NULL | currency per UOM | Not unique | PRICE_CHANGE requires requested_unit_price and previous_unit_price |
| `previous_promised_date` | `DATE` | Optional | Prior promised date or NULL | calendar date | Not unique | NULL or valid ISO date |
| `requested_promised_date` | `DATE` | Optional | Requested new promised date or NULL | calendar date | Not unique | DATE_CHANGE requires requested_promised_date >= order_date |
| `reason_code` | `ENUM` | Required | SUPPLIER_CAPACITY, MATERIAL_SHORTAGE, TRANSPORT_DELAY, QUALITY_HOLD, PRICE_CHANGE, CUSTOMER_PRIORITY, DATA_CORRECTION, OTHER | none | Not unique | value in reason_code enum |
| `reason_text` | `TEXT` | Required | 1–2,000 trimmed characters | none | Not unique | non-empty text <= 2,000 chars |
| `requested_by_role` | `ENUM` | Required | supplier, planner, carrier_warehouse_operator, logistics_analyst, operations_manager | none | Not unique | value in ACTOR_ROLES |
| `requested_by_actor_id` | `VARCHAR(10)` | Required | Actor ID associated with requester role | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor and role must match |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | created_at <= requested_at; timestamps are timezone-aware |
| `updated_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | updated_at >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## Approval

Planner or operations-manager approval rounds for exceptions and threshold breaches.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `approval_id` | `VARCHAR(50)` | Required | APR-<change_request_id>-NN, e.g. APR-CHG-PO-2026-000001-000001-01 | none | Primary key; unique per change approval round; **PK** | ID embeds change_request_id and 2-digit approval round |
| `change_request_id` | `VARCHAR(40)` | Required | Existing ChangeRequest.change_request_id | none | Foreign key to change_requests.change_request_id; **FK** `change_requests.change_request_id` | must reference existing change request |
| `approval_round` | `INTEGER` | Required | Integer 1–99 | approval round | Unique per change_request_id | integer [1,99]; approval_id suffix equals approval_round |
| `approver_role` | `ENUM` | Required | planner or operations_manager only | none | Not unique | value in APPROVER_ROLES |
| `approver_actor_id` | `VARCHAR(10)` | Required | PLN-###### or OPS-###### | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor matching approver_role |
| `status` | `ENUM` | Required | PENDING, APPROVED, REJECTED, ESCALATED, WITHDRAWN | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.Approval |
| `requested_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime |
| `due_at` | `DATETIME` | Required | Timezone-aware ISO datetime >= requested_at | UTC recommended | Not unique | due_at >= requested_at |
| `decided_at` | `DATETIME` | Optional | Timezone-aware ISO datetime; NULL while PENDING | UTC recommended | Not unique | PENDING requires NULL; terminal decision requires timestamp >= requested_at |
| `decision_reason` | `TEXT` | Optional | 0–2,000 characters; required when rejected/escalated | none | Not unique | REJECTED or ESCALATED requires non-empty decision_reason; max 2,000 chars |
| `threshold_name` | `ENUM` | Optional | PRICE_CHANGE_PCT, DATE_SLIP_DAYS, QUANTITY_CHANGE_PCT, CANCELLATION, MANUAL_EXCEPTION | none | Not unique | NULL or recognized approval trigger |
| `threshold_value` | `DECIMAL(12,3)` | Optional | Finite non-negative numeric threshold or NULL | percent, days or quantity depending on threshold_name | Not unique | NULL or finite decimal >= 0 |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime; created_at <= requested_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## InventoryPlan

Inventory availability, receipts, shortage projection, ownership, and downstream plan revisions.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `inventory_plan_id` | `VARCHAR(32)` | Required | IP-<po_line_id>-NN, e.g. IP-PO-2026-000001-L01-01 | none | Primary key; globally unique; **PK** | ID embeds po_line_id plus 2-digit plan revision |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must equal PO of po_line_id |
| `po_line_id` | `VARCHAR(25)` | Required | Existing POLine.po_line_id | none | Foreign key to po_lines.po_line_id; **FK** `po_lines.po_line_id` | must reference existing PO line |
| `plan_revision_no` | `INTEGER` | Required | Integer 1–99; 2-digit suffix in ID | plan revision | Unique per po_line_id | integer [1,99]; suffix equals plan_revision_no |
| `status` | `ENUM` | Required | DRAFT, PROPOSED, APPROVED, REJECTED, ACTIVE, AT_RISK, PARTIALLY_FULFILLED, FULFILLED, SUPERSEDED, CANCELLED, CLOSED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.InventoryPlan |
| `demand_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in PO line UOM | Not unique | finite decimal >= 0 |
| `requested_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in PO line UOM | Not unique | copied from POLine.requested_qty unless anomaly-labelled |
| `acknowledged_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in PO line UOM | Not unique | finite decimal >= 0 |
| `promised_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in PO line UOM | Not unique | finite decimal >= 0 |
| `projected_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in PO line UOM | Not unique | projected receipt cannot be negative; compare with demand_qty |
| `on_hand_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in UOM | Not unique | finite decimal >= 0 |
| `reserved_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in UOM | Not unique | finite decimal >= 0; reserved_qty <= on_hand_qty for valid rows |
| `planned_receipt_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in UOM | Not unique | finite decimal >= 0 |
| `projected_available_qty` | `DECIMAL(14,3)` | Required | May be negative for diagnosed shortages; within DECIMAL(14,3) | quantity in UOM | Not unique | projected_available_qty = on_hand_qty - reserved_qty + planned_receipt_qty |
| `projected_shortage_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | quantity in UOM | Not unique | max(0, demand_qty - projected_available_qty) |
| `required_date` | `DATE` | Required | Valid date >= parent PO order_date | calendar date | Not unique | required_date >= parent PO order_date |
| `promised_date` | `DATE` | Optional | Current promised date or NULL until supplier commitment | calendar date | Not unique | NULL or valid ISO date >= parent PO order_date |
| `plan_start_date` | `DATE` | Required | Valid date; <= plan_end_date | calendar date | Not unique | plan_start_date <= plan_end_date |
| `plan_end_date` | `DATE` | Required | Valid date; >= plan_start_date | calendar date | Not unique | plan_end_date >= plan_start_date |
| `planner_actor_id` | `VARCHAR(10)` | Required | PLN-###### | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor with role planner |
| `approved_by_actor_id` | `VARCHAR(10)` | Optional | PLN-###### or OPS-######; NULL before approval | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | if status APPROVED or ACTIVE requires approver; approver role planner or operations_manager |
| `effective_date` | `DATE` | Required | Valid date | calendar date | Not unique | effective_date >= DATE(created_at) |
| `superseded_by` | `VARCHAR(32)` | Optional | InventoryPlan ID of replacement or NULL | none | Self foreign key to inventory_plans.inventory_plan_id; **FK** `inventory_plans.inventory_plan_id` | SUPERSEDED requires replacement; otherwise NULL |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime |
| `updated_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | updated_at >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## ProductionOrder

Downstream production schedules affected by component availability or changed supplier promises.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `production_order_id` | `VARCHAR(16)` | Required | PRO-YYYY- followed by exactly 6 digits | none | Primary key; globally unique; **PK** | fullmatch ^PRO-\d{4}-\d{6}$ |
| `inventory_plan_id` | `VARCHAR(32)` | Required | Existing InventoryPlan.inventory_plan_id | none | Foreign key to inventory_plans.inventory_plan_id; **FK** `inventory_plans.inventory_plan_id` | must reference existing inventory plan |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must equal plan PO |
| `po_line_id` | `VARCHAR(25)` | Required | Existing POLine.po_line_id | none | Foreign key to po_lines.po_line_id; **FK** `po_lines.po_line_id` | must equal plan PO line |
| `status` | `ENUM` | Required | DRAFT, RELEASED, SCHEDULED, IN_PROGRESS, PARTIALLY_COMPLETED, ON_HOLD, COMPLETED, CANCELLED, CLOSED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.ProductionOrder |
| `planned_qty` | `DECIMAL(14,3)` | Required | 0.001–99999999999.999 | finished-good quantity | Not unique | finite decimal > 0 |
| `released_qty` | `DECIMAL(14,3)` | Required | 0–planned_qty | finished-good quantity | Not unique | 0 <= released_qty <= planned_qty |
| `completed_qty` | `DECIMAL(14,3)` | Required | 0–released_qty | finished-good quantity | Not unique | 0 <= completed_qty <= released_qty <= planned_qty |
| `affected_material_qty` | `DECIMAL(14,3)` | Required | 0–99999999999.999 | input material quantity | Not unique | finite decimal >= 0 |
| `priority` | `ENUM` | Required | LOW, NORMAL, HIGH, URGENT | none | Not unique | value in production priority enum |
| `original_start_date` | `DATE` | Required | Valid planned date | calendar date | Not unique | valid ISO date |
| `current_start_date` | `DATE` | Required | Valid current schedule date | calendar date | Not unique | valid ISO date; may differ from original_start_date |
| `scheduled_end_date` | `DATE` | Required | Valid date >= current_start_date | calendar date | Not unique | scheduled_end_date >= current_start_date |
| `actual_start_date` | `DATE` | Optional | Actual start date or NULL before execution | calendar date | Not unique | NULL or actual_start_date >= current_start_date unless approved expedite |
| `actual_end_date` | `DATE` | Optional | Actual completion date or NULL until completed | calendar date | Not unique | NULL or actual_end_date >= actual_start_date |
| `schedule_shift_days` | `INTEGER` | Required | -365–365; signed difference from original start | calendar days | Not unique | integer in [-365,365] and equals current_start_date - original_start_date in days |
| `owner_role` | `ENUM` | Required | planner or operations_manager | none | Not unique | value in allowed production-owner roles |
| `owner_actor_id` | `VARCHAR(10)` | Required | PLN-###### or OPS-###### | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor matching owner_role |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime |
| `updated_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | updated_at >= created_at |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; otherwise listed anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## Notification

Traceable notification fan-out to supplier and operational role recipients, with delivery/retry outcome.

| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |
|---|---|---|---|---|---|---|
| `notification_id` | `VARCHAR(16)` | Required | NOT-YYYY- followed by exactly 6 digits | none | Primary key; globally unique; **PK** | fullmatch ^NOT-\d{4}-\d{6}$ |
| `po_id` | `VARCHAR(16)` | Required | Existing PurchaseOrder.po_id | none | Foreign key to purchase_orders.po_id; **FK** `purchase_orders.po_id` | must reference an existing PO |
| `ack_id` | `VARCHAR(30)` | Optional | Acknowledgement id or NULL when notification is not ack-specific | none | Optional foreign key to acknowledgements.ack_id; **FK** `acknowledgements.ack_id` | if supplied, acknowledgement must belong to po_id |
| `change_request_id` | `VARCHAR(40)` | Optional | ChangeRequest id or NULL when unrelated to a change | none | Optional foreign key to change_requests.change_request_id; **FK** `change_requests.change_request_id` | if supplied, change request must belong to po_id |
| `source_event_id` | `VARCHAR(40)` | Optional | Runtime event identifier or NULL for direct notifications | none | Optional foreign key to events.event_id; **FK** `events.event_id` | if supplied, event must exist in event ledger |
| `target_role` | `ENUM` | Required | supplier, planner, carrier_warehouse_operator, logistics_analyst, operations_manager | none | Not unique | value in NOTIFICATION_TARGET_ROLES |
| `target_actor_id` | `VARCHAR(10)` | Required | Actor ID associated with target_role | none | Foreign key to actors.actor_id; **FK** `actors.actor_id` | must reference actor matching target_role |
| `channel` | `ENUM` | Required | IN_APP, EMAIL, SMS, WEBHOOK | none | Not unique | value in notification channel enum |
| `status` | `ENUM` | Required | QUEUED, SENT, DELIVERED, BOUNCED, RETRY_PENDING, FAILED, CANCELLED | none | Not unique | enum and legal edge in STATUS_TRANSITIONS.Notification |
| `title` | `VARCHAR(200)` | Required | 1–200 trimmed characters | none | Not unique | non-empty after trim; max 200 chars |
| `body` | `TEXT` | Required | 1–8,000 characters | none | Not unique | non-empty text <= 8,000 chars |
| `scheduled_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | scheduled_at >= created_at |
| `sent_at` | `DATETIME` | Optional | Timezone-aware ISO datetime; NULL until attempted | UTC recommended | Not unique | NULL or sent_at >= scheduled_at |
| `delivered_at` | `DATETIME` | Optional | Timezone-aware ISO datetime; NULL until delivery confirmed | UTC recommended | Not unique | DELIVERED requires value >= sent_at; otherwise may be NULL |
| `retry_count` | `INTEGER` | Required | Integer 0–10 inclusive | attempt count | Not unique | integer in [0,10] |
| `last_error` | `TEXT` | Optional | Error details up to 2,000 characters or NULL | none | Not unique | NULL or string <= 2,000 chars; set for FAILED/BOUNCED |
| `created_at` | `DATETIME` | Required | Timezone-aware ISO datetime | UTC recommended | Not unique | valid datetime |
| `issue_type` | `ENUM` | Optional | NULL for normal rows; NOTIFICATION_FAILURE or other listed anomaly | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with ground_truth |
| `ground_truth` | `ENUM` | Optional | NULL for normal rows; otherwise source-truth anomaly class | none | Not unique | NULL or value in ANOMALY_TYPES; pairs with issue_type |

Lifecycle field: `status`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`.

## Machine-checkable validation API

```python
from supplier_ack.schema import ENTITIES, validate_record, validate_dataset, is_legal_transition

spec = ENTITIES['POLine']
print(spec.fields[0].validator)  # real callable
errors = validate_record('POLine', row, context={'purchase_orders': [po_row]})
dataset_errors = validate_dataset({'PurchaseOrder': [po_row], 'POLine': [row]})
assert is_legal_transition('PurchaseOrder', 'ISSUED', 'ACKNOWLEDGED')
```
