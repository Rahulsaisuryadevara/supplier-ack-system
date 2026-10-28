You are my senior software engineer. We are building a project for the YottaFlex AI recruitment challenge. Work as an individual candidate would: give me complete, runnable, production-quality code — no placeholders, no TODOs.

PROJECT OVERVIEW (do not skip any point):
Build a working, end-to-end solution for this workflow: "Manage supplier acknowledgements, promised dates, quantity changes and downstream schedule impacts." The solution must expose key decisions and exceptions, preserve traceability, and produce measurable outputs.

PRIMARY ACTORS / SYSTEMS: Supplier, planner, carrier/warehouse operator, logistics analyst, operations manager. These roles must appear in the data model (e.g., as notification targets, approvers, and data owners) — do not leave them as an unused list.

COMPLEXITY TARGET (medium): multiple related entities, conditional rules, at least one exception path, and meaningful evaluation metrics.

TASK 1 — Choose and justify the tech stack:
- Python 3.11+ project
- pandas for data generation and analysis
- SQLite (via the built-in sqlite3 or SQLAlchemy) for persistence — free and locally runnable
- argparse-based CLI
- pytest for testing
Justify each choice in one short paragraph (trade-offs included).

TASK 2 — Create this exact repository structure:
supplier-ack-system/
  README.md
  pyproject.toml            # or requirements.txt — pin all dependencies
  .gitignore                # exclude .venv, __pycache__, data/generated (keep data/samples)
  config/
    generator_config.yaml   # all knobs: scale, seed, thresholds, distributions
  src/supplier_ack/
    __init__.py
    ids.py                  # ID/nomenclature engine
    schema.py               # schema + data dictionary definitions
    generators/             # one module per entity family
    rules/                  # business rules: thresholds, approvals, plan updates
    events/                 # event history / state-change records
    validation/             # validation suite
    exports/                # CSV/JSON/SQL export pipeline
    metrics/                # evaluation metrics and reports
    workflow/               # runtime workflow engine
    cli.py                  # command-line interface
  tests/
  data/
    samples/                # small sample outputs committed to git
    generated/              # full-scale outputs (gitignored)
  docs/
    data_dictionary.md
    schema.md               # ER diagram + cardinality tables
    decisions.md            # assumptions, trade-offs, limitations
    provenance.md           # public data guidance / source manifest
  ai/
    prompt_history.md       # every prompt you give me, verbatim
    ai_disclosure.md        # where AI helped, what I reviewed/validated

TASK 3 — Write the initial README.md skeleton: project purpose, install steps, run steps, verification steps, repository layout. It will be completed later.

TASK 4 — Write generator_config.yaml with a first draft of all knobs: seed (20261022), po_count (10000), event_count (15000), starter scale (po_count=200, event_count=300), approval thresholds (price change %, date slip days, quantity change %), and distribution parameters. Every knob must be configurable — the starter and full datasets must use the SAME generator, only differing parameters.

TASK 5 — Create ai/prompt_history.md and start it with this very prompt pasted verbatim. Append every future prompt I give you to this file.

DELIVERABLES: repository tree, pyproject.toml/requirements.txt, README skeleton, config file, prompt_history.md initialized.

ACCEPTANCE CHECKLIST:
[ ] Project runs: `pip install -e .` succeeds (create a minimal __init__.py everywhere needed)
[ ] All 5 actors named somewhere in the design docs or config
[ ] Config has seed 20261022 and both starter and full scales
[ ] README explains install, run, verify

COMMIT MESSAGE: "feat: bootstrap repository structure, config, and README skeleton"

---

Continue the supplier-ack-system project. New task: produce the complete DATA DICTIONARY (Generation Step 1 of the problem statement). This is the foundation for everything else — be exhaustive, not illustrative.

For EACH of these 10 entities: Supplier, PurchaseOrder, POLine, Acknowledgement, PromiseDate, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification — create a full field-by-field dictionary. For every field specify:
1. Field name (snake_case)
2. Data type (exact: e.g., INTEGER, DECIMAL(12,2), DATE, VARCHAR(24), TEXT, BOOLEAN, ENUM)
3. Required or optional
4. Allowed values / domain (full enum lists, ranges, formats)
5. Units (where applicable: currency, days, quantities)
6. Uniqueness (primary key? unique per parent? not unique?)
7. Validation rule (a concrete, machine-checkable rule, e.g. "ack_accepted_qty + ack_rejected_qty = ack_total_qty" or "promise_date >= po.order_date for valid rows")

MANDATORY FIELDS TO INCLUDE (do not omit):
- Every entity needs a primary key using the documented ID conventions:
  Supplier: SUP-000001; PurchaseOrder: PO-2026-000001; POLine: <PO-id>-L01;
  Acknowledgement: ACK-<PO-id>-01 (suffix increments per revision: -01, -02...);
  PromiseDate: PD-<ACK-id>-01; ChangeRequest: CHG-<PO-id>-000001;
  Approval: APR-<change-id>-01; Notification: NOT-2026-000001;
  InventoryPlan: IP-<PO-line-id>-01; ProductionOrder: PRO-2026-000001.
- Foreign keys for every relationship (supplier_id on PO, po_id on ACK/CHG, po_line_id on ACK lines and PromiseDate, change_request_id on Approval, etc.)
- Lifecycle/status fields with full enum lists for: PurchaseOrder, POLine, Acknowledgement, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification (define each state and the legal transitions between them)
- Effective dates (created_at, effective_date, response_due_date, etc.) with date-ordering validation rules
- Actor/role references: approver (planner or operations manager), notification recipients (planner, carrier/warehouse operator, logistics analyst), supplier contact
- Revision/version fields (revision_no on Acknowledgement, superseded_by on revisions)
- Monetary fields: unit_price, line_total (with the rule line_total = quantity × unit_price)
- Quantities: requested, accepted, rejected, promised — with the reconciliation rule requested = accepted + rejected
- Money/quantity comparison fields: requested vs acknowledged vs promised vs projected
- Anomaly labelling fields: issue_type and ground_truth columns on relevant entities, NULL for normal rows

