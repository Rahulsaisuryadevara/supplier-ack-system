# Verification guide: how we know the solution works

This page links requirements to executable proof. Run commands from the repository root after `python -m pip install -e ".[dev]"`.

## Reproducible local verification

```bash
python -m pytest
bash scripts/demo.sh
python -m supplier_ack.cli verify-repro --scale starter --seed 20261022 --skip-full-scale
```

The pytest configuration enables `pytest-cov` automatically. The demo's final summary should contain `OVERALL: PASS — all demo steps completed.` The committed reproducibility report (`docs/reproducibility_report.md`) records a PASS for starter same-seed comparison and the different-seed counter-property, plus a full-scale same-seed comparison.

## Requirement-to-proof map

| Requirement | Proof in code/tests | Runtime/data proof |
|---|---|---|
| Stable identifiers for all ten entity formats | `tests/test_ids.py` | `python -m supplier_ack.cli generate --scale starter --seed 20261022`; validator check `8_id_format_checks` (see validation report for exact check names emitted by current version). |
| Relational schema and referential integrity | `tests/test_schema.py::test_ddl_executes_and_foreign_keys_are_enabled`, `test_foreign_key_rejects_bad_supplier_reference`, `test_bridge_tables_have_composite_unique_or_primary_keys`; `tests/test_relational_schema.py` | `python -m pytest tests/test_schema.py tests/test_relational_schema.py`; SQLite FK pragma and invalid insert tests. |
| Starter/full scale configuration and required coverage categories | `tests/test_generators.py::test_starter_scale_counts_and_exact_entity_columns`, `tests/test_anomalies.py::test_configured_edge_case_counts_and_internal_boolean_labels` | `generation_summary.json`, `coverage_report.csv`, `coverage_report.json`; `generate --scale starter` / `--scale full`. |
| Revision history preserved as immutable snapshots | `tests/test_acks.py::test_revision_rows_are_full_snapshots_and_superseded_pointers_resolve`, `tests/test_relational_schema.py::test_acknowledgement_revision_payload_cannot_be_overwritten`, `test_inventory_plan_versions_are_append_only` | `acknowledgements.csv`, `acknowledgement_lines.csv`, `promise_dates.csv`, `inventory_plans.csv`, `entity_event.csv`; `workflow status`. |
| Only approved changes affect plans | `tests/test_supply.py::test_pending_or_rejected_change_hard_blocks_new_plan_versions`, `tests/test_thresholds.py::test_can_apply_requires_approval_at_the_required_level`, `tests/test_workflow.py::test_pending_change_cannot_update_plan` | `workflow run`, then inspect plan versions and decision/exception output; validator `approval-before-apply` group. |
| Downstream impacts are identified and derived | `tests/test_supply.py::test_impacts_are_only_from_implemented_changes_and_severity_is_computed`, `test_impact_severity_worst_of_date_and_quantity_bands`; `tests/test_validation.py::test_missing_downstream_impact_caught` | `production_order_impact.csv`, `reports/impact_report.csv`; `report --dataset data/generated/`. |
| Acknowledgement status matches accepted/rejected quantities | `tests/test_derived.py::test_ack_status_boundaries_and_business_rounding`, `tests/test_validation.py::test_ack_status_inconsistency_caught` | `12_acknowledgement_status_consistency` validator group and `validation_report.md`. |
| Threshold routing and hard-limit rejection | `tests/test_thresholds.py::test_threshold_routing_is_config_driven`, `test_hard_policy_limits_are_deterministic_rejections`, `test_threshold_decision_recomputes_delta_from_old_and_new_values` | `change_requests.csv`, `approvals.csv`, `reports/decision_log.csv`. |
| Silence modeled without fabricated supplier response | `tests/test_notifications.py` and supplier-silence cases in `tests/test_supply.py` | `silence_report.csv`, pending silence chase ChangeRequests, notifications routed to planner and supplier. |
| Notifications route to correct roles and trace full lineage | `tests/test_notifications.py`, `tests/test_supply.py::test_notifications_use_po_owner_and_are_traceable` | `notifications.csv`, `notification_recipient.csv`, notification `trace()` result. |
| All four injected anomalies are detectable | `tests/test_anomalies.py`, `tests/test_detectors.py::test_starter_detection_has_perfect_precision_and_recall` | `python -m supplier_ack.cli detect --dataset data/generated/ --out reports/detection_report.md`; per-class output below. |
| Ground truth is complete and does not leak to model input | `tests/test_anomalies.py::test_ground_truth_files_are_separate_and_no_input_csv_label_leakage`, `tests/test_detectors.py::test_detectors_reject_label_columns`, `tests/test_validation.py::test_ground_truth_missing_record_caught`, `test_leakage_column_caught` | Validator groups for ground-truth coverage and input-label leakage; target files remain separate. |
| Same seed is byte-identical; different seed changes data | `tests/test_generators.py::test_same_seed_produces_identical_frames`, `tests/test_reproducibility.py::test_verify_reproducibility_cli_generates_byte_identical_starter_runs` | `verify-repro --scale starter --seed 20261022 --skip-full-scale`; detailed SHA-256 pairs in `docs/reproducibility_report.md`. |
| Runtime engine handles event types, exception paths, stale revisions, and plan refusal | `tests/test_workflow.py::test_demo_exercises_all_event_types_and_four_exception_paths`, `test_stale_revision_is_recorded_but_not_inserted`, `test_pending_change_cannot_update_plan` | `workflow run`, `workflow status`, `workflow exceptions`, `workflow decisions`. |
| CLI demo is end-to-end reproducible | `tests/test_e2e_demo.py::test_demo_script_end_to_end_reports_all_pass` (marker `e2e`) | `bash scripts/demo.sh` prints six PASS stages and `OVERALL: PASS`. |
| Documentation field names do not drift from code | `tests/test_data_dictionary.py::test_markdown_document_is_generated_from_same_schema_source` plus parsed field-table contract test | `docs/data_dictionary.md` is generated from `ENTITIES` in `schema.py`; schema and dictionary tests fail on drift. |

