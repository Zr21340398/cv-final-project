import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import trimesh
from conftest import FakeBackend

from asset3d.backends.hunyuan2 import HunyuanBackend
from asset3d.config import load_config, validate
from asset3d.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]


def install_reducer(monkeypatch, calls):
    class FaceReducer:
        def __call__(self, mesh, max_facenum):
            calls.append((mesh, max_facenum))
            # Deliberately mutate the supplied mesh to detect accidental raw-mesh reuse.
            mesh.vertices = mesh.vertices + [1, 2, 3]
            mesh.faces = mesh.faces[:max_facenum]
            return mesh

    shapegen = types.ModuleType("hy3dgen.shapegen")
    shapegen.FaceReducer = FaceReducer
    monkeypatch.setitem(sys.modules, "hy3dgen.shapegen", shapegen)


@pytest.mark.parametrize("value", [0, -1, 1.5, "40000", True, None])
def test_face_limit_requires_a_positive_integer(config, value):
    config["texture"]["max_faces_before_paint"] = value
    with pytest.raises(ValueError, match="max_faces_before_paint must be a positive integer"):
        validate(config)


def test_retry_config_is_explicit_and_keeps_the_runner_name():
    legacy = load_config(ROOT / "configs/hunyuan2_pilot.yaml")
    retry = load_config(ROOT / "configs/hunyuan2_pilot_retry.yaml")
    assert "max_faces_before_paint" not in legacy["texture"]
    assert retry["name"] == legacy["name"] == "hunyuan2"
    expected = deepcopy(legacy)
    expected["texture"]["max_faces_before_paint"] = 40000
    assert retry == expected


def test_reducer_only_mutates_a_texture_mesh_copy(config, monkeypatch):
    config["texture"]["max_faces_before_paint"] = 100
    calls = []
    install_reducer(monkeypatch, calls)
    raw = trimesh.creation.icosphere(subdivisions=2)
    vertices, faces = raw.vertices.copy(), raw.faces.copy()

    texture, metadata = HunyuanBackend(config).prepare_texture_mesh(raw)

    assert len(calls) == 1 and calls[0][0] is not raw and calls[0][1] == 100
    assert texture is not raw
    assert np.array_equal(raw.vertices, vertices)
    assert np.array_equal(raw.faces, faces)
    assert len(texture.faces) == 100
    assert metadata["faces_before"] == len(faces)
    assert metadata["faces_after"] == metadata["target_faces"] == 100
    assert metadata["applied"] is True and metadata["seconds"] >= 0


def test_legacy_and_small_meshes_do_not_run_the_reducer(config, monkeypatch):
    calls = []
    install_reducer(monkeypatch, calls)
    raw = trimesh.creation.icosphere(subdivisions=1)
    texture, metadata = HunyuanBackend(config).prepare_texture_mesh(raw)
    assert texture is raw and metadata is None and not calls

    config["texture"]["max_faces_before_paint"] = 40000
    texture, metadata = HunyuanBackend(config).prepare_texture_mesh(raw)
    assert texture is not raw and not calls
    assert np.array_equal(texture.faces, raw.faces)
    assert metadata["faces_after"] == metadata["faces_before"] == len(raw.faces)
    assert metadata["applied"] is False and metadata["seconds"] == 0


def test_prepaint_counts_survive_paint_failure_and_raw_glb_is_preserved(
    config, picture, tmp_path, monkeypatch
):
    config["texture"]["max_faces_before_paint"] = 100
    calls = []
    install_reducer(monkeypatch, calls)
    backend = FakeBackend(fail_texture=True)
    backend.prepare_texture_mesh = HunyuanBackend(config).prepare_texture_mesh
    out = tmp_path / "run"

    with pytest.raises(RuntimeError, match="texture failure"):
        Pipeline(config, backend).run(picture, out)

    raw = trimesh.load(out / "shape_raw.glb", force="mesh", process=False)
    assert len(raw.faces) == 320
    manifest = json.loads((out / "manifest.json").read_text())
    attempt = manifest["attempts"][0]
    assert attempt["failed_stage"] == "texture"
    assert attempt["texture_mesh"]["faces_before"] == 320
    assert attempt["texture_mesh"]["faces_after"] == 100
    assert attempt["timings"]["texture_mesh_reduce"] == attempt["texture_mesh"]["seconds"]
