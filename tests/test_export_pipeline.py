import json
import sqlite3
from pathlib import Path

from supplier_ack.exporting.pipeline import export_dataset


def test_csv_json_sql_exports_share_ids_and_sql_validates(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    report = export_dataset(repo / "data" / "samples", "csv,json,sql", output_root=tmp_path)
    assert report["row_counts"]["purchase_orders"] == 200
    csv_ids = (tmp_path / "csv" / "purchase_orders.csv").read_text(encoding="utf-8").splitlines()[1].split(",", 1)[0]
    json_rows = json.loads((tmp_path / "json" / "purchase_orders.json").read_text(encoding="utf-8"))
    assert json_rows[0]["po_id"] == csv_ids
    conn = sqlite3.connect(tmp_path / "sql" / "seed.db")
    try:
        sql_id = conn.execute("SELECT po_id FROM purchase_orders ORDER BY rowid LIMIT 1").fetchone()[0]
        assert sql_id in {r["po_id"] for r in json_rows}
        assert conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == len(json_rows)
        assert conn.execute('PRAGMA foreign_key_list("purchase_orders")').fetchall()
    finally:
        conn.close()
    validation = json.loads((tmp_path / "sql" / "sqlite_validation_summary.json").read_text())
    assert validation["overall_status"] == "PASS"


def test_secret_scan_is_part_of_validation_suite():
    from supplier_ack.validation.suite import VALIDATORS
    assert any(fn.__name__ == "validate_secret_scan" for fn in VALIDATORS)