## Four required edge cases and detector outputs

The starter baseline uses seed `20261022` and injects five examples of each class. The detector report produced by the recorded demo reports the following:

| Edge case | Expected violation | Detector output (starter baseline) | Intended handling |
|---|---|---|---|
| `UNAPPROVED_CHANGE_UPDATES_PLAN` | An effective plan version references a change without required approval. | TP=5, FP=0, FN=0, F1=1.000 | Reject/revert the unsafe projection; retain the last approved effective plan. |
| `ACK_WRONG_PO_LINE` | An acknowledgement-line reference belongs to another PO or does not exist. | TP=5, FP=0, FN=0, F1=1.000 | Flag invalid ownership/reference; do not silently remap it. |
| `PROMISE_DATE_BEFORE_ORDER_DATE` | A promise date precedes its parent PO order date. | TP=5, FP=0, FN=0, F1=1.000 | Reject/flag the temporal inconsistency. |
| `STALE_REVISION_OVERWRITE` | An older revision is marked current while a newer revision exists. | TP=5, FP=0, FN=0, F1=1.000 | Keep the highest valid revision effective and record the stale attempt. |

These are controlled synthetic test cohorts. Perfect precision/recall here proves the implementation detects the injected patterns; it does not imply equivalent performance on unseen production data.

## Reproducibility checksum evidence

The committed `docs/reproducibility_report.md` records two identical starter runs with seed `20261022` and a counter-run with seed `20261023`. All listed per-file SHA-256 pairs matched between starter run 1 and run 2. Selected exact checksums (SHA-256):

| Output | Run 1 and run 2 checksum | Match |
|---|---|---|
| `purchase_orders.csv` | `0a426490602ecd899375cad47d54fe613c69d1b22601b037096608e78d77e86a` | Yes |
| `acknowledgements.csv` | `317afc7811d2f647725c5e8112d6130b8e971af1551c15cf87924928378fdaec` | Yes |
| `ground_truth.csv` | `4c0274daeaf49369f48638a203f4120e02ed9c5029979f647fe8cfe80a310b6b` | Yes |
| `inventory_plans.csv` | `d909ba8c0ae7a102dafff1b7e9620eaf75fdf8dbbf4ac2438e53981200055e97` | Yes |
| `entity_event.csv` | `11dff242534b6c3338d5d252558d36ecf79c4e8b752c7569be03658ceddd6031` | Yes |

The report includes hashes for every generated file, matching table row counts, sorted per-column value hashes, means, and event ordering. Its recorded overall result is PASS for the starter same-seed check, different-seed counter-property, and full-scale double-generation pair. Re-run the CLI to regenerate environment-specific evidence rather than assuming a checksum remains valid after code/config/dependency changes.

## Acceptance criteria called out explicitly

1. **Revision history preserved:** `tests/test_acks.py::test_revision_rows_are_full_snapshots_and_superseded_pointers_resolve`; also protected by `tests/test_relational_schema.py::test_acknowledgement_revision_payload_cannot_be_overwritten`.
2. **Only approved changes affect plans:** `tests/test_supply.py::test_pending_or_rejected_change_hard_blocks_new_plan_versions`; runtime path additionally covered by `tests/test_workflow.py::test_pending_change_cannot_update_plan`.
3. **Downstream impact identified:** `tests/test_supply.py::test_impacts_are_only_from_implemented_changes_and_severity_is_computed`; missing impacts are challenged by `tests/test_validation.py::test_missing_downstream_impact_caught`.
4. **Acknowledgement status consistent:** `tests/test_derived.py::test_ack_status_boundaries_and_business_rounding`; invalid status/quantity reconciliation is challenged by `tests/test_validation.py::test_ack_status_inconsistency_caught`.

## Honest coverage and limitations note

A focused run of `tests/test_coverage.py` previously measured 55% statement coverage across the package; it was not the full-suite aggregate. The earlier constrained execution could not establish a trustworthy full-suite pass count or full aggregate coverage because subprocess-heavy CLI tests timed out. Run `python -m pytest` on the target machine to obtain the current pass count and coverage. Do not interpret a passing demo as a substitute for the full test suite, and do not interpret 55% focused coverage as complete coverage.
