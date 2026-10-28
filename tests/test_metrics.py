from __future__ import annotations
import hashlib
from pathlib import Path
import pandas as pd
from supplier_ack.metrics.engine import compute_metrics, load_dataset
from supplier_ack.metrics.reports import generate_reports

ROOT = Path(__file__).resolve().parents[1]


def test_metrics_derive_counts_from_starter_tables():
    ds = load_dataset(ROOT / "data" / "samples")
    metrics = compute_metrics(ds)
    assert metrics["overall"]["purchase_orders"] == len(ds["purchase_orders"])
    assert metrics["change_metrics"]["total_changes"] == len(ds["change_requests"])
    assert metrics["schedule_impact"]["impact_count"] == len(ds["production_order_impact"])
    assert metrics["exception_metrics"]["total"] == int(ds["ground_truth"]["issue_type"].notna().sum())
    assert set(metrics["supplier_scorecard"].columns) >= {"ack_rate_pct", "on_time_promise_rate_pct", "avg_slip_days", "median_slip_days", "partial_acceptance_rate_pct", "silence_rate_pct", "revision_rate_pct"}
    assert set(metrics["supply_metrics"]["plan_version_churn"]) >= {"lines", "total_versions", "mean_versions_per_line", "max_versions_per_line"}


def _hashes(folder: Path):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_report_pipeline_generates_persona_reports_figures_and_is_deterministic(tmp_path):
    dataset = ROOT / "data" / "samples"
    first, second = tmp_path / "r1", tmp_path / "r2"
    result = generate_reports(dataset, first)
    generate_reports(dataset, second)
    required = {"summary_report.md", "exception_report.csv", "exception_report.md", "supplier_scorecard.csv", "impact_report.csv", "decision_log.csv", "data_quality_report.md", "report_manifest.json"}
    assert required <= {p.name for p in first.iterdir() if p.is_file()}
    figures = {"supplier_slip_day_distribution.png", "ack_status_breakdown.png", "changes_by_type_and_decision.png", "projected_vs_requested_supply.png", "exception_counts_by_type.png"}
    assert figures <= {p.name for p in (first / "figures").iterdir()}
    assert _hashes(first) == _hashes(second)
    assert result["supplier_count"] == len(pd.read_csv(dataset / "suppliers.csv"))
    assert "(a)" in (first / "data_quality_report.md").read_text()
    assert "(g)" in (first / "data_quality_report.md").read_text()
