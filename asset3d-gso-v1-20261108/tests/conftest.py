from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw

from asset3d.config import load_config


@pytest.fixture
def config():
    return load_config(Path(__file__).resolve().parents[1] / "configs/baseline.yaml")


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / "object.png"
    image = Image.new("RGBA", (96, 128), (255, 255, 255, 0))
    ImageDraw.Draw(image).ellipse((12, 20, 84, 104), fill=(220, 60, 20, 255))
    image.save(path)
    return path


def textured_mesh():
    mesh = trimesh.creation.icosphere(subdivisions=2)
    v = mesh.vertices
    uv = np.column_stack(
        (np.arctan2(v[:, 1], v[:, 0]) / (2 * np.pi) + 0.5, np.arcsin(np.clip(v[:, 2], -1, 1)) / np.pi + 0.5)
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, image=Image.new("RGB", (16, 16), (240, 100, 30)))
    return mesh


class FakeBackend:
    """Test-only deterministic fixture; never exposed by the production CLI."""

    def __init__(self, fail_texture=False):
        self.fail_texture = fail_texture
        self.shapes = 0

    def begin(self):
        return {"backend": "test fixture, not AI output"}

    def remove_background(self, image):
        raise AssertionError("Masked fixture should not call background removal")

    def load_shape(self):
        return {"cold": self.shapes == 0, "seconds": 0.0}

    def generate_shape(self, image, seed):
        self.shapes += 1
        return trimesh.creation.icosphere(subdivisions=2)

    def load_texture(self):
        return {"cold": True, "seconds": 0.0}

    def generate_texture(self, mesh, image):
        if self.fail_texture:
            raise RuntimeError("Simulated texture failure")
        return textured_mesh()

    def synchronize(self):
        pass

    def resources(self):
        return {"peak_allocated_bytes": 0}
