"""Input-only rule-based anomaly detectors and ground-truth evaluation.

Detector functions are pure with respect to their arguments: they neither read files
nor inspect any issue/ground-truth labels. Only ``evaluate_detections`` loads the
separate target artifact, after predictions have been produced.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from supplier_ack.rules.thresholds import evaluate_threshold

ANOMALY_TYPES = (
    "UNAPPROVED_CHANGE_UPDATES_PLAN",
    "ACK_WRONG_PO_LINE",
    "PROMISE_DATE_BEFORE_ORDER_DATE",
    "STALE_REVISION_OVERWRITE",
)
LABEL_COLUMNS = {"ground_truth", "issue_type", "boundary"}
INPUT_TABLES = (
    "suppliers", "purchase_orders", "po_lines", "acknowledgements",
    "acknowledgement_lines", "promise_dates", "change_requests", "approvals",
    "inventory_plans", "production_orders", "production_order_impact",
    "notifications", "notification_recipient", "actors", "carriers", "warehouses",
    "items", "production_order_line", "entity_event",
)


def _guard_input_frames(dataset: Mapping[str, pd.DataFrame]) -> None:
    """Fail closed if callers accidentally pass target labels as detector features."""
    for table, frame in dataset.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        leaked = LABEL_COLUMNS.intersection(str(c).lower() for c in frame.columns)
        if leaked:
            raise ValueError(f"detector input table {table!r} contains forbidden label columns: {sorted(leaked)}")


def _frame(dataset: Mapping[str, pd.DataFrame], table: str) -> pd.DataFrame:
    value = dataset.get(table, pd.DataFrame())
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame(value)


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _flag(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y"}


def _truthy_date(value: Any) -> pd.Timestamp | None:
    value = _text(value)
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _detection(table: str, record_id: Any, issue_type: str, **evidence: Any) -> dict[str, Any]:
    return {
        "record_type": table,
        "record_id": _text(record_id),
        "issue_type": issue_type,
        "evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str),
        **{key: value for key, value in evidence.items() if key in {"po_id", "supplier_id", "po_line_id", "change_request_id"}},
    }


def detect_unapproved_plan_updates(
    dataset: Mapping[str, pd.DataFrame], thresholds: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Find approved-change plan rows lacking an approved decision at the required level."""
    _guard_input_frames(dataset)
    plans = _frame(dataset, "inventory_plans")
    changes = _frame(dataset, "change_requests")
    approvals = _frame(dataset, "approvals")
    changes_by_id = {str(r.get("change_request_id")): r for r in changes.to_dict("records")}
    approvals_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in approvals.to_dict("records"):
        approvals_by_id.setdefault(str(row.get("change_request_id")), []).append(row)
    found: list[dict[str, Any]] = []
    candidates = plans.loc[plans.get("source", pd.Series(index=plans.index, dtype=object)).astype(str).str.lower().eq("approved_change")]
    for row in candidates.to_dict("records"):
        change_id = _text(row.get("change_request_id"))
        change = changes_by_id.get(change_id)
        if not change:
            found.append(_detection("InventoryPlan", row.get("inventory_plan_id"), ANOMALY_TYPES[0],
                                    change_request_id=change_id, po_id=row.get("po_id"), po_line_id=row.get("po_line_id"),
                                    reason="plan references a missing change request"))
            continue
        rule = evaluate_threshold(change, thresholds)
        required = str(rule["required_approval_level"]).lower()
        matching = [a for a in approvals_by_id.get(change_id, [])
                    if str(a.get("approval_level") or a.get("approver_role") or "").lower() == required]
        def order_key(a: dict[str, Any]) -> tuple[int, str]:
            try: round_no = int(float(a.get("approval_round") or 0))
            except (ValueError, TypeError): round_no = 0
            return round_no, _text(a.get("decided_at"))
        latest = max(matching, key=order_key) if matching else None
        if rule["hard_limit_breach"] or not latest or str(latest.get("status") or latest.get("decision") or "").upper() != "APPROVED":
            found.append(_detection("InventoryPlan", row.get("inventory_plan_id"), ANOMALY_TYPES[0],
                                    change_request_id=change_id, po_id=row.get("po_id"), po_line_id=row.get("po_line_id"),
                                    required_approval_level=required,
                                    latest_required_level_decision=(str(latest.get("status")) if latest else "MISSING"),
                                    hard_limit_breach=bool(rule["hard_limit_breach"])))
    return pd.DataFrame(found, columns=["record_type", "record_id", "issue_type", "evidence", "po_id", "supplier_id", "po_line_id", "change_request_id"])


