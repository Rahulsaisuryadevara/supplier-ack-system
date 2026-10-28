"""Keep runtime plotting/report dependencies declared for clean installs."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_plotting_and_reporting_dependencies_are_declared():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {dependency.split("[", 1)[0].split("=", 1)[0].strip().lower().replace("_", "-") for dependency in project["dependencies"]}
    assert {"matplotlib", "tabulate"}.issubset(declared)
