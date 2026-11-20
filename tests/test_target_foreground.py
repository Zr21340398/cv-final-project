"""Target selection validation and mask choice, without SAM/GPU dependencies."""

import hashlib
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from asset3d import target_foreground as target


def test_validation_import_is_stdlib_only():
    script = """
import builtins
real = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'numpy', 'PIL', 'torch', 'sam2'}:
        raise AssertionError(name)
    return real(name, *args, **kwargs)
builtins.__import__ = guarded
from asset3d.target_foreground import validate_selection
assert validate_selection({'box':[0,0,1,1]})['include_points'] == []
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )


def test_selection_canonicalizes_and_keeps_boundary_points():
    assert target.validate_selection({"box": [0.1, 0.1, 0.12, 0.12], "include_points": [[0, 1]]}) == {
        "box": [0.1, 0.1, 0.12, 0.12],
        "include_points": [[0.0, 1.0]],
        "exclude_points": [],
    }


@pytest.mark.parametrize(
    "selection",
    [
        None,
        [],
        {},
        {"box": [0, 0, 1, 1], "unknown": 1},
        {"box": [0, 0, 1]},
        {"box": [0, 0, 1, 1, 1]},
        {"box": [True, 0, 1, 1]},
        {"box": [0, 0, float("nan"), 1]},
        {"box": [0, 0, 1, float("inf")]},
        {"box": [0, 0, 1, 10**400]},
        {"box": [-0.01, 0, 1, 1]},
        {"box": [0, 0, 1.01, 1]},
        {"box": [0.9, 0.1, 0.1, 0.9]},
        {"box": [0, 0, 0.019, 1]},
        {"box": [0, 0, 1, 1], "include_points": [[0.5, 0.5]] * 17},
        {"box": [0, 0, 1, 1], "exclude_points": [[0.5, 0.5]] * 17},
        {"box": [0, 0, 1, 1], "include_points": None},
        {"box": [0, 0, 1, 1], "exclude_points": [[False, 0.5]]},
        {"box": [0, 0, 1, 1], "include_points": [[0.5]]},
        {"box": [0, 0, 1, 1], "exclude_points": [[float("nan"), 0.5]]},
        {"box": [0, 0, 1, 1], "exclude_points": [[0.5, 1.01]]},
    ],
)
def test_invalid_selection_is_rejected(selection):
    with pytest.raises(ValueError):
        target.validate_selection(selection)


def test_candidate_choice_obeys_points_and_preserves_original_pixels(monkeypatch):
    pixels = np.arange(64 * 80 * 3, dtype=np.uint8).reshape(64, 80, 3)
    image = Image.fromarray(pixels).convert("RGBA")
    image.info["exif"] = b"orientation-already-applied"
    masks = np.zeros((3, 64, 80), dtype=bool)
    masks[0, 8:56, 8:72] = True  # High score, but includes the unwanted hand point.
    masks[1, 8:40, 8:55] = True  # Valid and preferred over candidate 2.
    masks[2, 12:36, 12:50] = True
    seen = {}

    def predict(rgb, box, points, labels):
        seen.update(box=box, points=points, labels=labels)
        assert np.array_equal(np.asarray(rgb), pixels)
        return masks, np.array([0.99, 0.83, 0.72])

    monkeypatch.setattr(target, "_predict_masks", predict)
    result, metadata = target.segment_target(
        image, {"box": [0.1, 0.1, 0.9, 0.9], "include_points": [[0.3, 0.3]], "exclude_points": [[0.8, 0.8]]}
    )
    assert metadata["candidate_index"] == 1 and metadata["quality_review_required"]
    assert seen["labels"] == [1, 0]
    assert seen["points"][0] == [0.3 * 79, 0.3 * 63]
    assert np.array_equal(np.asarray(result)[:, :, :3], pixels)
    assert np.array_equal(np.asarray(result)[:, :, 3], masks[1].astype(np.uint8) * 255)
    assert not result.info


def test_no_candidate_meeting_exclusion_is_an_explicit_failure(monkeypatch):
    mask = np.zeros((1, 64, 64), dtype=bool)
    mask[:, 5:60, 5:60] = True
    monkeypatch.setattr(target, "_predict_masks", lambda *args: (mask, np.array([0.95])))
    with pytest.raises(ValueError, match="保留点和排除点"):
        target.segment_target(
            Image.new("RGBA", (64, 64), "yellow"),
            {"box": [0, 0, 1, 1], "include_points": [[0.25, 0.25]], "exclude_points": [[0.75, 0.75]]},
        )


@pytest.mark.parametrize("kind", ["empty", "opaque", "nan_score", "wrong_shape", "fractional"])
def test_invalid_predictions_never_become_an_approved_mask(monkeypatch, kind):
    masks = np.zeros((1, 64, 64), dtype=bool)
    masks[:, 10:50, 10:50] = True
    scores = np.array([0.9])
    if kind == "empty":
        masks[:] = False
    elif kind == "opaque":
        masks[:] = True
    elif kind == "nan_score":
        scores[:] = np.nan
    elif kind == "wrong_shape":
        masks = masks[:, :32]
    elif kind == "fractional":
        masks = masks.astype(float) * 0.8
    monkeypatch.setattr(target, "_predict_masks", lambda *args: (masks, scores))
    with pytest.raises((ValueError, RuntimeError)):
        target.segment_target(Image.new("RGBA", (64, 64), "yellow"), {"box": [0, 0, 1, 1]})


def test_original_transparency_is_not_filled(monkeypatch):
    image = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
    image.putpixel((20, 20), (10, 20, 30, 0))
    mask = np.zeros((1, 64, 64), dtype=bool)
    mask[:, 10:50, 10:50] = True
    monkeypatch.setattr(target, "_predict_masks", lambda *args: (mask, np.array([0.8])))
    result, _ = target.segment_target(image, {"box": [0, 0, 1, 1]})
    assert result.getpixel((20, 20)) == (10, 20, 30, 0)


def test_checkpoint_requires_exact_size_and_hash(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.pt"
    path.write_bytes(b"verified-fixture")
    monkeypatch.setenv("ASSET3D_SAM2_CHECKPOINT", str(path))
    monkeypatch.setattr(target, "SAM2_CHECKPOINT_SIZE", path.stat().st_size)
    monkeypatch.setattr(target, "SAM2_CHECKPOINT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    assert target._verify_checkpoint() == path
    path.write_bytes(b"modified-fixture")
    with pytest.raises(RuntimeError, match="SHA256"):
        target._verify_checkpoint()
    path.write_bytes(b"short")
    with pytest.raises(RuntimeError, match="不完整"):
        target._verify_checkpoint()


def test_offline_predictor_disables_automatic_hole_filling(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET3D_SAM2_CODE_DIR", str(tmp_path))
    monkeypatch.setattr(target, "_verify_code", lambda path: Path(path).resolve())
    checkpoint = tmp_path / "tiny.pt"
    monkeypatch.setattr(target, "_verify_checkpoint", lambda: checkpoint)
    package = ModuleType("sam2")
    package.__file__ = str(tmp_path / "sam2/__init__.py")
    builder, predictor = ModuleType("sam2.build_sam"), ModuleType("sam2.sam2_image_predictor")
    calls = {}
    model, instance = object(), object()

    def build(config, path, **kwargs):
        calls["build"] = (config, path, kwargs)
        return model

    def create(value, **kwargs):
        assert value is model
        calls["predictor"] = kwargs
        return instance

    builder.build_sam2 = build
    predictor.SAM2ImagePredictor = create
    for name, module in (
        ("sam2", package),
        ("sam2.build_sam", builder),
        ("sam2.sam2_image_predictor", predictor),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    assert target._load_predictor() is instance
    assert calls["build"] == (
        target.SAM2_CONFIG,
        str(checkpoint),
        {"device": "cuda", "apply_postprocessing": False},
    )
    assert calls["predictor"] == {"max_hole_area": 0.0, "max_sprinkle_area": 0.0}


@pytest.mark.parametrize("invalid_prior", [False, "shape", "nonfinite"])
def test_single_object_refinement_reuses_raw_logits_and_identical_prompts(monkeypatch, invalid_prior):
    calls, released = [], []
    mask = np.zeros((1, 64, 80), dtype=bool)
    mask[:, 8:56, 8:72] = True
    mask[:, 20:25, 20:25] = False  # A genuine hole must not be filled by postprocessing.
    image = Image.new("RGB", (80, 64), (11, 22, 33))
    logits = [np.full((1, 256, 256), -0.75, np.float32),
              np.full((1, 256, 256), 0.125, np.float32)]
    if invalid_prior == "shape":
        logits[0] = np.zeros((1, 64, 80), np.float32)
    elif invalid_prior == "nonfinite":
        logits[0][0, 0, 0] = np.nan

    class Predictor:
        def set_image(self, value):
            assert value.flags.writeable and np.array_equal(value, np.asarray(image))

        def predict(self, **kwargs):
            step = len(calls)
            calls.append(kwargs)
            assert kwargs["multimask_output"] is False
            np.testing.assert_array_equal(kwargs["box"], [8, 6, 72, 58])
            np.testing.assert_array_equal(kwargs["point_coords"], [[30, 30], [1, 1]])
            np.testing.assert_array_equal(kwargs["point_labels"], [1, 0])
            if step == 0:
                assert kwargs["mask_input"] is None
            else:
                np.testing.assert_array_equal(kwargs["mask_input"], logits[step - 1])
                assert not np.shares_memory(kwargs["mask_input"], logits[step - 1])
            return mask, np.array([0.9]), logits[min(step, 1)]

        def reset_predictor(self):
            released.append("reset")

    torch = ModuleType("torch")
    torch.bfloat16 = object()
    torch.inference_mode = nullcontext
    torch.autocast = lambda *args, **kwargs: nullcontext()
    torch.cuda = SimpleNamespace(is_available=lambda: True, is_bf16_supported=lambda: True,
                                 empty_cache=lambda: released.append("cache"))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(target, "_load_predictor", Predictor)
    args = (image, [8, 6, 72, 58], [[30, 30], [1, 1]], [1, 0])
    if invalid_prior:
        with pytest.raises(RuntimeError, match="中间蒙版"):
            target._predict_masks(*args)
        assert len(calls) == 1
    else:
        actual, _ = target._predict_masks(*args)
        assert len(calls) == 3
        np.testing.assert_array_equal(actual, mask)
        assert target.MASK_STRATEGY == "single_mask_logits_refinement_v1"
    assert released == ["reset", "cache"]
