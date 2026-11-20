"""Preview confirmation reuses exactly the approved pixels without GPU inference."""

import importlib.util
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import FakeBackend
from PIL import Image, ImageDraw

from asset3d.backends.trellis2 import TrellisBackend
from asset3d.config import load_config
from asset3d.foreground_preview import prepare_preview, validate_foreground, validate_preview
from asset3d.pipeline import Pipeline
from asset3d.recording import file_hash

ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location("foreground_remote", ROOT / "scripts/generate_remote.py")
remote = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(remote)


class PreviewBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.mask_calls = 0
        self.model_calls = 0
        self.received = None

    def prepare_foreground(self, image):
        self.mask_calls += 1
        self.oriented_size = image.size
        self.oriented_info = dict(image.info)
        if image.getchannel("A").getextrema()[0] == 255:
            image = image.copy()
            image.putalpha(0)
            ImageDraw.Draw(image).rectangle((8, 8, image.width - 9, image.height - 9),
                                           fill=(150, 80, 25, 255))
        return image

    def prepare_model_input(self, image):
        self.model_calls += 1
        # Distinctive output represents the pinned official preprocessing result.
        return Image.new("RGB", (73, 73), (17, 58, 109))

    def generate_shape(self, image, seed):
        raise AssertionError("Confirmed input must bypass normal image preprocessing")

    def generate_shape_prepared(self, image, seed):
        self.received = image.copy()
        return super().generate_shape(image, seed)


@pytest.fixture
def preview_job(tmp_path, picture):
    job = tmp_path / "job"
    (job / "inputs").mkdir(parents=True)
    (job / "inputs/input.png").write_bytes(picture.read_bytes())
    spec = {"name": "preview", "images": ["input.png"], "seeds": [42],
            "export_plugin": "surface_repair",
            "variants": [{"name": "trellis2", "decimation_target": 500000, "texture_size": 2048}]}
    (job / "request.json").write_text(json.dumps(spec))
    config = remote.variant_config(load_config(ROOT / "configs/trellis2_gso_dev.yaml"),
                                   spec, spec["variants"][0])
    return job, config


def test_preview_stops_before_generation_and_uses_separate_status(preview_job, monkeypatch):
    job, config = preview_job
    backend = PreviewBackend()
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: backend)
    remote.prepare(job)
    assert backend.shapes == 0
    assert backend.mask_calls == backend.model_calls == 1
    assert not (job / "results").exists()
    assert not (job / "status.json").exists()
    assert json.loads((job / "preview-status.json").read_text())["state"] == "前景待确认"
    paths = validate_preview(job, config, file_hash(job / "preview.json"))
    assert {p.name for p in paths.values()} == {"foreground.png", "model_input.png"}
    # A recovered preview operation does not produce a different image.
    remote.prepare(job)
    assert backend.mask_calls == 1


def test_confirmed_pipeline_preserves_approved_bytes_and_pixels(preview_job, monkeypatch):
    job, config = preview_job
    preparation = PreviewBackend()
    prepare_preview(job, config, preparation)
    paths = validate_preview(job, config, file_hash(job / "preview.json"))
    record = json.loads((job / "preview.json").read_text())
    backend = PreviewBackend()
    monkeypatch.setattr("asset3d.pipeline.prepare_image", lambda *a: pytest.fail("Do not preprocess twice"))
    out = job / "result"
    Pipeline(config, backend).run(job / "inputs/input.png", out,
                                  prepared_input=paths, prepared_sha256=record)
    assert backend.mask_calls == backend.model_calls == 0
    with Image.open(paths["model_input"]) as expected:
        assert backend.received.mode == expected.mode == "RGB"
        assert backend.received.size == expected.size
        assert backend.received.tobytes() == expected.tobytes()
    for key, path in paths.items():
        assert (out / (key + ".png")).read_bytes() == path.read_bytes()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["identity"]["prepared_input"] == {
        key + "_sha256": record[key + "_sha256"] for key in paths
    }
    assert set(manifest["artifacts"]) == {
        "input.png", "foreground.png", "model_input.png", "shape_raw.glb", "asset.glb"
    }


@pytest.mark.parametrize("target", ["input", "request", "foreground", "model_input", "record", "config"])
def test_changed_confirmation_inputs_are_rejected(preview_job, target):
    job, config = preview_job
    prepare_preview(job, config, PreviewBackend())
    approval = file_hash(job / "preview.json")
    files = {"input": job / "inputs/input.png", "request": job / "request.json",
             "foreground": job / "prepared/foreground.png", "model_input": job / "prepared/model_input.png",
             "record": job / "preview.json"}
    if target == "config":
        config = deepcopy(config)
        config["texture"]["texture_size"] = 1024
    else:
        files[target].write_bytes(files[target].read_bytes() + b" ")
    with pytest.raises(ValueError, match="变化"):
        validate_preview(job, config, approval)