Write the dictionary to docs/data_dictionary.md as one table per entity, plus a summary table listing: entity, primary key, foreign keys, row counts (baseline volumes), and which generation step produces it.

Also export the dictionary as a machine-readable src/supplier_ack/schema.py Python module: for each entity define a dataclass or dict spec with field name, type, required, enum values, and a validator function per validation rule. Validators must be real callable functions, not comments.

ACCEPTANCE CHECKLIST:
[ ] All 10 entities present, each with ≥8 meaningfully specified fields
[ ] Every field has all 7 specification attributes
[ ] Every entity has a primary key following the ID conventions exactly
[ ] Every relationship has a foreign key field
[ ] Every status field has a full enum and documented legal transitions
[ ] Arithmetic and date-ordering validation rules are machine-checkable
[ ] docs/data_dictionary.md and src/supplier_ack/schema.py both complete and consistent

COMMIT MESSAGE: "feat: complete data dictionary for all 10 entities with validation rules"

---

Continue the supplier-ack-system project. New task: design the full relational schema and event-history model (Entities and Relationships section of the problem statement). Produce docs/schema.md and the SQLite DDL in src/supplier_ack/schema.py (as a create_schema.sql string plus a create_all() function).

REQUIREMENTS — cover every point:
1. Primary key for every entity; foreign key for every relationship. Validate all joins (declare FK constraints in DDL).
2. Document cardinality for EVERY relationship: 1:1, 1:N, or N:M. Use bridge tables for all many-to-many relationships. Specifically:
   - Supplier → PurchaseOrder: 1:N
   - PurchaseOrder → POLine: 1:N
   - PO/POLine → Acknowledgement: 1:N (revisions)
   - Acknowledgement → PromiseDate: 1:N (one per acknowledged line)
   - ChangeRequest → Approval: 1:N (a change may need multiple approval levels)
   - POLine → InventoryPlan: 1:N (projected supply versions)
   - POLine → ProductionOrder: 1:N (downstream schedule impact)
   - Notification → recipients: model recipients via a bridge table notification_recipient(notification_id, actor_role) since one notification can target multiple roles (planner, carrier/warehouse operator, logistics analyst, operations manager)
   - Any N:M between ProductionOrder and POLine (a production order consuming multiple PO lines) must use a bridge table: production_order_line(production_order_id, po_line_id, allocated_quantity)
3. Document optional relationships: e.g., a ChangeRequest may have no Approval yet (pending), a Notification may have no linked change (system-wide notices), a ProductionOrder may not exist for every PO line.
4. Effective dates and lifecycle states: document which tables are event/append-only history vs current-state snapshots. Never overwrite history: acknowledgements keep every revision row; InventoryPlan keeps every projected-supply version; Approval keeps decision history.
5. Event history: create a dedicated event log table entity_event(event_id, entity_type, entity_id, event_type, event_timestamp, actor_role, payload_json, previous_state, new_state). Every state change (PO created, ack received, ack accepted/rejected, change requested, change approved/rejected, plan updated, notification sent) writes an event row. The current state is derivable, never destructive.
6. Anomaly handling: anomaly rows must NOT silently corrupt other rows. Anomalies are recorded with issue_type + ground_truth labels (e.g., on the entity itself or in the ground truth file), and the schema must allow them to exist without breaking FK integrity where possible — document exactly which integrity constraint each anomaly type deliberately violates or satisfies.
7. Include an ER diagram as a Mermaid erDiagram in docs/schema.md showing all 10+ entities, bridge tables, and the event log, with cardinality labels on every edge.
8. Lifecycle diagrams: for PurchaseOrder, Acknowledgement, ChangeRequest, and InventoryPlan, document the state machine (states + legal transitions) as a table, and note which business rule triggers each transition.

ACCEPTANCE CHECKLIST:
[ ] DDL executes cleanly against SQLite with FK enforcement ON (PRAGMA foreign_keys = ON)
[ ] Every relationship in the problem is documented with cardinality
[ ] All N:M relationships use bridge tables
[ ] Optional relationships documented
[ ] Event log table exists and design shows append-only history for revisions
[ ] Anomaly labelling strategy documented (no silent corruption of unrelated rows)
[ ] Mermaid ER diagram present in docs/schema.md
[ ] 4 lifecycle state machines documented

COMMIT MESSAGE: "feat: relational schema, bridge tables, event history model, and lifecycle state machines"

---

Continue the supplier-ack-system project. New task: implement the deterministic ID/nomenclature engine in src/supplier_ack/ids.py (Generation Step 3 of the problem statement).

REQUIRED CONVENTIONS — implement exactly:
- Supplier: SUP-000001 (6-digit zero-padded counter)
- PurchaseOrder: PO-2026-000001 (year segment 2026, 6-digit counter)
- POLine: <PO-id>-L01, <PO-id>-L02, ... (2-digit line counter, per PO)
- Acknowledgement: ACK-<PO-id>-01, then -02, -03 for each revision of the same PO (2-digit revision counter per PO)
- PromiseDate: PD-<ACK-id>-01 (counter within an acknowledgement)
- ChangeRequest: CHG-<PO-id>-000001 (6-digit counter per PO)
- Approval: APR-<change-id>-01 (counter per change request — note: embeds the full CHG id, so the format is APR-CHG-PO-2026-000001-000001-01; if you judge this too unwieldy, you may instead use APR-<change-sequence>-01 where change-sequence is the CHG id; either way document the decision in docs/decisions.md)
- Notification: NOT-2026-000001 (year + 6-digit global counter)
- InventoryPlan: IP-<PO-line-id>-01 (version counter per PO line)
- ProductionOrder: PRO-2026-000001

