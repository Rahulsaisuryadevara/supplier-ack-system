"""Focused unit fixtures for all fourteen dataset validators."""
import json
from pathlib import Path

import pandas as pd

from supplier_ack.validation.suite import (
    validate_primary_keys, validate_foreign_keys, validate_enums, validate_dates,
    validate_arithmetic, validate_lifecycle, validate_duplicates, validate_id_formats,
    validate_revision_history, validate_approval_before_apply, validate_downstream_impact,
    validate_ack_status, validate_ground_truth_coverage, validate_leakage,
)


def ds(**tables):
    base={"suppliers":[],"purchase_orders":[],"po_lines":[],"acknowledgements":[],"acknowledgement_lines":[],
          "promise_dates":[],"change_requests":[],"approvals":[],"inventory_plans":[],"production_orders":[],
          "production_order_line":[],"production_order_impact":[],"notifications":[],"notification_recipient":[],
          "entity_event":[],"actors":[],"carriers":[],"warehouses":[],"items":[],"ground_truth_records":[]}
    base.update(tables); return base

def fails(result): return result.status == "FAIL" and result.unknown_failure_count > 0

def test_primary_key_duplicate_caught():
    d=ds(suppliers=[{"supplier_id":"SUP-1"},{"supplier_id":"SUP-1"}]); assert fails(validate_primary_keys(d))

def test_fk_unknown_reference_caught():
    d=ds(po_lines=[{"po_line_id":"LINE-1","po_id":"PO-MISSING","item_id":"ITEM-MISSING"}]); assert fails(validate_foreign_keys(d))

def test_invalid_enum_caught():
    d=ds(suppliers=[{"supplier_id":"SUP-1","supplier_status":"INVALID"}]); assert fails(validate_enums(d))

def test_date_ordering_violation_caught():
    d=ds(purchase_orders=[{"po_id":"PO-1","order_date":"2026-01-10","response_due_at":"2026-01-01"}]); assert fails(validate_dates(d))

def test_arithmetic_violation_caught():
    d=ds(po_lines=[{"po_line_id":"LINE-1","po_id":"PO-1","requested_qty":"2","unit_price":"5","line_total":"7"}]); assert fails(validate_arithmetic(d))

def test_illegal_lifecycle_transition_caught():
    d=ds(entity_event=[{"event_id":"EVT-1","entity_type":"Acknowledgement","entity_id":"ACK-1","event_timestamp":"2026-01-01","previous_state":"{\"status\":\"PROCESSED\"}","new_state":"{\"status\":\"SUBMITTED\"}"}]); assert fails(validate_lifecycle(d))

def test_duplicate_bridge_row_caught():
    row={"production_order_id":"PRO-1","po_line_id":"LINE-1"}; d=ds(production_order_line=[row,row.copy()]); assert fails(validate_duplicates(d))

def test_bad_child_id_caught():
    d=ds(acknowledgements=[{"ack_id":"ACK-1"}],acknowledgement_lines=[{"acknowledgement_line_id":"AL-1","ack_id":"ACK-1"}]); assert fails(validate_id_formats(d))

def test_revision_gap_caught():
    d=ds(acknowledgements=[{"ack_id":"ACK-1","po_id":"PO-1","revision_no":"1","superseded_by":"ACK-3"},{"ack_id":"ACK-3","po_id":"PO-1","revision_no":"3","superseded_by":""}]); assert fails(validate_revision_history(d))

def test_unapproved_change_plan_is_expected_anomaly():
    d=ds(inventory_plans=[{"inventory_plan_id":"IP-1","source":"approved_change","change_request_id":"CHG-1"}],ground_truth_records=[{"record_type":"InventoryPlan","record_id":"IP-1","issue_type":"UNAPPROVED_CHANGE_UPDATES_PLAN","related_entity_ids":"{}"}])
    r=validate_approval_before_apply(d); assert r.status=="EXPECTED_ANOMALY" and r.unknown_failure_count==0

def test_missing_downstream_impact_caught():
    d=ds(change_requests=[{"change_request_id":"CHG-1","po_id":"PO-1","change_type":"date","delta":"10","status":"IMPLEMENTED"}],approvals=[{"change_request_id":"CHG-1","status":"APPROVED"}],production_orders=[{"po_id":"PO-1","po_line_id":"LINE-1","status":"AT_RISK"}],po_lines=[{"po_id":"PO-1","po_line_id":"LINE-1"}],production_order_line=[{"po_line_id":"LINE-1","production_order_id":"PRO-1"}])
    assert fails(validate_downstream_impact(d))

def test_ack_status_inconsistency_caught():
    d=ds(acknowledgements=[{"ack_id":"ACK-1","status":"ACCEPTED","ack_accepted_qty":"0","ack_rejected_qty":"10"}]); assert fails(validate_ack_status(d))

def test_ground_truth_missing_record_caught():
    d=ds(ground_truth_records=[{"record_type":"PromiseDate","record_id":"PROM-404","issue_type":"PROMISE_DATE_BEFORE_ORDER_DATE","boundary":"False"}]); assert fails(validate_ground_truth_coverage(d))

def test_leakage_column_caught(tmp_path):
    pd.DataFrame({"id":[1],"issue_type":["bad"]}).to_csv(tmp_path/"suppliers.csv",index=False)
    assert fails(validate_leakage(tmp_path))

def test_labelled_invalid_promise_date_is_expected_anomaly():
    d=ds(purchase_orders=[{"po_id":"PO-1","order_date":"2026-01-10"}],promise_dates=[{"promise_date_id":"PD-1","po_id":"PO-1","promised_date":"2026-01-01"}],ground_truth_records=[{"record_type":"PromiseDate","record_id":"PD-1","issue_type":"PROMISE_DATE_BEFORE_ORDER_DATE","related_entity_ids":"{}"}])
    r=validate_dates(d); assert r.status=="EXPECTED_ANOMALY" and r.unknown_failure_count==0
