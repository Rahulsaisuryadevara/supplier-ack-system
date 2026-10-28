"""Fourteen-group dataset validation suite with ground-truth-aware anomaly handling."""
from __future__ import annotations
import csv, json, re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from supplier_ack.schema import ENTITIES
from supplier_ack.rules.derived import derive_ack_status
from supplier_ack.rules.thresholds import evaluate_threshold

@dataclass
class CheckResult:
    check_name: str
    status: str
    checked_rows: int
    failure_count: int
    sample_failures: list[dict[str, Any]]
    expected_anomaly_count: int = 0
    unknown_failure_count: int = 0
    def to_dict(self): return asdict(self)

TABLES = {
    "suppliers":"suppliers", "purchase_orders":"purchase_orders", "po_lines":"po_lines",
    "acknowledgements":"acknowledgements", "acknowledgement_lines":"acknowledgement_lines",
    "promise_dates":"promise_dates", "change_requests":"change_requests", "approvals":"approvals",
    "inventory_plans":"inventory_plans", "production_orders":"production_orders",
    "production_order_line":"production_order_line", "production_order_impact":"production_order_impact",
    "notifications":"notifications", "notification_recipient":"notification_recipient", "entity_event":"entity_event",
    "actors":"actors", "carriers":"carriers", "warehouses":"warehouses", "items":"items",
}
PK = {"suppliers":"supplier_id","purchase_orders":"po_id","po_lines":"po_line_id","acknowledgements":"ack_id",
      "acknowledgement_lines":"acknowledgement_line_id","promise_dates":"promise_date_id","change_requests":"change_request_id",
      "approvals":"approval_id","inventory_plans":"inventory_plan_id","production_orders":"production_order_id",
      "production_order_impact":"impact_id","notifications":"notification_id","actors":"actor_id","carriers":"carrier_id",
      "warehouses":"warehouse_id","items":"item_id","entity_event":"event_id"}
KNOWN_TYPES = {"UNAPPROVED_CHANGE_UPDATES_PLAN","ACK_WRONG_PO_LINE","PROMISE_DATE_BEFORE_ORDER_DATE","STALE_REVISION_OVERWRITE"}


def _s(v): return "" if v is None or (isinstance(v,float) and pd.isna(v)) else str(v).strip()
def _num(v, default=0.0):
    try: return float(v)
    except (ValueError,TypeError): return default
def _day(v):
    try: return date.fromisoformat(_s(v)[:10]) if _s(v) else None
    except ValueError: return None

def load_dataset(directory: str | Path) -> dict[str, list[dict[str, Any]]]:
    root=Path(directory); out={}
    for name in TABLES:
        p=root/f"{name}.csv"
        if p.exists(): out[name]=pd.read_csv(p, dtype=str, keep_default_na=False).to_dict(orient="records")
    gt=root/"ground_truth.csv"
    out["ground_truth_records"]=pd.read_csv(gt,dtype=str,keep_default_na=False).to_dict(orient="records") if gt.exists() else []
    return out

def _ground_truth(dataset):
    records=dataset.get("ground_truth_records",[]); by_type=defaultdict(set); by_id=defaultdict(set); all_ids=set()
    for g in records:
        typ=_s(g.get("issue_type")); rid=_s(g.get("record_id")); rtype=_s(g.get("record_type"))
        if typ:
            by_type[typ].add((rtype,rid)); by_id[typ].add(rid); all_ids.add((rtype,rid))
        try: related=json.loads(g.get("related_entity_ids") or "{}")
        except Exception: related={}
        if isinstance(related,dict):
            for v in related.values():
                if v: by_id[typ].add(str(v))
    return records,by_type,by_id,all_ids

def _result(name, checked, failures, gt_by_id=None):
    gt_by_id=gt_by_id or {}; known=[]; unknown=[]
    for f in failures:
        issue=f.get("issue_type"); rid=str(f.get("record_id", "")); related=set(map(str,f.get("related_ids",[])))
        is_known=bool(issue and (rid in gt_by_id.get(issue,set()) or related.intersection(gt_by_id.get(issue,set()))))
        (known if is_known else unknown).append(f)
    status="FAIL" if unknown else ("EXPECTED_ANOMALY" if known else "PASS")
    return CheckResult(name,status,int(checked),len(failures),(unknown+known)[:10],len(known),len(unknown))