RULES:
- Counters are zero-padded and monotonically increasing
- IDs are immutable once issued — provide no API to change them
- Referenced IDs must be exactly consistent across files/tables: an ACK row referencing a PO must use the byte-identical PO id string
- The engine is deterministic: given the same generation sequence, it issues the same IDs (no randomness in ID assignment)
- Implement as a class IDFactory with methods: next_supplier_id(), next_po_id(), next_line_id(po_id), next_ack_id(po_id), next_promise_date_id(ack_id), next_change_id(po_id), next_approval_id(change_id), next_notification_id(), next_inventory_plan_id(po_line_id), next_production_order_id(). Persist counter state in memory; optionally serialize/deserialize to JSON for reproducibility.
- Unit-test round-tripping: generate 1000 IDs of each type, assert format via regex, assert uniqueness, assert zero-padding width, assert exact embedding of parent IDs.

Write tests/test_ids.py with at least 12 test cases covering formats, padding, uniqueness, immutability (issuing never reuses), and cross-reference exactness.

ACCEPTANCE CHECKLIST:
[ ] All 10 ID formats implemented and regex-validated
[ ] Zero-padded, deterministic, immutable
[ ] Parent IDs embedded exactly (byte-identical cross-references)
[ ] test_ids.py passes with ≥12 tests
[ ] Any judgment call (e.g., the APR format) documented in docs/decisions.md

COMMIT MESSAGE: "feat: deterministic zero-padded ID engine for all entities with full test coverage"

---

You are my senior software engineer. We are building a project for the YottaFlex AI recruitment challenge. Work as an individual candidate would: give me complete, runnable, production-quality code — no placeholders, no TODOs.

PROJECT OVERVIEW (do not skip any point):
Build a working, end-to-end solution for this workflow: "Manage supplier acknowledgements, promised dates, quantity changes and downstream schedule impacts." The solution must expose key decisions and exceptions, preserve traceability, and produce measurable outputs.

PRIMARY ACTORS / SYSTEMS: Supplier, planner, carrier/warehouse operator, logistics analyst, operations manager. These roles must appear in the data model (e.g., as notification targets, approvers, and data owners) — do not leave them as an unused list.

COMPLEXITY TARGET (medium): multiple related entities, conditional rules, at least one exception path, and meaningful evaluation metrics.

TASK 1 — Choose and justify the tech stack:
- Python 3.11+ project
- pandas for data generation and analysis
- SQLite (via the built-in sqlite3 or SQLAlchemy) for persistence — free and locally runnable
- argparse-based CLI
- pytest for testing
Justify each choice in one short paragraph (trade-offs included).

TASK 2 — Create this exact repository structure:
supplier-ack-system/
  README.md
  pyproject.toml            # or requirements.txt — pin all dependencies
  .gitignore                # exclude .venv, __pycache__, data/generated (keep data/samples)
  config/
    generator_config.yaml   # all knobs: scale, seed, thresholds, distributions
  src/supplier_ack/
    __init__.py
    ids.py                  # ID/nomenclature engine
    schema.py               # schema + data dictionary definitions
    generators/             # one module per entity family
    rules/                  # business rules: thresholds, approvals, plan updates
    events/                 # event history / state-change records
    validation/             # validation suite
    exports/                # CSV/JSON/SQL export pipeline
    metrics/                # evaluation metrics and reports
    workflow/               # runtime workflow engine
    cli.py                  # command-line interface
  tests/
  data/
    samples/                # small sample outputs committed to git
    generated/              # full-scale outputs (gitignored)
  docs/
    data_dictionary.md
    schema.md               # ER diagram + cardinality tables
    decisions.md            # assumptions, trade-offs, limitations
    provenance.md           # public data guidance / source manifest
  ai/
    prompt_history.md       # every prompt you give me, verbatim
    ai_disclosure.md        # where AI helped, what I reviewed/validated

TASK 3 — Write the initial README.md skeleton: project purpose, install steps, run steps, verification steps, repository layout. It will be completed later.

TASK 4 — Write generator_config.yaml with a first draft of all knobs: seed (20261022), po_count (10000), event_count (15000), starter scale (po_count=200, event_count=300), approval thresholds (price change %, date slip days, quantity change %), and distribution parameters. Every knob must be configurable — the starter and full datasets must use the SAME generator, only differing parameters.

TASK 5 — Create ai/prompt_history.md and start it with this very prompt pasted verbatim. Append every future prompt I give you to this file.

DELIVERABLES: repository tree, pyproject.toml/requirements.txt, README skeleton, config file, prompt_history.md initialized.

ACCEPTANCE CHECKLIST:
[ ] Project runs: `pip install -e .` succeeds (create a minimal __init__.py everywhere needed)
[ ] All 5 actors named somewhere in the design docs or config
[ ] Config has seed 20261022 and both starter and full scales
[ ] README explains install, run, verify

COMMIT MESSAGE: "feat: bootstrap repository structure, config, and README skeleton"

---

Continue the supplier-ack-system project. New task: produce the complete DATA DICTIONARY (Generation Step 1 of the problem statement). This is the foundation for everything else — be exhaustive, not illustrative.

For EACH of these 10 entities: Supplier, PurchaseOrder, POLine, Acknowledgement, PromiseDate, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification — create a full field-by-field dictionary. For every field specify:
1. Field name (snake_case)
2. Data type (exact: e.g., INTEGER, DECIMAL(12,2), DATE, VARCHAR(24), TEXT, BOOLEAN, ENUM)
3. Required or optional
4. Allowed values / domain (full enum lists, ranges, formats)
5. Units (where applicable: currency, days, quantities)
6. Uniqueness (primary key? unique per parent? not unique?)
7. Validation rule (a concrete, machine-checkable rule, e.g. "ack_accepted_qty + ack_rejected_qty = ack_total_qty" or "promise_date >= po.order_date for valid rows")

