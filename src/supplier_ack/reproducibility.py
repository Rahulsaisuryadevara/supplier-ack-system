"""Deterministic-generation demonstration and checksum report writer."""
from __future__ import annotations

import hashlib
import importlib.metadata
import gc
import json
import math
import os
import subprocess
import textwrap
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "generator_config.yaml"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _null(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _token(value: Any) -> str:
    """Stable typed token for checksums of sorted column values."""
    if _null(value):
        return "NULL:"
    if isinstance(value, (bool, np.bool_)):
        return "BOOL:1" if bool(value) else "BOOL:0"
    if isinstance(value, (int, np.integer)):
        return f"INT:{int(value)}"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return "NULL:" if math.isnan(number) else f"FLOAT:{number:.17g}"
    return "STR:" + str(value)


def column_value_checksum(series: pd.Series) -> str:
    digest = hashlib.sha256()
    for value in sorted(_token(v) for v in series.tolist()):
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _row_checksum(row: dict[str, Any]) -> str:
    def norm(value: Any) -> Any:
        if _null(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating, float)):
            number = float(value)
            return None if math.isnan(number) else format(number, ".17g")
        if isinstance(value, (np.bool_,)):
            return bool(value)
        return value
    serialized = json.dumps({k: norm(v) for k, v in row.items()}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def inspect_run(directory: str | Path, *, retain_example_frames: bool = True) -> dict[str, Any]:
    """Return checksums for all files/tables without retaining full-scale tables in memory."""
    root = Path(directory)
    files = {
        p.relative_to(root).as_posix(): file_sha256(p)
        for p in sorted(root.rglob("*")) if p.is_file()
    }
    tables: dict[str, Any] = {}
    event_order_checksums: dict[str, str] = {}
    retained = {"purchase_orders", "po_lines", "acknowledgements"} if retain_example_frames else set()
    for path in sorted(root.glob("*.csv")):
        frame = pd.read_csv(path, encoding="utf-8", low_memory=False)
        columns = {str(c): column_value_checksum(frame[c]) for c in frame.columns}
        means: dict[str, str] = {}
        for col in frame.columns:
            series = frame[col]
            if pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
                mean = pd.to_numeric(series, errors="coerce").mean()
                means[str(col)] = "NA" if pd.isna(mean) else f"{float(mean):.10f}"
        table_result = {"rows": int(len(frame)), "sha256": files[path.name],
                        "columns": columns, "means": means}
        if path.stem == "entity_event":
            for event_col in ("event_id", "event_timestamp"):
                if event_col in frame:
                    digest = hashlib.sha256()
                    for value in frame[event_col].astype(str).tolist():
                        digest.update(value.encode("utf-8")); digest.update(b"\n")
                    event_order_checksums[event_col] = digest.hexdigest()
        if path.stem in retained:
            # Retain only a compact, deterministic example slice. Full-scale run
            # summaries should not keep tens of thousands of records in RAM merely
            # to print three proof-of-determinism examples.
            if path.stem == "purchase_orders" and "po_id" in frame:
                frame = frame.loc[frame["po_id"].astype(str).eq("PO-2026-000001")].head(1).copy()
            elif path.stem == "po_lines" and "po_line_id" in frame:
                frame = frame.loc[frame["po_line_id"].astype(str).eq("PO-2026-000001-L01")].head(1).copy()
            elif path.stem == "acknowledgements":
                sample = frame.head(250)
                if "po_id" in frame:
                    first_po = frame.loc[frame["po_id"].astype(str).eq("PO-2026-000001")]
                    if not first_po.empty:
                        sample = pd.concat([first_po, sample], ignore_index=True).drop_duplicates("ack_id")
                frame = sample.copy()
            table_result["frame"] = frame
        tables[path.stem] = table_result
        del frame
    gc.collect()
    return {"directory": str(root), "files": files, "tables": tables,
            "event_order_checksums": event_order_checksums}


def _table_comparison(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for name in sorted(set(a["tables"]) | set(b["tables"])):
        ta, tb = a["tables"].get(name), b["tables"].get(name)
        match = bool(ta and tb and ta["rows"] == tb["rows"] and ta["sha256"] == tb["sha256"])
        out.append({"table_name": name, "rows_run1": ta["rows"] if ta else "MISSING",
                    "rows_run2": tb["rows"] if tb else "MISSING",
                    "checksum_run1": ta["sha256"] if ta else "MISSING",
                    "checksum_run2": tb["sha256"] if tb else "MISSING", "match": "YES" if match else "NO"})
    return out


def _file_comparison(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for name in sorted(set(a["files"]) | set(b["files"])):
        first, second = a["files"].get(name, "MISSING"), b["files"].get(name, "MISSING")
        out.append({"file": name, "sha256_run1": first, "sha256_run2": second,
                    "match": "YES" if first == second and first != "MISSING" else "NO"})
    return out


def _column_comparison(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any] | None = None) -> list[dict[str, str]]:
    out = []
    names = sorted(set(a["tables"]) | set(b["tables"]) | (set(c["tables"]) if c else set()))
    for table in names:
        ta, tb = a["tables"].get(table, {}), b["tables"].get(table, {})
        tc = c["tables"].get(table, {}) if c else {}
        cols = sorted(set(ta.get("columns", {})) | set(tb.get("columns", {})) | set(tc.get("columns", {})))
        for col in cols:
            x = ta.get("columns", {}).get(col, "MISSING")
            y = tb.get("columns", {}).get(col, "MISSING")
            z = tc.get("columns", {}).get(col, "N/A") if c else "N/A"
            out.append({"table_name": table, "column_name": col, "checksum_run1": x, "checksum_run2": y,
                        "match_run1_run2": "YES" if x == y and x != "MISSING" else "NO",
                        "checksum_run3": z,
                        "match_run1_run3": ("YES" if x == z and x != "MISSING" else "NO") if c else "N/A"})
    return out


def _mean_comparison(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any] | None = None) -> list[dict[str, str]]:
    out = []
    names = sorted(set(a["tables"]) | set(b["tables"]) | (set(c["tables"]) if c else set()))
    for table in names:
        ta, tb = a["tables"].get(table, {}), b["tables"].get(table, {})
        tc = c["tables"].get(table, {}) if c else {}
        cols = sorted(set(ta.get("means", {})) | set(tb.get("means", {})) | set(tc.get("means", {})))
        for col in cols:
            x, y = ta.get("means", {}).get(col, "N/A"), tb.get("means", {}).get(col, "N/A")
            z = tc.get("means", {}).get(col, "N/A") if c else "N/A"
            out.append({"table_name": table, "column_name": col, "mean_run1": x, "mean_run2": y,
                        "match_run1_run2": "YES" if x == y else "NO", "mean_run3": z,
                        "match_run1_run3": ("YES" if x == z else "NO") if c else "N/A"})
    return out


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    escape = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    output.extend("| " + " | ".join(escape(x) for x in row) + " |" for row in rows)
    return "\n".join(output) + "\n"


def _record(run: dict[str, Any], table: str, id_col: str, value: str) -> dict[str, Any] | None:
    item = run["tables"].get(table)
    if not item or id_col not in item["frame"]:
        return None
    found = item["frame"].loc[item["frame"][id_col].astype(str).eq(value)]
    return found.iloc[0].to_dict() if not found.empty else None


def _examples(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        ("PurchaseOrder", "purchase_orders", "po_id", "PO-2026-000001"),
        ("POLine", "po_lines", "po_line_id", "PO-2026-000001-L01"),
    ]
    ack_df = a["tables"].get("acknowledgements", {}).get("frame", pd.DataFrame())
    for ack_id in ack_df.get("ack_id", pd.Series(dtype=str)).astype(str).tolist():
        ra, rb, rc = (_record(run, "acknowledgements", "ack_id", ack_id) for run in (a, b, c))
        if ra is not None and rb is not None and rc is not None and _row_checksum(ra) == _row_checksum(rb) != _row_checksum(rc):
            candidates.append(("Acknowledgement", "acknowledgements", "ack_id", ack_id))
            break
    result = []
    for entity, table, key, identifier in candidates:
        ra, rb, rc = (_record(run, table, key, identifier) for run in (a, b, c))
        if not all(row is not None for row in (ra, rb, rc)):
            continue
        ha, hb, hc = (_row_checksum(row) for row in (ra, rb, rc))
        result.append({"entity": entity, "record_id": identifier, "same_seed_identical": ha == hb,
                       "different_seed_differs": ha != hc, "hash1": ha, "hash2": hb, "hash3": hc,
                       "fields": {k: ra[k] for k in list(ra)[:7]}})
    return result


def _run_one(config_path: Path, scale: str, seed: int, output: Path) -> dict[str, Any]:
    """Run generation in a clean interpreter, then inspect files in the parent.

    Process isolation means each repeat starts with a clean Python/pandas state and
    exits before the next scale starts. This is closer to a user's actual rerun and
    avoids retaining generated DataFrames between full-scale repeats.
    """
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    print(f"[repro] generating {scale} seed={seed} -> {output}", flush=True)
    worker = textwrap.dedent(r"""
        import sys
        from pathlib import Path
        import yaml
        from supplier_ack.generators.framework import generate_dataset, write_generated_data
        config_path, scale, seed, output = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
        print(f'[repro-worker] generation start scale={scale} seed={seed}', flush=True)
        config = yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
        frames = generate_dataset(config, scale=scale, seed=seed, validate=False, inject_anomalies=True)
        print(f'[repro-worker] generation complete scale={scale} seed={seed}', flush=True)
        write_generated_data(frames, config, scale, seed, output_dir=output, publish_ground_truth=False)
        print(f'[repro-worker] export complete scale={scale} seed={seed}', flush=True)
    """)
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    subprocess.run(
        [sys.executable, "-c", worker, str(config_path.resolve()), scale, str(seed), str(output.resolve())],
        cwd=REPO_ROOT, env=env, check=True, timeout=300,
    )
    gc.collect()
    print(f"[repro] checksumming {scale} seed={seed}", flush=True)
    result = inspect_run(output, retain_example_frames=True)
    print(f"[repro] complete {scale} seed={seed}: {len(result['tables'])} tables, {len(result['files'])} files", flush=True)
    return result


def _versions() -> dict[str, str]:
    result = {}
    for package in ("numpy", "pandas", "PyYAML", "pytest"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "not-installed"
    return result


def verify_reproducibility(*, seed: int = 20261022, scale: str = "starter",
                           config_path: str | Path = DEFAULT_CONFIG,
                           output_dir: str | Path = REPO_ROOT / ".reproducibility",
                           report_path: str | Path | None = None,
                           include_full_scale: bool = True) -> dict[str, Any]:
    """Generate same-seed runs 1/2, different-seed run 3, and a full-scale pair."""
    if scale not in {"starter", "full"}:
        raise ValueError("scale must be 'starter' or 'full'")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    cfg_path = Path(config_path).expanduser()
    if not cfg_path.is_absolute() and not cfg_path.exists():
        cfg_path = REPO_ROOT / cfg_path
    if not cfg_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("config file must contain a mapping")
    root = Path(output_dir).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    report_path = Path(report_path).expanduser() if report_path else REPO_ROOT / "docs" / "reproducibility_report.md"
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    other_seed = seed + 1 if seed != 0 else 1

    run1 = _run_one(cfg_path.resolve(), scale, seed, root / scale / "run1")
    run2 = _run_one(cfg_path.resolve(), scale, seed, root / scale / "run2")
    run3 = _run_one(cfg_path.resolve(), scale, other_seed, root / scale / "run3")
    table_same = _table_comparison(run1, run2)
    files_same = _file_comparison(run1, run2)
    tables_diff = []
    for name in sorted(set(run1["tables"]) | set(run3["tables"])):
        a, b = run1["tables"].get(name), run3["tables"].get(name)
        tables_diff.append({"table_name": name, "rows_run1": a["rows"] if a else "MISSING",
                            "rows_run3": b["rows"] if b else "MISSING",
                            "checksum_run1": a["sha256"] if a else "MISSING",
                            "checksum_run3": b["sha256"] if b else "MISSING",
                            "match": "YES" if a and b and a["sha256"] == b["sha256"] else "NO"})
    files_diff = []
    for name in sorted(set(run1["files"]) | set(run3["files"])):
        a, b = run1["files"].get(name, "MISSING"), run3["files"].get(name, "MISSING")
        files_diff.append({"file": name, "sha256_run1": a, "sha256_run3": b,
                           "match": "YES" if a == b and a != "MISSING" else "NO"})
    columns = _column_comparison(run1, run2, run3)
    means = _mean_comparison(run1, run2, run3)
    examples = _examples(run1, run2, run3)
    event_ids_same = (run1.get("event_order_checksums", {}).get("event_id") is not None
                      and run1.get("event_order_checksums", {}).get("event_id") == run2.get("event_order_checksums", {}).get("event_id"))
    event_timestamps_same = (run1.get("event_order_checksums", {}).get("event_timestamp") is not None
                             and run1.get("event_order_checksums", {}).get("event_timestamp") == run2.get("event_order_checksums", {}).get("event_timestamp"))
    same_pass = (all(x["match"] == "YES" for x in table_same)
                 and all(x["match"] == "YES" for x in files_same)
                 and all(x["match_run1_run2"] == "YES" for x in columns)
                 and all(x["match_run1_run2"] == "YES" for x in means)
                 and event_ids_same and event_timestamps_same
                 and len(examples) == 3 and all(x["same_seed_identical"] and x["different_seed_differs"] for x in examples))
    different_seed_pass = (any(x["match"] == "NO" for x in tables_diff if x["table_name"] != "ground_truth")
                           and all(x["different_seed_differs"] for x in examples))

    full = None
    if scale == "full":
        # The selected run1/run2 pair is itself the required full-scale demonstration.
        full = {"run1": run1, "run2": run2, "tables": table_same, "files": files_same,
                "columns": columns, "means": means, "event_ids_same": event_ids_same,
                "event_timestamps_same": event_timestamps_same,
                "pass": all(r["match"] == "YES" for r in table_same)
                        and all(r["match"] == "YES" for r in files_same)
                        and all(r["match_run1_run2"] == "YES" for r in columns)
                        and all(r["match_run1_run2"] == "YES" for r in means)
                        and event_ids_same and event_timestamps_same}
    elif include_full_scale:
        full1 = _run_one(cfg_path.resolve(), "full", seed, root / "full" / "run1")
        full2 = _run_one(cfg_path.resolve(), "full", seed, root / "full" / "run2")
        ftables = _table_comparison(full1, full2)
        ffiles = _file_comparison(full1, full2)
        fcolumns = _column_comparison(full1, full2)
        fmeans = _mean_comparison(full1, full2)
        fids = (full1.get("event_order_checksums", {}).get("event_id") is not None
                and full1.get("event_order_checksums", {}).get("event_id") == full2.get("event_order_checksums", {}).get("event_id"))
        ftimestamps = (full1.get("event_order_checksums", {}).get("event_timestamp") is not None
                       and full1.get("event_order_checksums", {}).get("event_timestamp") == full2.get("event_order_checksums", {}).get("event_timestamp"))
        fpass = (all(x["match"] == "YES" for x in ftables) and all(x["match"] == "YES" for x in ffiles)
                 and all(x["match_run1_run2"] == "YES" for x in fcolumns)
                 and all(x["match_run1_run2"] == "YES" for x in fmeans) and fids and ftimestamps)
        full = {"run1": full1, "run2": full2, "tables": ftables, "files": ffiles,
                "columns": fcolumns, "means": fmeans, "event_ids_same": fids,
                "event_timestamps_same": ftimestamps, "pass": fpass}

    overall_pass = same_pass and different_seed_pass and (full is None or full["pass"])
    env = _versions()
    config_rel = Path(os.path.relpath(cfg_path.resolve(), REPO_ROOT)).as_posix()
    worker_lines = [
        "from pathlib import Path",
        "import yaml",
        "from supplier_ack.generators.framework import generate_dataset, write_generated_data",
        f"config = yaml.safe_load(Path({config_rel!r}).read_text(encoding='utf-8'))",
        "",
    ]
    worker_specs = [
        ("run1", scale, seed, root / scale / "run1"),
        ("run2", scale, seed, root / scale / "run2"),
        ("run3", scale, other_seed, root / scale / "run3"),
    ]
    if scale == "starter" and include_full_scale:
        worker_specs.extend([
            ("full/run1", "full", seed, root / "full" / "run1"),
            ("full/run2", "full", seed, root / "full" / "run2"),
        ])
    for label, run_scale, run_seed, run_path in worker_specs:
        relative_out = Path(os.path.relpath(run_path.resolve(), REPO_ROOT)).as_posix()
        worker_lines.extend([
            f"# {label}",
            f"frames = generate_dataset(config, scale={run_scale!r}, seed={run_seed}, validate=False, inject_anomalies=True)",
            f"write_generated_data(frames, config, {run_scale!r}, {run_seed}, output_dir=Path({relative_out!r}), publish_ground_truth=False)",
            "",
        ])
    lines = [
        "# Reproducibility Demonstration", "", f"**Overall result: {'PASS' if overall_pass else 'FAIL'}**", "",
        f"- Selected scale: `{scale}`", f"- Run 1/2 seed: `{seed}`", f"- Run 3 counter-property seed: `{other_seed}`", "",
        "## Exact command and execution environment", "",
        "```bash", f"python -m supplier_ack.cli verify-reproducibility --seed {seed} --scale {scale}", "```", "",
        f"- Generator config: `{Path(os.path.relpath(cfg_path.resolve(), REPO_ROOT)).as_posix()}`", f"- Run directory: `{Path(os.path.relpath(root.resolve(), REPO_ROOT)).as_posix()}`",
        f"- Python: `{sys.version.split()[0]}` ({platform.python_implementation()})",
        f"- Platform: `{platform.platform()}`", "- Dependencies: " + ", ".join(f"{k} `{v}`" for k, v in env.items()), "",
        "Each run executes `generate_dataset(config, scale, seed, validate=False, inject_anomalies=True)` and `write_generated_data(..., publish_ground_truth=False)` in a fresh Python subprocess. Outputs are written before the next run starts, and generated business/event timestamps derive from seeded entity dates; no wall-clock time is used in dataset records. Manifest generation timestamps, where present, are operational metadata only.", "",
        "Exact generation calls run in separate Python processes (the CLI command above is the one-command entry point):", "", "```python",
        *worker_lines,
        "```", "",
        "## Same-seed row counts and per-table SHA-256", "",
        _md_table(["table_name", "rows_run1", "rows_run2", "checksum_run1", "checksum_run2", "match"],
                  [[r[k] for k in ("table_name", "rows_run1", "rows_run2", "checksum_run1", "checksum_run2", "match")] for r in table_same]),
        "## Same-seed per-file SHA-256", "",
        _md_table(["file", "sha256_run1", "sha256_run2", "match"],
                  [[r[k] for k in ("file", "sha256_run1", "sha256_run2", "match")] for r in files_same]),
        "## Different-seed counter-property by table (run 1 vs run 3)", "",
        _md_table(["table_name", "rows_run1", "rows_run3", "checksum_run1", "checksum_run3", "match"],
                  [[r[k] for k in ("table_name", "rows_run1", "rows_run3", "checksum_run1", "checksum_run3", "match")] for r in tables_diff]),
        "## Different-seed per-file SHA-256", "",
        _md_table(["file", "sha256_run1", "sha256_run3", "match"],
                  [[r["file"], r["sha256_run1"], r["sha256_run3"], r["match"]] for r in files_diff]),
        "## Per-column value checksums", "",
        "Each column is hashed from sorted, typed, null-aware values; table/file checksums also verify row ordering and byte identity.", "",
        _md_table(["table_name", "column_name", "checksum_run1", "checksum_run2", "match_run1_run2", "checksum_run3", "match_run1_run3"],
                  [[r[k] for k in ("table_name", "column_name", "checksum_run1", "checksum_run2", "match_run1_run2", "checksum_run3", "match_run1_run3")] for r in columns]),
        "## Numeric-column means (10 decimal places)", "",
        _md_table(["table_name", "column_name", "mean_run1", "mean_run2", "match_run1_run2", "mean_run3", "match_run1_run3"],
                  [[r[k] for k in ("table_name", "column_name", "mean_run1", "mean_run2", "match_run1_run2", "mean_run3", "match_run1_run3")] for r in means]),
        "## Event-log determinism", "",
        f"- Same event IDs and ordering in run 1/2: **{'YES' if event_ids_same else 'NO'}**",
        f"- Same event timestamps in run 1/2: **{'YES' if event_timestamps_same else 'NO'}**",
        "- Event IDs, timestamps, sequence order, and exported bytes are compared; generated events use entity/seed-derived time only.", "",
        "## Three concrete ID-content examples", "",
        _md_table(["entity", "record_id", "same-seed content", "different-seed content", "row hash run1", "row hash run2", "row hash run3", "sample run1 fields"],
                  [[x["entity"], x["record_id"], "IDENTICAL" if x["same_seed_identical"] else "DIFFERENT",
                    "DIFFERENT" if x["different_seed_differs"] else "IDENTICAL", x["hash1"], x["hash2"], x["hash3"], json.dumps(x["fields"], default=str)] for x in examples]),
        "## Full-scale same-seed double-generation", "",
    ]
    if full is not None:
        lines.extend([
            f"**Full-scale result: {'PASS' if full['pass'] else 'FAIL'}**", "",
            _md_table(["table_name", "rows_run1", "rows_run2", "checksum_run1", "checksum_run2", "match"],
                      [[r[k] for k in ("table_name", "rows_run1", "rows_run2", "checksum_run1", "checksum_run2", "match")] for r in full["tables"]]),
            "### Full-scale per-file SHA-256", "",
            _md_table(["file", "sha256_run1", "sha256_run2", "match"],
                      [[r[k] for k in ("file", "sha256_run1", "sha256_run2", "match")] for r in full["files"]]),
            "### Full-scale per-column value checksums", "",
            _md_table(["table_name", "column_name", "checksum_run1", "checksum_run2", "match"],
                      [[r["table_name"], r["column_name"], r["checksum_run1"], r["checksum_run2"], r["match_run1_run2"]] for r in full["columns"]]),
            "### Full-scale numeric means (10 decimal places)", "",
            _md_table(["table_name", "column_name", "mean_run1", "mean_run2", "match"],
                      [[r["table_name"], r["column_name"], r["mean_run1"], r["mean_run2"], r["match_run1_run2"]] for r in full["means"]]),
            f"- Full-scale event IDs and ordering identical: **{'YES' if full['event_ids_same'] else 'NO'}**",
            f"- Full-scale event timestamps identical: **{'YES' if full['event_timestamps_same'] else 'NO'}**", "",
        ])
    else:
        lines.extend(["Full-scale double-generation was skipped or the selected scale was already `full`.", ""])
    lines.extend(["## Conclusion", "", "Same-seed outputs must match for every table/file/column checksum and numeric mean. Run 3 must diverge in entity data, proving the seed drives generation."])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"overall_pass": overall_pass, "same_seed_pass": same_pass, "different_seed_pass": different_seed_pass,
            "full_scale": full, "report_path": str(report_path), "run1": run1, "run2": run2, "run3": run3,
            "examples": examples, "same_table_results": table_same, "same_file_results": files_same}
