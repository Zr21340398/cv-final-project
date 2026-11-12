import csv
import json
from copy import deepcopy

import pytest
import trimesh
from conftest import FakeBackend

from asset3d.evaluation.batch import evaluate_batch
from asset3d.evaluation.summarize import summarize
from asset3d.pipeline import Pipeline
from asset3d.recording import file_hash, object_hash, save_json


def make_experiment(tmp_path, picture, configs, seeds=(42,), run=True):
    root = tmp_path / "experiment"
    reference = tmp_path / "reference.glb"
    trimesh.creation.icosphere(subdivisions=2).export(reference)
    obj = {
        "id": "a",
        "image": str(picture),
        "image_sha256": file_hash(picture),
        "reference": str(reference),
        "reference_sha256": file_hash(reference),
        "split": "dev",
    }
    plan = {"configs": configs, "objects": [obj], "seeds": list(seeds), "split": "dev"}
    save_json(root / "experiment.json", {"plan": plan, "plan_sha256": object_hash(plan)})
    if run:
        for config in configs:
            for seed in seeds:
                Pipeline(config, FakeBackend()).run(
                    picture, root / config["name"] / "a" / f"seed-{seed}", seed
                )
    evaluation = tmp_path / "evaluation.yaml"
    evaluation.write_text("samples: 100\nseed: 2026\nnormalization: unit_bbox\n")
    return root, evaluation


def csv_rows(root):
    with (root / "summary/runs.csv").open() as stream:
        return list(csv.DictReader(stream))


def test_raw_and_final_asset_metrics_remain_separate(tmp_path, config, picture):
    root, evaluation = make_experiment(tmp_path, picture, [config])
    run = root / "baseline/a/seed-42"
    assert evaluate_batch(root, evaluation) == []
    raw = (run / "metrics.json").read_bytes()
    assert evaluate_batch(root, evaluation, artifact="asset.glb") == []
    assert (run / "metrics.json").read_bytes() == raw
    final = json.loads((run / "metrics_asset.json").read_text())
    assert final["prediction_sha256"] == file_hash(run / "asset.glb")
    report = summarize(root, root / "summary")
    assert "chamfer_l2" in report["baseline"]["metrics"]
    assert "asset_chamfer_l2" in report["baseline"]["metrics"]


def test_corrupted_completed_mesh_is_neither_evaluated_nor_counted_success(tmp_path, config, picture):
    root, evaluation = make_experiment(tmp_path, picture, [config])
    run = root / "baseline/a/seed-42"
    assert evaluate_batch(root, evaluation) == []
    (run / "shape_raw.glb").write_bytes(b"changed")
    errors = evaluate_batch(root, evaluation)
    assert len(errors) == 1 and "shape_raw.glb" in errors[0]["error"]
    report = summarize(root, root / "summary")["baseline"]
    assert report["invalid"] == 1 and report["completed"] == 0 and report["success_rate"] == 0
    assert "chamfer_l2" not in report["metrics"]


def test_changed_reference_invalidates_cached_scores(tmp_path, config, picture):
    root, evaluation = make_experiment(tmp_path, picture, [config])
    assert evaluate_batch(root, evaluation) == []
    (tmp_path / "reference.glb").write_bytes(b"different reference")
    report = summarize(root, root / "summary")["baseline"]
    assert report["invalid"] == 1 and not report["metrics"]
    assert "reference" in evaluate_batch(root, evaluation)[0]["error"]


def test_evaluation_rejects_plan_or_source_changes(tmp_path, config, picture, monkeypatch):
    root, evaluation = make_experiment(tmp_path, picture, [config], run=False)
    path = root / "experiment.json"
    doc = json.loads(path.read_text())
    doc["plan"]["seeds"] = [123]
    save_json(path, doc)
    with pytest.raises(ValueError, match="plan"):
        evaluate_batch(root, evaluation)
    doc["plan"]["source_hash"] = "frozen-source"
    doc["plan_sha256"] = object_hash(doc["plan"])
    save_json(path, doc)
    monkeypatch.setattr("asset3d.evaluation.batch.environment", lambda: {"source_hash": "new-source"})
    with pytest.raises(ValueError, match="source changed"):
        evaluate_batch(root, evaluation)


def test_empty_evaluation_reports_skips_instead_of_completion(tmp_path, config, picture):
    root, evaluation = make_experiment(tmp_path, picture, [config], run=False)
    assert evaluate_batch(root, evaluation) == []
    report = json.loads((root / "evaluation-report.json").read_text())
    assert report["evaluated"] == 0 and report["skipped_count"] == 1
    assert report["skipped"][0]["reason"] == "not_run"