MANDATORY FIELDS TO INCLUDE (do not omit):
- Every entity needs a primary key using the documented ID conventions:
  Supplier: SUP-000001; PurchaseOrder: PO-2026-000001; POLine: <PO-id>-L01;
  Acknowledgement: ACK-<PO-id>-01 (suffix increments per revision: -01, -02...);
  PromiseDate: PD-<ACK-id>-01; ChangeRequest: CHG-<PO-id>-000001;
  Approval: APR-<change-id>-01; Notification: NOT-2026-000001;
  InventoryPlan: IP-<PO-line-id>-01; ProductionOrder: PRO-2026-000001.
- Foreign keys for every relationship (supplier_id on PO, po_id on ACK/CHG, po_line_id on ACK lines and PromiseDate, change_request_id on Approval, etc.)
- Lifecycle/status fields with full enum lists for: PurchaseOrder, POLine, Acknowledgement, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification (define each state and the legal transitions between them)
- Effective dates (created_at, effective_date, response_due_date, etc.) with date-ordering validation rules
- Actor/role references: approver (planner or operations manager), notification recipients (planner, carrier/warehouse operator, logistics analyst), supplier contact
- Revision/version fields (revision_no on Acknowledgement, superseded_by on revisions)
- Monetary fields: unit_price, line_total (with the rule line_total = quantity × unit_price)
- Quantities: requested, accepted, rejected, promised — with the reconciliation rule requested = accepted + rejected
- Money/quantity comparison fields: requested vs acknowledged vs promised vs projected
- Anomaly labelling fields: issue_type and ground_truth columns on relevant entities, NULL for normal rows

Write the dictionary to docs/data_dictionary.md as one table per entity, plus a summary table listing: entity, primary key, foreign keys, row counts (baseline volumes), and which generation step produces it.

Also export the dictionary as a machine-readable src/supplier_ack/schema.py Python module: for each entity define a dataclass or dict spec with field name, type, required, enum values, and a validator function per validation rule. Validators must be real callable functions, not comments.

ACCEPTANCE CHECKLIST:
[ ] All 10 entities present, each with ≥8 meaningfully specified fields
[ ] Every field has all 7 specification attributes
[ ] Every entity has a primary key following the ID conventions exactly
[ ] Every relationship has a foreign key field
[ ] Every status field has a full enum and documented legal transitions
[ ] Arithmetic and date-ordering validation rules are machine-checkable
[ ] docs/data_dictionary.md and src/supplier_ack/schema.py both complete and consistent

COMMIT MESSAGE: "feat: complete data dictionary for all 10 entities with validation rules"

---

Continue the supplier-ack-system project. New task: design the full relational schema and event-history model (Entities and Relationships section of the problem statement). Produce docs/schema.md and the SQLite DDL in src/supplier_ack/schema.py (as a create_schema.sql string plus a create_all() function).

REQUIREMENTS — cover every point:
1. Primary key for every entity; foreign key for every relationship. Validate all joins (declare FK constraints in DDL).
2. Document cardinality for EVERY relationship: 1:1, 1:N, or N:M. Use bridge tables for all many-to-many relationships. Specifically:
   - Supplier → PurchaseOrder: 1:N
   - PurchaseOrder → POLine: 1:N
   - PO/POLine → Acknowledgement: 1:N (revisions)
   - Acknowledgement → PromiseDate: 1:N (one per acknowledged line)
   - ChangeRequest → Approval: 1:N (a change may need multiple approval levels)
   - POLine → InventoryPlan: 1:N (projected supply versions)
   - POLine → ProductionOrder: 1:N (downstream schedule impact)
   - Notification → recipients: model recipients via a bridge table notification_recipient(notification_id, actor_role) since one notification can target multiple roles (planner, carrier/warehouse operator, logistics analyst, operations manager)
   - Any N:M between ProductionOrder and POLine (a production order consuming multiple PO lines) must use a bridge table: production_order_line(production_order_id, po_line_id, allocated_quantity)
3. Document optional relationships: e.g., a ChangeRequest may have no Approval yet (pending), a Notification may have no linked change (system-wide notices), a ProductionOrder may not exist for every PO line.
4. Effective dates and lifecycle states: document which tables are event/append-only history vs current-state snapshots. Never overwrite history: acknowledgements keep every revision row; InventoryPlan keeps every projected-supply version; Approval keeps decision history.
5. Event history: create a dedicated event log table entity_event(event_id, entity_type, entity_id, event_type, event_timestamp, actor_role, payload_json, previous_state, new_state). Every state change (PO created, ack received, ack accepted/rejected, change requested, change approved/rejected, plan updated, notification sent) writes an event row. The current state is derivable, never destructive.
6. Anomaly handling: anomaly rows must NOT silently corrupt other rows. Anomalies are recorded with issue_type + ground_truth labels (e.g., on the entity itself or in the ground truth file), and the schema must allow them to exist without breaking FK integrity where possible — document exactly which integrity constraint each anomaly type deliberately violates or satisfies.
7. Include an ER diagram as a Mermaid erDiagram in docs/schema.md showing all 10+ entities, bridge tables, and the event log, with cardinality labels on every edge.
8. Lifecycle diagrams: for PurchaseOrder, Acknowledgement, ChangeRequest, and InventoryPlan, document the state machine (states + legal transitions) as a table, and note which business rule triggers each transition.

ACCEPTANCE CHECKLIST:
[ ] DDL executes cleanly against SQLite with FK enforcement ON (PRAGMA foreign_keys = ON)
[ ] Every relationship in the problem is documented with cardinality
[ ] All N:M relationships use bridge tables
[ ] Optional relationships documented
[ ] Event log table exists and design shows append-only history for revisions
[ ] Anomaly labelling strategy documented (no silent corruption of unrelated rows)
[ ] Mermaid ER diagram present in docs/schema.md
[ ] 4 lifecycle state machines documented

