# Data quality and evaluation report

## (a) Realistic distributions and meaningful variation

Key source-field distribution statistics (numeric values are computed from the supplied dataset):

- Requested line quantity: n=39,876, mean=472.8560, std=469.4536, median=333.9525, min=10.0000, max=5000.0000
- Unit price: n=39,876, mean=601.0448, std=525.7227, median=459.3400, min=12.6100, max=2390.2600
- Promise slip days (stored current promise): n=34,122, mean=1.5909, std=5.3956, median=-1.0000, min=-62.0000, max=54.0000
- Change delta percentage: n=2,862, mean=-2.3312, std=12.5188, median=2.3312, min=-82.6495, max=13.6011
- Production delay days: n=5,000, mean=3.3236, std=4.4418, median=1.0000, min=0.0000, max=37.0000

Figures: `figures/supplier_slip_day_distribution.png`, `figures/ack_status_breakdown.png`, `figures/changes_by_type_and_decision.png`, `figures/projected_vs_requested_supply.png`, and `figures/exception_counts_by_type.png`.

## (b) Consistent IDs and valid joins

Validation artifact status: **PASS**; checks with PASS status: 9; EXPECTED_ANOMALY checks: 6. Source validation file: `data/generated/validation_summary.json` (or the corresponding dataset directory).

Key validation evidence:

- Primary/foreign-key integrity: `2_foreign_key_integrity`: **EXPECTED_ANOMALY**
- Lifecycle transitions: `6_lifecycle_transitions`: **PASS**
- Arithmetic reconciliation: `5_arithmetic_reconciliation`: **EXPECTED_ANOMALY**
- Acknowledgement status consistency: `12_acknowledgement_status_consistency`: **PASS**
- Export leakage: `14_input_label_leakage`: **PASS**

## (c) Dependency/lifecycle consistency across entities

The lifecycle-transition and entity-current-state checks are in the validation summary above. Known stale-revision and deliberately injected cross-reference cases are expected only when represented in ground truth; other violations are failures.

## (d) Correct derived values and reconciliation

The generator uses `supplier_ack.rules.derived` as the shared source for derived-value calculation and reconciliation. Available reconciliation evidence:
`generated/generation_summary.json` contains generation/reconciliation summary keys: `acknowledgement_metrics, anomaly_injection, change_workflow, config_source, coverage_report, distributions, downstream_schedule, event_counts, ground_truth_row_count, notification_workflow, projected_supply, row_counts, scale, seed, supplier_silence_report_rows, target_event_count`.
Arithmetic validator evidence: `5_arithmetic_reconciliation`: **EXPECTED_ANOMALY**. The clean-baseline derived reconciliation is run by the generator before anomaly injection; deliberately labelled anomalies are evaluated separately through ground truth.

## (e) Normal, boundary, failure, and exception coverage

Ground-truth row count: **5,191**. Label counts: `{"ACK_WRONG_PO_LINE": 25, "PROMISE_DATE_BEFORE_ORDER_DATE": 25, "STALE_REVISION_OVERWRITE": 25, "UNAPPROVED_CHANGE_UPDATES_PLAN": 25, "normal": 5091}`. Valid boundary cases: **4**.

The four labelled anomaly families are UNAPPROVED_CHANGE_UPDATES_PLAN, ACK_WRONG_PO_LINE, PROMISE_DATE_BEFORE_ORDER_DATE, and STALE_REVISION_OVERWRITE (100 full-scale rows total, 25 per family in this dataset). The four `boundary=True` rows are valid threshold-edge examples, not injected failures. The remaining ground-truth rows record expected outcomes for ordinary change requests and impacted production orders rather than exceptions.

## (f) Separate ground truth

Ground truth is exported separately (`ground_truth.csv` / `ground_truth.json`); ground-truth and issue labels are not intended to be input features. Dataset manifest: generator version `0.1.0`, seed `20261022`, scale `full`. Leakage check result: see validation summary's leakage group; exported input tables are checked for `ground_truth` and `issue_type` columns.

## (g) Fixed-seed reproducibility

Reproducibility evidence is available in `docs/reproducibility_report.md`.

## Evidence paths

- Dataset root: `/mnt/data/supplier-ack-system/data/generated`
- Manifest SHA-256: `84bbe897e814bc5bb672702f490b5abdaa93770d11f3760dbda6599722f1fe42`
- Validation: `validation_summary.json`, `validation_report.md`
- Reconciliation: generator post-step and `generation_summary.json`
- Ground truth: `ground_truth.csv`, `ground_truth.json`
- Reproducibility: `docs/reproducibility_report.md`
