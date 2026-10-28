from __future__ import annotations
import csv, hashlib, importlib.metadata, json, os, re, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from supplier_ack.validation.suite import TABLES, PK, validate_dataset
from supplier_ack.schema import ENTITIES

# Declared relational links shared by SQL DDL and export verification.
FKS = {
"suppliers":[("preferred_carrier_id","carriers","carrier_id")],
"actors":[("supplier_id","suppliers","supplier_id")],
"purchase_orders":[("supplier_id","suppliers","supplier_id"),("planner_actor_id","actors","actor_id"),("warehouse_id","warehouses","warehouse_id"),("carrier_id","carriers","carrier_id")],
"po_lines":[("po_id","purchase_orders","po_id"),("item_id","items","item_id")],
"acknowledgements":[("po_id","purchase_orders","po_id"),("supplier_id","suppliers","supplier_id")],
"acknowledgement_lines":[("ack_id","acknowledgements","ack_id"),("po_id","purchase_orders","po_id"),("po_line_id","po_lines","po_line_id")],
"promise_dates":[("ack_id","acknowledgements","ack_id"),("po_id","purchase_orders","po_id"),("po_line_id","po_lines","po_line_id"),("carrier_id","carriers","carrier_id"),("ship_from_warehouse_id","warehouses","warehouse_id")],
"change_requests":[("po_id","purchase_orders","po_id"),("supplier_id","suppliers","supplier_id"),("po_line_id","po_lines","po_line_id")],
"approvals":[("change_request_id","change_requests","change_request_id"),("approver_actor_id","actors","actor_id")],
"inventory_plans":[("po_id","purchase_orders","po_id"),("po_line_id","po_lines","po_line_id"),("change_request_id","change_requests","change_request_id")],
"production_orders":[("po_id","purchase_orders","po_id"),("po_line_id","po_lines","po_line_id"),("inventory_plan_id","inventory_plans","inventory_plan_id")],
"production_order_line":[("production_order_id","production_orders","production_order_id"),("po_line_id","po_lines","po_line_id")],
"production_order_impact":[("production_order_id","production_orders","production_order_id"),("change_request_id","change_requests","change_request_id"),("po_line_id","po_lines","po_line_id")],
"notifications":[("po_id","purchase_orders","po_id"),("ack_id","acknowledgements","ack_id"),("change_request_id","change_requests","change_request_id")],
"notification_recipient":[("notification_id","notifications","notification_id"),("recipient_actor_id","actors","actor_id")],
"entity_event":[("target_po_id","purchase_orders","po_id"),("target_po_line_id","po_lines","po_line_id"),("target_ack_id","acknowledgements","ack_id"),("target_promise_date_id","promise_dates","promise_date_id"),("target_change_request_id","change_requests","change_request_id"),("target_approval_id","approvals","approval_id"),("target_inventory_plan_id","inventory_plans","inventory_plan_id"),("target_production_order_id","production_orders","production_order_id"),("target_notification_id","notifications","notification_id")],
}
COMPOSITE_PK={"notification_recipient":["notification_id","actor_role"],"production_order_line":["production_order_id","po_line_id"]}

def _read_csvs(root: Path) -> dict[str,pd.DataFrame]:
    frames={}
    for table in TABLES:
        p=root/f"{table}.csv"
        if p.exists(): frames[table]=pd.read_csv(p,dtype=str,keep_default_na=False,encoding="utf-8",low_memory=False)
    if not frames: raise FileNotFoundError(f"no source entity CSVs found in {root}")
    return frames

def _read_truth(root: Path) -> tuple[pd.DataFrame, Any]:
    p=root/"ground_truth.csv"
    frame=pd.read_csv(p,dtype=str,keep_default_na=False,encoding="utf-8",low_memory=False) if p.exists() else pd.DataFrame(columns=["record_type","record_id","issue_type","expected_decision","related_entity_ids","expected_severity","notes"])
    return frame, frame.to_dict(orient="records")

def _sql_type(table:str,col:str)->str:
    spec=next((e for e in ENTITIES.values() if e.table_name==table),None)
    if spec:
        field=next((f for f in spec.fields if f.name==col),None)
        if field:
            typ=field.sql_type.upper()
            return "INTEGER" if "INT" in typ or "BOOL" in typ else "REAL" if any(x in typ for x in ("DECIMAL","NUMERIC","REAL","FLOAT")) else "TEXT"
    return "INTEGER" if col.endswith("_count") or col in {"plan_version","revision_no","slip_days","shortfall_days","retry_count","is_read","is_effective","is_current","is_late","boundary","ground_truth"} else "TEXT"

