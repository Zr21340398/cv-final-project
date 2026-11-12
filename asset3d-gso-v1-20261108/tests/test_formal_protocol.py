import json
from copy import deepcopy

import pytest
import trimesh
from conftest import FakeBackend

from asset3d.config import load_config
from asset3d.data import read_manifest
from asset3d.formal import DEFAULT_CONFIGS, development_evidence, run_formal
from asset3d.pipeline import Pipeline
from asset3d.recording import environment, object_hash, save_json


def test_formal_step_configs_keep_all_other_variables_fixed():
    configs = [load_config(p) for p in DEFAULT_CONFIGS]
    assert [c["shape"]["steps"] for c in configs] == [50, 30, 20]
    normalized = []
    for c in configs:
        assert c["texture"]["max_faces_before_paint"] == 40000
        assert c["preprocess"]["background"] == "keep"
        assert c["model"]["local_files_only"] is True
        c = deepcopy(c)
        del c["name"]
        del c["shape"]["steps"]
        normalized.append(c)
    assert normalized[0] == normalized[1] == normalized[2]


def test_test_split_requires_explicit_development_handoff(tmp_path):
    with pytest.raises(ValueError, match="Test requires explicit"):
        run_formal("missing.csv", "missing-selection.csv", None, [42], tmp_path / "out", "test")
    assert not (tmp_path / "out").exists()


def test_formal_bad_data_never_dispatches_gpu(tmp_path, monkeypatch):
    import asset3d.experiments as experiments
    import asset3d.formal_data as data

    monkeypatch.setattr(
        data, "audit_formal_dataset", lambda *a, **kw: {"ready": False, "errors": ["missing"]}
    )

    def forbidden(*args, **kwargs):
        pytest.fail("No batch may start for invalid data")

    monkeypatch.setattr(experiments, "run_experiments", forbidden)
    with pytest.raises(ValueError, match="dataset is not ready"):
        run_formal("missing.csv", "missing-selection.csv", None, [42], tmp_path / "out", dry_run=True)
    assert not (tmp_path / "out").exists()


def test_cli_dispatches_batch_execution_controls(monkeypatch, tmp_path):
    import asset3d.experiments as experiments
    from asset3d.cli import main

    calls = []
    monkeypatch.setattr(experiments, "run_experiments", lambda *a, **kw: calls.append((a, kw)) or [])
    assert (
        main(
            [
                "batch",
                "--manifest",
                "unused.csv",
                "--output",
                str(tmp_path),
                "--dry-run",
                "--timeout",
                "25",
                "--limit",
                "1",
            ]
        )
        == 0
    )
    assert calls[0][1] == {"timeout": 25, "limit": 1, "retry_failed": False, "dry_run": True}


def test_development_handoff_checks_all_results_and_artifact_hashes(tmp_path, picture):
    config = load_config(DEFAULT_CONFIGS[0])
    reference = tmp_path / "reference.glb"
    trimesh.creation.box().export(reference)
    manifest = tmp_path / "objects.csv"
    manifest.write_text(
        "id,image,reference,split\n"
        + "".join(f"o{i},{picture.name},{reference.name},dev\n" for i in range(10))
    )
    objects = read_manifest(manifest, "dev")
    root = tmp_path / "dev"
    protocol = {"roster_sha256": "roster-30-objects", "render_protocol_sha256": "render-protocol"}
    plan = {
        "split": "dev",
        "source_hash": environment()["source_hash"],
        "context": {"formal_gso": True, **protocol},
        "configs": [config],
        "seeds": [42],
        "objects": objects,
    }
    save_json(root / "experiment.json", {"plan": plan, "plan_sha256": object_hash(plan)})
    for obj in objects:
        Pipeline(config, FakeBackend()).run(picture, root / config["name"] / obj["id"] / "seed-42")
    assert development_evidence(root, [config], [42], manifest, **protocol) == object_hash(plan)
    with pytest.raises(ValueError, match="object roster changed"):
        development_evidence(
            root, [config], [42], manifest, **{**protocol, "roster_sha256": "changed-test-object"}
        )
    with pytest.raises(ValueError, match="rendering differs"):
        development_evidence(
            root, [config], [42], manifest, **{**protocol, "render_protocol_sha256": "changed-camera"}
        )
    with pytest.raises(ValueError, match="same seeds"):
        development_evidence(root, [config], [123], manifest, **protocol)
    with pytest.raises(ValueError, match="not validated"):
        development_evidence(root, [load_config(DEFAULT_CONFIGS[1])], [42], manifest, **protocol)
    (root / config["name"] / "o9/seed-42/asset.glb").write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        development_evidence(root, [config], [42], manifest, **protocol)
    doc = json.loads((root / "experiment.json").read_text())
    doc["plan"]["source_hash"] = "new-source"
    doc["plan_sha256"] = object_hash(doc["plan"])
    save_json(root / "experiment.json", doc)
    with pytest.raises(ValueError, match="same source"):
        development_evidence(root, [config], [42], manifest, **protocol)