COMMIT MESSAGE: "feat: relational schema, bridge tables, event history model, and lifecycle state machines"

---

Continue the supplier-ack-system project. New task: implement the deterministic ID/nomenclature engine in src/supplier_ack/ids.py (Generation Step 3 of the problem statement).

REQUIRED CONVENTIONS — implement exactly:
- Supplier: SUP-000001 (6-digit zero-padded counter)
- PurchaseOrder: PO-2026-000001 (year segment 2026, 6-digit counter)
- POLine: <PO-id>-L01, <PO-id>-L02, ... (2-digit line counter, per PO)
- Acknowledgement: ACK-<PO-id>-01, then -02, -03 for each revision of the same PO (2-digit revision counter per PO)
- PromiseDate: PD-<ACK-id>-01 (counter within an acknowledgement)
- ChangeRequest: CHG-<PO-id>-000001 (6-digit counter per PO)
- Approval: APR-<change-id>-01 (counter per change request — note: embeds the full CHG id, so the format is APR-CHG-PO-2026-000001-000001-01; if you judge this too unwieldy, you may instead use APR-<change-sequence>-01 where change-sequence is the CHG id; either way document the decision in docs/decisions.md)
- Notification: NOT-2026-000001 (year + 6-digit global counter)
- InventoryPlan: IP-<PO-line-id>-01 (version counter per PO line)
- ProductionOrder: PRO-2026-000001

RULES:
- Counters are zero-padded and monotonically increasing
- IDs are immutable once issued — provide no API to change them
- Referenced IDs must be exactly consistent across files/tables: an ACK row referencing a PO must use the byte-identical PO id string
- The engine is deterministic: given the same generation sequence, it issues the same IDs (no randomness in ID assignment)
- Implement as a class IDFactory with methods: next_supplier_id(), next_po_id(), next_line_id(po_id), next_ack_id(po_id), next_promise_date_id(ack_id), next_change_id(po_id), next_approval_id(change_id), next_notification_id(), next_inventory_plan_id(po_line_id), next_production_order_id(). Persist counter state in memory; optionally serialize/deserialize to JSON for reproducibility.
- Unit-test round-tripping: generate 1000 IDs of each type, assert format via regex, assert uniqueness, assert zero-padding width, assert exact embedding of parent IDs.

ACCEPTANCE CHECKLIST:
[ ] All 10 ID formats implemented and regex-validated
[ ] Zero-padded, deterministic, immutable
[ ] Parent IDs embedded exactly (byte-identical cross-references)
[ ] test_ids.py passes with ≥12 tests
[ ] Any judgment call (e.g., the APR format) documented in docs/decisions.md

COMMIT MESSAGE: "feat: deterministic zero-padded ID engine for all entities with full test coverage"

---

Continue the supplier-ack-system project. New task: build the seeded, parameterized synthetic-data generator framework and the MASTER DATA generation (Generation Steps 2 and 4 of the problem statement).

FRAMEWORK REQUIREMENTS:
- Single generator that serves BOTH the starter and full datasets; only the config scale differs. Command: python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter|full --seed 20261022
- Fixed default seed: 20261022. Use numpy.random.default_rng(seed) or an equivalent single RNG object threaded through every generator module. No module may call the global random or np.random directly — all randomness flows through the injected rng. This is required for reproducibility.
- Deterministic ID issuance via the IDFactory from the previous step.
- Every generator module emits pandas DataFrames whose columns exactly match the data dictionary from Prompt 2.
- Generation ORDER must respect dependencies (Generation Step 2: "Generate master data first", then "dependent transaction/event records using valid parent IDs"): Supplier → PurchaseOrder → POLine → Acknowledgement/PromiseDate → ChangeRequest/Approval → InventoryPlan/ProductionOrder → Notification.