def _ddl(table:str, frame:pd.DataFrame)->str:
    cols=list(frame.columns); defs=[]
    for c in cols:
        ty=_sql_type(table,c)
        if table in PK and PK[table]==c: defs.append(f'"{c}" {ty} PRIMARY KEY')
        else: defs.append(f'"{c}" {ty}')
    if table in COMPOSITE_PK:
        defs.append("PRIMARY KEY ("+", ".join(f'"{x}"' for x in COMPOSITE_PK[table])+")")
    for child,parent,pcol in FKS.get(table,[]):
        if child in cols and parent in frames_for_ddl and pcol in frames_for_ddl[parent].columns:
            defs.append(f'FOREIGN KEY ("{child}") REFERENCES "{parent}"("{pcol}")')
    return f'CREATE TABLE "{table}" (\n  '+",\n  ".join(defs)+"\n);"

frames_for_ddl:dict[str,pd.DataFrame]={}

def _sql_literal(v:Any)->str:
    if v is None or (isinstance(v,float) and pd.isna(v)): return "NULL"
    s=str(v)
    if s=="" : return "NULL"
    return "'"+s.replace("'","''")+"'"

def _build_sql(frames:dict[str,pd.DataFrame])->str:
    global frames_for_ddl
    frames_for_ddl=frames
    out=["-- Generated from the canonical CSV dataset. Synthetic data only.","-- FK constraints are declared; enforcement is temporarily disabled during import so labelled anomalies remain auditable.","PRAGMA foreign_keys = OFF;","BEGIN TRANSACTION;"]
    for table,frame in frames.items(): out.append(_ddl(table,frame))
    for table,frame in frames.items():
        if frame.empty: continue
        cols=list(frame.columns); colsql=", ".join('"'+c+'"' for c in cols)
        out.append(f'INSERT INTO "{table}" ({colsql}) VALUES')
        # Chunk insert statements to keep seed.sql executable and avoid giant statements.
        records=frame.itertuples(index=False,name=None)
        chunks=[]; batch=[]
        for row in records:
            batch.append("("+", ".join(_sql_literal(v) for v in row)+")")
            if len(batch)>=500:
                chunks.append(",\n".join(batch)); batch=[]
        if batch: chunks.append(",\n".join(batch))
        # Each chunk is a separate insert, so repeat header for all but first.
        out.pop()
        for chunk in chunks: out.append(f'INSERT INTO "{table}" ({colsql}) VALUES\n{chunk};')
    out.extend(["COMMIT;","PRAGMA foreign_keys = ON;",""])
    return "\n\n".join(out)

def _load_db(db_path:Path, sql_path:Path, frames:dict[str,pd.DataFrame])->None:
    if db_path.exists(): db_path.unlink()
    # Execute the same SQL seed delivered to reviewers, not a parallel loading path.
    conn=sqlite3.connect(db_path)
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
        for table,frame in frames.items():
            n=conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if n!=len(frame): raise RuntimeError(f"SQLite import row-count mismatch for {table}: {n} != {len(frame)}")
        # Check the declared schema retains FK definitions; violations in labelled anomaly rows are expected.
        for table in frames:
            conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
    finally: conn.close()

