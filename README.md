# Supplier Acknowledgement Management System

A deterministic, locally runnable Python/SQLite implementation of a supplier acknowledgement workflow for the YottaFlex AI recruitment challenge. It turns supplier responses and proposed changes into traceable decisions, approval-gated supply projections, downstream schedule impacts, notifications, validation results, and measurable reports. The included data is synthetic. Supplier, actor, item, purchase-order, and operational records are generated fixtures; no real supplier/customer records or personal data are intended to be included.

## Problem objective → system capability

| Problem objective | Implemented capability and proof |
|---|---|
| Manage supplier acknowledgements | Revision-aware `Acknowledgement` and line-level `acknowledgement_lines` records; status derivation; `generate`, `workflow run`, and `workflow status`. |
| Manage promised dates | Versioned `PromiseDate` rows with current/superseded state, logistics links, and date-order validation. |
| Manage quantity changes | `ChangeRequest` quantity deltas evaluated by shared threshold rules; immutable `Approval` decisions. |
| Identify downstream schedule impacts | Production-order allocation bridge, computed `production_order_impact` records, severity bands, and status changes. |
| Expose key decisions and exceptions | Workflow decision log and exception queue; `workflow decisions` and `workflow exceptions`; threshold metadata and validation reports. |
| Preserve traceability | Append-only `entity_event` snapshots, revision chains, approval/plan versions, recipient bridge, and `trace()` notification lineage. |
| Produce measurable outputs | Coverage reports, validation checks, anomaly precision/recall, supplier/exception/impact reports, manifests, row counts, and SHA-256 checksums. |

## Requirements

- Python 3.11 or newer
- `pip`
- Bash for `scripts/demo.sh` (on Windows, use Git Bash; the automated e2e test skips when Bash is unavailable)

## Quickstart

Run from the repository root. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m supplier_ack.cli --help
```

On macOS/Linux, activate with `source .venv/bin/activate` instead. Then run the demo (Bash or Git Bash):

```bash
bash scripts/demo.sh
```

Expected final line:

```text
OVERALL: PASS — all demo steps completed.
```

The script runs six stages: starter generation/reconciliation/validation; CSV, JSON and SQL export; dataset validation; anomaly detection; persona/data-quality reporting; and runtime event processing against a disposable copy of the committed demo database. The script preserves the committed `data/samples/demo.db`.

Verify independently:

```bash
python -m supplier_ack.cli doctor
python -m supplier_ack.cli validate --dataset data/generated/
python -m supplier_ack.cli detect --dataset data/generated/ --out reports/detection_report.md
python -m pytest
```

A successful validation prints `Validation: PASS` and zero failed checks. Detection prints `Detection: PASS` and reports TP/FP/FN/F1 for each anomaly class. Pytest includes a coverage summary by default. The e2e demo test is marked `e2e` and can be selected with `python -m pytest -m e2e`.

## Full CLI workflow

The installed `supplier-ack` entry point and `python -m supplier_ack.cli` expose the same commands. Commands below use the module form for copy/paste consistency.

### 1. Generate data

```bash
# Starter: 200 POs and 300 counted events (ACK revisions + ChangeRequests)
python -m supplier_ack.cli generate --scale starter --seed 20261022

# Full: 10,000 POs and 15,000 counted events
python -m supplier_ack.cli generate --scale full --seed 20261022

