import json
from copy import deepcopy

import pytest
from conftest import FakeBackend

from asset3d.export import check_glb
from asset3d.pipeline import Pipeline


def test_full_pipeline_and_no_overwrite(config, picture, tmp_path):
    backend = FakeBackend()
    pipeline = Pipeline(config, backend)
    out = tmp_path / "run"
    asset = pipeline.run(picture, out)
    assert asset.name == "asset.glb"
    assert check_glb(asset)["meshes"][0]["has_texture"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert set(manifest["artifacts"]) == {"input.png", "foreground.png", "shape_raw.glb", "asset.glb"}
    assert pipeline.run(picture, out, resume=True) == asset
    assert backend.shapes == 1
    with pytest.raises(FileExistsError):
        pipeline.run(picture, out)


def test_resume_texture_does_not_regenerate_geometry(config, picture, tmp_path):
    backend = FakeBackend(fail_texture=True)
    out = tmp_path / "run"
    with pytest.raises(RuntimeError, match="texture failure"):
        Pipeline(config, backend).run(picture, out)
    assert (out / "shape_raw.glb").is_file()
    m = json.loads((out / "manifest.json").read_text())
    assert m["status"] == "failed" and m["attempts"][0]["failed_stage"] == "texture"
    backend.fail_texture = False
    Pipeline(config, backend).run(picture, out, resume=True)
    assert backend.shapes == 1
    m = json.loads((out / "manifest.json").read_text())
    assert "shape_raw.glb" in m["attempts"][1]["reused"]


def test_resume_rejects_different_config_or_seed(config, picture, tmp_path):
    out = tmp_path / "run"
    Pipeline(config, FakeBackend()).run(picture, out)
    changed = deepcopy(config)
    changed["shape"]["steps"] = 20
    with pytest.raises(ValueError, match="changed"):
        Pipeline(changed, FakeBackend()).run(picture, out, resume=True)
    with pytest.raises(ValueError, match="changed"):
        Pipeline(config, FakeBackend()).run(picture, out, seed=99, resume=True)


def test_corrupted_cache_and_lock_rejected(config, picture, tmp_path):
    out = tmp_path / "run"
    pipeline = Pipeline(config, FakeBackend())
    pipeline.run(picture, out)
    (out / "shape_raw.glb").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Cached artifact"):
        pipeline.run(picture, out, resume=True)
    (out / ".running.lock").touch()
    with pytest.raises(RuntimeError, match="locked"):
        pipeline.run(picture, out, resume=True)


def test_shape_only_not_reported_as_textured_completion(config, picture, tmp_path):
    config["texture"]["enabled"] = False
    out = tmp_path / "run"
    result = Pipeline(config, FakeBackend()).run(picture, out)
    assert result.name == "shape_raw.glb"
    assert json.loads((out / "manifest.json").read_text())["status"] == "shape_only"
