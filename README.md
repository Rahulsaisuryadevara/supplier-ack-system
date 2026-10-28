# Supplier Acknowledgement Management System

## Purpose

A locally runnable, traceable workflow for managing supplier purchase-order acknowledgements, promised-date changes, quantity changes, approval exceptions, and downstream schedule impacts. The design models five operational actors: **Supplier**, **Planner**, **Carrier/Warehouse Operator**, **Logistics Analyst**, and **Operations Manager**. The initial repository bootstrap establishes the configuration, package, and verification conventions; workflow behavior will be implemented in subsequent stages.

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

## Run

The CLI entry point is `supplier-ack`. Once the workflow implementation is added, the intended commands are:

```bash
supplier-ack --help
supplier-ack generate --config config/generator_config.yaml --scale starter
supplier-ack run --config config/generator_config.yaml --scale starter
supplier-ack report --db data/generated/supplier_ack.db
```

During this bootstrap stage, use `supplier-ack --help` to verify the installed command and inspect available options. Runtime subcommands will be completed with the workflow implementation.

## Verify

```bash
python -m pytest
pip install -e .
python -c "import supplier_ack; print(supplier_ack.__file__)"
```

Tests and CLI workflow coverage will grow alongside the implementation. Full-scale generated outputs belong in `data/generated/` and are ignored by Git; small reproducible examples belong in `data/samples/`.

## Repository layout

```text
supplier-ack-system/
├── README.md
├── pyproject.toml
├── .gitignore
├── config/
│   └── generator_config.yaml
├── src/supplier_ack/
│   ├── ids.py
│   ├── schema.py
│   ├── cli.py
│   ├── generators/
│   ├── rules/
│   ├── events/
│   ├── validation/
│   ├── exports/
│   ├── metrics/
│   └── workflow/
├── tests/
├── data/
│   ├── samples/
│   └── generated/
├── docs/
└── ai/
```

## Technology choices (initial)

- **Python 3.11+** keeps the project approachable and benefits from mature data and testing libraries; the trade-off is that throughput is lower than a compiled service for very high-volume workloads.
- **pandas** supports deterministic synthetic-data generation, tabular transformations, and measurable evaluation reports; the trade-off is additional memory overhead compared with streaming row-by-row processing.
- **SQLite** is a zero-server, free persistence option suitable for a reproducible single-user challenge submission; the trade-off is limited concurrent-write throughput compared with a client/server database.
- **argparse** provides a built-in, dependency-free CLI; the trade-off is less convenience for complex command trees than a dedicated CLI framework.
- **pytest** makes rules and workflow behavior easy to test with readable fixtures; the trade-off is one development dependency and the need to maintain tests as rules evolve.
