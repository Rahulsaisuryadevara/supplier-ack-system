# Prompt history — supplier-ack-system

This file records, verbatim and in chronological order, every task prompt given to the AI coding assistant for this project. Each prompt is followed by a one-line note of what the assistant produced in response. Prompts 1–18 and the fix request were given in the first conversation; Prompts 19–21 continued in a second conversation after the first reached its length limit (Prompt 19 includes the context handover block that was sent together with it). See the record-keeping note at the end for how this record was maintained and completed.

---

## Prompt 1 — Project bootstrap &amp; architecture plan (verbatim)

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
  .gitignore                # exclude .venv, **pycache**, data/generated (keep data/samples)  
  config/  
    generator\_config.yaml   # all knobs: scale, seed, thresholds, distributions  
  src/supplier\_ack/  
    **init**.py  
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
    data\_dictionary.md  
    schema.md               # ER diagram + cardinality tables  
    decisions.md            # assumptions, trade-offs, limitations  
    provenance.md           # public data guidance / source manifest  
  ai/  
    prompt\_history.md       # every prompt you give me, verbatim  
    ai\_disclosure.md        # where AI helped, what I reviewed/validated

TASK 3 — Write the initial README.md skeleton: project purpose, install steps, run steps, verification steps, repository layout. It will be completed later.

TASK 4 — Write generator\_config.yaml with a first draft of all knobs: seed (20261022), po\_count (10000), event\_count (15000), starter scale (po\_count=200, event\_count=300), approval thresholds (price change %, date slip days, quantity change %), and distribution parameters. Every knob must be configurable — the starter and full datasets must use the SAME generator, only differing parameters.

TASK 5 — Create ai/prompt\_history.md and start it with this very prompt pasted verbatim. Append every future prompt I give you to this file.

DELIVERABLES: repository tree, pyproject.toml/requirements.txt, README skeleton, config file, prompt\_history.md initialized.

ACCEPTANCE CHECKLIST:  
\[ \] Project runs: `pip install -e .` succeeds (create a minimal **init**.py everywhere needed)  
\[ \] All 5 actors named somewhere in the design docs or config  
\[ \] Config has seed 20261022 and both starter and full scales  
\[ \] README explains install, run, verify

COMMIT MESSAGE: "feat: bootstrap repository structure, config, and README skeleton"

---

AI output note: Bootstrapped the repository layout, package metadata, starter README, generator configuration, and initial prompt-history file.

---

## Prompt 2 — Complete data dictionary, Generation Step 1 (verbatim)

Continue the supplier-ack-system project. New task: produce the complete DATA DICTIONARY (Generation Step 1 of the problem statement). This is the foundation for everything else — be exhaustive, not illustrative.

For EACH of these 10 entities: Supplier, PurchaseOrder, POLine, Acknowledgement, PromiseDate, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification — create a full field-by-field dictionary. For every field specify:

1. Field name (snake\_case)
2. Data type (exact: e.g., INTEGER, DECIMAL(12,2), DATE, VARCHAR(24), TEXT, BOOLEAN, ENUM)
3. Required or optional
4. Allowed values / domain (full enum lists, ranges, formats)
5. Units (where applicable: currency, days, quantities)
6. Uniqueness (primary key? unique per parent? not unique?)
7. Validation rule (a concrete, machine-checkable rule, e.g. "ack\_accepted\_qty + ack\_rejected\_qty = ack\_total\_qty" or "promise\_date &gt;= po.order\_date for valid rows")

MANDATORY FIELDS TO INCLUDE (do not omit):

- Every entity needs a primary key using the documented ID conventions:  
Supplier: SUP-000001; PurchaseOrder: PO-2026-000001; POLine: -L01;  
Acknowledgement: ACK--01 (suffix increments per revision: -01, -02...);  
PromiseDate: PD--01; ChangeRequest: CHG--000001;  
Approval: APR--01; Notification: NOT-2026-000001;  
InventoryPlan: IP--01; ProductionOrder: PRO-2026-000001.
- Foreign keys for every relationship (supplier\_id on PO, po\_id on ACK/CHG, po\_line\_id on ACK lines and PromiseDate, change\_request\_id on Approval, etc.)
- Lifecycle/status fields with full enum lists for: PurchaseOrder, POLine, Acknowledgement, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification (define each state and the legal transitions between them)
- Effective dates (created\_at, effective\_date, response\_due\_date, etc.) with date-ordering validation rules
- Actor/role references: approver (planner or operations manager), notification recipients (planner, carrier/warehouse operator, logistics analyst), supplier contact
- Revision/version fields (revision\_no on Acknowledgement, superseded\_by on revisions)
- Monetary fields: unit\_price, line\_total (with the rule line\_total = quantity × unit\_price)
- Quantities: requested, accepted, rejected, promised — with the reconciliation rule requested = accepted + rejected
- Money/quantity comparison fields: requested vs acknowledged vs promised vs projected
- Anomaly labelling fields: issue\_type and ground\_truth columns on relevant entities, NULL for normal rows

Write the dictionary to docs/data\_dictionary.md as one table per entity, plus a summary table listing: entity, primary key, foreign keys, row counts (baseline volumes), and which generation step produces it.

Also export the dictionary as a machine-readable src/supplier\_ack/schema.py Python module: for each entity define a dataclass or dict spec with field name, type, required, enum values, and a validator function per validation rule. Validators must be real callable functions, not comments.

ACCEPTANCE CHECKLIST:  
\[ \] All 10 entities present, each with ≥8 meaningfully specified fields  
\[ \] Every field has all 7 specification attributes  
\[ \] Every entity has a primary key following the ID conventions exactly  
\[ \] Every relationship has a foreign key field  
\[ \] Every status field has a full enum and documented legal transitions  
\[ \] Arithmetic and date-ordering validation rules are machine-checkable  
\[ \] docs/data\_dictionary.md and src/supplier\_ack/schema.py both complete and consistent

COMMIT MESSAGE: "feat: complete data dictionary for all 10 entities with validation rules"

---

AI output note: Created the initial exhaustive entity-field dictionary and corresponding machine-readable schema specification.

---

## Prompt 3 — Relational schema, relationships, lifecycle &amp; event history (verbatim)

Continue the supplier-ack-system project. New task: design the full relational schema and event-history model (Entities and Relationships section of the problem statement). Produce docs/schema.md and the SQLite DDL in src/supplier\_ack/schema.py (as a create\_schema.sql string plus a create\_all() function).

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
  - Notification → recipients: model recipients via a bridge table notification\_recipient(notification\_id, actor\_role) since one notification can target multiple roles (planner, carrier/warehouse operator, logistics analyst, operations manager)
  - Any N:M between ProductionOrder and POLine (a production order consuming multiple PO lines) must use a bridge table: production\_order\_line(production\_order\_id, po\_line\_id, allocated\_quantity)
3. Document optional relationships: e.g., a ChangeRequest may have no Approval yet (pending), a Notification may have no linked change (system-wide notices), a ProductionOrder may not exist for every PO line.
4. Effective dates and lifecycle states: document which tables are event/append-only history vs current-state snapshots. Never overwrite history: acknowledgements keep every revision row; InventoryPlan keeps every projected-supply version; Approval keeps decision history.
5. Event history: create a dedicated event log table entity\_event(event\_id, entity\_type, entity\_id, event\_type, event\_timestamp, actor\_role, payload\_json, previous\_state, new\_state). Every state change (PO created, ack received, ack accepted/rejected, change requested, change approved/rejected, plan updated, notification sent) writes an event row. The current state is derivable, never destructive.
6. Anomaly handling: anomaly rows must NOT silently corrupt other rows. Anomalies are recorded with issue\_type + ground\_truth labels (e.g., on the entity itself or in the ground truth file), and the schema must allow them to exist without breaking FK integrity where possible — document exactly which integrity constraint each anomaly type deliberately violates or satisfies.
7. Include an ER diagram as a Mermaid erDiagram in docs/schema.md showing all 10+ entities, bridge tables, and the event log, with cardinality labels on every edge.
8. Lifecycle diagrams: for PurchaseOrder, Acknowledgement, ChangeRequest, and InventoryPlan, document the state machine (states + legal transitions) as a table, and note which business rule triggers each transition.

ACCEPTANCE CHECKLIST:  
\[ \] DDL executes cleanly against SQLite with FK enforcement ON (PRAGMA foreign\_keys = ON)  
\[ \] Every relationship in the problem is documented with cardinality  
\[ \] All N:M relationships use bridge tables  
\[ \] Optional relationships documented  
\[ \] Event log table exists and design shows append-only history for revisions  
\[ \] Anomaly labelling strategy documented (no silent corruption of unrelated rows)  
\[ \] Mermaid ER diagram present in docs/schema.md  
\[ \] 4 lifecycle state machines documented

COMMIT MESSAGE: "feat: relational schema, bridge tables, event history model, and lifecycle state machines"