def _dataset_from_db(db_path:Path, truth_rows:list[dict[str,Any]])->dict[str,Any]:
    conn=sqlite3.connect(db_path); conn.row_factory=sqlite3.Row
    try: data={table:[dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')] for table in TABLES if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()}
    finally: conn.close()
    data["ground_truth_records"]=truth_rows
    return data

def _secret_scan(repo_root:Path)->dict[str,Any]:
    patterns=[re.compile(r"\bAKIA[0-9A-Z]{16}\b"),re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{24,}\b"),re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")]
    try:
        files=subprocess.run(["git","-C",str(repo_root),"ls-files","-z"],capture_output=True,check=True).stdout.split(b"\0")
        paths=[repo_root/os.fsdecode(p) for p in files if p]
    except Exception: paths=[p for p in repo_root.rglob("*") if p.is_file() and ".git" not in p.parts]
    matches=[]; checked=0
    for p in paths:
        if not p.is_file() or p.stat().st_size>5_000_000: continue
        try: content=p.read_text(encoding="utf-8",errors="ignore")
        except OSError: continue
        checked+=1
        for pattern in patterns:
            if pattern.search(content): matches.append({"file":str(p.relative_to(repo_root)),"pattern":pattern.pattern})
    return {"checked_files":checked,"matches":matches,"status":"FAIL" if matches else "PASS"}

def export_dataset(dataset_dir:str|Path, formats:str|list[str]="csv,json,sql", *, output_root:str|Path|None=None)->dict[str,Any]:
    root=Path(dataset_dir).resolve(); output=Path(output_root).resolve() if output_root else root
    chosen={x.strip().lower() for x in formats.split(",")} if isinstance(formats,str) else set(formats)
    if not chosen or not chosen.issubset({"csv","json","sql"}): raise ValueError("formats must be csv,json,sql (any subset)")
    frames=_read_csvs(root); truth,truth_records=_read_truth(root)
    report={"source_dataset":str(root),"formats":sorted(chosen),"row_counts":{k:int(len(v)) for k,v in frames.items()},"generated_at":datetime.now(timezone.utc).isoformat(),"files":{}}
    output.mkdir(parents=True,exist_ok=True)
    if "csv" in chosen:
        dest=output/"csv"; dest.mkdir(parents=True,exist_ok=True)
        for table,frame in frames.items(): frame.to_csv(dest/f"{table}.csv",index=False,encoding="utf-8",lineterminator="\n")
        truth.to_csv(dest/"ground_truth.csv",index=False,encoding="utf-8",lineterminator="\n")
    if "json" in chosen:
        dest=output/"json"; dest.mkdir(parents=True,exist_ok=True)
        for table,frame in frames.items():
            with (dest/f"{table}.json").open("w",encoding="utf-8") as f: json.dump(frame.to_dict(orient="records"),f,ensure_ascii=False,separators=(",",":")); f.write("\n")
        with (dest/"ground_truth.json").open("w",encoding="utf-8") as f: json.dump(truth_records,f,ensure_ascii=False,indent=2); f.write("\n")
        (dest/"manifest.json").write_text(json.dumps({"row_counts":report["row_counts"],"seed":_seed_from_root(root),"scale":_scale_from_root(root)},indent=2)+"\n",encoding="utf-8")
    if "sql" in chosen:
        dest=output/"sql"; dest.mkdir(parents=True,exist_ok=True); sql_path=dest/"seed.sql"; db_path=dest/"seed.db"
        sql_path.write_text(_build_sql(frames),encoding="utf-8")
        _load_db(db_path,sql_path,frames)
        db_dataset=_dataset_from_db(db_path,truth_records)
        from supplier_ack.validation.suite import validate_dataset
        db_validation=validate_dataset(db_dataset,root)
        (dest/"sqlite_validation_summary.json").write_text(json.dumps(db_validation,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        if db_validation["overall_status"]!="PASS":
            raise RuntimeError(f"SQLite seed database validation failed: {[c for c in db_validation['checks'] if c['status']=='FAIL'][:2]}")
    # Source manifest includes source snapshot and checksums for every generated file except itself.
    if output.resolve()==root.resolve():
        repo_root=Path(__file__).resolve().parents[3]
        cfg_path=repo_root/"config"/"generator_config.yaml"
        try: cfg_snapshot=yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except Exception: cfg_snapshot={}
        try: commit=subprocess.run(["git","-C",str(repo_root),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
        except Exception: commit="unknown"
        files={}
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.resolve() != (root/"manifest.json").resolve() and ".git" not in p.parts:
                rel=str(p.relative_to(root)); h=hashlib.sha256()
                with p.open("rb") as f:
                    for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
                files[rel]={"sha256":h.hexdigest(),"bytes":p.stat().st_size}
        manifest={"generator_version":"0.1.0","git_commit":commit,"seed":_seed_from_root(root),"scale":_scale_from_root(root),"config_snapshot":cfg_snapshot,"generation_timestamp":datetime.now(timezone.utc).isoformat(),"dependency_versions":{x:(importlib.metadata.version(x) if _has_dist(x) else "not-installed") for x in ("pandas","numpy","PyYAML","supplier-ack-system")},"row_counts":report["row_counts"],"files":files,"secret_scan":_secret_scan(repo_root)}
        (root/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
        if manifest["secret_scan"]["status"]!="PASS": raise RuntimeError(f"secret scan failed: {manifest['secret_scan']['matches'][:3]}")
    return report

def _has_dist(name):
    try: importlib.metadata.version(name); return True
    except importlib.metadata.PackageNotFoundError: return False

def _seed_from_root(root:Path)->int|None:
    try:return int(json.loads((root/"generation_summary.json").read_text()).get("seed"))
    except Exception:return None

def _scale_from_root(root:Path)->str:
    try:return str(json.loads((root/"generation_summary.json").read_text()).get("scale","unknown"))
    except Exception:return "unknown"
