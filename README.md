# Supplier Acknowledgement Management System

## Purpose

A locally runnable, traceable workflow for managing supplier purchase-order acknowledgements, promised-date changes, quantity changes, approval exceptions, and downstream schedule impacts. The data model includes Supplier, Planner, Carrier/Warehouse Operator, Logistics Analyst, and Operations Manager roles, and retains the provenance needed to measure decisions and exceptions.

This repository includes the complete field dictionary and relational SQLite schema, deterministic ID factory, seeded master-data generator, coverage-driven acknowledgement/promise-date revisions, rule-based change requests and append-only approvals, projected supply versions gated by approval, downstream production-order impacts, traceable notifications, and supplier-silence chases.

## Requirements

- Python 3.11 or newer
- `pip`
- Git (optional)

## Install

From the repository root:

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Generate seeded synthetic data and coverage scenarios

The starter and full datasets use the same generator code. The scale selects only parameters in `config/generator_config.yaml`; the seed makes runs reproducible. Generation now includes master data, acknowledgement revisions, line-level promise dates, rule-driven price/date/quantity change requests, append-only multi-level approval decisions, versioned InventoryPlans (only approved updates affect projection), ProductionOrders and allocation bridges, computed downstream impacts with severity bands, role-correct traceable notifications, overdue-silence chases, and coverage reports for both scales. The CLI also prints three example notification traces.

```bash
# Starter: 40 suppliers, 200 purchase orders, 2–6 lines per PO
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 20261022

# Full: 200 suppliers, 10,000 purchase orders, 2–6 lines per PO
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale full --seed 20261022

# Override the seed or output location
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 7 --output-dir /tmp/supplier-ack-output
```

Starter CSVs are written to `data/samples/`; full-scale CSVs are written to `data/generated/` (gitignored). Entity CSVs include `suppliers.csv`, `purchase_orders.csv`, `po_lines.csv`, `acknowledgements.csv`, `promise_dates.csv`, `change_requests.csv`, `approvals.csv`, `inventory_plans.csv`, `production_orders.csv`, `notifications.csv`, and the support bridges `production_order_line.csv`, `production_order_impact.csv`, and `notification_recipient.csv`, alongside reference masters. `silence_report.csv` contains overdue POs with no acknowledgement row. `coverage_report.csv` and `coverage_report.json` report observed counts and percentages for all eight required categories at both starter and full scales. `generation_summary.json` records row counts, event-budget reconciliation, distribution statistics, threshold-routing and approval-decision summaries, scale, and seed. Generated core entities are validated against `src/supplier_ack/schema.py` before exporting by default. `event_count` counts acknowledgement revision rows plus ChangeRequest rows; Approval rows and PromiseDate revision rows are separate dependent records.

## Verify

```bash
python -m pytest -q
python -m supplier_ack.cli --version
python -m supplier_ack.cli status
```

To verify deterministic output, rerun the same scale with the same seed and compare CSV files. Changing `--seed` changes sampled data but keeps scale counts and field contracts unchanged. The starter outputs are small and committed under `data/samples/`; full-scale outputs are intentionally excluded by `.gitignore`.

## Repository layout

```text
supplier-ack-system/
├── README.md
├── pyproject.toml
├── .gitignore
├── config/generator_config.yaml
├── src/supplier_ack/
│   ├── ids.py
│   ├── schema.py
│   ├── cli.py
│   └── generators/
│       ├── common.py
│       ├── suppliers.py
│       ├── reference_data.py
│       ├── purchase_orders.py
│       ├── po_lines.py
│       └── framework.py
├── tests/
├── data/samples/
├── data/generated/
├── docs/
└── ai/
```

## Technology choices

- **Python 3.11+:** approachable, typed implementation with a mature ecosystem; lower raw throughput than a compiled service but sufficient for challenge-scale synthetic data.
- **pandas:** schema-aligned tabular generation, CSV export, and summary statistics; memory use grows with full-scale row counts.
- **NumPy `Generator`:** an injected, seeded RNG produces reproducible synthetic distributions; keeping one RNG stream means changes in generation order can change subsequent samples, so module ordering is explicit.
- **SQLite:** free, built-in, serverless persistence with enforced foreign keys; concurrent writes are more limited than a client/server database.
- **argparse:** built-in CLI with no extra runtime framework; more manual than a dedicated CLI package but keeps dependencies small.
- **pytest:** readable regression tests for ID formats, schema constraints, and generation invariants; tests must evolve with business rules.

## Dataset validation (Generation Step 8)

Run the 14-group validator against exported CSVs and the separated ground-truth file:

```bash
python -m supplier_ack.cli validate --dataset data/generated/
```

The command writes `validation_summary.json` and `validation_report.md` into the dataset directory. Known violations that match a labelled ground-truth anomaly are reported as `EXPECTED_ANOMALY`; unlabelled/unknown violations are `FAIL`. Overall status is `PASS` when there are no unknown violations. `generate` invokes this validator after exporting and fails loudly if an unknown violation is found.