def _rows(dataset, name): return dataset.get(name, [])
def _id(row, table): return _s(row.get(PK.get(table,"")))

def validate_primary_keys(dataset):
    fails=[]; checked=0
    for table, pk in PK.items():
        rows=_rows(dataset,table); checked+=len(rows); seen=set()
        for r in rows:
            v=_s(r.get(pk))
            if not v: fails.append({"table":table,"record_id":v,"reason":f"missing primary key {pk}"})
            elif v in seen: fails.append({"table":table,"record_id":v,"reason":f"duplicate primary key {pk}"})
            seen.add(v)
    return _result("1_primary_key_uniqueness",checked,fails)

def validate_foreign_keys(dataset):
    fails=[]; checked=0; _,_,gt,allids=_ground_truth(dataset)
    parents={t:{_s(r.get(pk)) for r in _rows(dataset,t)} for t,pk in PK.items()}
    # FK mapping: table, field, parent table; cross-PO ACK line has a dedicated labelled exception.
    specs={"purchase_orders":[("supplier_id","suppliers"),("planner_actor_id","actors"),("warehouse_id","warehouses"),("carrier_id","carriers")],
    "po_lines":[("po_id","purchase_orders"),("item_id","items")],"acknowledgements":[("po_id","purchase_orders"),("supplier_id","suppliers")],
    "acknowledgement_lines":[("ack_id","acknowledgements"),("po_id","purchase_orders"),("po_line_id","po_lines")],
    "promise_dates":[("ack_id","acknowledgements"),("po_id","purchase_orders"),("po_line_id","po_lines"),("carrier_id","carriers"),("ship_from_warehouse_id","warehouses")],
    "change_requests":[("po_id","purchase_orders"),("supplier_id","suppliers"),("po_line_id","po_lines")],
    "approvals":[("change_request_id","change_requests"),("approver_actor_id","actors")],
    "inventory_plans":[("po_id","purchase_orders"),("po_line_id","po_lines"),("change_request_id","change_requests")],
    "production_orders":[("po_id","purchase_orders"),("po_line_id","po_lines"),("inventory_plan_id","inventory_plans")],
    "production_order_line":[("production_order_id","production_orders"),("po_line_id","po_lines")],
    "production_order_impact":[("production_order_id","production_orders"),("change_request_id","change_requests"),("po_line_id","po_lines")],
    "notifications":[("po_id","purchase_orders"),("ack_id","acknowledgements"),("change_request_id","change_requests")],
    "notification_recipient":[("notification_id","notifications"),("recipient_actor_id","actors")],
    "entity_event":[("target_po_id","purchase_orders"),("target_ack_id","acknowledgements"),("target_change_request_id","change_requests"),("target_approval_id","approvals"),("target_inventory_plan_id","inventory_plans"),("target_production_order_id","production_orders"),("target_notification_id","notifications")]}
    ack_by_id={_s(a.get("ack_id")):a for a in _rows(dataset,"acknowledgements")}
    line_by_id={_s(a.get("po_line_id")):a for a in _rows(dataset,"po_lines")}
    for table,fields in specs.items():
        for r in _rows(dataset,table):
            checked+=len(fields)
            for field,parent in fields:
                v=_s(r.get(field))
                if v and v not in parents.get(parent,set()):
                    issue="ACK_WRONG_PO_LINE" if table=="acknowledgement_lines" and field=="po_line_id" else None
                    fails.append({"table":table,"record_id":_id(r,table),"reason":f"{field} references missing {parent} {v}","issue_type":issue,"related_ids":[v]})
            if table=="acknowledgement_lines":
                ack=ack_by_id.get(_s(r.get("ack_id")))
                line=line_by_id.get(_s(r.get("po_line_id")))
                if ack and line and _s(ack.get("po_id"))!=_s(line.get("po_id")):
                    fails.append({"table":table,"record_id":_id(r,table),"reason":"ACK line belongs to a different PO","issue_type":"ACK_WRONG_PO_LINE","related_ids":[_s(r.get("po_line_id")),_s(r.get("po_id"))]})
    return _result("2_foreign_key_integrity",checked,fails,gt)

