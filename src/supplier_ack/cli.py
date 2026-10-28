"""CLI bootstrap. Full workflow subcommands are added with runtime implementation."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supplier-ack",
        description="Manage supplier acknowledgements and downstream schedule impacts.",
    )
    parser.add_argument("--version", action="version", version="supplier-ack 0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show bootstrap status and configured workflow scope")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "status":
        print("Supplier acknowledgement system bootstrap is installed.")
        print("Configured actors: Supplier, Planner, Carrier/Warehouse Operator, "
              "Logistics Analyst, Operations Manager.")
        return
    build_parser().print_help()


if __name__ == "__main__":
    main()
