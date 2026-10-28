# Design decisions, assumptions, trade-offs, and limitations

- **Python 3.11+:** accessible ecosystem and straightforward local execution; not intended as a high-throughput distributed service.
- **pandas:** concise deterministic synthetic-data generation and evaluation; memory use grows with dataset size.
- **SQLite:** free, serverless persistence for a single-candidate challenge; write concurrency is limited compared with server databases.
- **argparse:** standard-library CLI with no runtime framework dependency; more manual work than Typer for complex commands.
- **pytest:** expressive regression tests for conditional business rules; tests must be kept aligned with evolving policies.
- **Synthetic data:** generated records are fictional and should not be represented as real supplier performance.
- **Approval policy:** percentage and date-slip thresholds are configurable. The workflow should preserve the original request, decision, approver, and reason.
- **Actors:** Supplier owns acknowledgements and change requests; Planner owns schedule updates; Carrier/Warehouse Operator confirms physical milestones; Logistics Analyst assesses transit risk; Operations Manager approves escalations.
- **Limitations at bootstrap:** persistence and end-to-end workflow commands are not implemented yet; this repository stage provides the installable package, configuration, design, and CLI foundation.