def validate_enums(dataset):
    fails=[]; checked=0
    for entity,spec in ENTITIES.items():
        table=spec.table_name
        for r in _rows(dataset,table):
            for field in spec.fields:
                if field.enum_values:
                    checked+=1; val=_s(r.get(field.name))
                    if val and val not in field.enum_values: fails.append({"table":table,"record_id":_id(r,table),"reason":f"{field.name}={val!r} not in {field.enum_values}"})
    return _result("3_allowed_enums",checked,fails)

def validate_dates(dataset):
    fails=[]; checked=0; _,_,gt,_=_ground_truth(dataset)
    pos={_s(r.get("po_id")):r for r in _rows(dataset,"purchase_orders")}
    for r in _rows(dataset,"acknowledgements"):
        checked+=1; po=pos.get(_s(r.get("po_id"))); od=_day(po.get("order_date")) if po else None; resp=_day(r.get("acknowledged_at"))
        if od and resp and resp<od: fails.append({"table":"acknowledgements","record_id":_id(r,"acknowledgements"),"reason":"response before order date"})
    for r in _rows(dataset,"promise_dates"):
        checked+=1; po=pos.get(_s(r.get("po_id"))); od=_day(po.get("order_date")) if po else None; pdte=_day(r.get("promised_date"))
        if od and pdte and pdte<od: fails.append({"table":"promise_dates","record_id":_id(r,"promise_dates"),"reason":"promise date before order date","issue_type":"PROMISE_DATE_BEFORE_ORDER_DATE"})
    for r in _rows(dataset,"production_orders"):
        checked+=1; req=_day(r.get("required_by_date")); start=_day(r.get("planned_start_date"))
        if req and start and req<start: fails.append({"table":"production_orders","record_id":_id(r,"production_orders"),"reason":"required_by_date before planned_start_date"})
    for r in _rows(dataset,"purchase_orders"):
        checked+=1; od=_day(r.get("order_date")); due=_day(r.get("response_due_at"))
        if od and due and due<od: fails.append({"table":"purchase_orders","record_id":_id(r,"purchase_orders"),"reason":"response_due_at before order_date"})
    return _result("4_date_ordering",checked,fails,gt)

def validate_arithmetic(dataset):
    fails=[]; checked=0
    lines={_s(r.get("po_line_id")):r for r in _rows(dataset,"po_lines")}; sums=defaultdict(float)
    for r in _rows(dataset,"po_lines"):
        checked+=1; q=_num(r.get("requested_qty")); p=_num(r.get("unit_price")); total=_num(r.get("line_total")); expected=round(q*p,2)
        if abs(expected-total)>0.011: fails.append({"table":"po_lines","record_id":_id(r,"po_lines"),"reason":f"line_total {total} != qty*price {expected}"})
        sums[_s(r.get("po_id"))]+=total
    for r in _rows(dataset,"purchase_orders"):
        checked+=1; total=_num(r.get("total_order_value")); expected=round(sums[_s(r.get("po_id"))],2)
        if abs(total-expected)>0.02: fails.append({"table":"purchase_orders","record_id":_id(r,"purchase_orders"),"reason":f"PO total {total} != line sum {expected}"})
    for r in _rows(dataset,"acknowledgement_lines"):
        checked+=1; q=_num(r.get("requested_qty")); a=_num(r.get("accepted_qty")); rej=_num(r.get("rejected_qty"))
        if abs(a+rej-q)>0.011: fails.append({"table":"acknowledgement_lines","record_id":_id(r,"acknowledgement_lines"),"reason":"accepted + rejected != requested"})
    # approved_ack plan projections must reconcile to the effective promise snapshot.
    promises_by_line=defaultdict(list)
    for promise in _rows(dataset,"promise_dates"):
        if _s(promise.get("status")).upper()=="CURRENT": promises_by_line[_s(promise.get("po_line_id"))].append(promise)
    for plan in _rows(dataset,"inventory_plans"):
        if _s(plan.get("source"))!="approved_ack" or _s(plan.get("is_effective")) not in {"1","True","true"}: continue
        checked+=1; candidates=promises_by_line.get(_s(plan.get("po_line_id")),[])
        if candidates:
            latest=max(candidates,key=lambda x:_num(x.get("revision_no")))
            if abs(_num(plan.get("projected_qty"))-_num(latest.get("promised_qty")))>0.011 or _s(plan.get("projected_delivery_date"))!=_s(latest.get("promised_date")):
                fails.append({"table":"inventory_plans","record_id":_id(plan,"inventory_plans"),"reason":"effective approved_ack plan differs from current approved promise","issue_type":"STALE_REVISION_OVERWRITE","related_ids":[_s(plan.get("po_line_id"))]})
    _,_,gt,_=_ground_truth(dataset)
    return _result("5_arithmetic_reconciliation",checked,fails,gt)

