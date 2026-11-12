import json

import pytest

from asset3d.viewer_manifest import build_viewer_manifest, write_viewer_manifest


def test_index_tracks_real_outputs_and_reference_with_portable_paths(tmp_path):
    root = tmp_path / "results" / "study"
    root.mkdir(parents=True)
    reference = tmp_path / "data" / "cup" / "reference_normalized.glb"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"reference")
    plan = {"plan": {"configs": [{"name": "baseline"}, {"name": "improved"}],
                     "objects": [{"id": "cup", "reference": "/obsolete/server/path.glb"}],
                     "seeds": [42, 123]}}
    (root / "experiment.json").write_text(json.dumps(plan), encoding="utf-8")
    generated = root / "baseline" / "cup" / "seed-42"
    generated.mkdir(parents=True)
    (generated / "manifest.json").write_text('{"status":"completed"}', encoding="utf-8")
    (generated / "asset.glb").write_bytes(b"model")
    (generated / "input.png").write_bytes(b"image")
    stale = root / "baseline" / "cup" / "seed-123"
    stale.mkdir(parents=True)
    (stale / "asset.glb").write_bytes(b"incomplete output")
    improved = root / "improved" / "cup" / "seed-42"
    improved.mkdir(parents=True)
    (improved / "input.png").write_bytes(b"different image")
    target = root / "viewer-manifest.json"
    write_viewer_manifest(root, target, tmp_path / "data")
    result = json.loads(target.read_text(encoding="utf-8"))
    assert (target.parent / result["objects"][0]["reference"]).resolve() == reference.resolve()
    assert (target.parent / result["objects"][0]["input"]).resolve() == generated / "input.png"
    assert len(result["runs"]) == 4
    assert result["variants"][0]["config"]["name"] == "baseline"
    assert result["runs"][0]["status"] == "completed"
    assert (target.parent / result["runs"][0]["input"]).resolve() == generated / "input.png"
    assert (target.parent / result["runs"][2]["input"]).resolve() == improved / "input.png"
    assert result["runs"][1]["input"] is None
    assert (target.parent / result["runs"][0]["models"]["asset"]).resolve() == generated / "asset.glb"
    assert result["runs"][1]["status"] == "pending" and result["runs"][1]["models"] == {}
    with pytest.raises(FileExistsError):
        write_viewer_manifest(root, target)
    write_viewer_manifest(root, target, overwrite=True)


def test_index_rejects_unsafe_plan_paths(tmp_path):
    plan = {"plan": {"configs": [{"name": "../../bad"}],
                     "objects": [{"id": "cup", "reference": None}], "seeds": [42]}}
    (tmp_path / "experiment.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe configuration"):
        build_viewer_manifest(tmp_path, tmp_path / "index.json")


def test_index_checks_relocated_reference_hash(tmp_path):
    root = tmp_path / "exp"
    root.mkdir()
    ref = tmp_path / "references" / "cup" / "reference_normalized.glb"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"wrong reference")
    plan = {"plan": {"configs": [{"name": "baseline"}],
                     "objects": [{"id": "cup", "reference_sha256": "0" * 64}], "seeds": [42]}}
    (root / "experiment.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="Reference SHA256 mismatch for cup"):
        write_viewer_manifest(root, root / "viewer-manifest.json", tmp_path / "references")
    assert not (root / "viewer-manifest.json").exists()


def test_batch_writes_index_during_generation(tmp_path, monkeypatch):
    from asset3d import experiments

    manifest = tmp_path / "manifest.csv"
    manifest.write_text("fixture", encoding="utf-8")
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    reference = tmp_path / "reference.glb"
    reference.write_bytes(b"reference")
    rows = [{"id": "cup", "image": str(image), "reference": str(reference), "split": "dev"}]
    monkeypatch.setattr(experiments, "read_manifest", lambda *_: rows)
    monkeypatch.setattr(experiments, "load_config", lambda _: {"name": "baseline", "shape": {"steps": 50}})

    class FakePipeline:
        def __init__(self, config):
            self.config = config

        def run(self, image, directory, seed, resume):
            directory.mkdir(parents=True)
            (directory / "asset.glb").write_bytes(b"asset")
            (directory / "manifest.json").write_text('{"status":"completed"}', encoding="utf-8")

    monkeypatch.setattr(experiments, "Pipeline", FakePipeline)
    root = tmp_path / "results"
    assert experiments.run_experiments(manifest, ["config"], [42], root, "dev") == []
    index = json.loads((root / "viewer-manifest.json").read_text(encoding="utf-8"))
    assert index["variants"][0]["config"]["shape"]["steps"] == 50
    assert index["runs"][0]["models"]["asset"].endswith("asset.glb")
    assert index["runs"][0]["status"] == "completed"


def test_batch_continues_and_preserves_foreign_index(tmp_path, monkeypatch, capsys):
    from asset3d import experiments

    manifest = tmp_path / "manifest.csv"
    manifest.write_text("fixture", encoding="utf-8")
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    rows = [{"id": "cup", "image": str(image), "reference": None, "split": "real"}]
    monkeypatch.setattr(experiments, "read_manifest", lambda *_: rows)
    monkeypatch.setattr(experiments, "load_config", lambda _: {"name": "baseline"})
    ran = []

    class FakePipeline:
        def __init__(self, config):
            pass

        def run(self, image, directory, seed, resume):
            ran.append(seed)

    monkeypatch.setattr(experiments, "Pipeline", FakePipeline)
    root = tmp_path / "results"
    root.mkdir()
    foreign = root / "viewer-manifest.json"
    foreign.write_text('{"custom":"keep"}', encoding="utf-8")
    assert experiments.run_experiments(manifest, ["config"], [42], root, "real") == []
    assert ran == [42]
    assert json.loads(foreign.read_text(encoding="utf-8")) == {"custom": "keep"}
    assert "Viewer index update failed" in capsys.readouterr().err


def test_auto_index_reports_write_error(tmp_path, monkeypatch, capsys):
    from asset3d import experiments

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(experiments, "write_viewer_manifest", fail)
    experiments._update_viewer_manifest(tmp_path)
    assert "OSError: disk full" in capsys.readouterr().err
