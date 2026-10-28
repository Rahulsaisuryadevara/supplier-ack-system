# Supplier Acknowledgement Dataset Validation

**Overall status: PASS**

| Check | Status | Checked rows | Failures | Expected anomalies | Unknown failures |
|---|---:|---:|---:|---:|---:|
| 1_primary_key_uniqueness | PASS | 7361 | 0 | 0 | 0 |
| 2_foreign_key_integrity | EXPECTED_ANOMALY | 33807 | 5 | 5 | 0 |
| 3_allowed_enums | PASS | 20269 | 0 | 0 | 0 |
| 4_date_ordering | EXPECTED_ANOMALY | 1188 | 5 | 5 | 0 |
| 5_arithmetic_reconciliation | PASS | 2159 | 0 | 0 | 0 |
| 6_lifecycle_transitions | PASS | 2453 | 0 | 0 | 0 |
| 7_duplicate_checks | PASS | 1750 | 0 | 0 | 0 |
| 8_id_format_checks | EXPECTED_ANOMALY | 9353 | 5 | 5 | 0 |
| 9_revision_history | EXPECTED_ANOMALY | 2002 | 5 | 5 | 0 |
| 10_approval_before_apply | EXPECTED_ANOMALY | 1114 | 5 | 5 | 0 |
| 11_downstream_impact | PASS | 86 | 0 | 0 | 0 |
| 12_acknowledgement_status_consistency | PASS | 214 | 0 | 0 | 0 |
| 13_ground_truth_coverage | PASS | 145 | 0 | 0 | 0 |
| 14_input_label_leakage | PASS | 21 | 0 | 0 | 0 |

## 2_foreign_key_integrity

- `AL-EDGE-0020261022-000001`: ACK line belongs to a different PO (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000002`: po_line_id references missing po_lines PO-2026-999999-L99 (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000003`: ACK line belongs to a different PO (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000004`: po_line_id references missing po_lines PO-2026-999999-L99 (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000005`: ACK line belongs to a different PO (issue_type=ACK_WRONG_PO_LINE)

## 4_date_ordering

- `PD-EDGE-0020261022-000001`: promise date before order date (issue_type=PROMISE_DATE_BEFORE_ORDER_DATE)
- `PD-EDGE-0020261022-000002`: promise date before order date (issue_type=PROMISE_DATE_BEFORE_ORDER_DATE)
- `PD-EDGE-0020261022-000003`: promise date before order date (issue_type=PROMISE_DATE_BEFORE_ORDER_DATE)
- `PD-EDGE-0020261022-000004`: promise date before order date (issue_type=PROMISE_DATE_BEFORE_ORDER_DATE)
- `PD-EDGE-0020261022-000005`: promise date before order date (issue_type=PROMISE_DATE_BEFORE_ORDER_DATE)

## 8_id_format_checks

- `AL-EDGE-0020261022-000001`: child id does not embed ack_id (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000002`: child id does not embed ack_id (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000003`: child id does not embed ack_id (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000004`: child id does not embed ack_id (issue_type=ACK_WRONG_PO_LINE)
- `AL-EDGE-0020261022-000005`: child id does not embed ack_id (issue_type=ACK_WRONG_PO_LINE)

## 9_revision_history

- `PD-ACK-PO-2026-000097-01-02`: older promise revision is current while a newer revision exists (issue_type=STALE_REVISION_OVERWRITE)
- `PD-ACK-PO-2026-000097-01-03`: older promise revision is current while a newer revision exists (issue_type=STALE_REVISION_OVERWRITE)
- `PD-ACK-PO-2026-000097-01-04`: older promise revision is current while a newer revision exists (issue_type=STALE_REVISION_OVERWRITE)
- `PD-ACK-PO-2026-000097-01-05`: older promise revision is current while a newer revision exists (issue_type=STALE_REVISION_OVERWRITE)
- `PD-ACK-PO-2026-000097-01-06`: older promise revision is current while a newer revision exists (issue_type=STALE_REVISION_OVERWRITE)

## 10_approval_before_apply

- `IP-PO-2026-000014-L04-02`: change-sourced plan lacks approval at required level (issue_type=UNAPPROVED_CHANGE_UPDATES_PLAN)
- `IP-PO-2026-000089-L05-02`: change-sourced plan lacks approval at required level (issue_type=UNAPPROVED_CHANGE_UPDATES_PLAN)
- `IP-PO-2026-000142-L04-02`: change-sourced plan lacks approval at required level (issue_type=UNAPPROVED_CHANGE_UPDATES_PLAN)
- `IP-PO-2026-000121-L02-02`: change-sourced plan lacks approval at required level (issue_type=UNAPPROVED_CHANGE_UPDATES_PLAN)
- `IP-PO-2026-000094-L02-02`: change-sourced plan lacks approval at required level (issue_type=UNAPPROVED_CHANGE_UPDATES_PLAN)
