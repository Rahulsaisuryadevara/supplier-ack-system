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