def validate_lifecycle(dataset):
    fails=[]; checked=0
    events=sorted(_rows(dataset,"entity_event"),key=lambda r:_s(r.get("event_timestamp")))
    last={}; last_event_state={}; legal={
        "Acknowledgement":{"DRAFT":{"SUBMITTED"},"SUBMITTED":{"PROCESSED","EXCEPTION"}},
        "ChangeRequest":{"OPEN":{"SUBMITTED","PENDING_APPROVAL"},"SUBMITTED":{"UNDER_REVIEW"},"UNDER_REVIEW":{"APPROVED","REJECTED"},"APPROVED":{"IMPLEMENTED","APPLIED"},"PENDING_APPROVAL":{"APPROVED","REJECTED"},"REJECTED":{"PENDING_APPROVAL","SUBMITTED"},"open":{"pending_approval"},"pending_approval":{"approved","rejected","applied"},"approved":{"applied"},"rejected":{"pending_approval"}},
        "Approval":{"PENDING":{"APPROVED","REJECTED","ESCALATED"}},
        "ProductionOrder":{"PLANNED":{"AT_RISK","RESCHEDULED","CONFIRMED"},"AT_RISK":{"RESCHEDULED","CONFIRMED","DELAYED"},"RESCHEDULED":{"CONFIRMED","DELAYED","AT_RISK"},"planned":{"at_risk","rescheduled","confirmed"},"at_risk":{"rescheduled","confirmed","delayed"},"rescheduled":{"confirmed","delayed","at_risk"}}}
    for e in events:
        checked+=1; et=_s(e.get("entity_type")); eid=_s(e.get("entity_id"))
        try: old=json.loads(e.get("previous_state") or "{}")
        except Exception: old={}
        try: new=json.loads(e.get("new_state") or "{}")
        except Exception: new={}
        oldstate=_s(old.get("lifecycle_state") or old.get("status")); newstate=_s(new.get("lifecycle_state") or new.get("status"))
        if oldstate and newstate and oldstate!=newstate and et in legal and newstate not in legal[et].get(oldstate,set()):
            fails.append({"table":"entity_event","record_id":_id(e,"entity_event"),"reason":f"illegal {et} transition {oldstate}->{newstate}"})
        if newstate:
            last[(et,eid)]=newstate
            last_event_state[(et,eid)]=newstate
    # The stored lifecycle state must match the last emitted legal transition.
    current_tables={"Acknowledgement":("acknowledgements","ack_id","lifecycle_state"),"ChangeRequest":("change_requests","change_request_id","status"),"ProductionOrder":("production_orders","production_order_id","status"),"Approval":("approvals","approval_id","status")}
    for entity,(table,pk,state_field) in current_tables.items():
        current={_s(r.get(pk)):r for r in _rows(dataset,table)}
        for (et,eid),state in last.items():
            if et!=entity or eid not in current: continue
            stored=_s(current[eid].get(state_field))
            emitted=last_event_state.get((entity,eid),"")
            if stored and emitted and stored.upper()!=emitted.upper():
                fails.append({"table":table,"record_id":eid,"reason":f"stored state {stored} differs from last event state {emitted}"})
    return _result("6_lifecycle_transitions",checked,fails)

def validate_duplicates(dataset):
    fails=[]; checked=0
    for table,fields in (("acknowledgements",("po_id","revision_no")),("notifications",("notification_id",)),("production_order_line",("production_order_id","po_line_id")),("notification_recipient",("notification_id","actor_role","recipient_actor_id"))):
        seen=set()
        for r in _rows(dataset,table):
            checked+=1; key=tuple(_s(r.get(f)) for f in fields)
            if key in seen: fails.append({"table":table,"record_id":_id(r,table),"reason":f"duplicate key {key}"})
            seen.add(key)
    return _result("7_duplicate_checks",checked,fails)

