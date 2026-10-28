"""Command-line interface for the supplier acknowledgement project."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import yaml

from supplier_ack.generators.framework import generate_and_write

DEFAULT_SEED = 20261022


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supplier-ack",
        description="Generate and manage supplier acknowledgement workflow data.",
    )
    parser.add_argument("--version", action="version", version="supplier-ack 0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show bootstrap status and configured workflow scope")
    generate = subparsers.add_parser("generate", help="Generate seeded synthetic master and transaction data")
    generate.add_argument("--config", default="config/generator_config.yaml", help="Path to YAML generator configuration")
    generate.add_argument("--scale", choices=("starter", "full"), default="starter", help="Dataset scale (default: starter)")
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Deterministic RNG seed (default: {DEFAULT_SEED})")
    generate.add_argument("--output-dir", default=None, help="Optional output directory; defaults to data/samples or data/generated")
    generate.add_argument("--skip-validation", action="store_true", help="Skip schema-level validation (not recommended)")
    validate = subparsers.add_parser("validate", help="Run the 14-group ground-truth-aware validation suite")
    validate.add_argument("--dataset", default="data/generated/", help="Directory containing exported CSV tables and ground truth")
    export = subparsers.add_parser("export", help="Export one dataset as CSV, JSON, and SQLite seed data")
    export.add_argument("--dataset", default="data/generated/", help="Source directory containing entity CSVs")
    export.add_argument("--formats", default="csv,json,sql", help="Comma-separated formats: csv,json,sql")
    export.add_argument("--output-dir", default=None, help="Export root (defaults to --dataset)")
    repro = subparsers.add_parser("verify-reproducibility", help="Regenerate seeded data and compare checksums")
    repro.add_argument("--config", default="config/generator_config.yaml", help="Path to YAML generator configuration")
    repro.add_argument("--scale", choices=("starter", "full"), default="starter", help="Scale for run1/run2/run3")
    repro.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Deterministic RNG seed (default: {DEFAULT_SEED})")
    repro.add_argument("--output-dir", default=".reproducibility", help="Root directory for isolated run1/run2/run3 outputs")
    repro.add_argument("--report", default=None, help="Report path (defaults to docs/reproducibility_report.md)")
    repro.add_argument("--skip-full-scale", action="store_true", help="Skip the additional full-scale run1/run2 pair (useful in focused tests)")
    return parser


def _resolve_config_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.exists():
        return candidate.resolve()
    project_root = Path(__file__).resolve().parents[2]
    fallback = project_root / candidate
    if fallback.exists():
        return fallback.resolve()
    raise FileNotFoundError(f"generator config does not exist: {raw_path}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export":
        from supplier_ack.exporting.pipeline import export_dataset
        dataset_path = Path(args.dataset).expanduser()
        if not dataset_path.exists():
            project_root = Path(__file__).resolve().parents[2]
            dataset_path = project_root / dataset_path
        if not dataset_path.is_dir():
            parser.error(f"dataset directory does not exist: {args.dataset}")
        output_path = Path(args.output_dir).expanduser() if args.output_dir else dataset_path
        try:
            report = export_dataset(dataset_path, args.formats, output_root=output_path)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            parser.error(str(exc))
        print(f"Export complete: {output_path.resolve()} | formats={','.join(report['formats'])}")
        for table, count in report["row_counts"].items(): print(f"  {table:28s} {count:>9,d} rows")
        return
    if args.command == "verify-reproducibility":
        from supplier_ack.reproducibility import verify_reproducibility
        try:
            result = verify_reproducibility(
                seed=args.seed,
                scale=args.scale,
                config_path=_resolve_config_path(args.config),
                output_dir=args.output_dir,
                report_path=args.report,
                include_full_scale=not args.skip_full_scale,
            )
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            parser.error(str(exc))
        print(f"Reproducibility: {'PASS' if result['overall_pass'] else 'FAIL'}")
        print(f"  Same-seed comparisons: {'PASS' if result['same_seed_pass'] else 'FAIL'}")
        print(f"  Different-seed counter-property: {'PASS' if result['different_seed_pass'] else 'FAIL'}")
        if result.get("full_scale") is not None:
            print(f"  Full-scale double-generation: {'PASS' if result['full_scale']['pass'] else 'FAIL'}")
        print(f"  Report: {result['report_path']}")
        for example in result["examples"]:
            print(f"  {example['entity']} {example['record_id']}: same seed identical={example['same_seed_identical']}; different seed differs={example['different_seed_differs']}")
        if not result["overall_pass"]:
            raise SystemExit(1)
        return
    if args.command == "validate":
        from supplier_ack.validation.suite import validate_directory
        dataset_path = Path(args.dataset).expanduser()
        if not dataset_path.exists():
            project_root = Path(__file__).resolve().parents[2]
            dataset_path = project_root / dataset_path
        if not dataset_path.is_dir():
            parser.error(f"dataset directory does not exist: {args.dataset}")
        report = validate_directory(dataset_path)
        print(f"Validation: {report['overall_status']} ({report['summary']['check_count']} checks; {report['summary']['failed']} failed)")
        for check in report["checks"]:
            print(f"  {check['check_name']:42s} {check['status']:17s} rows={check['checked_rows']:>8,} failures={check['failure_count']:>5,}")
        if report["overall_status"] == "FAIL":
            raise SystemExit(1)
        return
    if args.command == "status":
        print("Supplier acknowledgement system is installed.")
        print("Actors: Supplier, Planner, Carrier/Warehouse Operator, Logistics Analyst, Operations Manager.")
        return
    if args.command == "generate":
        config_path = _resolve_config_path(args.config)
        with config_path.open("r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle)
        if not isinstance(cfg, dict):
            parser.error(f"configuration root must be a YAML mapping: {config_path}")
        if args.scale not in cfg.get("scales", {}):
            parser.error(f"scale {args.scale!r} is not configured in {config_path}")
        try:
            generate_and_write(cfg, scale=args.scale, seed=args.seed, output_dir=args.output_dir,
                               validate=not args.skip_validation)
        except (ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        return
    parser.print_help()


if __name__ == "__main__":
    main()