---

AI output note: Added the relational schema/DDL, relationships, bridge tables, and event-history design.

---

## Prompt 4 — Deterministic ID / nomenclature engine, Generation Step 3 (verbatim)

Continue the supplier-ack-system project. New task: implement the deterministic ID/nomenclature engine in src/supplier\_ack/ids.py (Generation Step 3 of the problem statement).

REQUIRED CONVENTIONS — implement exactly:

- Supplier: SUP-000001 (6-digit zero-padded counter)
- PurchaseOrder: PO-2026-000001 (year segment 2026, 6-digit counter)
- POLine: -L01, -L02, ... (2-digit line counter, per PO)
- Acknowledgement: ACK--01, then -02, -03 for each revision of the same PO (2-digit revision counter per PO)
- PromiseDate: PD--01 (counter within an acknowledgement)
- ChangeRequest: CHG--000001 (6-digit counter per PO)
- Approval: APR--01 (counter per change request — note: embeds the full CHG id, so the format is APR-CHG-PO-2026-000001-000001-01; if you judge this too unwieldy, you may instead use APR--01 where change-sequence is the CHG id; either way document the decision in docs/decisions.md)
- Notification: NOT-2026-000001 (year + 6-digit global counter)
- InventoryPlan: IP--01 (version counter per PO line)
- ProductionOrder: PRO-2026-000001

RULES:

- Counters are zero-padded and monotonically increasing
- IDs are immutable once issued — provide no API to change them
- Referenced IDs must be exactly consistent across files/tables: an ACK row referencing a PO must use the byte-identical PO id string
- The engine is deterministic: given the same generation sequence, it issues the same IDs (no randomness in ID assignment)
- Implement as a class IDFactory with methods: next\_supplier\_id(), next\_po\_id(), next\_line\_id(po\_id), next\_ack\_id(po\_id), next\_promise\_date\_id(ack\_id), next\_change\_id(po\_id), next\_approval\_id(change\_id), next\_notification\_id(), next\_inventory\_plan\_id(po\_line\_id), next\_production\_order\_id(). Persist counter state in memory; optionally serialize/deserialize to JSON for reproducibility.
- Unit-test round-tripping: generate 1000 IDs of each type, assert format via regex, assert uniqueness, assert zero-padding width, assert exact embedding of parent IDs.

Write tests/test\_ids.py with at least 12 test cases covering formats, padding, uniqueness, immutability (issuing never reuses), and cross-reference exactness.

ACCEPTANCE CHECKLIST:  
\[ \] All 10 ID formats implemented and regex-validated  
\[ \] Zero-padded, deterministic, immutable  
\[ \] Parent IDs embedded exactly (byte-identical cross-references)  
\[ \] test\_ids.py passes with ≥12 tests  
\[ \] Any judgment call (e.g., the APR format) documented in docs/decisions.md

COMMIT MESSAGE: "feat: deterministic zero-padded ID engine for all entities with full test coverage"

---

AI output note: Implemented parent-scoped deterministic identifiers and ID format tests.

---

## Prompt 5 — Seeded generator framework + master data, Steps 2 &amp; 4 (verbatim)

Continue the supplier-ack-system project. New task: build the seeded, parameterized synthetic-data generator framework and the MASTER DATA generation (Generation Steps 2 and 4 of the problem statement).

FRAMEWORK REQUIREMENTS:

- Single generator that serves BOTH the starter and full datasets; only the config scale differs. Command: python -m supplier\_ack.cli generate --config config/generator\_config.yaml --scale starter|full --seed 20261022
- Fixed default seed: 20261022. Use numpy.random.default\_rng(seed) or an equivalent single RNG object threaded through every generator module. No module may call the global random or np.random directly — all randomness flows through the injected rng. This is required for reproducibility.
- Deterministic ID issuance via the IDFactory from the previous step.
- Every generator module emits pandas DataFrames whose columns exactly match the data dictionary from Prompt 2.
- Generation ORDER must respect dependencies (Generation Step 2: "Generate master data first", then "dependent transaction/event records using valid parent IDs"): Supplier → PurchaseOrder → POLine → Acknowledgement/PromiseDate → ChangeRequest/Approval → InventoryPlan/ProductionOrder → Notification.

MASTER DATA GENERATION (this prompt only):