def validate_id_formats(dataset):
    fails=[]; checked=0; _,_,gt,_=_ground_truth(dataset)
    for table,pk in PK.items():
        for r in _rows(dataset,table):
            checked+=1; val=_s(r.get(pk))
            if val and not re.fullmatch(r"[A-Z][A-Z0-9-]{2,100}",val): fails.append({"table":table,"record_id":val,"reason":"id format does not match uppercase entity ID convention"})
    # Child IDs must embed parent IDs for versioned and bridge records.
    for table,field,parent in (("inventory_plans","inventory_plan_id","po_line_id"),("acknowledgement_lines","acknowledgement_line_id","ack_id")):
        for r in _rows(dataset,table):
            checked+=1
            if _s(r.get(parent)) and _s(r.get(parent)) not in _s(r.get(field)):
                issue="ACK_WRONG_PO_LINE" if table=="acknowledgement_lines" else None
                fails.append({"table":table,"record_id":_id(r,table),"reason":f"child id does not embed {parent}","issue_type":issue,"related_ids":[_s(r.get(parent))]})
    return _result("8_id_format_checks",checked,fails,gt)

def validate_revision_history(dataset):
    fails=[]; checked=0; _,_,gt,_=_ground_truth(dataset); rows=_rows(dataset,"acknowledgements"); bypo=defaultdict(list)
    for r in rows: bypo[_s(r.get("po_id"))].append(r)
    for po,group in bypo.items():
        checked+=len(group); nums=sorted(int(_num(r.get("revision_no"))) for r in group)
        if len(nums)>1 and nums!=list(range(1,max(nums)+1)):
            fails.append({"table":"acknowledgements","record_id":_s(group[0].get("ack_id")),"reason":"revision numbers are not contiguous"})
        for r in group:
            newer=[x for x in group if _num(x.get("revision_no"))>_num(r.get("revision_no"))]
            if newer and not _s(r.get("superseded_by")):
                fails.append({"table":"acknowledgements","record_id":_id(r,"acknowledgements"),"reason":"older revision lacks superseded_by"})
            if not newer and _s(r.get("superseded_by")):
                fails.append({"table":"acknowledgements","record_id":_id(r,"acknowledgements"),"reason":"newest revision points to another revision"})
    # Effective PromiseDate must point to the newest acknowledgement revision for its PO line.
    promise_groups=defaultdict(list)
    for promise in _rows(dataset,"promise_dates"):
        promise_groups[_s(promise.get("po_line_id"))].append(promise)
    for line,group in promise_groups.items():
        max_revision=max((_num(r.get("revision_no")) for r in group),default=0)
        for r in group:
            checked+=1
            if _s(r.get("status")).upper()=="CURRENT" and _num(r.get("revision_no"))<max_revision:
                fails.append({"table":"promise_dates","record_id":_id(r,"promise_dates"),"reason":"older promise revision is current while a newer revision exists","issue_type":"STALE_REVISION_OVERWRITE"})
    # Injected stale plan rows are an expected exception to effective-version ordering.
    plan_groups=defaultdict(list)
    for plan in _rows(dataset,"inventory_plans"): plan_groups[_s(plan.get("po_line_id"))].append(plan)
    gt_record_ids=_ground_truth(dataset)[3]
    for line,raw_group in plan_groups.items():
        group=sorted(raw_group,key=lambda r:_num(r.get("plan_version")))
        checked+=len(group)
        effective_rows=[r for r in group if _s(r.get("is_effective")) in {"1","True","true"}]
        if group and len(effective_rows)!=1:
            fails.append({"table":"inventory_plans","record_id":_id(group[-1],"inventory_plans"),"reason":"plan history must have exactly one effective version","issue_type":"STALE_REVISION_OVERWRITE" if any(("InventoryPlan",_id(r,"inventory_plans")) in gt_record_ids for r in group) else None})
        # An effective version must also be the greatest plan_version. Exactly one
        # effective flag is not sufficient if the current pointer was overwritten.
        if group and effective_rows and _id(effective_rows[0],"inventory_plans") != _id(group[-1],"inventory_plans"):
            current_id=_id(effective_rows[0],"inventory_plans")
            fails.append({"table":"inventory_plans","record_id":current_id,
                          "reason":"older InventoryPlan version is effective while a newer version exists",
                          "issue_type":"STALE_REVISION_OVERWRITE"})
    return _result("9_revision_history",checked,fails,gt)

