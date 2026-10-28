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