1. Supplier (\~200 suppliers at full scale, \~40 at starter): realistic B2B supplier names (synthetic, e.g., "Vertex Industrial Supplies"), unique supplier\_id, region, lead\_time\_days (varied distribution: most 7–30 days, a tail up to 90), reliability\_score (beta distribution — most suppliers reliable, a few unreliable), on\_time\_rate (correlated with reliability\_score, NOT independent), preferred/carrier preferences. Record every distribution choice in docs/decisions.md with justification.
2. PurchaseOrder (10,000 at full scale, 200 at starter): po\_id (PO-2026-...), supplier\_id (weighted sampling so some suppliers get more POs — a realistic Pareto-ish skew, not uniform), order\_date (spread over a working calendar, e.g., Jan–Jun 2026, weekdays only), requested\_delivery\_date = order\_date + supplier lead time + buffer, status lifecycle start, buyer/planner actor reference, total\_amount (derived LATER — do not generate it here).
3. POLine (2–6 lines per PO, so \~30,000+ lines at full scale): po\_line\_id (-L01...), item description from a synthetic parts catalog (create a synthetic item master of \~50 items with unit\_price ranges), quantity (varied: 10–5000, log-normal-ish), unit\_price (within the item's range), currency, requested qty/date inherited from PO. line\_total must be COMPUTED = quantity × unit\_price, never independently random (Generation Step 6 principle).

Also emit the first synthetic reference data: the item master and the actor roster (named planners, warehouse operators, logistics analysts, operations managers — synthetic names, roles).

WRITE the generation to be checkpointable: each entity family gets a function generate\_suppliers(rng, cfg) → DataFrame etc.

Then generate the STARTER dataset for suppliers/POs/POLines and save to data/samples/ as CSVs. Print a summary: row counts per table, distribution stats (mean/median/p90 of quantity, lead time, lines per PO).

ACCEPTANCE CHECKLIST:  
\[ \] One command generates starter or full scale with the same code path  
\[ \] Seed 20261022 hardcoded as default; --seed flag overrides  
\[ \] No global RNG usage anywhere (grep for np.random. and random.) to verify  
\[ \] Supplier counts, PO counts, and lines-per-PO match config at both scales  
\[ \] quantity × unit\_price = line\_total for every row  
\[ \] Starter CSVs exist in data/samples/ and open cleanly  
\[ \] Distribution choices justified in docs/decisions.md

COMMIT MESSAGE: "feat: seeded generator framework with supplier, PO, and PO-line master data"

---

AI output note: Added the seeded generator framework and master/reference data generation modules.

---

## Prompt 6 — Volumes, coverage &amp; distribution control, Step 4 complete (verbatim)

Continue the supplier-ack-system project. New task: implement the required VOLUME and COVERAGE profile (Generation Step 4 of the problem statement) as explicit, config-driven scenario mix knobs.

BASELINE VOLUMES (config-driven, these are the full-scale defaults):

- 10,000 PurchaseOrders, \~15,000 acknowledgement/change events total (count acknowledgements + change requests together; e.g., \~10,000 acknowledgements covering most POs and \~5,000 change requests on a subset)
- Starter scale: 200 POs, 300 events (same ratios)

REQUIRED COVERAGE — implement each as a config knob with a target proportion, and make the proportions realistic (document them):

1. Partial acceptance: acknowledgements where accepted\_qty &lt; requested\_qty and rejected\_qty = requested − accepted, with a rejection\_reason (capacity, price, stock, logistics)
2. Full acceptance: accepted = requested
3. Full rejection: accepted = 0
4. Date slips: promised\_date later than requested\_delivery\_date (slip days drawn from a realistic distribution: most slips 3–14 days, tail to 60)
5. On-time promises: promised\_date ≤ requested date
6. Price changes: unit\_price on the acknowledgement differs from the PO line price (±0.5% to ±15%)
7. Supplier silence: POs that NEVER receive an acknowledgement — model these explicitly as POs with response\_due\_date passed and no ACK row; also produce a "silence report" listing them (do not fabricate empty ACK rows; document this modeling decision)
8. Multiple revisions: POs with 2–4 acknowledgement revisions (a supplier revises their promise); later revisions supersede earlier ones via superseded\_by and revision\_no, but ALL revision rows are retained (never overwrite history)

DISTRIBUTION QUALITY (Evaluation focus (a): "realistic distributions and meaningful variation"):

- Use proper statistical distributions (normal/log-normal/beta/weighted categorical), not uniform-everything
- Correlate sensibly: unreliable suppliers slip dates more and partially accept more; large quantity lines get more partial acceptances; price changes skew upward
- Print a coverage report after generation: for each of the 8 categories above, the count and percentage at both scales

Also add a config validation function that warns if the coverage mix is impossible for the requested volumes (e.g., revision POs cannot exceed PO count).

ACCEPTANCE CHECKLIST:  
\[ \] Full-scale defaults: 10,000 POs and \~15,000 ack/change events; starter 200/300  
\[ \] All 8 coverage categories present with counts/percentages in the coverage report  
\[ \] Multiple revisions retained as separate rows with superseded\_by linkage  
\[ \] Supplier silence modeled without fake ACK rows, with a silence report  
\[ \] Distributions are parameterized and documented; no uniform-everything  
\[ \] Coverage report prints for both starter and full scales

COMMIT MESSAGE: "feat: coverage-mix engine with partial acceptance, date slips, price changes, silence, and revisions"

AI output note: Added configurable coverage/scenario mix controls and coverage reporting.

---

## Prompt 7 — Acknowledgements &amp; PromiseDates generation (verbatim)

Continue the supplier-ack-system project. New task: generate the Acknowledgement and PromiseDate records (core of the workflow's "generate acknowledgements with accepted/rejected quantities and promised dates" requirement).

ACKNOWLEDGEMENT (ACK--NN):

- po\_id references an existing PO exactly; ack status lifecycle: draft → submitted → processed (or → exception)
- Per PO line, the acknowledgement carries: requested\_qty (copied from the PO line — byte-consistent), accepted\_qty, rejected\_qty, rejected\_reason, acknowledged unit\_price, response timestamp
- INVARIANT: accepted\_qty + rejected\_qty = requested\_qty for every acknowledged line. Compute accepted\_qty first, then rejected\_qty = requested − accepted. Never generate them independently (Generation Step 6: derived from source records).
- For revision rows: revision\_no increments; previous revision gets superseded\_by = new ack id; every revision is a full-row snapshot (history preserved)
- Supplier response time: response\_timestamp = po.order\_date + supplier-specific response delay distribution (fast suppliers reply in 1–3 days, slow ones near or past response\_due\_date; a share respond LATE — ties into date-slip and approval logic later)
- Compare acknowledged values with requested values and store computed deltas: qty\_delta\_pct, price\_delta\_pct, date\_slip\_days — computed columns, not random

PROMISE DATE (PD--NN):

- One row per acknowledged line that has a promise: promise\_date, promised\_qty (= accepted\_qty for that line), promise\_confidence (high/medium/low — correlates with supplier reliability), ship-from location (warehouse node from a small synthetic network), carrier reference (synthetic carrier code tied to the carrier/warehouse operator actor)
- promise\_date derived from: order\_date + supplier lead time + slip (or negative slip/early for good suppliers), rounded to business days. Never independent of the supplier profile.
- Date fields must satisfy ordering rules for VALID rows: order\_date ≤ response\_timestamp, promise\_date ≥ order\_date, response due date ordering as per the dictionary. (Deliberate anomalies come later in the anomaly-injection prompt — normal generation must be clean.)

EVENT LOG: every acknowledgement submission and every revision writes an entity\_event row (ack\_submitted, ack\_revised) with actor\_role=supplier.

Implement in src/supplier\_ack/generators/acks.py. Then run the starter generation end-to-end for these tables and print: ack coverage %, partial acceptance %, average date slip, revision counts histogram.

ACCEPTANCE CHECKLIST:  
\[ \] accepted + rejected = requested holds for 100% of acknowledged lines  
\[ \] All revisions retained with superseded\_by; no row overwritten  
\[ \] Deltas (qty, price, date) computed, not generated  
\[ \] Promise dates derived from supplier profiles with realistic ordering  
\[ \] Event rows written for every ack submission/revision  
\[ \] Byte-exact FK references to POs and lines  
\[ \] Starter CSVs generated for Acknowledgement and PromiseDate

COMMIT MESSAGE: "feat: acknowledgement and promise-date generation with revisions and computed deltas"

---

AI output note: Added acknowledgement revisions, promised-date records, and quantity/status reconciliation rules.

---

## Prompt 8 — ChangeRequests, Approvals &amp; threshold rules (verbatim)

Continue the supplier-ack-system project. New task: implement ChangeRequest, Approval, and the conditional approval-threshold rules (the "compare changes with requested values; apply approval thresholds for price/date/quantity changes" requirement).

CHANGEREQUEST (CHG--NNNNNN):

- Raised when an acknowledgement or promise differs from the requested values beyond configured tolerance: price change %, date slip days, quantity shortfall %
- Fields: change\_type (price/date/quantity), old\_value, new\_value, delta computed from source records, requested\_by (supplier for confirmed changes, or planner for expedite requests), status lifecycle: open → pending\_approval → approved/rejected → applied
- Rule (document in docs/decisions.md): within-threshold changes auto-approve at planner level; above-threshold changes escalate to the operations manager. Thresholds from config, e.g.: price ±5%, date slip ≤7 days, quantity shortfall ≤10% → planner auto/quick approval; anything beyond → operations manager escalation.

APPROVAL (APR--NN):

- One or more approval steps per change: approver actor (planner or operations manager), decision (approved/rejected/pending), decision timestamp, comments, approval\_level
- Approval must be a separate append-only record — never overwrite: a rejected-then-appealed change gets two Approval rows
- Conditional rules to implement explicitly:
  1. price change within threshold → planner approves; above threshold → operations manager required
  2. date slip within threshold → planner approves; slip &gt; threshold → operations manager AND flag downstream impact (used next prompt)
  3. quantity change within threshold → planner; beyond → operations manager
  4. supplier silence past response\_due\_date → auto-generated "escalation" change request of type date, routed to the planner with a chase notification
- A change is only "applied" after at least one approved Approval row exists at the required level. Enforce this in a pure function can\_apply(change, approvals) → (bool, reason) that the next prompts reuse.

EVENT LOG: change\_requested, approval\_decided, change\_applied events with actor roles.

Ground-truth principle (problem statement): "Generate outcomes and ground-truth labels from documented rules, not independent random assignment." Outcomes (approved/rejected) must be computed from these rules — never coin-flipped.

Implement in src/supplier\_ack/generators/changes.py + src/supplier\_ack/rules/thresholds.py. Run starter generation; print: change counts by type, auto vs escalated split, approval decision distribution, escalation reasons.

ACCEPTANCE CHECKLIST:  
\[ \] All 3 change types generated with computed deltas  
\[ \] Threshold logic in pure, unit-tested functions; thresholds config-driven  
\[ \] Approval records append-only; multiple approval levels supported  
\[ \] Escalation path exists (planner → operations manager) and is exercised in data  
\[ \] Silence-triggered escalation changes generated  
\[ \] can\_apply() exists and enforces approval-before-apply  
\[ \] Outcomes computed from documented rules, not random  
\[ \] Event log rows for every change/approval state change

COMMIT MESSAGE: "feat: change requests, multi-level approvals, and configurable threshold rules"



AI output note: Added change requests, approval records, threshold evaluation, and escalation routing.

---

## Prompt 9 — Projected supply, downstream impact &amp; notifications (verbatim)

Continue the supplier-ack-system project. New task: implement the downstream half of the workflow — "update projected supply only after approval; notify affected planners" — plus InventoryPlan, ProductionOrder, and Notification.

INVENTORYPLAN (IP--NN):

- Represents the PROJECTED SUPPLY for a PO line, as versioned append-only rows: plan\_version, projected\_qty, projected\_delivery\_date, source (po\_baseline / approved\_ack / approved\_change), created\_at, effective flags
- Version 1 always = the original PO line values (baseline projection)
- A new version row is created ONLY when: an acknowledgement is fully processed with promises AND its change is approved (or within-threshold auto-approved). If a change is pending or rejected, NO new InventoryPlan version is created — the projection stays at the last approved state. This is the acceptance criterion "only approved changes affect plans" — implement it as a hard rule and unit-test it.
- Every version row keeps the previous version linkage (previous\_version\_id). History never overwritten.

PRODUCTIONORDER (PRO-2026-NNNNNN) — DOWNSTREAM SCHEDULE IMPACT:

- Production orders consume PO lines: production\_order\_line bridge (allocated\_quantity)
- Each production order has: required\_by\_date, planned\_start\_date, priority, status lifecycle (planned → at\_risk → rescheduled → confirmed / delayed)
- IMPACT PROPAGATION RULE (the heart of "downstream schedule impacts"): when an approved change slips a promise date or reduces promised quantity beyond a tolerance, find the production orders whose required\_by\_date now conflicts with the new projected delivery, or whose allocated quantity exceeds the new projected supply. For each affected production order: create/emit an impact record (impact\_id, production\_order\_id, change\_id, impact\_type date\_conflict/quantity\_shortfall, severity computed from slip days and shortfall %), update the production order status to at\_risk or rescheduled, and record the rescheduled planned\_start\_date computed from the new projected date.
- Production order status changes must flow through the event log with actor\_role=planner or operations manager.
- Compute, don't fabricate: severity = documented function of slip days and shortfall %.

NOTIFICATION (NOT-2026-NNNNNN):

- Generated on: change raised (to owning planner), approval decisions (to requester), plan updates (to planner + logistics analyst), downstream impacts (to planner + carrier/warehouse operator when a delivery slot moves), supplier silence chases (to planner + supplier), weekly summary to operations manager
- Fields: not\_id, not\_type, severity, subject, body (rendered from a template with entity ids — traceable), recipient references via the notification\_recipient bridge (role + optional actor id), related\_entity\_type/id (the PO/ACK/CHG it traces to), sent\_at, read status
- "Notify affected planners": map each PO to its owning planner (buyer field on the PO); notifications must go to the RIGHT planner, not a random one.

Traceability acceptance: given any Notification, one must be able to walk back: notification → change → acknowledgement → PO → supplier. Implement a helper function trace(not\_id) that returns this chain and print 3 example traces.

Implement in src/supplier\_ack/generators/supply.py (or workflow modules), then run the starter generation end-to-end for ALL tables and print an end-to-end run summary.

ACCEPTANCE CHECKLIST:  
\[ \] InventoryPlan versions: baseline version for every line; new versions only after approval — verified by a test that a rejected/pending change produces no new version  
\[ \] Production order impact propagation works: slip/shortfall → impact records + status changes  
\[ \] Severity computed from a documented function  
\[ \] Notifications go to correct recipients by role and trace to source entities  
\[ \] trace() helper returns a full chain for sample notifications  
\[ \] Event log rows written for plan updates, impacts, and notifications  
\[ \] Starter dataset now covers all 10 entities end-to-end

COMMIT MESSAGE: "feat: projected supply versions, downstream production impacts, and traceable notifications"

AI output note: Added inventory plan versioning, downstream production impact, and role-targeted notifications.

---

## Prompt 10 — Derived values &amp; reconciliation, Generation Step 6 (verbatim)

Continue the supplier-ack-system project. New task: enforce the derived-value and reconciliation discipline (Generation Step 6 of the problem statement) across the whole dataset. From now dont take much time, take 10-15mins max.

"Calculate derived values (totals, balances, scores, statuses and dates) from source records rather than generating them independently."

TASK 1 — Build src/supplier\_ack/rules/derived.py as a single derived-attribute library used by BOTH the generator and the validation suite:

- PO total\_amount = Σ line\_total of its POLines
- Acknowledgement deltas (qty/price/date) recomputed from source columns
- Acknowledgement status derivation: full\_accept / partial\_accept / full\_reject / revised, from accepted vs requested
- PromiseDate derived flags: is\_late (vs requested date), slip\_days
- ChangeRequest derived fields: delta\_abs, delta\_pct, required\_approval\_level (from thresholds)
- InventoryPlan derived: latest\_approved\_version per line (via plan version ordering + approval joins)
- ProductionOrder derived: at\_risk flag, shortfall\_qty (allocated − projected), delay\_days
- Supplier derived scores: ack\_rate, on\_time\_promise\_rate, avg\_slip\_days — recomputed from the actual acknowledgement rows
- Notification derived: open\_impact\_count per PO

TASK 2 — Reconciliation engine: a function reconcile(dataset) that recomputes every derived value from raw sources and asserts equality with stored values, returning a per-entity reconciliation report (checked\_count, mismatch\_count, sample mismatches). Wire it into the generator as a post-generation step so the generator cannot ship an internally inconsistent dataset.

TASK 3 — Arithmetical invariants to enforce (add to the library):

- accepted + rejected = requested per acknowledged line
- line\_total = qty × unit\_price everywhere
- PO total = Σ line totals
- InventoryPlan latest version quantity/dates equal the approved acknowledgement promise
- Production order allocated ≤ projected supply for confirmed orders (violations allowed only for at\_risk orders — document this)
- Every event-log state change for an entity matches that entity's stored lifecycle transitions

TASK 4 — Add a "status consistency" rule per the acceptance criteria ("acknowledgement status is consistent"): the derived ack status must agree with the stored ack status; write unit tests for the derivation function including boundary cases (accepted = 0, accepted = requested, rounding).

Run the starter dataset through reconcile() and print the reconciliation report — it must show zero mismatches before anomaly injection (anomalies come next).

ACCEPTANCE CHECKLIST:  
\[ \] derived.py library exists and is the single source of truth for derived values  
\[ \] Generator calls reconcile() after generation; zero mismatches on clean starter data  
\[ \] All 6 invariant groups enforced and unit-tested  
\[ \] Ack status derivation tested at boundaries  
\[ \] Supplier scores recomputed from data, not generated

COMMIT MESSAGE: "feat: derived-value library and reconciliation engine with zero-mismatch gate"



AI output note: Centralized derived-value rules and wired reconciliation/status consistency checks into generation.

---

## Prompt 11 — Labelled anomaly injection &amp; ground truth, Steps 5 &amp; 7 (verbatim)

Continue the supplier-ack-system project. New task: inject the four required labelled edge cases and produce the separated ground-truth file (Generation Steps 5 and 7 of the problem statement).

REQUIRED EDGE CASES — inject each in a controlled, documented way, AFTER valid baseline generation:

1. UNAPPROVED\_CHANGE\_UPDATES\_PLAN: an InventoryPlan version row exists whose source links to a ChangeRequest that has NO approved Approval. Exact counts from config (e.g., 25 full-scale, 5 starter).
2. ACK\_WRONG\_PO\_LINE: acknowledgement lines referencing a po\_line\_id that does not belong to the referenced PO (cross-PO line reference), plus a variant referencing a non-existent line id. Keep the row with an issue\_type label rather than "silently corrupting unrelated rows" — label it, do not randomize other data around it.
3. PROMISE\_DATE\_BEFORE\_ORDER\_DATE: PromiseDate rows where promise\_date &lt; po.order\_date (logically impossible).
4. STALE\_REVISION\_OVERWRITE: an older revision (lower revision\_no, earlier timestamp) appears as the current/latest version — e.g., the latest InventoryPlan version or the effective promise points to an older revision while a newer revision exists.

DESIGN RULES:

- Generate valid baseline records first, then inject labelled edge cases as a separate pipeline stage.
- Each injected row carries issue\_type from the four-type enum and a boolean ground\_truth flag; normal rows are NULL/False.
- Add valid boundary cases: accepted\_qty = requested\_qty, slip exactly equal to threshold days, and price delta exactly at ±threshold, labelled boundary=True.
- Injection is deterministic under the seed.
- Produce data/generated/ground\_truth.csv and ground\_truth.json with expected decisions from documented rules, plus expected approval outcomes for every change request and expected status for every impacted production order.
- Never leak ground\_truth/issue\_type into input/export tables. Strip them from exported entity CSVs and validate this automatically; retain them only in internal generator state and separate ground-truth files.

ACCEPTANCE CHECKLIST:  
\[ \] All four anomaly types injected at configured counts, deterministic under seed  
\[ \] Exact threshold boundary cases included  
\[ \] ground\_truth.csv and ground\_truth.json contain expected decisions  
\[ \] Exported input files have no ground\_truth/issue\_type leakage  
\[ \] Injection stage separate from baseline generation  
\[ \] Each anomaly documented in docs/decisions.md

COMMIT MESSAGE: "feat: labelled anomaly injection and separated ground-truth files with leakage checks"

---

AI output note: Added four controlled anomaly classes, separate ground truth, and input-label leakage checks.

---

## Prompt 12 — Validation suite, Generation Step 8 (verbatim)

Continue the supplier-ack-system project. New task: implement the full validation suite (Generation Step 8 of the problem statement) as src/supplier\_ack/validation/ with a CLI command: python -m supplier\_ack.cli validate --dataset data/generated/

VALIDATE ALL OF THESE — each validator returns (check\_name, status PASS/FAIL, checked\_rows, failure\_count, sample\_failures):

1. Primary-key uniqueness: every entity's PK unique across its table
2. Foreign-key integrity: every FK references an existing parent row — EXCEPT deliberately injected anomalies; the validator must distinguish "known-labelled violation" (present in ground truth) from "unknown violation" (a bug). Known violations: report as EXPECTED\_ANOMALY, unknown ones: FAIL.
3. Allowed enums: every status/type/severity/reason column matches its data-dictionary enum
4. Date ordering: order\_date ≤ response\_timestamp ≤ promised processing; promise\_date ≥ order\_date except labelled anomalies; response\_due\_date ordering; production required\_by ≥ planned\_start; effective dates consistent
5. Arithmetic reconciliation: the Prompt 10 invariants (accepted+rejected=requested; qty×price=total; PO total = Σ lines; plan version = approved promise)
6. Lifecycle transitions: every event-log state change is a legal transition per the Prompt 3 state machines; entity current state = last legal event state
7. Duplicate checks: no duplicate (po\_id, revision\_no) acknowledgements; no duplicate notification ids; no duplicate bridge rows
8. ID format checks: every id matches its regex convention; every child id embeds the exact parent id
9. Revision-history checks (acceptance criteria "revision history is preserved"): for every multi-revision ack, all revisions exist as rows, revision\_no is contiguous, superseded\_by chains are intact and acyclic, and the newest revision is the effective one — EXCEPT the STALE\_REVISION\_OVERWRITE labelled rows
10. Approval-before-apply check (acceptance criteria "only approved changes affect plans"): every InventoryPlan version whose source is a change/ack has an approved Approval at the required level — EXCEPT the UNAPPROVED\_CHANGE\_UPDATES\_PLAN labelled rows
11. Downstream-impact check (acceptance criteria "downstream impact is identified"): every approved slip/shortfall change with conflicting production orders has an impact record and a notification
12. Acknowledgement-status consistency (acceptance criteria "acknowledgement status is consistent"): derived status equals stored status everywhere
13. Ground-truth coverage: every ground\_truth record id exists in the dataset; every labelled anomaly in the dataset exists in ground truth (bidirectional check)
14. Leakage check: no ground\_truth/issue\_type columns in exported input files

OUTPUT: a validation\_summary.json with every check's result plus overall PASS/FAIL (FAIL only on unknown violations), and a human-readable validation\_report.md. Wire the validator into the generate command as a post-step: generation fails loudly on unknown violations.

Also write tests/test\_validation.py: unit tests per validator using tiny fixture datasets containing one deliberate violation of each kind, asserting each validator catches exactly its violation.

ACCEPTANCE CHECKLIST:  
\[ \] All 14 validation groups implemented and runnable via one CLI command  
\[ \] Known/labelled anomalies reported as EXPECTED\_ANOMALY, unknown violations FAIL  
\[ \] validation\_summary.json + validation\_report.md produced  
\[ \] The 4 acceptance criteria from the problem statement each have a dedicated validator  
\[ \] tests/test\_validation.py proves each validator catches its violation type  
\[ \] Full-scale validation completes and passes

COMMIT MESSAGE: "feat: 14-group validation suite distinguishing labelled anomalies from unknown violations"

AI output note (reconstructed from the recorded deliverable output): Added the 15-check validation suite distinguishing labelled (expected) anomalies from unknown violations, with ground-truth-aware reporting.

---

## Prompt 13 — Export pipeline &amp; provenance, Generation Step 9 (verbatim)

Continue the supplier-ack-system project. New task: implement the export pipeline (Generation Step 9 of the problem statement).

EXPORT FORMATS — from one dataset, produce all three:

1. CSV: one file per entity (10+ files including bridge tables and the event log) in data/generated/csv/, plus ground\_truth.csv. UTF-8, header row, ids byte-identical across files.
2. JSON: data/generated/json/ — one file per entity as an array of records, PLUS a master manifest (see below), plus ground\_truth.json
3. SQL seed data: data/generated/sql/seed.sql — CREATE TABLE statements (with FK constraints) + INSERT statements for every table, loadable into a fresh SQLite DB in one command; plus a .db file produced directly. Verify by loading seed.sql into an empty SQLite database and running the validation suite against it.

ALSO EXPORT (the documentation bundle):

- README.md updates: how to run the generator (exact command with --seed 20261022 --scale full), expected runtimes, disk footprint, how to validate, how to regenerate
- docs/schema.md and docs/data\_dictionary.md refreshed to final state
- data/generated/manifest.json — the SOURCE MANIFEST: generator version, git commit hash, seed, scale, config snapshot, per-table row counts, per-file SHA-256 checksums, generation timestamp, dependency versions
- validation\_summary.json and validation\_report.md from Prompt 12
- A starter-dataset bundle in data/samples/ small enough to commit to git (so reviewers can inspect data without regenerating)

PUBLIC DATA GUIDANCE / LAWFUL USE:

- State that all data is fully synthetic; no external datasets are used
- Document the schema-inspiration basis (standard procurement/acknowledgement concepts) without copying any proprietary schema
- Include a section: "If external data were used, we would record: source URL, dataset/version, retrieval date, license/terms, attribution, transformations, fields discarded" — with the rule that only legally redistributable data would be used and no confidential/personal information is included (supplier and actor names are synthetic; state this explicitly)
- Confirm the repo contains no secrets or credentials (add a check to the validation suite: scan for API-key-looking strings in committed files)

CLI: python -m supplier\_ack.cli export --dataset data/generated/ --formats csv,json,sql

ACCEPTANCE CHECKLIST:  
\[ \] CSV, JSON, and SQL exports all generated from the same dataset with consistent ids  
\[ \] seed.sql loads into an empty SQLite DB which passes the validation suite  
\[ \] manifest.json with row counts + SHA-256 checksums + seed + config snapshot  
\[ \] README documents the exact regeneration command  
\[ \] docs/provenance.md covers the lawful-use guidance fully  
\[ \] Starter bundle committed under data/samples/  
\[ \] Secret-scan check passes

COMMIT MESSAGE: "feat: CSV/JSON/SQL export pipeline, source manifest, and provenance documentation"

---

AI output note: Added CSV/JSON/SQL/SQLite exports, manifests, checksums, and provenance artifacts.

---

## Prompt 14 — Reproducibility harness, Generation Step 10 (verbatim)

Continue the supplier-ack-system project. New task: implement the reproducibility demonstration (Generation Step 10 of the problem statement): "Regenerate twice with the same seed and compare row counts/checksums to demonstrate reproducibility."

TASK 1 — Add a CLI command: python -m supplier\_ack.cli verify-reproducibility --seed 20261022 --scale starter  
It must:

1. Generate the dataset into run1/.
2. Generate it AGAIN into run2/ with the same seed and config.
3. Compare per-table row counts, per-file SHA-256 checksums, per-column value checksums (e.g., hash of sorted values), summary statistics (means to 10 decimal places).
4. Also demonstrate the COUNTER-PROPERTY: generate run3/ with a different seed and show checksums DIFFER (proves the seed actually drives the output, not accidentally-cached results).
5. Emit docs/reproducibility\_report.md with a table: table\_name, rows\_run1, rows\_run2, checksum\_run1, checksum\_run2, match YES/NO, plus the run3 divergence table, plus exact commands used and environment (Python version, dependency versions).

TASK 2 — Also verify ID determinism specifically: same seed → same PO-2026-000001 has identical content in both runs; different seed → different content. Show 3 concrete examples in the report.

TASK 3 — Register reproducibility as a pytest test (marked slow) that runs the starter-scale double-generation and asserts byte-identical outputs.

TASK 4 — Ensure the event log is also deterministic: same event ids, same timestamps, same ordering. (If you use timestamps: derive them deterministically from the seeded rng and the entity dates — NOT from wall-clock time. Wall-clock may appear ONLY in the manifest generation\_timestamp, never inside the data.)

Run the full-scale double-generation too and record results in docs/reproducibility\_report.md.

Acceptance: starter CLI test; same-seed byte-identical outputs; different-seed output differs; complete report; no wall-clock time in data; full-scale reproducibility demonstrated.

Also diagnose and fix the previous timeout in the coverage test module's subprocess/reproducibility section.

COMMIT MESSAGE: "feat: reproducibility harness with double-generation checksum comparison and report"

AI output note: Added same-seed checksum comparison, different-seed counter-checks, and reproducibility reporting.

---

## Prompt 15 — Runtime workflow engine (verbatim)

Continue the supplier-ack-system project. New task: build the RUNTIME WORKFLOW ENGINE — the "working solution for this end-to-end workflow" beyond static data generation. While the generator simulates history, the engine must be able to process NEW events live: python -m supplier\_ack.cli workflow run --db data/generated/app.db

ARCHITECTURE:

- Event-driven processing: load a SQLite DB created from the generator's seed data; then accept a stream of new input events (JSON event files: ack\_submitted, promise\_updated, change\_requested, approval\_decision, silence\_timeout) and process them through the same rules library (rules/thresholds.py, rules/derived.py) used by the generator — ONE implementation, reused by both. This is a key design point: generator and runtime share the rule code.
- Every processed event: writes the entity state change, writes an entity\_event row (append-only), evaluates the rule chain, and produces outcomes.

RULE CHAIN per event (mirroring the business logic exactly):

1. ack\_submitted → validate references → compute accepted/rejected/partial status → compare with requested values → compute deltas → create change requests where thresholds are crossed → route approvals (planner vs operations manager per thresholds) → DO NOT touch the InventoryPlan yet
2. approval\_decision → if approved at the required level → create a new InventoryPlan version (only now!) → propagate downstream: evaluate production order conflicts → create impact records → update production order statuses → generate notifications to affected planners and roles
3. promise\_updated with an earlier date than order date → exception path: reject the promise, mark the acknowledgement exception, notify the planner, record the issue (this is a deliberate runtime exception path)
4. change\_requested for an unapproved change → any attempt to update the plan is refused by the engine with a documented error event (runtime enforcement of "only approved changes affect plans")
5. silence\_timeout → auto-escalation change + chase notification
6. A late-arriving OLD revision (revision\_no lower than the current latest) → engine refuses to make it effective (stale-revision guard) but records it (history preserved)

EXCEPTIONS &amp; DECISIONS EXPOSURE:

- Maintain a live exception queue: every exception (invalid references, unapproved-plan-update attempts, impossible dates, stale revisions) becomes a queryable exception record with severity, rule id, entity trace
- Maintain a decision log: every threshold decision (auto-approve/escalate/reject) with the rule that fired, the values compared, and the approver

CLI commands:

- workflow run --db X --events events.json : process an event file, print a processing summary (events processed, changes raised, approvals routed, plans updated, impacts, notifications, exceptions)
- workflow status --db X --po PO-2026-000042 : full status of one PO: current ack, effective promise, open changes, plan versions, impacts, notifications, event timeline
- workflow exceptions --db X : list the exception queue
- workflow decisions --db X : list the decision log

Create a demo event file (data/samples/demo\_events.json) exercising every event type INCLUDING the 4 runtime exception paths, and run it in the README as the "verify key behavior" walkthrough.

ACCEPTANCE CHECKLIST:  
\[ \] Runtime shares the rules library with the generator (no duplicated threshold logic)  
\[ \] All 6 event types processed; all 4 runtime exception paths produce exception records  
\[ \] Plan updates strictly gated on approval — engine refuses otherwise (tested)  
\[ \] Stale revision guard works (tested)  
\[ \] Exception queue + decision log queryable via CLI  
\[ \] workflow status shows a complete traceable timeline for a sample PO  
\[ \] demo\_events.json walkthrough documented in README

COMMIT MESSAGE: "feat: event-driven workflow engine with shared rules, exception queue, and decision log"

AI output note (reconstructed from the recorded deliverable output): Added the event-driven runtime workflow engine with exception queue, decision log, stale-revision guard, and unapproved-plan-update refusal.

---

## Prompt 16 — Metrics, decisions &amp; exception reporting (verbatim)

Continue the supplier-ack-system project. New task: produce the MEASURABLE OUTPUTS and expose key decisions and exceptions (the objective: "expose key decisions and exceptions, preserve traceability, and produce measurable outputs").

TASK 1 — src/supplier\_ack/metrics/ with a metrics engine computing, from the generated dataset (or a runtime DB):  
SUPPLIER METRICS: ack rate, on-time promise rate, avg/median slip days, partial acceptance rate, silence rate, revision rate — per supplier and overall  
CHANGE METRICS: changes by type, auto-approved vs escalated vs rejected counts and %, approval turnaround (decision\_time − request\_time) by approver level, rejection reasons  
SCHEDULE IMPACT METRICS: production orders at risk count, rescheduled count, total delay days, shortfall quantities, severity distribution  
SUPPLY METRICS: projected vs requested supply coverage by week (a projected-receipts timeline), plan version churn per line  
EXCEPTION METRICS: exceptions by type and severity, open vs resolved  
WORKFLOW METRICS: POs fully acknowledged / partially / silent; median time from ack to plan update; notification volume by type and recipient role

TASK 2 — Reports (CLI: python -m supplier\_ack.cli report --dataset data/generated/ --out reports/):

- reports/summary\_report.md — executive summary for the OPERATIONS MANAGER: headline KPIs with interpretation text generated from thresholds (e.g., "Supplier X's on-time rate (62%) is 2σ below the portfolio — flagged")
- reports/exception\_report.csv/md — every exception with its full trace chain (exception → entity → PO → supplier), for the LOGISTICS ANALYST
- reports/supplier\_scorecard.csv — per-supplier scores for the PLANNER
- reports/impact\_report.csv — production order impacts for the CARRIER/WAREHOUSE OPERATOR view (what ships when, what moved)
- reports/decision\_log.csv — every approval decision with rule and values compared

TASK 3 — Data quality / evaluation report addressing the problem's evaluation focus (a)–(g) directly:  
reports/data\_quality\_report.md with one section per evaluation dimension:  
(a) realistic distributions and meaningful variation — show distribution stats/plots for key numeric fields  
(b) consistent IDs and valid joins — cite validation results  
(c) dependency/lifecycle consistency across entities — cite lifecycle validator results  
(d) correct derived values and reconciliation — cite the reconciliation report  
(e) normal, boundary, failure and exception coverage — counts per category including the 4 anomaly types and boundary cases  
(f) separate ground truth — describe ground\_truth structure and the leakage check  
(g) fixed-seed reproducibility — cite the reproducibility report

TASK 4 — Visualization (matplotlib, saved to reports/figures/): supplier slip-day distribution, ack status breakdown pie, changes by type and decision, projected vs requested supply timeline, exception counts by type. Reference figures from the markdown reports.

Run on the full-scale dataset; all reports must be generated and committed for the starter dataset.

ACCEPTANCE CHECKLIST:  
\[ \] All 6 metric groups computed from the data (no invented numbers)  
\[ \] 5 report files + data\_quality\_report.md generated  
\[ \] data\_quality\_report.md explicitly answers (a)–(g) with cited evidence  
\[ \] Figures generated and referenced  
\[ \] Every actor persona has a report aimed at them (ops manager, logistics analyst, planner, warehouse operator)  
\[ \] Reports regenerate deterministically with the dataset

COMMIT MESSAGE: "feat: metrics engine, persona-targeted reports, and (a)-(g) data-quality evaluation report"

AI output note (reconstructed from the recorded deliverable output): Added persona-specific reports and the data-quality evaluation report.

---

## Prompt 17 — Anomaly detection &amp; evaluation against ground truth (verbatim)

Continue the supplier-ack-system project. New task: build the ANOMALY DETECTION module and evaluate it against the ground truth — this delivers "meaningful evaluation metrics" and proves the four required edge cases are detectable by the solution itself (not just labelled).

TASK 1 — src/supplier\_ack/metrics/detectors.py: rule-based detectors for the four anomaly classes, written as pure functions over the dataset:

1. detect\_unapproved\_plan\_updates(): InventoryPlan versions whose source change lacks a required-level approved Approval
2. detect\_wrong\_line\_refs(): ack lines whose po\_line\_id does not belong to the ack's po\_id, or references non-existent lines
3. detect\_impossible\_promise\_dates(): promise\_date &lt; po.order\_date
4. detect\_stale\_revision\_effective(): effective/current promise or plan version pointing to a revision older than the latest existing revision  
Plus a fifth detector: detect\_boundary\_cases() — rows exactly at each threshold (report only, not anomalies).

TASK 2 — Evaluation harness: run all detectors on the full dataset, join detections against ground\_truth.json, and produce reports/detection\_report.md with a confusion matrix per anomaly class: TP, FP, FN, TN, precision, recall, F1, and overall accuracy. Because detectors are rule-based from the same documented rules, they should reach perfect scores on the injected anomalies — if any anomaly is missed, that is a bug in the detector or the generator: fix it and document what was wrong in docs/decisions.md.

TASK 3 — Detection must use ONLY input features (entity tables), NEVER ground\_truth columns — assert this in code (the ground truth file is loaded only by the evaluator, not the detectors). This directly honors "never leak it into input features."

TASK 4 — CLI: python -m supplier\_ack.cli detect --dataset data/generated/ — prints detections and writes the report. Add a pytest that runs detection on the starter dataset and asserts perfect precision/recall against its ground truth.

ACCEPTANCE CHECKLIST:  
\[ \] 4 detectors + boundary reporter implemented as pure functions  
\[ \] detection\_report.md with per-class confusion matrices, precision/recall/F1, accuracy  
\[ \] Perfect detection achieved on all 4 classes (or bugs found, fixed, and documented)  
\[ \] Detectors never read ground-truth columns — enforced and tested  
\[ \] pytest detection test passes at starter scale

COMMIT MESSAGE: "feat: rule-based anomaly detectors with precision/recall evaluation against ground truth"

AI output note (reconstructed from the recorded deliverable output): Added rule-based detectors for the four anomaly classes, evaluated against the separated ground truth.

---

## Prompt 18 — Unified CLI, demo script &amp; error-handling audit (verbatim)

Continue the supplier-ack-system project. New task: unify and polish the CLI so another person can install, run, and verify everything (the YottaFlex guideline: "Include clear steps so another person can install dependencies, configure the project, run it, and verify key behavior").

TASK 1 — Final CLI surface under python -m supplier\_ack.cli (and a console script entry point supplier-ack):  
  generate      --scale starter|full --seed N --config PATH   (runs generation + reconcile + validation)  
  export        --formats csv,json,sql --out PATH  
  validate      --dataset PATH  
  verify-repro  --seed N --scale starter|full  
  workflow run / status / exceptions / decisions --db PATH  
  report        --dataset PATH --out reports/  
  detect        --dataset PATH  
  doctor        (environment check: python version, dependency versions, disk space estimate, seed sanity)  
  --help everywhere; every command documented in README with copy-pasteable examples.

TASK 2 — One-command demo: makefile or script scripts/demo.sh that runs, at starter scale: generate → export → validate → detect → report → workflow demo events, and prints a clear pass/fail summary at each step. A reviewer must be able to run this single script and watch the whole system work end to end.

TASK 3 — Ship a committed demo database: build data/samples/demo.db (starter scale, seed 20261022) via the export pipeline, plus demo\_events.json, so the workflow CLI is instantly explorable without any generation step.

TASK 4 — Error handling audit: every CLI command must fail with a helpful message (exit code ≠ 0) on: missing config, bad seed type, unknown scale, missing dataset, corrupt CSV, SQLite without FK pragma. No stack traces for user errors.

TASK 5 — Performance sanity: at full scale (10,000 POs / 15,000 events), measure and record in docs/decisions.md the runtime and peak memory of generate/validate/export; optimize obvious bottlenecks (vectorize pandas, avoid row-by-row loops where possible) so the full run completes in a reasonable time on a laptop (target: under \~10 minutes total; document actual numbers).

ACCEPTANCE CHECKLIST:  
\[ \] All commands work with --help and documented examples  
\[ \] scripts/demo.sh runs the entire system at starter scale with pass/fail output  
\[ \] demo.db + demo\_events.json committed and loadable  
\[ \] User errors produce helpful messages with non-zero exit codes  
\[ \] Full-scale performance measured and documented, no pathological runtimes  
\[ \] README updated to final form with install → configure → run → verify for every path

COMMIT MESSAGE: "feat: unified CLI, one-command demo script, demo database, and error-handling audit"

AI output note (reconstructed from the recorded deliverable output): Added the unified CLI, one-command demo script, committed demo database, and error-handling audit.

---

## Fix request — cross-platform test paths &amp; dependency declarations (verbatim)

Fix request before I continue. My local machine is Windows, and 2 tests fail when I run pytest:

tests/test\_workflow\_engine.py::test\_pending\_change\_cannot\_update\_plan  
tests/test\_workflow\_engine.py::test\_stale\_revision\_is\_recorded\_but\_not\_inserted

Both fail with: FileNotFoundError: \[Errno 2\] No such file or directory: '\\tmp\\test-pending-plan-gate.json'  
The test helper \_write\_event writes to a hardcoded "/tmp/..." path, which does not exist on Windows.

Fix all hardcoded /tmp paths in the test suite to use a cross-platform temp directory (tempfile.gettempdir() or pytest's tmp\_path fixture).

Also: matplotlib and tabulate are imported by the code but were NOT declared in pyproject.toml dependencies — I had to install them manually. Add them to the dependency list so a clean install works everywhere.

Commit message: "fix: cross-platform temp paths in workflow tests and declare plotting dependencies"

AI output note (reconstructed from the recorded deliverable output): Fixed the hardcoded /tmp paths in the workflow tests via a cross-platform temp directory, declared matplotlib and tabulate as project dependencies, and added a dependency-presence regression test.

---

## Prompt 19 — Complete automated test suite, new chat with context handover (verbatim)

PROJECT CONTEXT — read this fully before doing any work.

This project continues from a previous conversation that hit its length limit. I have attached the current complete repository ZIP in this chat. Extract it and treat it as the single source of truth — extend the existing code, never rebuild from scratch. If anything I say conflicts with the attached code, the CODE wins and you flag the conflict to me.

PROJECT: a working, end-to-end solution for "manage supplier acknowledgements, promised dates, quantity changes and downstream schedule impacts" — exposing key decisions and exceptions, preserving traceability, and producing measurable outputs. Actors: Supplier, Planner, Carrier/Warehouse Operator, Logistics Analyst, Operations Manager. This is an individual submission for the YottaFlex AI recruitment challenge.

TECH: Python 3.11+, pandas, SQLite, argparse CLI, pytest. Layout: src/supplier\_ack/ with ids.py, schema.py, cli.py, reproducibility.py and packages generators/, rules/, events/, validation/, exports/, metrics/, workflow/; config/generator\_config.yaml; tests/; docs/ (data\_dictionary, schema, decisions, provenance); ai/prompt\_history.md; data/samples/ (committed starter bundle + demo.db + demo\_events.json); data/generated/ (gitignored).

ALREADY BUILT AND WORKING — verify against the code, do not redo:

- 10 entities (Supplier, PurchaseOrder, POLine, Acknowledgement, PromiseDate, ChangeRequest, Approval, InventoryPlan, ProductionOrder, Notification) + bridge tables + append-only entity\_event log; complete data dictionary and SQLite DDL with FK constraints
- ID conventions: SUP-, PO-2026-NNNNNN, -LNN, ACK--NN (revisions), PD--NN, CHG--NNNNNN, APR--NN, NOT-2026-NNNNNN, IP--NN, PRO-2026-NNNNNN
- Seeded generator (fixed seed 20261022): starter 200 POs / 300 events, full 10,000 POs / 15,000 events; coverage mix (partial acceptance, date slips, price changes, supplier silence, multi-revision); derived values computed from sources with a reconciliation engine
- Config-driven approval thresholds (within-threshold → planner auto-approve; beyond → operations manager escalation); plan updates strictly gated on approval; downstream production-order impacts; traceable notifications to correct recipients by role
- Anomaly injection: 4 labelled edge cases (UNAPPROVED\_CHANGE\_UPDATES\_PLAN, ACK\_WRONG\_PO\_LINE, PROMISE\_DATE\_BEFORE\_ORDER\_DATE, STALE\_REVISION\_OVERWRITE) + boundary cases; separate ground\_truth.csv/json; no label leakage into input exports
- Validation suite: 15 checks distinguishing EXPECTED\_ANOMALY (known, labelled) from FAIL (unknown violations)
- Export pipeline: CSV + JSON + SQL seed + SQLite db + manifest with SHA-256 checksums + secret scan + provenance docs
- Reproducibility harness: same-seed double-generation checksum comparison + different-seed counter-test (verify-repro CLI command)
- Runtime workflow engine: event-driven processing on the SQLite db, exception queue, decision log, stale-revision guard, unapproved-plan-update refusal
- Rule-based anomaly detectors for the 4 anomaly classes, evaluated against ground truth with precision/recall
- Unified CLI (generate / export / validate / verify-repro / workflow run|status|exceptions|decisions / report / detect / doctor) with --help everywhere; scripts/demo.sh running 6 stages end-to-end (all PASS on my machine); committed demo database in data/samples/
- Test suite: 175 tests collected, 174 passing in one run (matplotlib and tabulate are declared dependencies; test temp paths are cross-platform — a hardcoded /tmp bug on Windows was already fixed)

KNOWN ISSUE TO FIX IN THIS TASK: the generate command's starter-scale default output directory is NOT data/generated — locally I had to pass --output-dir data/generated manually for tests to find data/generated/ground\_truth.csv. Fix the default so both scales write to data/generated.

ONGOING RULES:

- ai/prompt\_history.md in the repo already contains Prompts 1-18 verbatim plus my fix requests. Append EVERY new prompt I give you to that file, verbatim, in order.
- Keep the fixed seed 20261022 everywhere; never use wall-clock time inside generated data.
- Commit after each task with the commit message I provide.
- My machine is Windows — never use Unix-only paths like /tmp in code or tests.

Work on the repository I attached in this conversation (see the project context above). New task: complete the automated test suite (the problem asks: "Included any tests the problem asks for"; the FAQ says no test suite is mandatory but demonstration of verification is required — we exceed the bar).

TASK 0 — Fix the generate command's default output directory: both starter and full scales must write to data/generated by default, so `python -m supplier_ack.cli generate --scale starter` with no --output-dir produces data/generated/ground\_truth.csv. Add a test that runs generate with defaults and asserts that file exists.

TASK — finalize tests/ with full coverage of:

1. test\_ids.py — ID formats (already exists; extend to all 10 formats)
2. test\_schema.py — DDL executes; FK enforcement ON rejects bad inserts; bridge tables enforce composite uniqueness
3. test\_generators.py — starter-scale generation: row counts match config; all 8 coverage categories present; accepted+rejected=requested invariant; revision chains intact
4. test\_thresholds.py — every conditional rule: within/beyond threshold for price/date/quantity; escalation routing; silence escalation; can\_apply() gating (rejected → cannot apply)
5. test\_supply.py — plan updates ONLY after approval; baseline version per line; downstream impact propagation produces impact records and status changes; severity function boundaries
6. test\_notifications.py — correct recipient roles per event type; trace() returns full chain
7. test\_derived.py — every derived-value rule and the 6 invariant groups; ack status boundaries
8. test\_anomalies.py — each of the 4 anomaly types injectable deterministically; boundary cases at exact thresholds; ground truth bidirectional coverage; leakage check
9. test\_validation.py — each validator catches its violation (exists; extend)
10. test\_reproducibility.py — double-generation byte-identical at starter scale (slow-marked)
11. test\_workflow.py — runtime engine: all 6 event types; all 4 runtime exception paths; stale revision guard; unapproved-plan-update refusal
12. test\_detectors.py — perfect precision/recall on starter ground truth (exists; keep green)

Also:

- Add coverage measurement (pytest --cov) and record the final coverage % in docs/decisions.md with an honest note about any untested area
- One integration test marked e2e that runs scripts/demo.sh end-to-end and asserts the summary shows all-pass
- All tests must pass from a clean checkout with only: pip install -e .\[dev\]; pytest

Run the full suite; fix every failure; report the final pass count and coverage.

ACCEPTANCE CHECKLIST:  
\[ \] 12 test modules, all green  
\[ \] Coverage measured and documented  
\[ \] e2e integration test passes from clean checkout  
\[ \] The 4 acceptance criteria of the problem each covered by at least one test: revision history preserved; only approved changes affect plans; downstream impact identified; ack status consistent  
\[ \] pytest from clean checkout: 100% pass

COMMIT MESSAGE: "test: complete 12-module test suite covering rules, anomalies, workflow, and acceptance criteria"

AI output note: Added/finalized the test suite, default output-directory regression test, coverage configuration, and e2e demo test; full-suite completion was not verified in the constrained execution environment.

---

## Prompt 20 — Final documentation pass (verbatim)

Continue in the same repository as the previous task (the attached project). New task: final documentation pass (the YottaFlex guideline: "Make your reasoning visible — problem, assumptions, key decisions, trade-offs, testing approach, limitations, and how you know the solution works").

TASK 1 — README.md (final, complete):

- What the project does (map every sentence of the problem's objective to a system capability in a small table)
- Quickstart: install → demo script → expected output → how to verify
- Full workflow: generate starter/full, export, validate, detect, report, workflow CLI examples
- Repository layout with one-line explanation per directory
- Data generation section: fixed seed 20261022, scale parameterization, the 10-step generation pipeline summary
- Testing section: how to run tests, what they cover
- Performance section: measured runtimes and footprint

TASK 2 — docs/decisions.md (final, complete) — every design decision in one place, each with: the decision, the alternatives considered, the trade-off, and the reason. Must include at least: tech stack choice; SQLite vs other storage; generator/runtime shared rule library; supplier-silence modeling choice; revision history as full-row snapshots; threshold values chosen and why; approval escalation design; anomaly labelling vs silent corruption; APR id format choice; determinism strategy; derived-value library design. Also an explicit ASSUMPTIONS section (every assumption made where the problem statement was ambiguous) and a LIMITATIONS section (what is NOT built, e.g., no hosted demo, no auth, single-user CLI, SQLite scale ceiling) and NEXT STEPS.

TASK 3 — docs/verification.md — "how you know the solution works": a walkthrough mapping each problem requirement to its proof: which validation check, test, report, or CLI command demonstrates it. Include the four required edge cases with their detector outputs, the reproducibility checksums, and the acceptance criteria (revision history preserved; only approved changes affect plans; downstream impact identified; ack status consistent) each with its specific test name.

TASK 4 — Refresh docs/schema.md and docs/data\_dictionary.md to match the final implementation exactly (no drift between docs and code). Add a docs check to the test suite that parses the data dictionary tables and asserts every documented field exists in the schema module.

ACCEPTANCE CHECKLIST:  
\[ \] README complete: a new user can install, run, and verify with copy-paste commands  
\[ \] Every problem-statement sentence mapped to a capability  
\[ \] decisions.md covers ≥11 decisions with alternatives and trade-offs, plus assumptions, limitations, next steps  
\[ \] verification.md maps every requirement (including 4 edge cases + 4 acceptance criteria) to concrete proof  
\[ \] Docs/code drift check test passes  
\[ \] All documents regenerated and consistent

COMMIT MESSAGE: "docs: final README, decision log with trade-offs, assumptions, limitations, and requirement-to-proof map"

AI output note: Updated README, design decisions, verification mapping, schema/data dictionary documentation, and added a dictionary-to-schema drift test; the full test suite remained unverified.

---

## Prompt 21 — AI-use transparency, repo hygiene &amp; submission readiness (verbatim)

Continue in the same repository as the previous task. Final task: AI-use transparency and submission readiness (YottaFlex requires prompt history and honest AI disclosure; the FAQ requires no secrets and a public repo).

TASK 1 — Finalize ai/prompt\_history.md: it must contain EVERY prompt I gave you during this project — Prompts 1-18 from the earlier phase (they should already be in the file from the previous conversation), my fix requests (the /tmp Windows fix and the dependency declarations), and Prompts 19, 20, and 21 — verbatim and in order, with a one-line note after each of what the AI produced. Verify the file is complete against the repository history; if any earlier prompt is missing or truncated, tell me and I will provide it verbatim. Add a note on any tool that could not export prompts and how the record was kept (per FAQ item 6).

TASK 2 — Finalize ai/ai\_disclosure.md with these sections:

- WHERE AI ACCELERATED THE WORK: (boilerplate, schemas, test scaffolding, docs structure) — be specific
- WHERE I RELIED HEAVILY ON AI: be honest about which parts you reviewed most lightly
- WHAT I PERSONALLY REVIEWED, CHANGED, OR VALIDATED: the threshold rules and their values, the data model cardinalities, the anomaly labelling design, the approval-gating logic — describe the actual verification you did (ran the validator, ran the tests, checked sample rows by hand, traced notifications end-to-end)
- OWNERSHIP statement: confirm you can explain the core logic, key design choices, dependencies, and limitations (per FAQ item 7)
- A list of any external snippets used with attribution and license status (per FAQ item 10)

TASK 3 — Repo hygiene audit:

- Secret scan: no credentials/API keys/tokens anywhere (run a scan; also verify .gitignore excludes data/generated, caches, virtualenvs)
- No personal/sensitive data; all names synthetic — state this in README
- License file added (MIT)
- requirements.txt/pyproject.toml pinned and installable
- Check the repo renders well on GitHub: README headings, tables aligned, Mermaid diagrams render, no broken relative links

TASK 4 — Submission checklist file (docs/submission\_checklist.md) with ticked boxes for every YottaFlex requirement:

- [ ] Working executable code with install/run/verify steps (guideline 01)
- [ ] Public GitHub repository with meaningful commit history (guideline 02)
- [ ] Prompt history included and AI disclosure written (guideline 03)
- [ ] Reasoning visible: assumptions, decisions, trade-offs, testing, limitations (guideline 04)
- [ ] Dedicated new public repository; submit the link from the recruitment email address (FAQ 3)
- [ ] Code + prompt history + supporting artifacts in a clearly identifiable directory (FAQ 4)
- [ ] No imported complete solution; only standard dependencies + attributed snippets (FAQ 10)
- [ ] No secrets/sensitive data; safe sample data; setup explained in README (FAQ 12)
- [ ] Latest version pushed before the 72-hour deadline (FAQ 2)

TASK 5 — Final gate: from a CLEAN CLONE in a fresh directory, run: pip install -e .; scripts/demo.sh; pytest. Everything must pass. Then git push and give me the final repository state summary: total commits, file count, dataset stats at full scale, and any known limitations to mention in the submission email.

ACCEPTANCE CHECKLIST:  
\[ \] prompt\_history.md complete and verbatim  
\[ \] ai\_disclosure.md honest and specific (acceleration vs heavy reliance vs personal validation)  
\[ \] Secret scan clean; license added; gitignore correct; GitHub rendering verified  
\[ \] submission\_checklist.md covers every guideline and FAQ item  
\[ \] Clean-clone install + demo + pytest all pass  
\[ \] Final push done; ready to submit the repo link

COMMIT MESSAGE: "docs: AI disclosure, prompt history, submission checklist, and final repo hygiene"

AI output note: Added an explicit AI-use disclosure, MIT license, synthetic-data note, submission checklist, and this verbatim copy of Prompt 21; prompt-history completeness remained blocked by earlier source prompts that were not present verbatim in the tracked record.

---

## Record-keeping note

The prompt record is maintained as a plain Markdown file committed with the project; no automated prompt-export tool was available, so prompts were appended to this file as they were sent. A completeness audit before submission found two defects introduced when the work moved to a second conversation: Prompts 1–4 appeared twice, and Prompts 12 and 15–18 plus the fix request were missing. This final version was restored by the candidate from the original prompt records: the duplicated block was removed, the missing prompts were re-inserted verbatim in chronological order, and the one-line output notes marked "(reconstructed from the recorded deliverable output)" were summarized from the recorded deliverables of those tasks. All prompt texts are verbatim as sent.