def validate_approval_before_apply(dataset):
    fails=[]; checked=0; _,_,gt,_=_ground_truth(dataset)
    approvals=defaultdict(list)
    for a in _rows(dataset,"approvals"): approvals[_s(a.get("change_request_id"))].append(a)
    changes={_s(c.get("change_request_id")):c for c in _rows(dataset,"change_requests")}
    for r in _rows(dataset,"inventory_plans"):
        checked+=1; source=_s(r.get("source")); cid=_s(r.get("change_request_id"))
        if source=="approved_change" and cid:
            change=changes.get(cid,{})
            required=_s(change.get("required_approval_level")).lower()
            valid=[a for a in approvals[cid] if _s(a.get("status"))=="APPROVED" and (not required or _s(a.get("approval_level")).lower()==required)]
            if not valid:
                fails.append({"table":"inventory_plans","record_id":_id(r,"inventory_plans"),"reason":"change-sourced plan lacks approval at required level","issue_type":"UNAPPROVED_CHANGE_UPDATES_PLAN","related_ids":[cid]})
    return _result("10_approval_before_apply",checked,fails,gt)

def validate_downstream_impact(dataset):
    fails=[]; checked=0
    impacts=_rows(dataset,"production_order_impact"); notifs=_rows(dataset,"notifications")
    impacted={_s(i.get("change_request_id")) for i in impacts}; notified={_s(n.get("change_request_id")) for n in notifs}
    orders=_rows(dataset,"production_orders"); lines=_rows(dataset,"production_order_line")
    approvals_by_change=defaultdict(list)
    for a in _rows(dataset,"approvals"): approvals_by_change[_s(a.get("change_request_id"))].append(a)
    po_line_ids_by_po=defaultdict(set)
    for l in _rows(dataset,"po_lines"): po_line_ids_by_po[_s(l.get("po_id"))].add(_s(l.get("po_line_id")))
    orders_by_line=defaultdict(list)
    for o in orders: orders_by_line[_s(o.get("po_line_id"))].append(o)
    for c in _rows(dataset,"change_requests"):
        checked+=1
        kind=_s(c.get("change_type")).lower(); delta=_num(c.get("delta")); cid=_s(c.get("change_request_id"))
        approved=any(_s(a.get("status"))=="APPROVED" for a in approvals_by_change[cid])
        if not approved or _s(c.get("status")).lower() not in {"approved","applied","implemented"}: continue
        if kind=="date" and delta>7 or kind=="quantity" and abs(delta)>10:
            po_lines=po_line_ids_by_po[_s(c.get("po_id"))]
            has_conflict=any(_s(o.get("status")).lower() in {"at_risk","rescheduled","delayed"} for line_id in po_lines for o in orders_by_line[line_id])
            if has_conflict and (cid not in impacted or cid not in notified): fails.append({"table":"change_requests","record_id":cid,"reason":"approved slip/shortfall with affected production order lacks impact or notification"})
    return _result("11_downstream_impact",checked,fails)

def validate_ack_status(dataset):
    fails=[]; checked=0
    lines=_rows(dataset,"acknowledgement_lines")
    sums=defaultdict(lambda:[0.0,0.0]); requested=defaultdict(float)
    for r in lines:
        key=(_s(r.get("ack_id"))); sums[key][0]+=_num(r.get("accepted_qty")); sums[key][1]+=_num(r.get("rejected_qty")); requested[key]+=_num(r.get("requested_qty"))
    for r in _rows(dataset,"acknowledgements"):
        checked+=1; ack=_s(r.get("ack_id")); a=_num(r.get("ack_accepted_qty")); rej=_num(r.get("ack_rejected_qty")); req=a+rej
        status=_s(r.get("status")); expected="ACCEPTED" if rej<=0.00001 else ("REJECTED" if a<=0.00001 else "PARTIALLY_ACCEPTED")
        if status not in {expected,"SUPERSEDED"}: fails.append({"table":"acknowledgements","record_id":ack,"reason":f"stored status {status} inconsistent with accepted/rejected quantities; expected {expected}"})
    return _result("12_acknowledgement_status_consistency",checked,fails)