def test_shape_only_output_has_raw_scores_without_textured_success(tmp_path, config, picture):
    config["texture"]["enabled"] = False
    root, evaluation = make_experiment(tmp_path, picture, [config])
    assert evaluate_batch(root, evaluation) == []
    assert evaluate_batch(root, evaluation, artifact="asset.glb") == []
    report = summarize(root, root / "summary")["baseline"]
    assert report["shape_only"] == 1 and report["completed"] == 0
    assert "chamfer_l2" in report["metrics"] and "asset_chamfer_l2" not in report["metrics"]
    assert json.loads((root / "evaluation-report-asset.json").read_text())["evaluated"] == 0


def test_failed_reevaluation_does_not_reuse_old_scores(tmp_path, config, picture, monkeypatch):
    root, evaluation = make_experiment(tmp_path, picture, [config])
    assert evaluate_batch(root, evaluation) == []

    def fail(*args):
        raise RuntimeError("evaluation failed")

    monkeypatch.setattr("asset3d.cli.evaluate_one", fail)
    assert len(evaluate_batch(root, evaluation)) == 1
    report = summarize(root, root / "summary")["baseline"]
    assert report["completed"] == 1
    assert "chamfer_l2" not in report["metrics"]
    assert csv_rows(root)[0]["metrics_error"]


def test_resume_cache_check_does_not_replace_real_process_time(tmp_path, config, picture):
    root, _ = make_experiment(tmp_path, picture, [config])
    save_json(
        root / "process-logs/baseline/a-seed-42.json",
        {
            "attempts": [
                {"status": "completed", "wall_seconds": 125.0},
                {"status": "skipped", "reason": "already_completed", "wall_seconds": 0.01},
            ]
        },
    )
    report = summarize(root, root / "summary")["baseline"]
    assert report["completed"] == 1
    assert float(csv_rows(root)[0]["process_wall_seconds"]) == 125.0


def test_validation_failure_cannot_hide_behind_old_completed_manifest(tmp_path, config, picture):
    root, _ = make_experiment(tmp_path, picture, [config])
    save_json(
        root / "process-logs/baseline/a-seed-42.json",
        {
            "attempts": [
                {"status": "completed", "wall_seconds": 125.0},
                {"status": "failed", "phase": "validation", "error": "source mismatch"},
                {"status": "skipped", "reason": "previous_failure_requires_retry", "blocking": True},
            ]
        },
    )
    report = summarize(root, root / "summary")["baseline"]
    assert report["completed"] == 0 and report["failed"] == 1 and not report["metrics"]


def test_restored_artifact_revalidation_recovers_valid_success(tmp_path, config, picture):
    root, _ = make_experiment(tmp_path, picture, [config])
    save_json(
        root / "process-logs/baseline/a-seed-42.json",
        {
            "attempts": [
                {"status": "completed", "wall_seconds": 125.0},
                {"status": "failed", "phase": "validation", "error": "artifact changed"},
                {"status": "skipped", "reason": "already_completed", "artifacts_validated": True},
            ]
        },
    )
    report = summarize(root, root / "summary")["baseline"]
    assert report["completed"] == 1 and report["failed"] == 0
    assert float(csv_rows(root)[0]["process_wall_seconds"]) == 125.0
    # A stale revalidated marker cannot make a subsequently damaged artifact valid.
    (root / "baseline/a/seed-42/asset.glb").write_bytes(b"damaged again")
    assert summarize(root, root / "summary")["baseline"]["invalid"] == 1


def test_paired_statistics_use_common_successful_clean_pairs(tmp_path, config, picture):
    other = deepcopy(config)
    other["name"] = "fast"
    other["shape"]["steps"] = 20
    root, evaluation = make_experiment(tmp_path, picture, [config, other], seeds=(42, 123))
    assert evaluate_batch(root, evaluation) == []
    path = root / "fast/a/seed-123/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["status"] = "failed"
    save_json(path, manifest)
    summarize(root, root / "summary")
    pair = json.loads((root / "summary/summary.json").read_text())["paired_comparisons"][0]
    assert pair["config_a"] == "baseline" and pair["config_b"] == "fast"
    assert pair["common_successful_runs"] == pair["common_clean_runs"] == 1
    assert pair["metrics"]["chamfer_l2"]["paired_runs"] == 1
    assert pair["metrics"]["wall_seconds"]["paired_runs"] == 1