Validation groups cover primary keys, foreign keys, allowed enums, date ordering, arithmetic reconciliation, lifecycle transitions/current state, duplicates, ID conventions, revision history, approval-before-apply, downstream impacts, acknowledgement status consistency, ground-truth coverage, and input label leakage.

## Export, manifest, and reviewer bundle (Generation Step 9)

Export the canonical full-scale dataset into CSV, JSON, and SQLite SQL seed formats:

```bash
python -m supplier_ack.cli generate --config config/generator_config.yaml --seed 20261022 --scale full
python -m supplier_ack.cli export --dataset data/generated/ --formats csv,json,sql
python -m supplier_ack.cli validate --dataset data/generated/
```

`export` reads the same flat source CSV tables and writes one CSV per table under `data/generated/csv/`, JSON arrays under `data/generated/json/`, and `data/generated/sql/seed.sql` plus `seed.db`. The SQL file is a standalone SQLite script; it declares primary/foreign keys and temporarily disables FK enforcement while loading so deliberately labelled anomaly rows remain auditable. You can load it into an empty database with `sqlite3 fresh.db < data/generated/sql/seed.sql`. The exporter loads that exact script into a fresh SQLite database, checks table row counts, and runs the same ground-truth-aware validation suite against the imported rows. Expected labelled violations remain `EXPECTED_ANOMALY`; unknown violations fail the export.

`data/generated/manifest.json` records generator version, current git commit, seed/scale, config snapshot, per-table row counts, dependency versions, UTC generation timestamp, secret-scan result, and SHA-256 checksums and byte sizes for files present at export time (the manifest does not checksum itself). `validation_summary.json` and `validation_report.md` are produced by the validation step. A compact, reviewable starter dataset and validation outputs are tracked under `data/samples/`.

### Expected runtime and disk footprint

On a typical developer workstation, starter generation and validation generally take under a minute. Full-scale generation plus validation can take roughly 1–3 minutes depending on CPU and disk speed; export to all three formats is I/O-heavy and can take several additional minutes. Full-scale flat CSVs are approximately 130–150 MB in this environment; JSON and SQL seed exports and the SQLite database can add several hundred MB. Allow at least 1 GB free disk space for a full-scale all-format export. Actual timings and checksums are captured in the manifest for each run.

To reproduce from a clean checkout, install the project (`python -m pip install -e '.[dev]'`), then run the three commands above with the fixed seed and scale. The starter bundle can be inspected without running the full generator.


## Reproducibility demonstration

Run the seeded reproduction harness (this also regenerates the full-scale pair unless explicitly skipped):

```bash
python -m supplier_ack.cli verify-reproducibility --seed 20261022 --scale starter
```

The harness writes isolated CSV run snapshots under `.reproducibility/`, compares table row counts, every output file's SHA-256, sorted per-column value hashes, and numeric means to ten decimal places. It also checks deterministic IDs and event-log IDs/timestamps/order, then generates run 3 with a different seed to prove that the seed changes entity content. The report is written to `docs/reproducibility_report.md`. The generation API derives event timestamps from seeded entity dates; it does not use wall-clock timestamps in generated records. Use `--skip-full-scale` only for a focused local/test run.

## Runtime workflow engine (live event processing)

The offline generator creates a reproducible historical dataset; the runtime engine processes new events transactionally against SQLite while reusing `rules/thresholds.py` (`evaluate_threshold`, `required_approval_level`, `can_apply`, `computed_delta`) and `rules/derived.py` (`derive_ack_status`, `derive_promise_date`). It does not maintain a second copy of the business thresholds. Runtime audit timestamps are wall-clock timestamps for actual processing; generated historical business data remains deterministic.

Run a stream of events from the sample file. If `data/generated/app.db` does not exist, the engine initializes it from `data/generated/sql/seed.db` when present, otherwise it uses the committed starter seed `data/samples/sql/seed.db`:

```bash
python -m supplier_ack.cli workflow run --db data/generated/app.db --events data/samples/demo_events.json
python -m supplier_ack.cli workflow status --db data/generated/app.db --po PO-2026-000043
python -m supplier_ack.cli workflow exceptions --db data/generated/app.db
python -m supplier_ack.cli workflow decisions --db data/generated/app.db
```

`demo_events.json` exercises two new acknowledgement revisions, a threshold-based change request, a valid approval that creates an InventoryPlan version, an impossible promise date, an unapproved plan-update attempt, a supplier silence timeout, a late-arriving stale revision, and an invalid PO reference. Relative `promised_offset_days` and `offset_days` values let the sample derive dates from the chosen seed database rather than relying on one scale-specific date. The last four paths create queryable exception records. Event IDs are idempotency keys: replaying the same input event IDs is ignored rather than applying the event twice. The engine appends `entity_event` audit rows and retains runtime exceptions and threshold decisions in `runtime_exception` and `runtime_decision`.

Key safety guarantees:

