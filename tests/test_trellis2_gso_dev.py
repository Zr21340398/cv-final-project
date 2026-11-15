"""核验开发集检查会拦截换图或样本集不匹配。"""
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_trellis2_gso_dev.py"
spec = importlib.util.spec_from_file_location("gso_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_preflight_rejects_changed_data(tmp_path, monkeypatch):
    folder = tmp_path / "data/manifests"
    folder.mkdir(parents=True)
    image = tmp_path / "image.png"
    Image.new("RGBA", (40, 40), (1, 2, 3, 128)).save(image)
    rows = [{"id": f"gso_{i:02d}", "image": str(image),
             "image_sha256": "correct", "reference_sha256": "reference"} for i in range(10)]
    hashes = {r["id"]: {"image_sha256": "correct", "reference_sha256": "reference"} for r in rows}
    (folder / "gso-dev-v1-frozen-hashes.json").write_text(json.dumps(hashes), encoding="utf-8")
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    monkeypatch.setattr(preflight, "read_manifest", lambda path, split: rows)
    assert len(preflight.check("manifest.csv")) == 10
    rows[0]["image_sha256"] = "changed"
    with pytest.raises(ValueError, match="image_sha256"):
        preflight.check("manifest.csv")
    rows.pop()
    with pytest.raises(ValueError, match="10"):
        preflight.check("manifest.csv")
