import json

import numpy as np
import pytest
import trimesh
from conftest import FakeBackend
from PIL import Image

from asset3d.config import validate
from asset3d.pipeline import Pipeline
from asset3d.planar_texture import clean_planar_texture


def plane(texture):
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        faces=[[0, 1, 2], [0, 2, 3]],
        process=False,
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=[[0, 0], [1, 0], [1, 1], [0, 1]], image=texture
    )
    return mesh


def test_noisy_plane_is_flattened_without_changing_raw_mesh():
    rng = np.random.default_rng(42)
    original = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    mesh = plane(Image.fromarray(original))
    source = Image.new("RGBA", (64, 64), (120, 120, 120, 255))

    cleaned, report = clean_planar_texture(mesh, source)

    assert report["applied"] is True
    assert report["regions"][0]["flattened"] is True
    assert np.array_equal(np.asarray(mesh.visual.material.image), original)
    assert np.max(np.asarray(cleaned.visual.material.image).std(axis=(0, 1))) < 1


def test_patterned_source_and_smooth_texture_are_preserved():
    rng = np.random.default_rng(5)
    noise = plane(Image.fromarray(rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)))
    source = np.full((64, 64, 4), 255, dtype=np.uint8)
    source[:, :32, :3] = 20
    unchanged, report = clean_planar_texture(noise, Image.fromarray(source))
    assert unchanged is noise
    assert report["reason"] == "input_has_pattern_or_insufficient_foreground"

    smooth = plane(Image.new("RGB", (64, 64), (120, 100, 80)))
    unchanged, report = clean_planar_texture(smooth, Image.new("RGB", (64, 64), "gray"))
    assert unchanged is smooth
    assert report["reason"] == "no_large_noisy_plane"


def test_pipeline_records_cleanup_and_keeps_raw_paint(config, tmp_path):
    class NoisyBackend(FakeBackend):
        def generate_texture(self, mesh, image):
            noise = np.random.default_rng(7).integers(0, 256, (64, 64, 3), dtype=np.uint8)
            return plane(Image.fromarray(noise))

    config["texture"]["planar_cleanup"] = True
    config["preprocess"]["background"] = "keep"
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 64), (100, 100, 100, 255)).save(source)
    out = tmp_path / "run"
    result = Pipeline(config, NoisyBackend()).run(source, out)
    assert result.is_file()
    assert (out / "asset_raw_paint.glb").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attempts"][0]["planar_cleanup"]["applied"] is True
    assert "asset_raw_paint.glb" in manifest["artifacts"]


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_cleanup_setting_requires_boolean(config, value):
    config["texture"]["planar_cleanup"] = value
    with pytest.raises(ValueError, match="planar_cleanup must be a boolean"):
        validate(config)