# Optional explicit location or config
python -m supplier_ack.cli generate --scale starter --output-dir data/generated --config config/generator_config.yaml
```

Both scales use the same generation pipeline and default to `data/generated/`. The committed, inspectable starter bundle remains under `data/samples/`; a fresh generation writes to the generated directory, which is gitignored. The generator performs baseline generation, derived-value reconciliation, anomaly injection, exports, and post-generation validation. It writes `ground_truth.csv` and `ground_truth.json` separately from input tables.

### 2. Export to reviewer-friendly formats

```bash
python -m supplier_ack.cli export --dataset data/generated/ --formats csv,json,sql
```

This writes format-specific outputs under `data/generated/`, including a standalone SQLite seed script/database and a manifest with row counts and checksums. SQL import validation preserves labelled edge cases for audit while ensuring unknown violations fail.

### 3. Validate the dataset

```bash
python -m supplier_ack.cli validate --dataset data/generated/
```

Validation distinguishes known, explicitly labelled edge cases (`EXPECTED_ANOMALY`) from unknown rule violations (`FAIL`). A successful run ends with `Validation: PASS` and zero failed checks.

### 4. Evaluate anomaly detectors

```bash
python -m supplier_ack.cli detect --dataset data/generated/ --out reports/detection_report.md
```

The four rule-based detectors are evaluated against the separate ground-truth target. The input tables are checked for target-label leakage. The default starter baseline reports five true positives per class, zero false positives, and zero false negatives (F1 1.000 per class).

### 5. Build reports

```bash
python -m supplier_ack.cli report --dataset data/generated/ --out reports/
```

The report command emits persona-oriented supplier, exception, impact, and data-quality outputs. Inspect the generated summary, exception and impact reports, scorecard, decision log, and report manifest under `reports/`.

### 6. Run the event-driven workflow

```bash
# Process the sample event stream against a SQLite database (creates/seeds it if missing)
python -m supplier_ack.cli workflow run --db data/generated/runtime.db --events data/samples/demo_events.json