def detect_wrong_line_refs(dataset: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Find acknowledgement-line references that are missing or belong to another PO."""
    _guard_input_frames(dataset)
    ack_lines, po_lines = _frame(dataset, "acknowledgement_lines"), _frame(dataset, "po_lines")
    known_line_po = {str(r.get("po_line_id")): str(r.get("po_id")) for r in po_lines.to_dict("records")}
    found = []
    for row in ack_lines.to_dict("records"):
        line_id, po_id = _text(row.get("po_line_id")), _text(row.get("po_id"))
        owner = known_line_po.get(line_id)
        if owner is None or owner != po_id:
            found.append(_detection("AcknowledgementLine", row.get("acknowledgement_line_id"), ANOMALY_TYPES[1],
                                    po_id=po_id, po_line_id=line_id, actual_line_owner_po_id=owner,
                                    reference_missing=owner is None))
    return pd.DataFrame(found, columns=["record_type", "record_id", "issue_type", "evidence", "po_id", "supplier_id", "po_line_id", "change_request_id"])


def detect_impossible_promise_dates(dataset: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Find promises dated before the date on which the referenced PO was ordered."""
    _guard_input_frames(dataset)
    promises, pos = _frame(dataset, "promise_dates"), _frame(dataset, "purchase_orders")
    order_dates = {str(r.get("po_id")): _truthy_date(r.get("order_date")) for r in pos.to_dict("records")}
    found = []
    for row in promises.to_dict("records"):
        promised = _truthy_date(row.get("promised_date"))
        ordered = order_dates.get(str(row.get("po_id")))
        if promised is not None and ordered is not None and promised.normalize() < ordered.normalize():
            found.append(_detection("PromiseDate", row.get("promise_date_id"), ANOMALY_TYPES[2],
                                    po_id=row.get("po_id"), po_line_id=row.get("po_line_id"),
                                    order_date=ordered.date().isoformat(), promised_date=promised.date().isoformat()))
    return pd.DataFrame(found, columns=["record_type", "record_id", "issue_type", "evidence", "po_id", "supplier_id", "po_line_id", "change_request_id"])


def detect_stale_revision_effective(dataset: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Find an effective promise/plan whose revision/version trails existing history."""
    _guard_input_frames(dataset)
    found: list[dict[str, Any]] = []
    promises = _frame(dataset, "promise_dates")
    if not promises.empty:
        work = promises.copy()
        work["_revision"] = pd.to_numeric(work.get("revision_no", 0), errors="coerce").fillna(0)
        max_revision = work.groupby("po_line_id", dropna=False)["_revision"].transform("max")
        effective = work.get("status", pd.Series(index=work.index, dtype=object)).astype(str).str.upper().eq("CURRENT")
        stale_rows = work.loc[effective & work["_revision"].lt(max_revision)].copy()
        stale_rows["_maximum_revision"] = max_revision.loc[stale_rows.index]
        for row in stale_rows.to_dict("records"):
            found.append(_detection("PromiseDate", row.get("promise_date_id"), ANOMALY_TYPES[3],
                                    po_id=row.get("po_id"), po_line_id=row.get("po_line_id"),
                                    revision_no=row.get("revision_no"), maximum_revision=int(row["_maximum_revision"])))
    plans = _frame(dataset, "inventory_plans")
    if not plans.empty:
        work = plans.copy()
        work["_version"] = pd.to_numeric(work.get("plan_version", 0), errors="coerce").fillna(0)
        max_version = work.groupby("po_line_id", dropna=False)["_version"].transform("max")
        effective = work.get("is_effective", pd.Series(index=work.index, dtype=object)).map(_flag)
        stale_rows = work.loc[effective & work["_version"].lt(max_version)].copy()
        stale_rows["_maximum_plan_version"] = max_version.loc[stale_rows.index]
        for row in stale_rows.to_dict("records"):
            found.append(_detection("InventoryPlan", row.get("inventory_plan_id"), ANOMALY_TYPES[3],
                                    po_id=row.get("po_id"), po_line_id=row.get("po_line_id"),
                                    plan_version=row.get("plan_version"), maximum_plan_version=int(row["_maximum_plan_version"])))
    return pd.DataFrame(found, columns=["record_type", "record_id", "issue_type", "evidence", "po_id", "supplier_id", "po_line_id", "change_request_id"])


def detect_boundary_cases(dataset: Mapping[str, pd.DataFrame], thresholds: Mapping[str, Any] | None = None) -> pd.DataFrame:
    """Report source rows exactly on configured thresholds; these are not anomalies."""
    _guard_input_frames(dataset)
    thresholds = thresholds or {}
    found: list[dict[str, Any]] = []
    changes = _frame(dataset, "change_requests")
    for row in changes.to_dict("records"):
        try:
            rule = evaluate_threshold(row, thresholds)
        except (ValueError, TypeError, KeyError):
            continue
        measured = abs(float(rule["measured_delta"])) if rule["change_type"] != "date" else max(0.0, float(rule["delta"]))
        if abs(measured - float(rule["threshold_value"])) <= 1e-8:
            found.append({"record_type": "ChangeRequest", "record_id": _text(row.get("change_request_id")),
                          "boundary_type": f"{rule['change_type']}_threshold", "delta": rule["delta"],
                          "threshold": rule["threshold_value"], "required_approval_level": rule["required_approval_level"]})
    lines = _frame(dataset, "acknowledgement_lines")
    if not lines.empty and {"requested_qty", "accepted_qty"}.issubset(lines.columns):
        requested = pd.to_numeric(lines["requested_qty"], errors="coerce")
        accepted = pd.to_numeric(lines["accepted_qty"], errors="coerce")
        for idx in lines.index[(requested - accepted).abs().le(0.0005)]:
            row = lines.loc[idx]
            found.append({"record_type": "AcknowledgementLine", "record_id": _text(row.get("acknowledgement_line_id")),
                          "boundary_type": "accepted_equals_requested", "delta": 0.0, "threshold": 0.0,
                          "required_approval_level": "none"})
    cols = ["record_type", "record_id", "boundary_type", "delta", "threshold", "required_approval_level"]
    if not found:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(found, columns=cols).drop_duplicates(["record_type", "record_id", "boundary_type"]).reset_index(drop=True)


def _load_input_frames(dataset_path: str | Path) -> tuple[Path, dict[str, pd.DataFrame]]:
    root = Path(dataset_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"dataset directory does not exist: {dataset_path}")
    csv_root = root / "csv" if (root / "csv").is_dir() else root
    frames: dict[str, pd.DataFrame] = {}
    for table in INPUT_TABLES:
        file = csv_root / f"{table}.csv"
        if file.is_file():
            try:
                frames[table] = pd.read_csv(file, dtype=str, keep_default_na=False, encoding="utf-8", low_memory=False)
            except Exception as exc:
                raise ValueError(f"cannot read input table {file}: {exc}") from exc
    if not frames or "purchase_orders" not in frames:
        raise FileNotFoundError(f"no usable entity CSVs found in {csv_root}; generate or export the dataset first")
    _guard_input_frames(frames)
    return root, frames


def evaluate_detections(dataset_path: str | Path, report_path: str | Path | None = None,
                        thresholds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run input-only detection, then evaluate predictions against separate ground truth."""
    root, frames = _load_input_frames(dataset_path)
    detections = pd.concat([
        detect_unapproved_plan_updates(frames, thresholds),
        detect_wrong_line_refs(frames),
        detect_impossible_promise_dates(frames),
        detect_stale_revision_effective(frames),
    ], ignore_index=True)
    boundaries = detect_boundary_cases(frames, thresholds)

    # Ground truth is intentionally loaded only after all predictions are materialized.
    truth_path = root / "ground_truth.json"
    if not truth_path.exists(): truth_path = root / "ground_truth.csv"
    if not truth_path.exists():
        raise FileNotFoundError(f"separated ground truth not found in {root} (expected ground_truth.json or .csv)")
    try:
        if truth_path.suffix.lower() == ".json":
            obj = json.loads(truth_path.read_text(encoding="utf-8"))
            truth_records = obj.get("records", obj) if isinstance(obj, dict) else obj
        else:
            truth_records = pd.read_csv(truth_path, dtype=str, keep_default_na=False, encoding="utf-8").to_dict("records")
    except Exception as exc:
        raise ValueError(f"cannot read separate ground-truth file {truth_path}: {exc}") from exc
    truth = pd.DataFrame(truth_records)
    if truth.empty:
        truth = pd.DataFrame(columns=["record_type", "record_id", "issue_type", "boundary"])

    def is_boundary(row: Mapping[str, Any]) -> bool:
        return _text(row.get("boundary")).lower() in {"1", "true", "yes"}
    if not truth.empty:
        truth["_issue"] = truth.get("issue_type", pd.Series(index=truth.index, dtype=object)).fillna("").astype(str).str.strip()
        truth["_is_boundary"] = truth.apply(lambda r: is_boundary(r), axis=1)
    results: list[dict[str, Any]] = []
    for issue in ANOMALY_TYPES:
        pred_subset = detections.loc[detections.issue_type.eq(issue)] if not detections.empty else detections
        predicted = {(str(r.record_type), str(r.record_id)) for r in pred_subset.itertuples()}
        subset = truth.loc[(truth["_issue"] == issue) & (~truth["_is_boundary"])] if not truth.empty else truth
        actual = {(str(r.get("record_type", "")), str(r.get("record_id", ""))) for r in subset.to_dict("records")}
        tp = len(predicted & actual); fp = len(predicted - actual); fn = len(actual - predicted)
        universe_tables = {
            ANOMALY_TYPES[0]: ["inventory_plans"],
            ANOMALY_TYPES[1]: ["acknowledgement_lines"],
            ANOMALY_TYPES[2]: ["promise_dates"],
            ANOMALY_TYPES[3]: ["promise_dates", "inventory_plans"],
        }[issue]
        total = sum(len(_frame(frames, table)) for table in universe_tables)
        tn = max(0, total - tp - fp - fn)
        precision = tp / (tp + fp) if tp + fp else 1.0 if not actual else 0.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        accuracy = (tp + tn) / total if total else 1.0
        results.append({"issue_type": issue, "record_universe": total, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                        "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
                        "actual_count": len(actual), "prediction_count": len(predicted), "perfect": fp == 0 and fn == 0})
    boundary_gt = truth.loc[truth["_is_boundary"]] if not truth.empty else truth
    anomaly_gt = truth.loc[truth.get("_issue", pd.Series(dtype=object)).isin(ANOMALY_TYPES)] if not truth.empty else truth
    exact_label_coverage = int(sum((str(r.get("record_type", "")), str(r.get("record_id", ""))) in {
        (str(d["record_type"]), str(d["record_id"])) for d in detections.to_dict("records")
    } for r in anomaly_gt.to_dict("records")))
    perfect = all(row["perfect"] for row in results) and exact_label_coverage == len(anomaly_gt)

    out = {"dataset": str(root), "detections": detections, "boundaries": boundaries, "classes": results,
           "ground_truth_anomaly_count": len(anomaly_gt), "matched_ground_truth_count": exact_label_coverage,
           "boundary_ground_truth_count": len(boundary_gt), "overall_accuracy": sum(r["tp"] + r["tn"] for r in results) / max(1, sum(r["record_universe"] for r in results)),
           "overall_pass": perfect}
    if report_path is not None:
        report = Path(report_path).expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        columns = ["issue_type", "record_universe", "tp", "fp", "fn", "tn", "precision", "recall", "f1", "accuracy"]
        lines = ["# Anomaly Detection Evaluation", "", f"**Overall result: {'PASS' if perfect else 'FAIL'}**", "",
                 f"- Injected anomaly records in target: {len(anomaly_gt):,}", f"- Detector predictions matched to ground truth: {exact_label_coverage:,}",
                 f"- Valid boundary cases reported separately: {len(boundaries):,} detected / {len(boundary_gt):,} labelled", "",
                 "Detectors receive only entity tables. The ground-truth file is loaded after prediction generation for evaluation only.", "",
                 "| Anomaly class | Universe | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in results:
            lines.append(f"| {r['issue_type']} | {r['record_universe']:,} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | {r['precision']:.4f} | {r['recall']:.4f} | {r['f1']:.4f} | {r['accuracy']:.4f} |")
        lines.extend(["", f"**Overall accuracy (micro over class-specific row universes): {out['overall_accuracy']:.4f}**", "", "## Detector evidence", ""])
        if detections.empty: lines.append("No anomalies detected.")
        else:
            lines.append("| Type | Record | PO | Evidence |\n|---|---|---|---|")
            for r in detections.to_dict("records"):
                lines.append(f"| {r['issue_type']} | `{r['record_id']}` | `{r.get('po_id', '')}` | `{str(r['evidence']).replace('|', '\\|')}` |")
        lines.extend(["", "## Boundary cases (valid; not scored as anomalies)", ""])
        if boundaries.empty: lines.append("No exact threshold boundary rows found.")
        else:
            lines.append("| Record type | Record ID | Boundary | Delta | Threshold | Required level |\n|---|---|---|---:|---:|---|")
            for r in boundaries.to_dict("records"):
                lines.append(f"| {r['record_type']} | `{r['record_id']}` | {r['boundary_type']} | {r['delta']} | {r['threshold']} | {r['required_approval_level']} |")
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out["report_path"] = str(report)
        out["detection_csv"] = str(report.with_suffix(".csv"))
        detections.to_csv(out["detection_csv"], index=False, encoding="utf-8", lineterminator="\n")
    return out
