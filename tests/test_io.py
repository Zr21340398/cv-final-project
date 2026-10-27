import numpy as np
import pytest
import trimesh
from conftest import textured_mesh
from PIL import Image

from asset3d.config import load_config
from asset3d.export import check_glb, export_glb
from asset3d.preprocess import prepare_image


def test_glb_roundtrip_keeps_texture(tmp_path):
    path = tmp_path / "asset.glb"
    export_glb(textured_mesh(), path)
    assert check_glb(path)["meshes"][0]["has_texture"]


def test_untextured_asset_rejected(tmp_path):
    path = tmp_path / "asset.glb"
    with pytest.raises(ValueError, match="textured"):
        export_glb(trimesh.creation.box(), path)
    assert not path.exists()


def test_opaque_rgba_still_needs_removal(tmp_path, config):
    path = tmp_path / "opaque.png"
    Image.new("RGBA", (64, 64), (120, 50, 30, 255)).save(path)
    calls = []

    def remover(image):
        calls.append(image)
        output = image.convert("RGBA")
        output.putalpha(Image.fromarray(np.pad(np.full((32, 32), 255, dtype=np.uint8), 16)))
        return output

    result = prepare_image(path, config["preprocess"], remover)
    assert len(calls) == 1 and result.size == (512, 512)
    assert np.asarray(result.getchannel("A")).min() == 0


def test_transparent_and_small_images_rejected(tmp_path, config):
    for size in ((64, 64), (10, 10)):
        path = tmp_path / "empty.png"
        Image.new("RGBA", size, (0, 0, 0, 0)).save(path)
        with pytest.raises(ValueError):
            prepare_image(path, config["preprocess"])


def test_inheritance_changes_only_steps(config):
    from pathlib import Path

    medium = load_config(Path(__file__).resolve().parents[1] / "configs/medium.yaml")
    assert medium["shape"]["steps"] == 30
    medium["name"] = config["name"]
    medium["shape"]["steps"] = config["shape"]["steps"]
    assert medium == config


def test_circular_config_rejected(tmp_path):
    path = tmp_path / "loop.yaml"
    path.write_text("extends: loop.yaml", encoding="utf-8")
    with pytest.raises(ValueError, match="Circular"):
        load_config(path)
