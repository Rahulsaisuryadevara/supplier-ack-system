# Dataset validation contract

`src/supplier_ack/validation/suite.py` is the Generation Step 8 validation entry point. Every check emits `check_name`, `status`, `checked_rows`, `failure_count`, and `sample_failures`, plus counts distinguishing known anomalies from unknown failures.

- `PASS`: no violations observed.
- `EXPECTED_ANOMALY`: violations exist, and each is associated with the relevant issue label in the separate ground-truth data.
- `FAIL`: at least one violation is not explained by ground truth.

Only `FAIL` fails the overall report. This does not mean anomalies are silently accepted: they remain visible in the report and retain record IDs and issue types.

Run `python -m supplier_ack.cli validate --dataset data/generated/`. The command writes `validation_summary.json` and `validation_report.md` beside the input tables. The `generate` command runs the same validation suite after exporting and raises an error on unknown violations.

The four intentionally injected anomaly types are expected exceptions in the relevant checks: `ACK_WRONG_PO_LINE` in foreign-key and ID checks; `PROMISE_DATE_BEFORE_ORDER_DATE` in date ordering; `STALE_REVISION_OVERWRITE` in revision and promise/plan reconciliation; and `UNAPPROVED_CHANGE_UPDATES_PLAN` in approval-before-apply. Ground-truth coverage checks labels in both directions and label-leakage checks ensure target-only columns are absent from input CSVs.