def validate_ground_truth_coverage(dataset):
    fails=[]; checked=0; records,bytype,byid,allids=_ground_truth(dataset)
    existing=set()
    type_names={"suppliers":"Supplier","purchase_orders":"PurchaseOrder","po_lines":"POLine","acknowledgements":"Acknowledgement","promise_dates":"PromiseDate","change_requests":"ChangeRequest","approvals":"Approval","inventory_plans":"InventoryPlan","production_orders":"ProductionOrder","production_order_impact":"ProductionOrderImpact","notifications":"Notification","actors":"Actor","carriers":"Carrier","warehouses":"Warehouse","items":"Item","entity_event":"EntityEvent"}
    for table,pk in PK.items(): existing.update((type_names.get(table,table.title().replace("_","")),_s(r.get(pk))) for r in _rows(dataset,table))
    existing.update(("AcknowledgementLine",_s(r.get("acknowledgement_line_id"))) for r in _rows(dataset,"acknowledgement_lines"))
    for g in records:
        checked+=1; typ=_s(g.get("record_type")); rid=_s(g.get("record_id"))
        if rid and (typ,rid) not in existing:
            fails.append({"table":"ground_truth_records","record_id":rid,"reason":f"ground-truth record {typ}/{rid} missing from dataset"})
    # Every anomaly that can be recognized from the deliberately malformed table shape must be represented.
    ack_by_id={_s(a.get("ack_id")):a for a in _rows(dataset,"acknowledgements")}
    line_by_id={_s(a.get("po_line_id")):a for a in _rows(dataset,"po_lines")}
    for r in _rows(dataset,"acknowledgement_lines"):
        ack=ack_by_id.get(_s(r.get("ack_id")))
        line=line_by_id.get(_s(r.get("po_line_id")))
        if ack and (line is None or _s(line.get("po_id"))!=_s(ack.get("po_id"))):
            checked+=1
            if not any(_s(g.get("issue_type"))=="ACK_WRONG_PO_LINE" and _s(g.get("record_id"))==_id(r,"acknowledgement_lines") for g in records): fails.append({"table":"acknowledgement_lines","record_id":_id(r,"acknowledgement_lines"),"reason":"unlabelled invalid ACK line reference"})
    # Bidirectional coverage: structural anomalies must have matching target labels.
    po_by_id={_s(p.get("po_id")):p for p in _rows(dataset,"purchase_orders")}
    promise_groups=defaultdict(list)
    for promise in _rows(dataset,"promise_dates"): promise_groups[_s(promise.get("po_line_id"))].append(promise)
    for r in _rows(dataset,"promise_dates"):
        po=po_by_id.get(_s(r.get("po_id")))
        if po and _day(r.get("promised_date")) and _day(po.get("order_date")) and _day(r.get("promised_date")) < _day(po.get("order_date")):
            checked+=1
            if not any(_s(g.get("issue_type"))=="PROMISE_DATE_BEFORE_ORDER_DATE" and _s(g.get("record_id"))==_id(r,"promise_dates") for g in records): fails.append({"table":"promise_dates","record_id":_id(r,"promise_dates"),"reason":"unlabelled promise-before-order anomaly"})
    approval_by_change=defaultdict(list)
    for a in _rows(dataset,"approvals"): approval_by_change[_s(a.get("change_request_id"))].append(a)
    for r in _rows(dataset,"inventory_plans"):
        cid=_s(r.get("change_request_id"))
        if _s(r.get("source"))=="approved_change" and cid and not any(_s(a.get("status"))=="APPROVED" for a in approval_by_change[cid]):
            checked+=1
            if not any(_s(g.get("issue_type"))=="UNAPPROVED_CHANGE_UPDATES_PLAN" and _s(g.get("record_id"))==_id(r,"inventory_plans") for g in records): fails.append({"table":"inventory_plans","record_id":_id(r,"inventory_plans"),"reason":"unlabelled unapproved-plan anomaly"})
    for line,group in promise_groups.items():
        max_revision=max((_num(r.get("revision_no")) for r in group),default=0)
        for r in group:
            if _s(r.get("status")).upper()=="CURRENT" and _num(r.get("revision_no"))<max_revision:
                checked+=1
                if not any(_s(g.get("issue_type"))=="STALE_REVISION_OVERWRITE" and _s(g.get("record_id"))==_id(r,"promise_dates") for g in records): fails.append({"table":"promise_dates","record_id":_id(r,"promise_dates"),"reason":"unlabelled stale-revision anomaly"})
    return _result("13_ground_truth_coverage",checked,fails)

