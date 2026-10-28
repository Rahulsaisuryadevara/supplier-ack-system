from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.e2e
def test_demo_script_end_to_end_reports_all_pass(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("scripts/demo.sh requires bash (e.g. Git Bash on Windows)")
    clone = tmp_path / "repo"
    clone.mkdir()
    # Copy only version-controlled files to model a clean checkout. Copying the
    # whole working tree also copies ignored generated outputs and .git, which
    # can make this integration test needlessly slow and non-hermetic.
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    if tracked_result.returncode == 0:
        relative_paths = [Path(os.fsdecode(item)) for item in tracked_result.stdout.split(b"\0") if item]
    else:
        # ZIP/source distributions may not include .git metadata. Recreate a
        # clean source tree by excluding generated outputs and local environments.
        excluded_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
        relative_paths = [
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file()
            and not any(part in excluded_dirs for part in path.relative_to(ROOT).parts)
            and path.relative_to(ROOT).parts[:2] != ("data", "generated")
            and not path.name.endswith((".pyc", ".pyo"))
        ]
    for relative in relative_paths:
        source = ROOT / relative
        if not source.is_file():
            continue
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    env = os.environ.copy()
    env["PYTHON"] = sys.executable
    env["PYTHONPATH"] = str(clone / "src")
    result = subprocess.run([bash, "scripts/demo.sh"], cwd=clone, env=env, text=True, capture_output=True, timeout=600)
    output = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, output[-12000:]
    assert "OVERALL: PASS" in output
    assert "FAIL |" not in output
