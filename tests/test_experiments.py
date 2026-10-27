import csv
import json
from pathlib import Path

import pytest
from conftest import FakeBackend

from asset3d.data import read_manifest
from asset3d.evaluation.summarize import summarize
from asset3d.pipeline import Pipeline
from asset3d.recording import save_json


def test_manifest_paths_resolved_and_unsafe_ids_rejected(tmp_path, picture):
    path = tmp_path / "data.csv"
    path.write_text(f"id,image,reference,split\nphoto,{picture.name},,real\n", encoding="utf-8")
    assert read_manifest(path)[0]["image"] == str(picture.resolve())
    path.write_text(f"id,image,reference,split\n../escape,{picture.name},,real\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe"):
        read_manifest(path)


def test_summary_includes_unrun_and_failed_objects(config, picture, tmp_path):
    root = tmp_path / "experiment"
    plan = {"configs": [config], "objects": [{"id": "a"}, {"id": "b"}], "seeds": [42, 123]}
    save_json(root / "experiment.json", {"plan": plan})
    Pipeline(config, FakeBackend()).run(picture, root / "baseline/a/seed-42")
    with pytest.raises(RuntimeError):
        Pipeline(config, FakeBackend(fail_texture=True)).run(picture, root / "baseline/a/seed-123", seed=123)
    report = summarize(root, root / "summary")
    assert report["baseline"]["planned"] == 4
    assert report["baseline"]["completed"] == 1
    assert report["baseline"]["not_run"] == 2
    assert report["baseline"]["success_rate"] == 0.25
    with (root / "summary/runs.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 4


def test_batch_resumes_full_matrix_and_records_failures(config, picture, tmp_path, monkeypatch):
    import asset3d.experiments as exp

    path = tmp_path / "data.csv"
    path.write_text(f"id,image,reference,split\na,{picture.name},,real\n", encoding="utf-8")
    monkeypatch.setattr(exp, "Pipeline", lambda c: Pipeline(c, FakeBackend()))
    config_path = Path(__file__).resolve().parents[1] / "configs/baseline.yaml"
    root = tmp_path / "batch"
    assert not exp.run_experiments(path, [config_path], [42, 123], root, "real")
    assert not exp.run_experiments(path, [config_path], [42, 123], root, "real", resume=True)
    m = json.loads((root / "baseline/a/seed-42/manifest.json").read_text())
    assert len(m["attempts"]) == 1
