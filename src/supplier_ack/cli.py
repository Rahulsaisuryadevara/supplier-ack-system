"""Unified command-line interface for supplier-ack-system."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import yaml

from supplier_ack import __version__
from supplier_ack.generators.framework import generate_and_write

DEFAULT_SEED = 20261022
REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(raw: str | Path, *, must_exist: bool = False, directory: bool | None = None) -> Path:
    candidate = Path(raw).expanduser()
    options = [candidate]
    if not candidate.is_absolute():
        options.append(REPO_ROOT / candidate)
    resolved = next((p.resolve() for p in options if p.exists()), None)
    if resolved is None:
        if must_exist:
            raise FileNotFoundError(f"path does not exist: {raw}")
        return options[0].resolve()
    if directory is True and not resolved.is_dir():
        raise NotADirectoryError(f"expected a directory, got: {resolved}")
    if directory is False and resolved.is_dir():
        raise IsADirectoryError(f"expected a file, got a directory: {resolved}")
    return resolved


def _resolve_config_path(raw_path: str) -> Path:
    try:
        return _path(raw_path, must_exist=True, directory=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"config file does not exist: {raw_path}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supplier-ack",
        description="Generate, validate, export, and operate the supplier acknowledgement workflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"supplier-ack {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser("generate", help="Generate, reconcile, and validate seeded synthetic data",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    generate.add_argument("--config", default="config/generator_config.yaml", help="YAML generator configuration")
    generate.add_argument("--scale", choices=("starter", "full"), default="starter", help="Dataset scale")
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic non-negative RNG seed")
    generate.add_argument("--output-dir", "--out", dest="output_dir", default=None, help="Dataset output directory (defaults by scale)")

    export = subparsers.add_parser("export", help="Export a dataset as CSV, JSON, and SQLite seed data",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    export.add_argument("--dataset", default="data/generated/", help="Directory containing source entity CSV files")
    export.add_argument("--formats", default="csv,json,sql", help="Comma-separated formats: csv,json,sql")
    export.add_argument("--out", "--output-dir", dest="output_dir", default=None, help="Export root; defaults to the dataset directory")

    validate = subparsers.add_parser("validate", help="Run the 14-group ground-truth-aware validation suite",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    validate.add_argument("--dataset", default="data/generated/", help="Directory containing exported CSV tables")

    repro = subparsers.add_parser("verify-repro", aliases=["verify-reproducibility"],
                                  help="Demonstrate deterministic regeneration and different-seed divergence",
                                  formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    repro.add_argument("--config", default="config/generator_config.yaml", help="YAML generator configuration")
    repro.add_argument("--scale", choices=("starter", "full"), default="starter", help="Scale for deterministic comparison")
    repro.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic non-negative RNG seed")
    repro.add_argument("--output-dir", default=".reproducibility", help="Output root for run1/run2/run3")
    repro.add_argument("--report", default=None, help="Report path (defaults to docs/reproducibility_report.md)")
    repro.add_argument("--skip-full-scale", action="store_true", help="Skip the extra full-scale same-seed pair")

    workflow = subparsers.add_parser("workflow", help="Process runtime events against a SQLite database",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    workflow_sub = workflow.add_subparsers(dest="workflow_command")
    workflow_run = workflow_sub.add_parser("run", help="Process a JSON event file (idempotent by event_id)")
    workflow_run.add_argument("--db", required=True, help="Application SQLite database; a starter seed is used if missing")
    workflow_run.add_argument("--events", default="data/samples/demo_events.json", help="Input JSON event stream")
    workflow_status = workflow_sub.add_parser("status", help="Show status and audit timeline for a purchase order")
    workflow_status.add_argument("--db", required=True)
    workflow_status.add_argument("--po", required=True)
    workflow_exceptions = workflow_sub.add_parser("exceptions", help="List the runtime exception queue")
    workflow_exceptions.add_argument("--db", required=True)
    workflow_decisions = workflow_sub.add_parser("decisions", help="List runtime threshold and approval decisions")
    workflow_decisions.add_argument("--db", required=True)

    report = subparsers.add_parser("report", help="Generate persona-targeted reports and data-quality evaluation",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    report.add_argument("--dataset", default="data/generated/", help="Directory of exported entity CSVs")
    report.add_argument("--out", default="reports/", help="Output root for reports and figures")

    detect = subparsers.add_parser("detect", help="Detect labelled edge-case patterns using entity data only",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    detect.add_argument("--dataset", default="data/generated/", help="Directory containing entity CSVs and separate ground truth")
    detect.add_argument("--out", default="reports/detection_report.md", help="Markdown evaluation report path")

    doctor = subparsers.add_parser("doctor", help="Check Python, dependencies, disk space, configuration, and seed determinism",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    doctor.add_argument("--config", default="config/generator_config.yaml", help="YAML generator configuration to check")

    subparsers.add_parser("status", help="Show package/bootstrap status")
    return parser


def _load_config(path: Path, parser: argparse.ArgumentParser) -> dict:
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        parser.error(f"cannot load config {path}: {exc}")
    if not isinstance(cfg, dict):
        parser.error(f"configuration root must be a YAML mapping: {path}")
    return cfg


def _doctor(config_arg: str) -> int:
    print(f"supplier-ack doctor (package {__version__})")
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python", sys.version_info >= (3, 11), sys.version.split()[0] + " (requires >=3.11)"))
    packages = ("pandas", "numpy", "PyYAML", "matplotlib", "pytest", "supplier-ack-system")
    for name in packages:
        try:
            version = importlib.metadata.version(name)
            checks.append((f"Dependency {name}", True, version))
        except importlib.metadata.PackageNotFoundError:
            required = name != "pytest"
            checks.append((f"Dependency {name}", not required, "not installed"))
    try:
        cfg_path = _resolve_config_path(config_arg)
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        okay = isinstance(cfg, dict) and {"starter", "full"}.issubset(set(cfg.get("scales", {})))
        checks.append(("Generator config", okay, f"{cfg_path} (starter/full scales present={okay})"))
    except (OSError, yaml.YAMLError, FileNotFoundError) as exc:
        checks.append(("Generator config", False, str(exc)))
    rng_a = np.random.default_rng(DEFAULT_SEED).integers(0, 2**31, size=8).tolist()
    rng_b = np.random.default_rng(DEFAULT_SEED).integers(0, 2**31, size=8).tolist()
    checks.append(("Seed sanity", rng_a == rng_b, f"seed={DEFAULT_SEED}; repeatable={rng_a == rng_b}"))
    usage = shutil.disk_usage(Path.cwd())
    estimates = {"starter": 100 * 1024**2, "full": 2 * 1024**3}
    checks.append(("Disk space (starter estimate)", usage.free >= estimates["starter"],
                   f"free={usage.free / 1024**3:.2f} GiB; estimated starter={estimates['starter'] / 1024**2:.0f} MiB"))
    print(f"Disk space (full estimate): {estimates['full'] / 1024**3:.1f} GiB; available={usage.free / 1024**3:.2f} GiB")
    for name, okay, detail in checks:
        print(f"[{'PASS' if okay else 'FAIL'}] {name}: {detail}")
    failures = sum(not okay for _, okay, _ in checks)
    print(f"Doctor result: {'PASS' if failures == 0 else 'FAIL'} ({len(checks)-failures}/{len(checks)} checks passed)")
    return 0 if failures == 0 else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            raise SystemExit(_doctor(args.config))

        if args.command == "generate":
            if args.seed < 0:
                parser.error("seed must be a non-negative integer")
            config_path = _resolve_config_path(args.config)
            cfg = _load_config(config_path, parser)
            if args.scale not in cfg.get("scales", {}):
                parser.error(f"scale {args.scale!r} is not configured in {config_path}")
            generate_and_write(cfg, scale=args.scale, seed=args.seed, output_dir=args.output_dir,
                               validate=True, retain_frames=False, post_validate=False)
            if args.output_dir:
                generated_path = _path(args.output_dir)
            else:
                output_key = "sample_output_dir" if args.scale == "starter" else "output_dir"
                default_output = cfg.get("workflow", {}).get(output_key, "data/samples" if args.scale == "starter" else "data/generated")
                generated_path = _path(default_output)
            print("\nPost-generation validation (isolated process):")
            validation_run = subprocess.run(
                [sys.executable, "-m", "supplier_ack.cli", "validate", "--dataset", str(generated_path)],
                cwd=REPO_ROOT, check=False,
            )
            if validation_run.returncode != 0:
                raise SystemExit(validation_run.returncode)
            return

        if args.command == "export":
            from supplier_ack.exporting.pipeline import export_dataset
            dataset_path = _path(args.dataset, must_exist=True, directory=True)
            output_path = _path(args.output_dir) if args.output_dir else dataset_path
            result = export_dataset(dataset_path, args.formats, output_root=output_path)
            print(f"Export complete: {output_path} | formats={','.join(result['formats'])}")
            for table, count in result["row_counts"].items():
                print(f"  {table:28s} {count:>9,d} rows")
            return

        if args.command == "validate":
            from supplier_ack.validation.suite import validate_directory
            dataset_path = _path(args.dataset, must_exist=True, directory=True)
            result = validate_directory(dataset_path)
            print(f"Validation: {result['overall_status']} ({result['summary']['check_count']} checks; {result['summary']['failed']} failed)")
            for check in result["checks"]:
                print(f"  {check['check_name']:42s} {check['status']:17s} rows={check['checked_rows']:>8,} failures={check['failure_count']:>5,}")
            if result["overall_status"] != "PASS":
                raise SystemExit(1)
            return

        if args.command in {"verify-repro", "verify-reproducibility"}:
            from supplier_ack.reproducibility import verify_reproducibility
            if args.seed < 0:
                parser.error("seed must be a non-negative integer")
            result = verify_reproducibility(seed=args.seed, scale=args.scale,
                config_path=_resolve_config_path(args.config), output_dir=args.output_dir,
                report_path=args.report, include_full_scale=not args.skip_full_scale)
            print(f"Reproducibility: {'PASS' if result['overall_pass'] else 'FAIL'}")
            print(f"  Same-seed comparisons: {'PASS' if result['same_seed_pass'] else 'FAIL'}")
            print(f"  Different-seed counter-property: {'PASS' if result['different_seed_pass'] else 'FAIL'}")
            if result.get("full_scale") is not None:
                print(f"  Full-scale double-generation: {'PASS' if result['full_scale']['pass'] else 'FAIL'}")
            print(f"  Report: {result['report_path']}")
            if not result["overall_pass"]:
                raise SystemExit(1)
            return

        if args.command == "workflow":
            from supplier_ack.workflow.engine import WorkflowEngine
            if not args.workflow_command:
                parser.error("workflow requires run, status, exceptions, or decisions")
            engine = WorkflowEngine(args.db)
            if args.workflow_command == "run":
                events_path = _path(args.events, must_exist=True, directory=False)
                result = engine.run(events_path)
            elif args.workflow_command == "status":
                result = engine.status(args.po)
            elif args.workflow_command == "exceptions":
                result = engine.exceptions()
            elif args.workflow_command == "decisions":
                result = engine.decisions()
            else:
                parser.error(f"unknown workflow action: {args.workflow_command}")
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
            return

        if args.command == "report":
            from supplier_ack.metrics.reports import generate_reports
            dataset_path = _path(args.dataset, must_exist=True, directory=True)
            result = generate_reports(dataset_path, args.out)
            print(f"Reports generated: {result['report_dir']}")
            print(f"  suppliers={result['supplier_count']} exceptions={result['exception_count']} impacts={result['impact_count']}")
            for filename in result["files"]:
                print(f"  {filename}")
            return

        if args.command == "detect":
            from supplier_ack.metrics.detectors import evaluate_detections
            dataset_path = _path(args.dataset, must_exist=True, directory=True)
            cfg = _load_config(_resolve_config_path("config/generator_config.yaml"), parser)
            output = _path(args.out)
            result = evaluate_detections(dataset_path, output, cfg.get("approval_thresholds", {}))
            print(f"Detection: {'PASS' if result['overall_pass'] else 'FAIL'}")
            print(f"  Ground-truth anomalies: {result['ground_truth_anomaly_count']}")
            print(f"  Correctly detected: {result['matched_ground_truth_count']}")
            for item in result["classes"]:
                print(f"  {item['issue_type']:40s} TP={item['tp']:>4} FP={item['fp']:>4} FN={item['fn']:>4} F1={item['f1']:.3f}")
            print(f"  Report: {result.get('report_path', output)}")
            if not result["overall_pass"]:
                raise SystemExit(1)
            return

        if args.command == "status":
            print("Supplier acknowledgement system is installed.")
            print("Actors: Supplier, Planner, Carrier/Warehouse Operator, Logistics Analyst, Operations Manager.")
            return
        parser.print_help()
    except SystemExit:
        raise
    except Exception as exc:
        # User-input and IO errors are presented as concise CLI diagnostics, not tracebacks.
        parser.error(f"{args.command or 'command'} failed: {exc}")


if __name__ == "__main__":
    main()
