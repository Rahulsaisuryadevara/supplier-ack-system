from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from supplier_ack.cli import main
from supplier_ack.reproducibility import column_value_checksum


@pytest.mark.slow
def test_verify_reproducibility_cli_generates_byte_identical_starter_runs(tmp_path: Path):
    config = Path(__file__).resolve().parents[1] / "config" / "generator_config.yaml"
    output = tmp_path / "runs"
    report = tmp_path / "reproducibility_report.md"

    main([
        "verify-reproducibility", "--seed", "20261022", "--scale", "starter",
        "--config", str(config), "--output-dir", str(output), "--report", str(report),
        "--skip-full-scale",
    ])

    run1, run2, run3 = output / "starter" / "run1", output / "starter" / "run2", output / "starter" / "run3"
    files1 = {p.relative_to(run1).as_posix(): p.read_bytes() for p in run1.rglob("*") if p.is_file()}
    files2 = {p.relative_to(run2).as_posix(): p.read_bytes() for p in run2.rglob("*") if p.is_file()}
    assert files1.keys() == files2.keys()
    assert all(files1[name] == files2[name] for name in files1)
    assert hashlib.sha256((run1 / "purchase_orders.csv").read_bytes()).hexdigest() != hashlib.sha256((run3 / "purchase_orders.csv").read_bytes()).hexdigest()

    events1 = pd.read_csv(run1 / "entity_event.csv", dtype=str, keep_default_na=False)
    events2 = pd.read_csv(run2 / "entity_event.csv", dtype=str, keep_default_na=False)
    assert events1["event_id"].tolist() == events2["event_id"].tolist()
    assert events1["event_timestamp"].tolist() == events2["event_timestamp"].tolist()
    assert report.exists()
    report_text = report.read_text(encoding="utf-8")
    assert "Overall result: PASS" in report_text
    assert "PO-2026-000001" in report_text
    assert "Three concrete ID-content examples" in report_text
    assert "Numeric-column means (10 decimal places)" in report_text


def test_column_value_checksum_is_independent_of_row_order():
    first = pd.Series([1, 2, 2, None, 4])
    second = pd.Series([4, None, 2, 1, 2])
    assert column_value_checksum(first) == column_value_checksum(second)