- A submitted acknowledgement never directly changes InventoryPlan. Only `approval_decision` can apply a change, and the engine calls the shared `can_apply()` function again inside the transaction before creating a new plan version.
- Invalid PO/line references, promises before the PO order date, stale revisions, wrong-level approvals, and unapproved plan updates are refused and recorded with rule IDs and trace IDs.
- Plan updates preserve `previous_version_id`; downstream production conflicts create impact records and update production-order status, with planner/operations and logistics/carrier/warehouse notifications routed by role.
- `workflow status` shows the latest acknowledgement, effective promises, open changes, plan history, impacts, notifications, and event timeline for a PO. Exception and decision commands return the durable runtime audit queues as JSON.

Run `pytest -q tests/test_workflow_engine.py` to verify the demo flow, approval-before-plan gate, and stale-revision guard.


## Metrics and persona reports

Generate the Operations Manager summary, Logistics Analyst exception trace report, Planner supplier scorecard and decision log, Carrier/Warehouse Operator impact report, data-quality evaluation, and five deterministic figures from the exported dataset:

```bash
python -m supplier_ack.cli report --dataset data/generated/ --out reports/
```

For the committed small reviewer dataset:

```bash
python -m supplier_ack.cli report --dataset data/samples/ --out reports/starter/
```

The command computes metrics from source tables, writes CSV/Markdown outputs and figures under `reports/`, and creates `report_manifest.json` with SHA-256 checksums so the same dataset can be regenerated and compared. Supplier alerts use the portfolio mean and population standard deviation; no scores or exception counts are randomly assigned.


## Unified CLI and one-command demo

Every command and subcommand supports `--help`. Use either `python -m supplier_ack.cli` or the installed `supplier-ack` console script.

```bash
# Check Python/dependencies/configuration/disk space/seed sanity
python -m supplier_ack.cli doctor

# Generate, reconcile, export source CSVs, and run the 14-group validation gate
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 20261022
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale full --seed 20261022

# Export all three formats from the generated source dataset
python -m supplier_ack.cli export --dataset data/generated/ --formats csv,json,sql --out data/generated/

# Validate, detect labelled anomalies, and build persona-targeted reports
python -m supplier_ack.cli validate --dataset data/generated/
python -m supplier_ack.cli detect --dataset data/generated/
python -m supplier_ack.cli report --dataset data/generated/ --out reports/

# Reproducibility (starter plus the full-scale pair unless --skip-full-scale is supplied)
python -m supplier_ack.cli verify-repro --seed 20261022 --scale starter

# Explore the committed starter database. Workflow commands mutate the database,
# so copy it first if you want to preserve the clean demo state.
cp data/samples/demo.db /tmp/supplier-ack-demo.db
python -m supplier_ack.cli workflow run --db /tmp/supplier-ack-demo.db --events data/samples/demo_events.json
python -m supplier_ack.cli workflow status --db /tmp/supplier-ack-demo.db --po PO-2026-000043
python -m supplier_ack.cli workflow exceptions --db /tmp/supplier-ack-demo.db
python -m supplier_ack.cli workflow decisions --db /tmp/supplier-ack-demo.db

# Full end-to-end starter walkthrough; each stage prints PASS/FAIL
bash scripts/demo.sh

# Complete test suite
python -m pytest -q
```

`export --out` is the export root; `--dataset` is the source directory and defaults to `data/generated/`. `generate` defaults to starter scale and seed `20261022`. The demo script generates starter data, exports CSV/JSON/SQL and the SQLite demo database, validates, detects anomalies, builds reports, and processes the demo event file against a disposable copy of the committed database so repeated runs do not mutate `data/samples/demo.db`.

### Error handling

Bad seed values and unknown scales are rejected by argument parsing. Missing config/dataset paths, malformed CSVs, invalid export formats, and SQLite databases without the required foreign-key declarations produce a concise command error and a non-zero exit code without a traceback. Run `python -m supplier_ack.cli <command> --help` or `python -m supplier_ack.cli workflow <action> --help` for command-specific options.

### Measured full-scale performance

Benchmarked on Python 3.13.5, pandas 2.2.3, NumPy 2.3.5, PyYAML 6.0.3, matplotlib 3.10.8, Linux x86_64. For 10,000 POs / 15,000 acknowledgement-plus-change events:

| Stage | Wall time | Peak RSS |
|---|---:|---:|
| Generation core + source CSV write | 33.56 s | 725,232 KiB |
| Validation (15 groups, 1,716,868 checked rows) | 12.07 s | 605,600 KiB |
| CSV/JSON/SQL export + SQLite seed verification | 27.46 s | 1,062,368 KiB |
| **Measured total of stages** | **73.09 s** | **about 1.04 GiB max** |

These are measured stage timings, not a promise for every laptop; disk speed and available RAM affect export time. The export run wrote the SQL seed and SQLite database and validated imported row counts. Allow at least 2 GiB free disk space for full-scale all-format exports; the `doctor` command reports current free space and a conservative estimate.
