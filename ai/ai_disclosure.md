# AI assistance disclosure

## Where AI helped

AI assistance was used to bootstrap repository structure, write the initial configuration and documentation, draft the package metadata and CLI entry point, and initialize this prompt-history file.

## Candidate review and validation

The candidate should independently review all generated code, confirm policy assumptions against the challenge brief, install the project in a clean Python 3.11+ environment, run the test suite, inspect generated sample data, and verify the end-to-end workflow before submission. This disclosure distinguishes generated scaffolding from work that has been independently reviewed and validated.

## Relational schema and event history update

AI assistance also drafted the normalized SQLite relational schema, bridge tables, typed event-log target references, audit triggers, lifecycle transition tables, and anomaly-integrity documentation. Database execution and regression tests were run locally; the candidate should still review business policies and test representative real workflow scenarios before submission.

## Deterministic ID engine update

AI assistance implemented `IDFactory`, its fixed-format global and parent-scoped counters, JSON state snapshot/restore, input validation, counter exhaustion guards, and the `tests/test_ids.py` suite. The current local verification run passed 44 tests and exercised the SQLite schema and CLI. The candidate should review the fixed 2026 challenge-year decision, the two-digit scoped-counter limits, and the selected full-parent Approval ID format.

## Seeded master-data generator update

AI assistance implemented the injected seeded NumPy RNG pipeline, IDFactory-driven Supplier/PurchaseOrder/POLine generation, synthetic item/carrier/warehouse masters, actor roster, CSV/summary exports, and CLI scale/seed options. Distribution parameters and rationale are documented in `docs/decisions.md`. Automated tests cover deterministic generation, valid parent relationships, schema-column matching, quantity/price arithmetic, generation-scale counts, and the prohibition on global RNG use. Local verification passed 56 tests and the full-scale in-memory data passed schema validation. The candidate should review the distributions and output samples, and repeat installation and verification in a networked clean environment.