def validate_leakage(directory):
    fails=[]; checked=0; root=Path(directory)
    for p in root.glob("*.csv"):
        if p.name=="ground_truth.csv": continue
        checked+=1
        try: cols=pd.read_csv(p,nrows=0).columns
        except Exception as e: fails.append({"table":p.name,"record_id":p.name,"reason":f"cannot read CSV header: {e}"}); continue
        leaked={c for c in cols if c.lower() in {"ground_truth","issue_type","boundary"}}
        if leaked: fails.append({"table":p.name,"record_id":p.name,"reason":f"label leakage columns: {sorted(leaked)}"})
    return _result("14_input_label_leakage",checked,fails)

def validate_secret_scan(dataset):
    """Scan tracked repository files for common credential/token signatures."""
    import os, re, subprocess
    repo_root = Path(__file__).resolve().parents[3]
    patterns = [
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{24,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ]
    try:
        tracked = subprocess.run(["git", "-C", str(repo_root), "ls-files", "-z"], capture_output=True, check=True).stdout.split(b"\0")
        paths = [repo_root / os.fsdecode(p) for p in tracked if p]
    except Exception:
        paths = [p for p in repo_root.rglob("*") if p.is_file() and ".git" not in p.parts]
    failures=[]; checked=0
    for path in paths:
        if not path.is_file() or path.stat().st_size > 5_000_000: continue
        try: content=path.read_text(encoding="utf-8", errors="ignore")
        except OSError: continue
        checked += 1
        for pattern in patterns:
            if pattern.search(content): failures.append({"table":"repository_files","record_id":str(path.relative_to(repo_root)),"reason":f"credential-looking pattern matched: {pattern.pattern}"})
    return _result("15_committed_file_secret_scan", checked, failures)


VALIDATORS=(validate_primary_keys,validate_foreign_keys,validate_enums,validate_dates,validate_arithmetic,validate_lifecycle,validate_duplicates,validate_id_formats,validate_revision_history,validate_approval_before_apply,validate_downstream_impact,validate_ack_status,validate_ground_truth_coverage,validate_secret_scan)

def validate_dataset(dataset: Mapping[str,Any], directory: str|Path|None=None) -> dict[str,Any]:
    results=[fn(dataset) for fn in VALIDATORS]
    if directory is not None: results.append(validate_leakage(directory))
    overall="FAIL" if any(r.status=="FAIL" for r in results) else "PASS"
    return {"overall_status":overall,"checks":[r.to_dict() for r in results],"summary":{"check_count":len(results),"passed":sum(r.status=="PASS" for r in results),"expected_anomaly_checks":sum(r.status=="EXPECTED_ANOMALY" for r in results),"failed":sum(r.status=="FAIL" for r in results)}}

def validate_directory(directory: str|Path, *, write_reports: bool=True) -> dict[str,Any]:
    root=Path(directory); dataset=load_dataset(root); report=validate_dataset(dataset,root)
    if write_reports:
        (root/"validation_summary.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        lines=["# Supplier Acknowledgement Dataset Validation", "", f"**Overall status: {report['overall_status']}**", "", "| Check | Status | Checked rows | Failures | Expected anomalies | Unknown failures |", "|---|---:|---:|---:|---:|---:|"]
        for c in report["checks"]: lines.append(f"| {c['check_name']} | {c['status']} | {c['checked_rows']} | {c['failure_count']} | {c['expected_anomaly_count']} | {c['unknown_failure_count']} |")
        for c in report["checks"]:
            if c["sample_failures"]:
                lines.extend(["",f"## {c['check_name']}",""])
                for f in c["sample_failures"]: lines.append(f"- `{f.get('record_id','')}`: {f.get('reason','')} (issue_type={f.get('issue_type') or 'unknown'})")
        (root/"validation_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report
