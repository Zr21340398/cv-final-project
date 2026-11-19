import csv
import json
from pathlib import Path

import pytest
import yaml

from asset3d.batch_definition import prepare_batch


def test_shared_subset_and_freeze(tmp_path):
    data = tmp_path / "datasets/sample"
    data.mkdir(parents=True)
    (data / "image.png").write_bytes(b"image")
    (data / "reference.glb").write_bytes(b"reference")
    with (data / "catalog.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "image", "reference", "split"])
        writer.writerow(["chosen", "image.png", "reference.glb", "dev"])
        writer.writerow(["not_downloaded", "missing.png", "missing.glb", "test"])
    work = tmp_path / "experiments/batch1"
    work.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    spec = {"schema_version": 1, "dataset_manifest": "datasets/sample/catalog.csv",
            "objects": ["chosen"], "split": "dev", "seeds": [42, 123],
            "configs": [str(repo / "configs/trellis2_gso_dev.yaml")]}
    definition = work / "batch.yaml"
    definition.write_text(yaml.safe_dump(spec), encoding="utf-8")
    selection, configs, seeds, output, split = prepare_batch(definition, tmp_path)
    assert output == work / "results"
    assert seeds == [42, 123] and split == "dev"
    assert "../../datasets/sample/image.png" in selection.read_text(encoding="utf-8")
    assert json.loads(Path(configs[0]).read_text(encoding="utf-8"))["backend"] == "trellis2"
    assert not list(work.rglob("*.glb"))
    prepare_batch(definition, tmp_path)  # 未变动的计划可继续使用。
    (data / "image.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        prepare_batch(definition, tmp_path)
