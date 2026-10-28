from __future__ import annotations
import json
from pathlib import Path
import supplier_ack.cli as cli

def test_generate_default_output_directory_is_data_generated(tmp_path, monkeypatch):
    config_src = Path(__file__).resolve().parents[1] / "config" / "generator_config.yaml"
    config_dir = tmp_path / "config"; config_dir.mkdir()
    config = config_dir / "generator_config.yaml"; config.write_bytes(config_src.read_bytes())
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    cli.main(["generate", "--config", str(config), "--scale", "starter"])
    generated = tmp_path / "data" / "generated"
    assert (generated / "ground_truth.csv").is_file()
    summary = json.loads((generated / "generation_summary.json").read_text(encoding="utf-8"))
    assert summary.get("seed", 20261022) == 20261022