@pytest.mark.parametrize('changed', ['model_input', 'original', 'config'])
def test_changed_file_between_validation_and_pipeline_is_rejected(preview_job, changed):
    job, config = preview_job
    prepare_preview(job, config, PreviewBackend())
    paths = validate_preview(job, config, file_hash(job / "preview.json"))
    record = json.loads((job / "preview.json").read_text())
    if changed == 'config':
        config['texture']['texture_size'] = 1024
    else:
        path = paths['model_input'] if changed == 'model_input' else job/'inputs/input.png'
        Image.new('RGB', (73, 73), 'red').save(path)
    with pytest.raises(ValueError, match="发生变化|changed"):
        Pipeline(config, PreviewBackend()).run(job / "inputs/input.png", job / "result",
                                               prepared_input=paths, prepared_sha256=record)
    assert not (job / "result").exists()


@pytest.mark.parametrize("kind", ["empty", "faint", "one_pixel", "opaque"])
def test_invalid_foreground_is_rejected(kind):
    image = Image.new("RGBA", (48, 48), (20, 30, 40, 0))
    if kind == "faint":
        image.putalpha(100)
    elif kind == "one_pixel":
        image.putpixel((10, 10), (10, 20, 30, 255))
    elif kind == "opaque":
        image.putalpha(255)
    with pytest.raises(ValueError):
        validate_foreground(image)


def test_exif_is_applied_once_and_removed_from_prepared_images(preview_job):
    job, config = preview_job
    image = Image.new("RGB", (48, 80), (200, 100, 50))
    exif = Image.Exif()
    exif[274] = 6
    image.save(job / "inputs/input.png", exif=exif)
    backend = PreviewBackend()
    prepare_preview(job, config, backend)
    assert backend.oriented_size == (80, 48)
    assert not backend.oriented_info
    for name in ("foreground", "model_input"):
        with Image.open(job / "prepared" / (name + ".png")) as prepared:
            assert not prepared.getexif()


def test_prepare_rejects_batch_before_loading_models(preview_job, monkeypatch):
    job, config = preview_job
    spec = json.loads((job / "request.json").read_text())
    spec["seeds"].append(123)
    (job / "request.json").write_text(json.dumps(spec))
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: pytest.fail("Do not load a batch preview"))
    with pytest.raises(ValueError, match="单张"):
        remote.prepare(job)


def test_remote_confirmed_execution_uses_preview_and_never_masks_again(preview_job, monkeypatch):
    job, config = preview_job
    prepare_preview(job, config, PreviewBackend())
    backend = PreviewBackend()
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: backend)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    remote.execute(job, file_hash(job / "preview.json"))
    assert backend.shapes == 1
    assert backend.mask_calls == backend.model_calls == 0
    assert backend.received.mode == "RGB"
    assert backend.received.getpixel((0, 0)) == (17, 58, 109)
    state = json.loads((job / "status.json").read_text())
    assert state == {"state": "完成", "failures": []}
    result = job / "results/trellis2/image_000/seed-42"
    assert (result / "model_input.png").read_bytes() == (job / "prepared/model_input.png").read_bytes()


def test_prepared_job_cannot_generate_without_confirmation(preview_job, monkeypatch):
    job, config = preview_job
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: PreviewBackend())
    remote.prepare(job)
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: pytest.fail("Do not load without confirmation"))
    with pytest.raises(ValueError, match="确认"):
        remote.execute(job)


def test_prepare_cli_failure_does_not_write_generation_status(preview_job):
    job, config = preview_job
    spec = json.loads((job / "request.json").read_text())
    spec["seeds"].append(123)
    (job / "request.json").write_text(json.dumps(spec))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/generate_remote.py"), str(job), "--prepare"],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert json.loads((job / "preview-status.json").read_text())["state"] == "失败"
    assert not (job / "status.json").exists()


def test_batch_default_retains_existing_preprocessing(preview_job, monkeypatch):
    job, config = preview_job
    spec = json.loads((job / "request.json").read_text())
    spec["seeds"].append(123)
    (job / "request.json").write_text(json.dumps(spec))
    backend = FakeBackend()
    monkeypatch.setattr(remote, "TrellisBackend", lambda c: backend)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    remote.execute(job)
    assert backend.shapes == 2
    for seed in (42, 123):
        result = job / f"results/trellis2/image_000/seed-{seed}"
        assert (result / "foreground.png").exists()
        assert not (result / "model_input.png").exists()
    assert not (job / "preview.json").exists()


def test_trellis_prepared_generation_disables_upstream_preprocessing(monkeypatch):
    class Tensor:
        def __init__(self, value):
            self.value = np.asarray(value)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    calls = []
    native = SimpleNamespace(vertices=Tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                             faces=Tensor([[0, 1, 2]]))
    def run(image, **kwargs):
        calls.append((image.copy(), kwargs))
        return [native]
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    config = load_config(ROOT / "configs/trellis2_gso_dev.yaml")
    backend = TrellisBackend(config)
    backend.pipeline = SimpleNamespace(run=run)
    image = Image.new("RGB", (32, 32), (11, 22, 33))
    backend.generate_shape_prepared(image, 42)
    assert calls[0][0].tobytes() == image.tobytes()
    assert calls[0][1]["preprocess_image"] is False
    assert calls[0][1]["seed"] == 42