# Query a purchase order; substitute a PO ID present in the database
python -m supplier_ack.cli workflow status --db data/generated/runtime.db --po PO-2026-000001
python -m supplier_ack.cli workflow exceptions --db data/generated/runtime.db
python -m supplier_ack.cli workflow decisions --db data/generated/runtime.db
```

Events are processed transactionally and idempotently by `event_id`. Approval requirements are recomputed from source values; an acknowledgement submission does not directly mutate projected supply. Only an eligible approval decision can append an effective InventoryPlan version. Runtime timestamps describe actual processing and are not used in deterministic generated records.

### 7. Verify reproducibility and environment

```bash
python -m supplier_ack.cli verify-repro --scale starter --seed 20261022 --skip-full-scale
python -m supplier_ack.cli doctor
python -m supplier_ack.cli --version
```

The reproducibility command generates two same-seed outputs and a different-seed counterexample, compares SHA-256 checksums, row counts, sorted per-column hashes, summary statistics, and event ordering, and writes `docs/reproducibility_report.md`. Omit `--skip-full-scale` to include the additional full-scale same-seed pair (slower and memory-intensive).

## Data generation

- **Fixed default seed:** `20261022` in both `config/generator_config.yaml` and the CLI. `--seed` is an explicit override.
- **Scale parameterization:** `starter` uses 40 suppliers, 200 POs, 300 counted events, and 100 production orders. `full` uses 200 suppliers, 10,000 POs, 15,000 counted events, and 5,000 production orders. Scale changes config values, not code paths.
- **Count definition:** `event_count` means acknowledgement revision rows plus ChangeRequest rows. Approval rows and PromiseDate revisions are dependent records outside that budget. Supplier silence deliberately creates no acknowledgement row.
- **No generated wall-clock timestamps:** historical business timestamps derive from seeded dates. Export manifests may include operational generation metadata.

The 10-step generation pipeline is:

1. Load and validate scale, distributions, thresholds, and coverage targets.
2. Generate seeded actors, suppliers, items, warehouses, and carriers.
3. Generate purchase-order headers and lines with stable IDs and derived totals.
4. Generate acknowledgements, revision chains, line snapshots, and promised-date versions to meet the configured coverage mix.
5. Generate price/date/quantity change requests, threshold decisions, approval rows, and supplier-silence chases.
6. Create baseline InventoryPlan versions, approved projections, production orders/allocations, and derived schedule impacts.
7. Emit role-routed notifications, append-only event snapshots, and deterministic labelled anomalies/boundary cases.
8. Reconcile derived values and run the ground-truth-aware validation suite.
9. Write flat CSVs, coverage/summary outputs, ground truth, and exportable JSON/SQL/SQLite artifacts when requested.
10. Verify output contracts and checksums through manifests and the reproducibility harness.

Anomaly labels are kept out of model-input tables; only `ground_truth.csv` and `ground_truth.json` are target files. Never use those target files as input features when evaluating detectors.

## Testing

Install test and coverage dependencies with `python -m pip install -e ".[dev]"`, then run:

```bash
python -m pytest
python -m pytest -m "not slow"
python -m pytest -m e2e
python -m pytest --cov=supplier_ack --cov-report=term-missing
```

The configured default already adds `--cov=supplier_ack --cov-report=term-missing`, so the first command reports statement coverage. `slow` marks seeded subprocess/reproducibility tests; `e2e` marks the six-stage demo integration test. The suite covers ID contracts, SQLite DDL/FKs/uniqueness, generated coverage and revision invariants, threshold routing, approval gating, downstream impacts, notifications and trace chains, derived values, anomaly injection/ground truth/leakage, validation checks, reproducibility, runtime events/exceptions, detectors, CLI behavior, and documentation/schema consistency. See `docs/verification.md` for the requirement-to-proof map.

## Performance and footprint

Measured on 2026-10-28 in the recorded Linux x86_64 environment (Python 3.13.5; pandas 2.2.3; NumPy 2.3.5; PyYAML 6.0.3; matplotlib 3.10.8), with the 10,000-PO / 15,000-event full scale:

| Stage | Wall time | Peak resident memory |
|---|---:|---:|
| Generation and source CSV writing | 33.56 s | 725,232 KiB |
| CSV validation | 12.07 s | 605,600 KiB |
| CSV/JSON/SQL export and SQLite verification | 27.46 s | 1,062,368 KiB |
| Sequential total | 73.09 s | Peak about 1.04 GiB |

These are environment-specific measurements, not performance guarantees. Full-scale all-format export can create hundreds of MB of artifacts; reserve approximately 2 GB of free disk for full-scale generation plus all exports. Starter runs are much smaller and are the default for interactive work. The current implementation is a local single-user CLI, not a hosted multi-tenant service.

## Repository layout

```text
supplier-ack-system/
├── config/                  # Scale, distributions, thresholds, anomaly targets
├── src/supplier_ack/        # Installable application package
│   ├── generators/          # Seeded entity generation and anomaly injection
│   ├── rules/               # Shared threshold, derived-value, and impact rules
│   ├── events/              # Event-history support
│   ├── validation/          # Cross-table and ground-truth-aware checks
│   ├── exporting/           # CSV/JSON/SQL/SQLite export pipeline
│   ├── exports/             # Export support package namespace
│   ├── metrics/             # Detectors, metrics, and persona reports
│   └── workflow/            # Transactional runtime event engine
├── tests/                   # Unit, integration, slow, e2e, and docs contract tests
├── data/samples/            # Committed starter tables, demo DB, and demo events
├── data/generated/          # Local generated output (gitignored)
├── docs/                    # Schema, dictionary, decisions, verification, provenance
├── reports/                 # Example/generated report artifacts
├── ai/                      # Prompt history and AI-use disclosure
├── scripts/                 # End-to-end demo runner
└── pyproject.toml            # Package metadata, dependencies, pytest configuration
```

## Design rationale and verification evidence

- `docs/decisions.md` records decisions, alternatives, trade-offs, assumptions, limitations, and next steps.
- `docs/schema.md` documents SQLite tables, relationships, event history, and integrity triggers.
- `docs/data_dictionary.md` is generated from the field specifications in `src/supplier_ack/schema.py`; a test checks the document against that source of truth.
- `docs/verification.md` maps each requirement to concrete tests, validator checks, CLI commands, detector results, and reproducibility evidence.
- `docs/provenance.md`, `ai/prompt_history.md`, and `ai/ai_disclosure.md` record data provenance guidance and development assistance.


## License

This project is released under the [MIT License](LICENSE).
