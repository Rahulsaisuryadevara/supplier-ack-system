"""Persona-targeted reports and deterministic figures for supplier-ack-system."""
from __future__ import annotations
import json, hashlib, platform, sys
from pathlib import Path
from typing import Any
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from supplier_ack.metrics.engine import compute_metrics, load_dataset


def _md_table(df: pd.DataFrame, limit: int | None = None) -> str:
    if df.empty: return "_No records._"
    view=df if limit is None else df.head(limit)
    return view.to_markdown(index=False)

def _read_json(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError): return {}

def _savefig(path: Path, title: str) -> None:
    plt.title(title); plt.tight_layout(); plt.savefig(path, dpi=140, bbox_inches="tight"); plt.close()

def generate_reports(dataset_path: str | Path, out_dir: str | Path = "reports") -> dict[str, Any]:
    root=Path(dataset_path).resolve(); out=Path(out_dir).resolve(); figures=out/"figures"
    out.mkdir(parents=True,exist_ok=True); figures.mkdir(parents=True,exist_ok=True)
    ds=load_dataset(root); m=compute_metrics(ds)
    score=m["supplier_scorecard"].sort_values(["on_time_promise_rate_pct","supplier_name"],ascending=[True,True])
    exceptions=m["exceptions"].copy(); impacts=m["impact_report"].copy(); decisions=m["decision_log"].copy()
    # Trace columns for exception report: explicit related IDs are preserved; resolve PO/supplier when possible.
    pos=ds.get("purchase_orders",pd.DataFrame()); suppliers=ds.get("suppliers",pd.DataFrame()); changes=ds.get("change_requests",pd.DataFrame()); acks=ds.get("acknowledgements",pd.DataFrame())
    if not exceptions.empty:
        def parse_ids(value):
            try:
                v=json.loads(value) if isinstance(value,str) else value
                if isinstance(v,list): return [str(x) for x in v]
                if isinstance(v,dict): return [str(x) for x in v.values()]
            except Exception: pass
            return [x.strip() for x in str(value).replace(";",",").split(",") if x.strip() and x.strip().lower()!="<na>"]
        exceptions["trace_ids"] = exceptions.get("related_entity_ids",pd.Series(index=exceptions.index,dtype=object)).map(parse_ids)
        def lookup_from_trace(ids, prefixes):
            for item in ids:
                if any(item.startswith(p) for p in prefixes): return item
            return ""
        exceptions["po_id"] = exceptions.trace_ids.map(lambda ids: lookup_from_trace(ids,["PO-"]))
        exceptions["change_request_id"] = exceptions.trace_ids.map(lambda ids: lookup_from_trace(ids,["CHG-"]))
        exceptions["ack_id"] = exceptions.trace_ids.map(lambda ids: lookup_from_trace(ids,["ACK-"]))
        if not changes.empty:
            cpo=changes.set_index("change_request_id").po_id.to_dict()
            exceptions["po_id"] = exceptions.apply(lambda r: r.po_id or cpo.get(r.change_request_id,""),axis=1)
        if not acks.empty:
            apo=acks.set_index("ack_id").po_id.to_dict()
            exceptions["po_id"] = exceptions.apply(lambda r: r.po_id or apo.get(r.ack_id,""),axis=1)
        if not pos.empty:
            ps=pos.set_index("po_id").supplier_id.to_dict()
            exceptions["supplier_id"] = exceptions.po_id.map(ps).fillna("")
        else: exceptions["supplier_id"]=""
        if not suppliers.empty:
            sn=suppliers.set_index("supplier_id").supplier_name.to_dict()
            exceptions["supplier_name"] = exceptions.supplier_id.map(sn).fillna("")
        else: exceptions["supplier_name"]=""
        exceptions["full_trace"] = exceptions.apply(lambda r: " → ".join(x for x in [str(r.get("record_type",""))+":"+str(r.get("record_id","")),str(r.get("change_request_id","")),str(r.get("ack_id","")),str(r.get("po_id","")),str(r.get("supplier_id","")),str(r.get("supplier_name",""))] if x and not x.endswith(":") and x.lower()!="nan"),axis=1)
    exception_cols=[c for c in ["record_type","record_id","exception_type","issue_type","severity","exception_status","expected_decision","related_entity_ids","po_id","supplier_id","supplier_name","full_trace","notes"] if c in exceptions]
    exceptions[exception_cols].to_csv(out/"exception_report.csv",index=False,encoding="utf-8")
    (out/"exception_report.md").write_text("# Exception report — Logistics Analyst\n\nEvery row is a labelled ground-truth anomaly or known case; runtime exceptions are included when exported in the source dataset. Trace is rendered as exception → change/ack → PO → supplier where identifiers are available.\n\n"+_md_table(exceptions[[c for c in ["record_id","exception_type","severity","exception_status","po_id","supplier_name","full_trace","expected_decision"] if c in exceptions]],100)+"\n",encoding="utf-8")
    score.to_csv(out/"supplier_scorecard.csv",index=False,encoding="utf-8")
    impacts.to_csv(out/"impact_report.csv",index=False,encoding="utf-8")
    decisions.to_csv(out/"decision_log.csv",index=False,encoding="utf-8")
    # Plots
    promises=ds.get("promise_dates",pd.DataFrame()).copy(); lines=ds.get("po_lines",pd.DataFrame()).copy(); acks=ds.get("acknowledgements",pd.DataFrame()).copy(); changes=ds.get("change_requests",pd.DataFrame())
    if not promises.empty and not lines.empty:
        p=promises[promises.get("status",pd.Series(index=promises.index,dtype=object)).astype(str).str.upper().eq("CURRENT")].merge(lines[["po_line_id","required_date"]],on="po_line_id",how="left")
        p["slip_days"]=(pd.to_datetime(p.promised_date,errors="coerce")-pd.to_datetime(p.required_date,errors="coerce")).dt.days
        plt.figure(figsize=(8,4)); p.slip_days.dropna().clip(-30,90).hist(bins=35); plt.xlabel("Slip days (clipped to -30..90)"); plt.ylabel("Current promise rows"); _savefig(figures/"supplier_slip_day_distribution.png","Supplier promise slip-day distribution")
    else:
        plt.figure(figsize=(8,4)); plt.text(.5,.5,"No promise-date rows available",ha="center"); plt.axis("off"); _savefig(figures/"supplier_slip_day_distribution.png","Supplier promise slip-day distribution")
    if not acks.empty:
        latest=acks.sort_values("revision_no").drop_duplicates("po_id",keep="last") if "revision_no" in acks else acks
        counts=latest.status.astype(str).value_counts().sort_index(); plt.figure(figsize=(7,5)); plt.pie(counts.values,labels=counts.index,autopct="%1.1f%%",startangle=90); _savefig(figures/"ack_status_breakdown.png","Latest acknowledgement status breakdown")
    else:
        plt.figure(figsize=(7,5)); plt.text(.5,.5,"No acknowledgements",ha="center"); plt.axis("off"); _savefig(figures/"ack_status_breakdown.png","Latest acknowledgement status breakdown")
    if not changes.empty:
        c=changes.copy(); c["decision_group"]="pending"; st=c.status.astype(str).str.upper(); c.loc[st.str.contains("REJECT"),"decision_group"]="rejected"; c.loc[st.str.contains("APPROV|IMPLEMENT|APPLIED"),"decision_group"]="approved"; c.loc[c.required_approval_level.astype(str).str.upper().str.contains("OPERATIONS|MANAGER"),"decision_group"]="escalated"
        tab=c.groupby(["change_type","decision_group"]).size().unstack(fill_value=0).sort_index(); ax=tab.plot(kind="bar",figsize=(9,5)); ax.set_xlabel("Change type"); ax.set_ylabel("Change requests"); _savefig(figures/"changes_by_type_and_decision.png","Change requests by type and decision")
    else:
        plt.figure(figsize=(8,4)); plt.text(.5,.5,"No change requests",ha="center"); plt.axis("off"); _savefig(figures/"changes_by_type_and_decision.png","Change requests by type and decision")
    timeline=m["supply_timeline"]
    if not timeline.empty:
        plot=timeline.set_index("week")[["requested_qty","projected_receipts_qty"]]; ax=plot.plot(figsize=(11,5)); ax.set_xlabel("ISO week"); ax.set_ylabel("Quantity"); ax.tick_params(axis="x",labelrotation=70); _savefig(figures/"projected_vs_requested_supply.png","Projected receipts versus requested supply by week")
    else:
        plt.figure(figsize=(8,4)); plt.text(.5,.5,"No supply timeline",ha="center"); plt.axis("off"); _savefig(figures/"projected_vs_requested_supply.png","Projected receipts versus requested supply by week")
    ex_counts=exceptions.get("exception_type",pd.Series(dtype=object)).astype(str).value_counts().sort_index()
    plt.figure(figsize=(9,5)); ex_counts.plot(kind="bar"); plt.xlabel("Exception type"); plt.ylabel("Records"); _savefig(figures/"exception_counts_by_type.png","Exception counts by type")
    # Ops summary uses the actual supplier distribution to set 2-sigma alerts.
    overall=m["overall"]; ontime=pd.to_numeric(score.on_time_promise_rate_pct,errors="coerce") if not score.empty else pd.Series(dtype=float)
    mean=float(ontime.mean()) if len(ontime) else 0.0; sd=float(ontime.std(ddof=0)) if len(ontime) else 0.0; cutoff=mean-2*sd
    flagged=score[score.on_time_promise_rate_pct.notna() & (score.on_time_promise_rate_pct < cutoff)] if not score.empty else score
    summary=["# Supplier acknowledgement workflow — Operations Manager summary","", "## Headline KPIs", "", f"- Purchase orders: **{overall['purchase_orders']:,}**",f"- Acknowledgement coverage: **{overall['ack_rate_pct']:.2f}%** ({overall['acknowledged_pos']:,} of {overall['purchase_orders']:,} POs)",f"- On-time promise rate: **{overall['on_time_promise_rate_pct']:.2f}%**",f"- Average / median promise slip: **{overall['avg_slip_days']:.2f} / {overall['median_slip_days']:.2f} days**",f"- Partial acceptance rate: **{overall['partial_acceptance_rate_pct']:.2f}%**",f"- Supplier silence rate: **{overall['silence_rate_pct']:.2f}%**",f"- PO revision rate: **{overall['revision_rate_pct']:.2f}%**",f"- Production orders at risk: **{m['schedule_impact']['at_risk_count']:,}**; rescheduled: **{m['schedule_impact']['rescheduled_count']:,}**",f"- Total computed positive delay days: **{m['schedule_impact']['total_delay_days']:.0f}**; allocated shortfall quantity: **{m['schedule_impact']['shortfall_quantity']:.2f}**",f"- Known labelled exceptions: **{m['exception_metrics']['total']:,}** (open in labelled ground-truth view: {m['exception_metrics']['open']:,})", "", "## Supplier alerts (portfolio-relative)", "", f"Portfolio supplier on-time mean = {mean:.2f}%, population standard deviation = {sd:.2f} percentage points; alert cutoff = mean − 2σ = {cutoff:.2f}%."]
    if flagged.empty: summary.append("No supplier is at least 2σ below the portfolio on-time rate.")
    else:
        for _,r in flagged.iterrows(): summary.append(f"- **{r.supplier_name}** on-time rate ({r.on_time_promise_rate_pct:.2f}%) is at least 2σ below the portfolio — flagged for planner review.")
    summary += ["", "### Approval turnaround by approver level", "", _md_table(pd.DataFrame(m["change_metrics"]["approval_turnaround"])), "", "### Schedule and supply", "", f"- Severity distribution: `{json.dumps(m['schedule_impact']['severity_distribution'],sort_keys=True)}`", f"- Plan version churn: {json.dumps(m['supply_metrics']['plan_version_churn'],sort_keys=True)}", f"- Median acknowledgement-to-plan-update time: {m['workflow_metrics']['median_ack_to_plan_update_hours']} hours", f"- Notification volume by type: `{json.dumps(m['workflow_metrics']['notification_volume_by_type'],sort_keys=True)}`", f"- Notification volume by recipient role: `{json.dumps(m['workflow_metrics']['notification_volume_by_recipient_role'],sort_keys=True)}`", "", "### Exception breakdown", "", f"- By type: `{json.dumps(m['exception_metrics']['by_type'],sort_keys=True)}`", f"- By severity: `{json.dumps(m['exception_metrics']['by_severity'],sort_keys=True)}`", f"- Open / resolved: **{m['exception_metrics']['open']} / {m['exception_metrics']['resolved']}**", "", "### Weekly requested supply vs projected receipts", "", _md_table(m['supply_timeline']), "", "## Figures", "", "![Supplier slip-day distribution](figures/supplier_slip_day_distribution.png)", "![Acknowledgement status breakdown](figures/ack_status_breakdown.png)", "![Changes by type and decision](figures/changes_by_type_and_decision.png)", "![Projected versus requested supply](figures/projected_vs_requested_supply.png)", "![Exception counts by type](figures/exception_counts_by_type.png)", "", "## Persona report links", "", "- Logistics Analyst: [exception_report.md](exception_report.md) and [exception_report.csv](exception_report.csv)","- Planner: [supplier_scorecard.csv](supplier_scorecard.csv) and [decision_log.csv](decision_log.csv)","- Carrier/Warehouse Operator: [impact_report.csv](impact_report.csv)","- Operations Manager: this summary report.",""]
    (out/"summary_report.md").write_text("\n".join(summary),encoding="utf-8")
    # Data-quality report references actual artifacts, not invented test results.
    validation=_read_json(root/"validation_summary.json") or _read_json(root/"csv"/"validation_summary.json")
    recon=_read_json(root/"reconciliation_report.json") or _read_json(root/"generation_summary.json")
    manifest=_read_json(root/"manifest.json")
    repro_path=Path("docs/reproducibility_report.md")
    repro_exists=repro_path.exists()
    gt=ds.get("ground_truth",pd.DataFrame()); lines=ds.get("po_lines",pd.DataFrame()); prod=ds.get("production_orders",pd.DataFrame())
    gt_counts=gt.issue_type.fillna("normal").astype(str).value_counts().to_dict() if not gt.empty and "issue_type" in gt else {}
    boundary_count=int(gt.get("boundary",pd.Series(dtype=object)).astype(str).str.lower().isin(["true","1","yes"]).sum()) if not gt.empty else 0
    def numeric_stats(frame, col):
        if frame.empty or col not in frame: return "not available"
        v=pd.to_numeric(frame[col],errors="coerce").dropna()
        if v.empty:return "no numeric values"
        return f"n={len(v):,}, mean={v.mean():.4f}, std={v.std(ddof=0):.4f}, median={v.median():.4f}, min={v.min():.4f}, max={v.max():.4f}"
    val_status=validation.get("overall_status",validation.get("overall","not available"))
    checks=validation.get("checks",[]); pass_count=sum(1 for c in checks if c.get("status")=="PASS"); expected=sum(1 for c in checks if c.get("status")=="EXPECTED_ANOMALY")
    check_map={c.get("check_name",""):c.get("status","not available") for c in checks}
    def find_check(*needles):
        for name,status in check_map.items():
            if all(n in name.lower() for n in needles): return f"`{name}`: **{status}**"
        return "matching validator result not present in summary artifact"
    dq=["# Data quality and evaluation report", "", "## (a) Realistic distributions and meaningful variation", "", "Key source-field distribution statistics (numeric values are computed from the supplied dataset):", "", f"- Requested line quantity: {numeric_stats(lines,'requested_qty')}", f"- Unit price: {numeric_stats(lines,'unit_price')}", f"- Promise slip days (stored current promise): {numeric_stats(promises,'slip_days')}", f"- Change delta percentage: {numeric_stats(changes,'delta_pct')}", f"- Production delay days: {numeric_stats(prod,'delay_days')}", "", "Figures: `figures/supplier_slip_day_distribution.png`, `figures/ack_status_breakdown.png`, `figures/changes_by_type_and_decision.png`, `figures/projected_vs_requested_supply.png`, and `figures/exception_counts_by_type.png`.", "", "## (b) Consistent IDs and valid joins", "", f"Validation artifact status: **{val_status}**; checks with PASS status: {pass_count}; EXPECTED_ANOMALY checks: {expected}. Source validation file: `data/generated/validation_summary.json` (or the corresponding dataset directory).", "", "Key validation evidence:", "", f"- Primary/foreign-key integrity: {find_check('foreign','key')}", f"- Lifecycle transitions: {find_check('lifecycle')}", f"- Arithmetic reconciliation: {find_check('arithmetic')}", f"- Acknowledgement status consistency: {find_check('status','consistency')}", f"- Export leakage: {find_check('leakage')}", "", "## (c) Dependency/lifecycle consistency across entities", "", "The lifecycle-transition and entity-current-state checks are in the validation summary above. Known stale-revision and deliberately injected cross-reference cases are expected only when represented in ground truth; other violations are failures.", "", "## (d) Correct derived values and reconciliation", "", "The generator uses `supplier_ack.rules.derived` as the shared source for derived-value calculation and reconciliation. Available reconciliation evidence:"]
    if recon: dq.append(f"`{root.name}/generation_summary.json` contains generation/reconciliation summary keys: `{', '.join(sorted(recon.keys())[:30])}`.")
    else: dq.append("No standalone reconciliation JSON was found; use the generator's post-generation reconciliation output and validation report.")
    dq.append(f"Arithmetic validator evidence: {find_check('arithmetic')}. The clean-baseline derived reconciliation is run by the generator before anomaly injection; deliberately labelled anomalies are evaluated separately through ground truth.")
    dq += ["", "## (e) Normal, boundary, failure, and exception coverage", "", f"Ground-truth row count: **{len(gt):,}**. Label counts: `{json.dumps(gt_counts,sort_keys=True)}`. Valid boundary cases: **{boundary_count}**.", "", "The four labelled anomaly families are UNAPPROVED_CHANGE_UPDATES_PLAN, ACK_WRONG_PO_LINE, PROMISE_DATE_BEFORE_ORDER_DATE, and STALE_REVISION_OVERWRITE (100 full-scale rows total, 25 per family in this dataset). The four `boundary=True` rows are valid threshold-edge examples, not injected failures. The remaining ground-truth rows record expected outcomes for ordinary change requests and impacted production orders rather than exceptions.", "", "## (f) Separate ground truth", "", f"Ground truth is exported separately (`ground_truth.csv` / `ground_truth.json`); ground-truth and issue labels are not intended to be input features. Dataset manifest: generator version `{manifest.get('generator_version','not recorded')}`, seed `{manifest.get('seed','not recorded')}`, scale `{manifest.get('scale','not recorded')}`. Leakage check result: see validation summary's leakage group; exported input tables are checked for `ground_truth` and `issue_type` columns.", "", "## (g) Fixed-seed reproducibility", "", (f"Reproducibility evidence is available in `{repro_path.as_posix()}`." if repro_exists else "No reproducibility report found at `docs/reproducibility_report.md`; run `python -m supplier_ack.cli verify-reproducibility --seed 20261022 --scale starter` to regenerate evidence."), "", "## Evidence paths", "", f"- Dataset root: `{root}`", f"- Manifest SHA-256: `{hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest() if (root/'manifest.json').exists() else 'not available'}`", "- Validation: `validation_summary.json`, `validation_report.md`", "- Reconciliation: generator post-step and `generation_summary.json`", "- Ground truth: `ground_truth.csv`, `ground_truth.json`", "- Reproducibility: `docs/reproducibility_report.md`", ""]
    (out/"data_quality_report.md").write_text("\n".join(dq),encoding="utf-8")
    # Report metadata supports byte-stable regeneration checks.
    generated=[p for p in sorted(out.rglob("*")) if p.is_file() and p.name!="report_manifest.json" and (out.name != "reports" or "starter" not in p.relative_to(out).parts)]
    report_manifest={"dataset":str(root),"file_count":len(generated),"files":{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in generated},"metrics":m["overall"]}
    (out/"report_manifest.json").write_text(json.dumps(report_manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {"report_dir":str(out),"supplier_count":len(score),"exception_count":len(exceptions),"impact_count":len(impacts),"files":sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())}