MASTER DATA GENERATION (this prompt only):
1. Supplier (~200 suppliers at full scale, ~40 at starter): realistic B2B supplier names (synthetic, e.g., "Vertex Industrial Supplies"), unique supplier_id, region, lead_time_days (varied distribution: most 7–30 days, a tail up to 90), reliability_score (beta distribution — most suppliers reliable, a few unreliable), on_time_rate (correlated with reliability_score, NOT independent), preferred/carrier preferences. Record every distribution choice in docs/decisions.md with justification.
2. PurchaseOrder (10,000 at full scale, 200 at starter): po_id (PO-2026-...), supplier_id (weighted sampling so some suppliers get more POs — a realistic Pareto-ish skew, not uniform), order_date (spread over a working calendar, e.g., Jan–Jun 2026, weekdays only), requested_delivery_date = order_date + supplier lead time + buffer, status lifecycle start, buyer/planner actor reference, total_amount (derived LATER — do not generate it here).
3. POLine (2–6 lines per PO, so ~30,000+ lines at full scale): po_line_id (<PO-id>-L01...), item description from a synthetic parts catalog (create a synthetic item master of ~50 items with unit_price ranges), quantity (varied: 10–5000, log-normal-ish), unit_price (within the item's range), currency, requested qty/date inherited from PO. line_total must be COMPUTED = quantity × unit_price, never independently random (Generation Step 6 principle).

Also emit the first synthetic reference data: the item master and the actor roster (named planners, warehouse operators, logistics analysts, operations managers — synthetic names, roles).

WRITE the generation to be checkpointable: each entity family gets a function generate_suppliers(rng, cfg) → DataFrame etc.

Then generate the STARTER dataset for suppliers/POs/POLines and save to data/samples/ as CSVs. Print a summary: row counts per table, distribution stats (mean/median/p90 of quantity, lead time, lines per PO).

ACCEPTANCE CHECKLIST:
[ ] One command generates starter or full scale with the same code path
[ ] Seed 20261022 hardcoded as default; --seed flag overrides
[ ] No global RNG usage anywhere (grep for np.random. and random.) to verify
[ ] Supplier counts, PO counts, and lines-per-PO match config at both scales
[ ] quantity × unit_price = line_total for every row
[ ] Starter CSVs exist in data/samples/ and open cleanly
[ ] Distribution choices justified in docs/decisions.md

COMMIT MESSAGE: "feat: seeded generator framework with supplier, PO, and PO-line master data"

---

Continue the supplier-ack-system project. New task: implement the required VOLUME and COVERAGE profile (Generation Step 4 of the problem statement) as explicit, config-driven scenario mix knobs.

BASELINE VOLUMES (config-driven, these are the full-scale defaults):
- 10,000 PurchaseOrders, ~15,000 acknowledgement/change events total (count acknowledgements + change requests together; e.g., ~10,000 acknowledgements covering most POs and ~5,000 change requests on a subset)
- Starter scale: 200 POs, 300 events (same ratios)

REQUIRED COVERAGE — implement each as a config knob with a target proportion, and make the proportions realistic (document them):
1. Partial acceptance: acknowledgements where accepted_qty < requested_qty and rejected_qty = requested − accepted, with a rejection_reason (capacity, price, stock, logistics)
2. Full acceptance: accepted = requested
3. Full rejection: accepted = 0
4. Date slips: promised_date later than requested_delivery_date (slip days drawn from a realistic distribution: most slips 3–14 days, tail to 60)
5. On-time promises: promised_date ≤ requested date
6. Price changes: unit_price on the acknowledgement differs from the PO line price (±0.5% to ±15%)
7. Supplier silence: POs that NEVER receive an acknowledgement — model these explicitly as POs with response_due_date passed and no ACK row; also produce a "silence report" listing them (do not fabricate empty ACK rows; document this modeling decision)
8. Multiple revisions: POs with 2–4 acknowledgement revisions (a supplier revises their promise); later revisions supersede earlier ones via superseded_by and revision_no, but ALL revision rows are retained (never overwrite history)

DISTRIBUTION QUALITY (Evaluation focus (a): "realistic distributions and meaningful variation"):
- Use proper statistical distributions (normal/log-normal/beta/weighted categorical), not uniform-everything
- Correlate sensibly: unreliable suppliers slip dates more and partially accept more; large quantity lines get more partial acceptances; price changes skew upward
- Print a coverage report after generation: for each of the 8 categories above, the count and percentage at both scales

Also add a config validation function that warns if the coverage mix is impossible for the requested volumes (e.g., revision POs cannot exceed PO count).

ACCEPTANCE CHECKLIST:
[ ] Full-scale defaults: 10,000 POs and ~15,000 ack/change events; starter 200/300
[ ] All 8 coverage categories present with counts/percentages in the coverage report
[ ] Multiple revisions retained as separate rows with superseded_by linkage
[ ] Supplier silence modeled without fake ACK rows, with a silence report
[ ] Distributions are parameterized and documented; no uniform-everything
[ ] Coverage report prints for both starter and full scales

COMMIT MESSAGE: "feat: coverage-mix engine with partial acceptance, date slips, price changes, silence, and revisions"

Continue the supplier-ack-system project. New task: generate the Acknowledgement and PromiseDate records (core of the workflow's "generate acknowledgements with accepted/rejected quantities and promised dates" requirement).

ACKNOWLEDGEMENT (ACK-<PO-id>-NN):
- po_id references an existing PO exactly; ack status lifecycle: draft → submitted → processed (or → exception)
- Per PO line, the acknowledgement carries: requested_qty (copied from the PO line — byte-consistent), accepted_qty, rejected_qty, rejected_reason, acknowledged unit_price, response timestamp
- INVARIANT: accepted_qty + rejected_qty = requested_qty for every acknowledged line. Compute accepted_qty first, then rejected_qty = requested − accepted. Never generate them independently (Generation Step 6: derived from source records).
- For revision rows: revision_no increments; previous revision gets superseded_by = new ack id; every revision is a full-row snapshot (history preserved)
- Supplier response time: response_timestamp = po.order_date + supplier-specific response delay distribution (fast suppliers reply in 1–3 days, slow ones near or past response_due_date; a share respond LATE — ties into date-slip and approval logic later)
- Compare acknowledged values with requested values and store computed deltas: qty_delta_pct, price_delta_pct, date_slip_days — computed columns, not random

PROMISE DATE (PD-<ACK-id>-NN):
- One row per acknowledged line that has a promise: promise_date, promised_qty (= accepted_qty for that line), promise_confidence (high/medium/low — correlates with supplier reliability), ship-from location (warehouse node from a small synthetic network), carrier reference (synthetic carrier code tied to the carrier/warehouse operator actor)
- promise_date derived from: order_date + supplier lead time + slip (or negative slip/early for good suppliers), rounded to business days. Never independent of the supplier profile.
- Date fields must satisfy ordering rules for VALID rows: order_date ≤ response_timestamp, promise_date ≥ order_date, response due date ordering as per the dictionary. (Deliberate anomalies come later in the anomaly-injection prompt — normal generation must be clean.)

EVENT LOG: every acknowledgement submission and every revision writes an entity_event row (ack_submitted, ack_revised) with actor_role=supplier.

Implement in src/supplier_ack/generators/acks.py. Then run the starter generation end-to-end for these tables and print: ack coverage %, partial acceptance %, average date slip, revision counts histogram.

ACCEPTANCE CHECKLIST:
[ ] accepted + rejected = requested holds for 100% of acknowledged lines
[ ] All revisions retained with superseded_by; no row overwritten
[ ] Deltas (qty, price, date) computed, not generated
[ ] Promise dates derived from supplier profiles with realistic ordering
[ ] Event rows written for every ack submission/revision
[ ] Byte-exact FK references to POs and lines
[ ] Starter CSVs generated for Acknowledgement and PromiseDate

COMMIT MESSAGE: "feat: acknowledgement and promise-date generation with revisions and computed deltas"

---

Continue the supplier-ack-system project. New task: implement ChangeRequest, Approval, and the conditional approval-threshold rules (the "compare changes with requested values; apply approval thresholds for price/date/quantity changes" requirement).

CHANGEREQUEST (CHG-<PO-id>-NNNNNN):
- Raised when an acknowledgement or promise differs from the requested values beyond configured tolerance: price change %, date slip days, quantity shortfall %
- Fields: change_type (price/date/quantity), old_value, new_value, delta computed from source records, requested_by (supplier for confirmed changes, or planner for expedite requests), status lifecycle: open → pending_approval → approved/rejected → applied
- Rule (document in docs/decisions.md): within-threshold changes auto-approve at planner level; above-threshold changes escalate to the operations manager. Thresholds from config, e.g.: price ±5%, date slip ≤7 days, quantity shortfall ≤10% → planner auto/quick approval; anything beyond → operations manager escalation.

APPROVAL (APR-<change-id>-NN):
- One or more approval steps per change: approver actor (planner or operations manager), decision (approved/rejected/pending), decision timestamp, comments, approval_level
- Approval must be a separate append-only record — never overwrite: a rejected-then-appealed change gets two Approval rows
- Conditional rules to implement explicitly:
  1. price change within threshold → planner approves; above threshold → operations manager required
  2. date slip within threshold → planner approves; slip > threshold → operations manager AND flag downstream impact (used next prompt)
  3. quantity change within threshold → planner; beyond → operations manager
  4. supplier silence past response_due_date → auto-generated "escalation" change request of type date, routed to the planner with a chase notification
- A change is only "applied" after at least one approved Approval row exists at the required level. Enforce this in a pure function can_apply(change, approvals) → (bool, reason) that the next prompts reuse.

EVENT LOG: change_requested, approval_decided, change_applied events with actor roles.

Ground-truth principle (problem statement): "Generate outcomes and ground-truth labels from documented rules, not independent random assignment." Outcomes (approved/rejected) must be computed from these rules — never coin-flipped.

Implement in src/supplier_ack/generators/changes.py + src/supplier_ack/rules/thresholds.py. Run starter generation; print: change counts by type, auto vs escalated split, approval decision distribution, escalation reasons.

ACCEPTANCE CHECKLIST:
[ ] All 3 change types generated with computed deltas
[ ] Threshold logic in pure, unit-tested functions; thresholds config-driven
[ ] Approval records append-only; multiple approval levels supported
[ ] Escalation path exists (planner → operations manager) and is exercised in data
[ ] Silence-triggered escalation changes generated
[ ] can_apply() exists and enforces approval-before-apply
[ ] Outcomes computed from documented rules, not random
[ ] Event log rows for every change/approval state change

COMMIT MESSAGE: "feat: change requests, multi-level approvals, and configurable threshold rules"


Continue the supplier-ack-system project. New task: implement the downstream half of the workflow — "update projected supply only after approval; notify affected planners" — plus InventoryPlan, ProductionOrder, and Notification.

INVENTORYPLAN (IP-<PO-line-id>-NN):
- Represents the PROJECTED SUPPLY for a PO line, as versioned append-only rows: plan_version, projected_qty, projected_delivery_date, source (po_baseline / approved_ack / approved_change), created_at, effective flags
- Version 1 always = the original PO line values (baseline projection)
- A new version row is created ONLY when: an acknowledgement is fully processed with promises AND its change is approved (or within-threshold auto-approved). If a change is pending or rejected, NO new InventoryPlan version is created — the projection stays at the last approved state. This is the acceptance criterion "only approved changes affect plans" — implement it as a hard rule and unit-test it.
- Every version row keeps the previous version linkage (previous_version_id). History never overwritten.

PRODUCTIONORDER (PRO-2026-NNNNNN) — DOWNSTREAM SCHEDULE IMPACT:
- Production orders consume PO lines: production_order_line bridge (allocated_quantity)
- Each production order has: required_by_date, planned_start_date, priority, status lifecycle (planned → at_risk → rescheduled → confirmed / delayed)
- IMPACT PROPAGATION RULE (the heart of "downstream schedule impacts"): when an approved change slips a promise date or reduces promised quantity beyond a tolerance, find the production orders whose required_by_date now conflicts with the new projected delivery, or whose allocated quantity exceeds the new projected supply. For each affected production order: create/emit an impact record (impact_id, production_order_id, change_id, impact_type date_conflict/quantity_shortfall, severity computed from slip days and shortfall %), update the production order status to at_risk or rescheduled, and record the rescheduled planned_start_date computed from the new projected date.
- Production order status changes must flow through the event log with actor_role=planner or operations manager.
- Compute, don't fabricate: severity = documented function of slip days and shortfall %.

NOTIFICATION (NOT-2026-NNNNNN):
- Generated on: change raised (to owning planner), approval decisions (to requester), plan updates (to planner + logistics analyst), downstream impacts (to planner + carrier/warehouse operator when a delivery slot moves), supplier silence chases (to planner + supplier), weekly summary to operations manager
- Fields: not_id, not_type, severity, subject, body (rendered from a template with entity ids — traceable), recipient references via the notification_recipient bridge (role + optional actor id), related_entity_type/id (the PO/ACK/CHG it traces to), sent_at, read status
- "Notify affected planners": map each PO to its owning planner (buyer field on the PO); notifications must go to the RIGHT planner, not a random one.

Traceability acceptance: given any Notification, one must be able to walk back: notification → change → acknowledgement → PO → supplier. Implement a helper function trace(not_id) that returns this chain and print 3 example traces.

Implement in src/supplier_ack/generators/supply.py (or workflow modules), then run the starter generation end-to-end for ALL tables and print an end-to-end run summary.

ACCEPTANCE CHECKLIST:
[ ] InventoryPlan versions: baseline version for every line; new versions only after approval — verified by a test that a rejected/pending change produces no new version
[ ] Production order impact propagation works: slip/shortfall → impact records + status changes
[ ] Severity computed from a documented function
[ ] Notifications go to correct recipients by role and trace to source entities
[ ] trace() helper returns a full chain for sample notifications
[ ] Event log rows written for plan updates, impacts, and notifications
[ ] Starter dataset now covers all 10 entities end-to-end

COMMIT MESSAGE: "feat: projected supply versions, downstream production impacts, and traceable notifications"

Continue the supplier-ack-system project. New task: enforce the derived-value and reconciliation discipline (Generation Step 6 of the problem statement) across the whole dataset. From now dont take much time, take 10-15mins max.

"Calculate derived values (totals, balances, scores, statuses and dates) from source records rather than generating them independently."

TASK 1 — Build src/supplier_ack/rules/derived.py as a single derived-attribute library used by BOTH the generator and the validation suite:
- PO total_amount = Σ line_total of its POLines
- Acknowledgement deltas (qty/price/date) recomputed from source columns
- Acknowledgement status derivation: full_accept / partial_accept / full_reject / revised, from accepted vs requested
- PromiseDate derived flags: is_late (vs requested date), slip_days
- ChangeRequest derived fields: delta_abs, delta_pct, required_approval_level (from thresholds)
- InventoryPlan derived: latest_approved_version per line (via plan version ordering + approval joins)
- ProductionOrder derived: at_risk flag, shortfall_qty (allocated − projected), delay_days
- Supplier derived scores: ack_rate, on_time_promise_rate, avg_slip_days — recomputed from the actual acknowledgement rows
- Notification derived: open_impact_count per PO

TASK 2 — Reconciliation engine: a function reconcile(dataset) that recomputes every derived value from raw sources and asserts equality with stored values, returning a per-entity reconciliation report (checked_count, mismatch_count, sample mismatches). Wire it into the generator as a post-generation step so the generator cannot ship an internally inconsistent dataset.

TASK 3 — Arithmetical invariants to enforce (add to the library):
- accepted + rejected = requested per acknowledged line
- line_total = qty × unit_price everywhere
- PO total = Σ line totals
- InventoryPlan latest version quantity/dates equal the approved acknowledgement promise
- Production order allocated ≤ projected supply for confirmed orders (violations allowed only for at_risk orders — document this)
- Every event-log state change for an entity matches that entity's stored lifecycle transitions

TASK 4 — Add a "status consistency" rule per the acceptance criteria ("acknowledgement status is consistent"): the derived ack status must agree with the stored ack status; write unit tests for the derivation function including boundary cases (accepted = 0, accepted = requested, rounding).

Run the starter dataset through reconcile() and print the reconciliation report — it must show zero mismatches before anomaly injection (anomalies come next).

ACCEPTANCE CHECKLIST:
[ ] derived.py library exists and is the single source of truth for derived values
[ ] Generator calls reconcile() after generation; zero mismatches on clean starter data
[ ] All 6 invariant groups enforced and unit-tested
[ ] Ack status derivation tested at boundaries
[ ] Supplier scores recomputed from data, not generated

COMMIT MESSAGE: "feat: derived-value library and reconciliation engine with zero-mismatch gate"


Continue the supplier-ack-system project. New task: inject the four required labelled edge cases and produce the separated ground-truth file (Generation Steps 5 and 7 of the problem statement).

REQUIRED EDGE CASES — inject each in a controlled, documented way, AFTER valid baseline generation:
1. UNAPPROVED_CHANGE_UPDATES_PLAN: an InventoryPlan version row exists whose source links to a ChangeRequest that has NO approved Approval. Exact counts from config (e.g., 25 full-scale, 5 starter).
2. ACK_WRONG_PO_LINE: acknowledgement lines referencing a po_line_id that does not belong to the referenced PO (cross-PO line reference), plus a variant referencing a non-existent line id. Keep the row with an issue_type label rather than "silently corrupting unrelated rows" — label it, do not randomize other data around it.
3. PROMISE_DATE_BEFORE_ORDER_DATE: PromiseDate rows where promise_date < po.order_date (logically impossible).
4. STALE_REVISION_OVERWRITE: an older revision (lower revision_no, earlier timestamp) appears as the current/latest version — e.g., the latest InventoryPlan version or the effective promise points to an older revision while a newer revision exists.

DESIGN RULES:
- Generate valid baseline records first, then inject labelled edge cases as a separate pipeline stage.
- Each injected row carries issue_type from the four-type enum and a boolean ground_truth flag; normal rows are NULL/False.
- Add valid boundary cases: accepted_qty = requested_qty, slip exactly equal to threshold days, and price delta exactly at ±threshold, labelled boundary=True.
- Injection is deterministic under the seed.
- Produce data/generated/ground_truth.csv and ground_truth.json with expected decisions from documented rules, plus expected approval outcomes for every change request and expected status for every impacted production order.
- Never leak ground_truth/issue_type into input/export tables. Strip them from exported entity CSVs and validate this automatically; retain them only in internal generator state and separate ground-truth files.

ACCEPTANCE CHECKLIST:
[ ] All four anomaly types injected at configured counts, deterministic under seed
[ ] Exact threshold boundary cases included
[ ] ground_truth.csv and ground_truth.json contain expected decisions
[ ] Exported input files have no ground_truth/issue_type leakage
[ ] Injection stage separate from baseline generation
[ ] Each anomaly documented in docs/decisions.md

COMMIT MESSAGE: "feat: labelled anomaly injection and separated ground-truth files with leakage checks"
