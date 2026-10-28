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
