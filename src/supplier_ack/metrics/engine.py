"""Deterministic, source-derived workflow metrics for CSV exports or SQLite runtime DBs."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

TABLES = ["suppliers","purchase_orders","po_lines","acknowledgements","acknowledgement_lines","promise_dates","change_requests","approvals","inventory_plans","production_orders","production_order_impact","notifications","notification_recipient","actors","entity_event","ground_truth"]

def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype_backend="numpy_nullable", keep_default_na=True, low_memory=False) if path.exists() else pd.DataFrame()

def load_dataset(path: str | Path) -> dict[str, pd.DataFrame]:
    root = Path(path)
    if root.is_file() and root.suffix in {".db", ".sqlite", ".sqlite3"}:
        con = sqlite3.connect(root)
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {n: pd.read_sql_query(f' SELECT * FROM "{n.replace(chr(34), chr(34)*2)}"', con) for n in names}
        finally: con.close()
    csv_root = root / "csv" if (root / "csv").is_dir() else root
    result = {}
    for name in TABLES:
        f = csv_root / f"{name}.csv"
        if not f.exists() and name == "ground_truth": f = root / "ground_truth.csv"
        result[name] = _read_csv(f)
    # A live exception queue can augment synthetic labelled anomaly rows.
    return result

def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")
def _pct(n: float, d: float) -> float:
    return round(100.0*n/d, 4) if d else 0.0

def compute_metrics(ds: dict[str, pd.DataFrame]) -> dict[str, Any]:
    suppliers, pos, lines = (ds.get(k, pd.DataFrame()).copy() for k in ("suppliers","purchase_orders","po_lines"))
    acks, acklines, promises = (ds.get(k, pd.DataFrame()).copy() for k in ("acknowledgements","acknowledgement_lines","promise_dates"))
    changes, approvals = (ds.get(k, pd.DataFrame()).copy() for k in ("change_requests","approvals"))
    plans, prod, impacts = (ds.get(k, pd.DataFrame()).copy() for k in ("inventory_plans","production_orders","production_order_impact"))
    notifs, recipients, gt = (ds.get(k, pd.DataFrame()).copy() for k in ("notifications","notification_recipient","ground_truth"))
    # latest ack revision per PO/line is the current outcome; revision rate is PO-level.
    if not acks.empty:
        acks["revision_no"] = _num(acks.get("revision_no", pd.Series(index=acks.index,dtype=float))).fillna(0)
        latest_ack = acks.sort_values(["revision_no","acknowledged_at"], na_position="first").drop_duplicates([c for c in ["po_id","po_line_id"] if c in acks], keep="last") if "po_line_id" in acks else acks.sort_values("revision_no").drop_duplicates("po_id", keep="last")
        acked_pos = set(acks.po_id.dropna().astype(str))
        rev_pos = acks.groupby("po_id").revision_no.max()
    else: latest_ack=acks; acked_pos=set(); rev_pos=pd.Series(dtype=float)
    po_supplier = pos.set_index("po_id").supplier_id.to_dict() if not pos.empty and "supplier_id" in pos else {}
    po_ids=set(pos.po_id.astype(str)) if not pos.empty else set()
    # Promise lateness/slips are recalculated from dates, not stored scores.
    if not promises.empty:
        req = lines.set_index("po_line_id").get("required_date", pd.Series(dtype=object)).to_dict() if not lines.empty else {}
        promises["_promise_date"] = pd.to_datetime(promises.get("promised_date"), errors="coerce")
        promises["_requested_date"] = promises.get("po_line_id", pd.Series(index=promises.index,dtype=object)).map(req).pipe(pd.to_datetime, errors="coerce")
        promises["_slip"] = (promises._promise_date - promises._requested_date).dt.days
        current_promises = promises[promises.get("status", pd.Series(index=promises.index,dtype=object)).astype(str).str.upper().eq("CURRENT")].copy()
    else:
        promises["_slip"] = pd.Series(dtype=float); current_promises=promises.copy()
    supplier_rows=[]
    for _, s in suppliers.iterrows():
        sid=str(s.get("supplier_id")); po_for=set(pos.loc[pos.supplier_id.astype(str).eq(sid),"po_id"].astype(str)) if not pos.empty else set()
        ack_for=acks[acks.get("supplier_id", acks.get("po_id", pd.Series(index=acks.index,dtype=object)).map(po_supplier)).astype(str).eq(sid)] if not acks.empty else acks
        # Rate denominator is POs belonging to supplier, numerator distinct POs with any acknowledgement.
        n_po=len(po_for); n_acked=len(po_for & acked_pos)
        pr=current_promises[current_promises.po_id.astype(str).isin(po_for)] if not current_promises.empty else current_promises
        slips=_num(pr.get("_slip",pd.Series(dtype=float))).dropna()
        latest_lines=latest_ack[latest_ack.po_id.astype(str).isin(po_for)] if not latest_ack.empty else latest_ack
        partial=float(latest_lines.status.astype(str).str.upper().str.contains("PARTIAL").mean()*100) if not latest_lines.empty else 0.0
        silent=len(po_for-acked_pos)
        revisions=int((rev_pos.reindex(list(po_for)).fillna(0)>1).sum()) if n_po else 0
        supplier_rows.append({"supplier_id":sid,"supplier_name":s.get("supplier_name"),"po_count":n_po,"acknowledged_po_count":n_acked,"ack_rate_pct":_pct(n_acked,n_po),"promise_count":len(pr),"on_time_promise_rate_pct":_pct(int((slips<=0).sum()),len(slips)) if len(slips) else None,"avg_slip_days":round(float(slips.mean()),4) if len(slips) else None,"median_slip_days":round(float(slips.median()),4) if len(slips) else None,"partial_acceptance_rate_pct":round(partial,4),"silence_rate_pct":_pct(silent,n_po),"revision_rate_pct":_pct(revisions,n_po),"revision_po_count":revisions,"silent_po_count":silent})
    scorecard=pd.DataFrame(supplier_rows)
    overall={"purchase_orders":len(pos),"acknowledged_pos":len(acked_pos),"ack_rate_pct":_pct(len(acked_pos),len(pos)),"promise_count":len(current_promises),"on_time_promise_rate_pct":_pct(int((_num(current_promises.get("_slip",pd.Series(dtype=float)).dropna())<=0).sum()),int(_num(current_promises.get("_slip",pd.Series(dtype=float)).dropna()).count())),"avg_slip_days":round(float(_num(current_promises.get("_slip",pd.Series(dtype=float))).dropna().mean()),4) if not current_promises.empty else 0.0,"median_slip_days":round(float(_num(current_promises.get("_slip",pd.Series(dtype=float))).dropna().median()),4) if not current_promises.empty else 0.0,"partial_acceptance_rate_pct":round(float(latest_ack.status.astype(str).str.upper().str.contains("PARTIAL").mean()*100),4) if not latest_ack.empty else 0.0,"silence_rate_pct":_pct(len(po_ids-acked_pos),len(pos)),"revision_rate_pct":_pct(int((rev_pos>1).sum()),len(pos))}
    # Change outcome and approval turnaround metrics.
    change_counts=changes.get("change_type",pd.Series(dtype=object)).astype(str).value_counts().sort_index().to_dict() if not changes.empty else {}
    outcome_counts={}
    if not changes.empty:
        statuses=changes.status.astype(str).str.upper()
        high=changes.required_approval_level.astype(str).str.upper().str.contains("OPERATIONS|MANAGER")
        rejected=statuses.str.contains("REJECT")
        approved=statuses.str.contains("APPROV|IMPLEMENT|APPLIED") & ~rejected
        outcome_counts={"auto_approved":int((approved & ~high).sum()),"escalated":int((high & ~rejected).sum()),"rejected":int(rejected.sum())}
        outcome_counts={k:{"count":v,"pct":_pct(v,len(changes))} for k,v in outcome_counts.items()}
    else: outcome_counts={k:{"count":0,"pct":0.0} for k in ("auto_approved","escalated","rejected")}
    approval_rows=[]
    if not approvals.empty:
        approvals["_requested"] = pd.to_datetime(approvals.get("requested_at"),errors="coerce")
        approvals["_decided"] = pd.to_datetime(approvals.get("decided_at"),errors="coerce")
        approvals["turnaround_hours"]=(approvals._decided-approvals._requested).dt.total_seconds()/3600
        for level,g in approvals.groupby("approval_level",dropna=False): approval_rows.append({"approval_level":str(level),"decisions":int(g._decided.notna().sum()),"mean_turnaround_hours":round(float(g.turnaround_hours.dropna().mean()),4) if g.turnaround_hours.notna().any() else None,"median_turnaround_hours":round(float(g.turnaround_hours.dropna().median()),4) if g.turnaround_hours.notna().any() else None})
    rejection_reasons=changes.loc[changes.status.astype(str).str.upper().str.contains("REJECT"),"reason_text"].fillna("unspecified").value_counts().to_dict() if not changes.empty and "reason_text" in changes else {}
    # Schedule impact metrics.
    status=prod.get("status",pd.Series(dtype=object)).astype(str).str.upper() if not prod.empty else pd.Series(dtype=object)
    risk=prod.get("at_risk",pd.Series(False,index=prod.index)).astype(str).str.lower().isin(["true","1","yes"])
    delay=_num(prod.get("delay_days",pd.Series(dtype=float))).fillna(0)
    short=_num(prod.get("shortfall_qty",pd.Series(dtype=float))).fillna(0)
    impact_metrics={"production_orders":len(prod),"at_risk_count":int((risk|status.isin(["AT_RISK","DELAYED"])).sum()),"rescheduled_count":int(status.eq("RESCHEDULED").sum()),"total_delay_days":round(float(delay.clip(lower=0).sum()),4),"shortfall_quantity":round(float(short.clip(lower=0).sum()),4),"severity_distribution":impacts.get("severity",pd.Series(dtype=object)).astype(str).value_counts().sort_index().to_dict() if not impacts.empty else {},"impact_count":len(impacts)}
    # Projected receipts grouped by ISO week; baseline requested supply is grouped by required date.
    if not lines.empty:
        lines["_required_week"] = pd.to_datetime(lines.get("required_date"),errors="coerce").dt.to_period("W").astype(str)
        requested=lines.assign(_qty=_num(lines.get("requested_qty",pd.Series(index=lines.index,dtype=float)))).groupby("_required_week")._qty.sum()
    else: requested=pd.Series(dtype=float)
    if not current_promises.empty:
        current_promises["_week"] = current_promises._promise_date.dt.to_period("W").astype(str)
        projected=current_promises.assign(_qty=_num(current_promises.get("promised_qty",pd.Series(index=current_promises.index,dtype=float)))).groupby("_week")._qty.sum()
    else: projected=pd.Series(dtype=float)
    weeks=sorted(set(requested.index.astype(str))|set(projected.index.astype(str)))
    supply_timeline=pd.DataFrame([{"week":w,"requested_qty":round(float(requested.get(w,0)),4),"projected_receipts_qty":round(float(projected.get(w,0)),4)} for w in weeks])
    churn=plans.groupby("po_line_id").size() if not plans.empty else pd.Series(dtype=int)
    supply_metrics={"weekly_projected_receipts":supply_timeline.to_dict("records"),"plan_version_churn":{"lines":int(churn.size),"total_versions":int(churn.sum()),"mean_versions_per_line":round(float(churn.mean()),4) if len(churn) else 0.0,"max_versions_per_line":int(churn.max()) if len(churn) else 0}}
    # Exceptions are explicit runtime exceptions when present plus labelled ground-truth anomalies.
    # Ground truth also contains expected outcomes for ordinary changes and impacted
    # orders; those are evaluation labels, not exceptions. Only non-null issue_type
    # rows are anomalies. Runtime exception tables are included when reading an app DB.
    exceptions=gt.copy()
    if not exceptions.empty and "issue_type" in exceptions:
        exceptions=exceptions[exceptions.issue_type.notna() & exceptions.issue_type.astype(str).str.strip().ne("")].copy()
    runtime_exception_table = "runtime_exception" if "runtime_exception" in ds else "runtime_exceptions" if "runtime_exceptions" in ds else None
    if runtime_exception_table and not ds[runtime_exception_table].empty:
        runtime_ex=ds[runtime_exception_table].copy()
        runtime_ex["exception_type"] = runtime_ex.get("rule_id", runtime_ex.get("exception_type", "runtime_exception"))
        runtime_ex["severity"] = runtime_ex.get("severity", "ERROR")
        runtime_ex["exception_status"] = runtime_ex.get("status", "OPEN")
        runtime_ex["record_type"] = runtime_ex.get("entity_type", "RuntimeException")
        runtime_ex["record_id"] = runtime_ex.get("entity_id", runtime_ex.get("exception_id", ""))
        runtime_ex["issue_type"] = runtime_ex["exception_type"]
        runtime_ex["expected_decision"] = runtime_ex.get("message", "Inspect runtime exception trace")
        runtime_ex["related_entity_ids"] = runtime_ex.get("entity_trace", runtime_ex.get("entity_id", ""))
        exceptions=pd.concat([exceptions,runtime_ex],ignore_index=True,sort=False)
    if not exceptions.empty:
        exceptions["exception_type"] = exceptions.get("issue_type",exceptions.get("exception_type",pd.Series(index=exceptions.index,dtype=object))).fillna("labelled_case")
        exceptions["severity"] = exceptions.get("expected_severity",exceptions.get("severity",pd.Series(index=exceptions.index,dtype=object))).fillna("INFO")
        exceptions["exception_status"] = exceptions.get("exception_status",pd.Series("OPEN",index=exceptions.index)).fillna("OPEN")
    else: exceptions=pd.DataFrame(columns=["record_type","record_id","issue_type","expected_decision","related_entity_ids","expected_severity","notes","exception_type","severity","exception_status"])
    ex_type=exceptions.get("exception_type",pd.Series(dtype=object)).astype(str).value_counts().sort_index().to_dict()
    ex_sev=exceptions.get("severity",pd.Series(dtype=object)).astype(str).value_counts().sort_index().to_dict()
    exception_metrics={"total":len(exceptions),"by_type":ex_type,"by_severity":ex_sev,"open":int(exceptions.get("exception_status",pd.Series(dtype=object)).astype(str).eq("OPEN").sum()),"resolved":int(exceptions.get("exception_status",pd.Series(dtype=object)).astype(str).eq("RESOLVED").sum())}
    # Workflow metrics.
    if not acks.empty:
        perpo=acks.groupby("po_id").revision_no.max()
        po_latest=acks.sort_values("revision_no").drop_duplicates("po_id",keep="last")
        pstatus=po_latest.status.astype(str).str.upper()
        fully=int(pstatus.str.contains("ACCEPTED").sum()-pstatus.str.contains("PARTIAL").sum())
        partial_pos=int(pstatus.str.contains("PARTIAL").sum())
    else: fully=partial_pos=0
    fully_silent=len(po_ids-acked_pos)
    plan_updates=[]
    if not plans.empty and not acks.empty:
        first_ack=acks.sort_values("acknowledged_at").drop_duplicates("po_id").set_index("po_id").acknowledged_at
        effective=plans[plans.get("is_effective",pd.Series(index=plans.index,dtype=object)).astype(str).str.lower().isin(["true","1","yes"])].copy()
        # Baseline rows predate the acknowledgement by design; only actual later
        # projection updates belong in acknowledgement-to-plan-update latency.
        if not effective.empty and "source" in effective:
            effective=effective[effective.source.astype(str).ne("po_baseline")]
        if not effective.empty:
            effective["_created"]=pd.to_datetime(effective.created_at,errors="coerce")
            for poid,g in effective.groupby("po_id"):
                if str(poid) in first_ack.index:
                    acktime=pd.to_datetime(first_ack.loc[str(poid)],errors="coerce")
                    hours=((g._created-acktime).dt.total_seconds()/3600).dropna()
                    plan_updates.extend(hours[hours>=0].tolist())
    notif_types=notifs.get("not_type",pd.Series(dtype=object)).astype(str).value_counts().sort_index().to_dict() if not notifs.empty else {}
    if not recipients.empty and not notifs.empty:
        notif_role=recipients.merge(notifs[["notification_id","not_type"]].drop_duplicates(),on="notification_id",how="left").groupby("actor_role").size().sort_index().to_dict()
    else: notif_role={}
    workflow_metrics={"po_fully_acknowledged":fully,"po_partially_acknowledged":partial_pos,"po_silent":fully_silent,"median_ack_to_plan_update_hours":round(float(np.median(plan_updates)),4) if plan_updates else None,"notification_volume_by_type":notif_types,"notification_volume_by_recipient_role":notif_role}
    # Decision log preserves every approval row and compared source values.
    decision_log=pd.DataFrame()
    if not approvals.empty:
        cols=[c for c in ["approval_id","change_request_id","approval_round","approver_role","approval_level","approver_actor_id","status","requested_at","decided_at","decision_reason","comments","threshold_name","threshold_value"] if c in approvals]
        decision_log=approvals[cols].copy()
        if not changes.empty:
            vals=changes[[c for c in ["change_request_id","change_type","old_value","new_value","delta","delta_pct","required_approval_level","reason_text"] if c in changes]].drop_duplicates("change_request_id")
            decision_log=decision_log.merge(vals,on="change_request_id",how="left",suffixes=("","_change"))
    if "runtime_decision" in ds and not ds["runtime_decision"].empty:
        rd=ds["runtime_decision"].copy()
        rd=rd.rename(columns={"decision_id":"approval_id","decision":"status","rule_id":"threshold_name","values_compared":"values_compared_json","required_approval_level":"approval_level","approver_actor_id":"approver_actor_id","created_at":"decided_at"})
        rd["approver_role"]="runtime"
        for col in set(decision_log.columns)|set(rd.columns):
            if col not in decision_log: decision_log[col]=pd.NA
            if col not in rd: rd[col]=pd.NA
        decision_log=pd.concat([decision_log,rd[decision_log.columns]],ignore_index=True,sort=False)
    # Impact view combines required/actual schedule, supplier and source change.
    impact_report=impacts.copy()
    if not impact_report.empty:
        if not prod.empty: impact_report=impact_report.merge(prod[[c for c in ["production_order_id","po_id","required_by_date","planned_start_date","status","priority"] if c in prod]],on="production_order_id",how="left",suffixes=("","_order"))
        if not pos.empty: impact_report=impact_report.merge(pos[["po_id","supplier_id"]].drop_duplicates("po_id"),on="po_id",how="left")
        if not suppliers.empty: impact_report=impact_report.merge(suppliers[["supplier_id","supplier_name"]],on="supplier_id",how="left")
        if not changes.empty: impact_report=impact_report.merge(changes[[c for c in ["change_request_id","change_type","old_value","new_value","delta_pct","status"] if c in changes]].drop_duplicates("change_request_id"),on="change_request_id",how="left",suffixes=("","_change"))
    return {"overall":overall,"supplier_scorecard":scorecard,"change_metrics":{"by_type":change_counts,"outcomes":outcome_counts,"approval_turnaround":approval_rows,"rejection_reasons":rejection_reasons,"total_changes":len(changes)},"schedule_impact":impact_metrics,"supply_metrics":supply_metrics,"exceptions":exceptions,"exception_metrics":exception_metrics,"workflow_metrics":workflow_metrics,"decision_log":decision_log,"impact_report":impact_report,"supply_timeline":supply_timeline,"dataframes":ds}
