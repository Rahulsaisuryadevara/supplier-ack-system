# Supplier Acknowledgement Management System

## Purpose

A locally runnable, traceable workflow for managing supplier purchase-order acknowledgements, promised-date changes, quantity changes, approval exceptions, and downstream schedule impacts. The data model includes Supplier, Planner, Carrier/Warehouse Operator, Logistics Analyst, and Operations Manager roles, and retains the provenance needed to measure decisions and exceptions.

This repository includes the complete field dictionary and relational SQLite schema, deterministic ID factory, seeded master-data generator, and coverage-driven acknowledgement/promise-date revisions, change requests, approvals, and silence reporting. Inventory-plan/production-order generation and the full runtime workflow are subsequent implementation stages; overdue supplier silence already produces planner-owned chase notifications.

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

The starter and full datasets use the same generator code. The scale selects only parameters in `config/generator_config.yaml`; the seed makes runs reproducible. Generation now includes master data, acknowledgement revisions, line-level promise dates, rule-driven price/date/quantity change requests, append-only multi-level approval decisions, overdue-silence chase notifications, a supplier-silence report, and a coverage report for both scales.

```bash
# Starter: 40 suppliers, 200 purchase orders, 2–6 lines per PO
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 20261022

# Full: 200 suppliers, 10,000 purchase orders, 2–6 lines per PO
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale full --seed 20261022

# Override the seed or output location
python -m supplier_ack.cli generate --config config/generator_config.yaml --scale starter --seed 7 --output-dir /tmp/supplier-ack-output
```

Starter CSVs are written to `data/samples/`; full-scale CSVs are written to `data/generated/` (gitignored). Entity CSVs include `suppliers.csv`, `purchase_orders.csv`, `po_lines.csv`, `acknowledgements.csv`, `promise_dates.csv`, `change_requests.csv`, `approvals.csv`, `notifications.csv`, and the support masters. `silence_report.csv` contains overdue POs with no acknowledgement row. `coverage_report.csv` and `coverage_report.json` report observed counts and percentages for all eight required categories at both starter and full scales. `generation_summary.json` records row counts, event-budget reconciliation, distribution statistics, threshold-routing and approval-decision summaries, scale, and seed. Generated core entities are validated against `src/supplier_ack/schema.py` before exporting by default. `event_count` counts acknowledgement revision rows plus ChangeRequest rows; Approval rows and PromiseDate revision rows are separate dependent records.

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
