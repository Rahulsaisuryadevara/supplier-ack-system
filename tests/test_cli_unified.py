from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from supplier_ack.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[1]


def test_unified_top_level_commands_are_registered():
    parser = build_parser()
    names = set(parser._subparsers._group_actions[0].choices)
    assert {"generate", "export", "validate", "verify-repro", "workflow", "report", "detect", "doctor"}.issubset(names)
    assert "verify-reproducibility" in names


@pytest.mark.parametrize("argv", [
    ["generate", "--help"], ["export", "--help"], ["validate", "--help"],
    ["verify-repro", "--help"], ["workflow", "--help"], ["workflow", "run", "--help"],
    ["workflow", "status", "--help"], ["workflow", "exceptions", "--help"],
    ["workflow", "decisions", "--help"], ["report", "--help"], ["detect", "--help"],
    ["doctor", "--help"],
])
def test_each_command_exposes_help(argv):
    proc = subprocess.run([sys.executable, "-m", "supplier_ack.cli", *argv], cwd=ROOT,
                          text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout.lower()


def _assert_clean_cli_error(argv, capsys, expected):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    output = capsys.readouterr().err
    assert exc.value.code != 0
    assert expected.lower() in output.lower()
    assert "Traceback" not in output


def test_missing_config_is_a_helpful_cli_error(capsys):
    _assert_clean_cli_error(["generate", "--config", "does-not-exist.yaml"], capsys, "config")


def test_bad_seed_type_is_a_helpful_cli_error(capsys):
    _assert_clean_cli_error(["generate", "--seed", "not-an-integer"], capsys, "invalid int value")


def test_unknown_scale_is_a_helpful_cli_error(capsys):
    _assert_clean_cli_error(["generate", "--scale", "gigantic"], capsys, "invalid choice")


def test_missing_dataset_is_a_helpful_cli_error(capsys, tmp_path):
    _assert_clean_cli_error(["validate", "--dataset", str(tmp_path / "missing")], capsys, "does not exist")


def test_corrupt_csv_is_a_helpful_cli_error(capsys, tmp_path):
    (tmp_path / "suppliers.csv").write_bytes(b"supplier_id,supplier_name\n\xff,\xfe\n")
    _assert_clean_cli_error(["validate", "--dataset", str(tmp_path)], capsys, "failed")


def test_sqlite_schema_without_fk_declarations_is_a_helpful_cli_error(capsys, tmp_path):
    db = tmp_path / "no-fk.db"
    conn = sqlite3.connect(db)
    try:
        for table in ("purchase_orders", "po_lines", "acknowledgements", "inventory_plans"):
            conn.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')
        conn.commit()
    finally:
        conn.close()
    _assert_clean_cli_error(["workflow", "exceptions", "--db", str(db)], capsys, "foreign keys")


def test_doctor_runs_and_reports_seed_sanity(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["doctor"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Doctor result: PASS" in output
    assert "Seed sanity" in output


def test_generate_output_covers_requested_scale_only(config=None):
    # Regression for a prior pathological runtime: the CLI must not silently
    # generate the opposite scale just to print a second coverage report.
    from supplier_ack.generators.framework import generate_dataset
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "generator_config.yaml").read_text())
    frames = generate_dataset(cfg, "starter", 20261022, validate=True, inject_anomalies=False)
    assert set(frames["coverage_report"]["scale"]) == {"starter"}
