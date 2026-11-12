import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from asset3d.evaluation.appearance import build_study
from asset3d.formal_data import validate_preview

VIEW_NAMES = [f"view-{index:03d}.png" for index in range(8)]
MODELS = ("private-model-a", "private-model-b")


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _preview(run, resolution=32):
    directory = run / "preview"
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, name in enumerate(VIEW_NAMES):
        Image.new("RGBA", (resolution, resolution), (index * 20, 80, 120, 255)).save(directory / name)
        frames.append(
            {
                "image": name,
                "camera_to_world": [[1, 0, 0, index], [0, 1, 0, 0], [0, 0, 1, 2], [0, 0, 0, 1]],
                "projection": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            }
        )
    cameras = {
        "blender_version": "4.3.0",
        "resolution": resolution,
        "projection_type": "orthographic",
        "ortho_scale": 1.8,
        "world_up": "Z",
        "first_camera_direction": "from negative Y, elevated",
        "input_to_render_space": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        "render_engine": "CYCLES_CPU",
        "clay": False,
        "samples": 32,
        "seed": 2026,
        "frames": frames,
    }
    _write_json(directory / "cameras.json", cameras)
    return directory


@pytest.fixture
def study_data(tmp_path):
    root = tmp_path / "experiment"
    root.mkdir()
    _write_json(
        root / "experiment.json",
        {"plan": {"configs": [{"name": name} for name in MODELS], "objects": [{"id": "private-object"}], "seeds": [42]}},
    )
    runs = []
    for model in MODELS:
        run = root / model / "private-object" / "seed-42"
        run.mkdir(parents=True)
        _write_json(run / "manifest.json", {"status": "completed"})
        Image.new("RGBA", (32, 32), (120, 100, 80, 255)).save(run / "input.png")
        _preview(run)
        runs.append(run)
    return root, runs, tmp_path / "study"


def _change_cameras(run, mutate):
    path = run / "preview" / "cameras.json"
    cameras = json.loads(path.read_text(encoding="utf-8"))
    mutate(cameras)
    _write_json(path, cameras)


def test_study_copies_anonymous_complete_views_and_ignores_object_normalization(study_data):
    root, runs, output = study_data
    _change_cameras(runs[1], lambda cameras: cameras["input_to_render_space"][0].__setitem__(3, 99))
    preview = validate_preview(runs[0] / "preview")
    assert [Path(path).name for path in preview["views"]] == VIEW_NAMES
    assert all(Path(path).is_absolute() for path in preview["views"])
    assert preview["cameras"]["resolution"] == 32
    assert isinstance(preview["checked_files"], list) and len(preview["checked_files"]) == 9
    assert "input_to_render_space" not in preview["protocol"]

    assert build_study(root, output) == output
    key = json.loads((output / "private-key.json").read_text(encoding="utf-8"))
    assert {entry["config"] for entry in key} == set(MODELS)
    assert {entry["sample"] for entry in key} == {"sample-0001", "sample-0002"}
    for entry in key:
        source = root / entry["config"] / entry["object"] / f"seed-{entry['seed']}"
        public = output / "public" / entry["sample"]
        assert {path.name for path in public.iterdir()} == {"input.png", *VIEW_NAMES}
        for filename in ["input.png", *VIEW_NAMES]:
            original = source / filename if filename == "input.png" else source / "preview" / filename
            assert (public / filename).read_bytes() == original.read_bytes()

    public_root = output / "public"
    with (public_root / "ratings-template.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, ratings = reader.fieldnames, list(reader)
    assert len(ratings) == 2
    assert {row["sample"] for row in ratings} == {entry["sample"] for entry in key}
    assert not {"config", "object", "seed"} & set(fields)
    public_text = "\n".join(str(path.relative_to(public_root)) for path in public_root.rglob("*"))
    public_text += (public_root / "ratings-template.csv").read_text(encoding="utf-8")
    public_text += (public_root / "README.txt").read_text(encoding="utf-8")
    assert all(value not in public_text for value in (*MODELS, "private-object"))


def test_study_rejects_second_run_missing_view_before_creating_output(study_data):
    root, runs, output = study_data
    validate_preview(runs[0] / "preview")
    (runs[1] / "preview" / "view-007.png").unlink()
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


def test_study_rejects_duplicate_camera_frame_before_creating_output(study_data):
    root, runs, output = study_data
    _change_cameras(runs[1], lambda cameras: cameras["frames"][7].__setitem__("image", "view-000.png"))
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


def test_study_rejects_image_size_different_from_camera_metadata(study_data):
    root, runs, output = study_data
    Image.new("RGBA", (64, 32), (80, 100, 120, 255)).save(runs[1] / "preview" / "view-003.png")
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


def test_study_rejects_different_complete_render_resolutions(study_data):
    root, runs, output = study_data
    _preview(runs[1], resolution=64)
    assert validate_preview(runs[0] / "preview")["cameras"]["resolution"] == 32
    assert validate_preview(runs[1] / "preview")["cameras"]["resolution"] == 64
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


@pytest.mark.parametrize("matrix", ["camera_to_world", "projection"])
def test_study_rejects_different_complete_camera_protocols(study_data, matrix):
    root, runs, output = study_data
    _change_cameras(runs[1], lambda cameras: cameras["frames"][3][matrix][0].__setitem__(3, 0.25))
    validate_preview(runs[0] / "preview")
    validate_preview(runs[1] / "preview")
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


@pytest.mark.parametrize("matrix", ["camera_to_world", "projection"])
def test_study_rejects_nonfinite_camera_matrix(study_data, matrix):
    root, runs, output = study_data
    _change_cameras(runs[1], lambda cameras: cameras["frames"][3][matrix][0].__setitem__(0, float("nan")))
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


def test_study_rejects_clay_preview_before_creating_output(study_data):
    root, runs, output = study_data
    _change_cameras(runs[1], lambda cameras: cameras.__setitem__("clay", True))
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()


def test_study_rejects_unreadable_second_input_before_creating_output(study_data):
    root, runs, output = study_data
    (runs[1] / "input.png").write_bytes(b"not an image")
    with pytest.raises(ValueError):
        build_study(root, output)
    assert not output.exists()
