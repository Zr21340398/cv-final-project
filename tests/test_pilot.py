import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import FakeBackend

from asset3d import pilot
from asset3d.backends.trellis2 import localize_pipeline
from asset3d.config import load_config
from asset3d.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]


def plan_fixture(tmp_path, picture):
    catalog = tmp_path / "input.csv"
    catalog.write_text(f"id,image,reference,split\na,{picture.name},,real\n", encoding="utf-8")
    prepared = pilot.prepare(catalog, tmp_path / "prepared")
    return pilot.initialize(
        prepared,
        [ROOT / "configs/trellis2.yaml", ROOT / "configs/hunyuan2_pilot.yaml"],
        [42, 123],
        tmp_path / "experiment",
    )


def test_paired_plan_freezes_inputs_and_rejects_mutations(tmp_path, picture):
    root = plan_fixture(tmp_path, picture)
    _, plan = pilot.read_plan(root)
    assert len(plan["configs"]) == 2 and plan["seeds"] == [42, 123]
    image = Path(plan["objects"][0]["image"])
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        pilot.read_plan(root)


def test_config_mutation_prevents_run(tmp_path, picture):
    root = plan_fixture(tmp_path, picture)
    frozen = root / "configs/trellis2.yaml"
    frozen.write_text(frozen.read_text().replace("1024_cascade", "1536_cascade"), encoding="utf-8")
    with pytest.raises(ValueError, match="configuration changed"):
        pilot.run(root, "trellis2")


def test_two_environments_use_same_inputs_seeds_and_count_failures(tmp_path, picture, monkeypatch):
    root = plan_fixture(tmp_path, picture)
    seen = []
    real_run = subprocess.run

    def child(command, **kwargs):
        if "--image" not in command:
            return real_run(command, **kwargs)

        def arg(name):
            return command[command.index(name) + 1]

        seen.append((arg("--image"), arg("--seed"), arg("--config")))
        c = load_config(arg("--config"))
        backend = FakeBackend()
        if c.get("backend") == "trellis2":
            backend.joint_generation = True
            backend.generation_stage = "native_shape_material"
            backend.texture_stage = "pbr_bake"
        if c["name"] == "hunyuan2" and arg("--seed") == "123":
            return SimpleNamespace(returncode=1)
        Pipeline(c, backend).run(arg("--image"), arg("--output"), int(arg("--seed")), "--resume" in command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pilot.subprocess, "run", child)
    assert pilot.run(root, "trellis2") == []
    assert len(pilot.run(root, "hunyuan2")) == 1
    assert [(a, b) for a, b, _ in seen[:2]] == [(a, b) for a, b, _ in seen[2:]]
    result = pilot.report(root, root / "summary")
    assert result["paired_successes"] == 1 and result["planned_pairs"] == 2
    summary = json.loads((root / "summary/summary.json").read_text())
    assert summary["configs"]["hunyuan2"]["success_rate"] == 0.5
    ratings = root / "summary/ratings.csv"
    ratings.write_text("human ratings must survive report regeneration")
    pilot.report(root, root / "summary")
    assert ratings.read_text() == "human ratings must survive report regeneration"


def test_timeout_remains_in_denominator(tmp_path, picture, monkeypatch):
    root = plan_fixture(tmp_path, picture)

    real_run = subprocess.run

    def timeout(*a, **k):
        if "--image" not in a[0]:
            return real_run(*a, **k)
        raise subprocess.TimeoutExpired(a[0], 1)

    monkeypatch.setattr(pilot.subprocess, "run", timeout)
    assert len(pilot.run(root, "trellis2", timeout=1, limit=1)) == 1
    pilot.report(root, root / "summary")
    rows = (root / "summary/runs.csv").read_text()
    assert "timeout" in rows


def test_joint_pipeline_restarts_native_state_on_texture_failure(tmp_path, picture):
    config = load_config(ROOT / "configs/trellis2.yaml")
    backend = FakeBackend(fail_texture=True)
    backend.joint_generation = True
    backend.generation_stage = "native_shape_material"
    backend.texture_stage = "pbr_bake"
    out = tmp_path / "run"
    with pytest.raises(RuntimeError):
        Pipeline(config, backend).run(picture, out)
    backend.fail_texture = False
    Pipeline(config, backend).run(picture, out, resume=True)
    assert backend.shapes == 2
    manifest = json.loads((out / "manifest.json").read_text())
    assert "native_shape_material" in manifest["attempts"][-1]["timings"]
    assert "shape" not in manifest["attempts"][-1]["timings"]


def test_local_bundle_resolves_external_decoder_and_encoders(tmp_path):
    roots = {key: tmp_path / key for key in ("main", "sparse_decoder", "image_encoder", "background")}
    bundle = tmp_path / "bundle"
    config = {
        "args": {
            "models": {"shape": "ckpts/shape", "decoder": "microsoft/TRELLIS-image-large/ckpts/decoder"},
            "image_cond_model": {"args": {"model_name": "unversioned"}},
            "rembg_model": {"args": {"model_name": "unversioned"}},
        }
    }
    result = localize_pipeline(config, bundle, roots)["args"]
    assert (bundle / result["models"]["decoder"]).resolve() == roots["sparse_decoder"] / "ckpts/decoder"
    assert result["image_cond_model"]["args"]["model_name"] == str(roots["image_encoder"].resolve())
    assert config["args"]["image_cond_model"]["args"]["model_name"] == "unversioned"


def test_invalid_config_and_empty_pilot_rejected(tmp_path):
    config = load_config(ROOT / "configs/trellis2.yaml")
    config["generation"]["pipeline_type"] = "unrecognized"
    from asset3d.config import validate

    with pytest.raises(ValueError):
        validate(config)
    catalog = tmp_path / "empty.csv"
    catalog.write_text("id,image,reference,split\n")
    with pytest.raises(ValueError):
        pilot.prepare(catalog, tmp_path / "prepared")


def test_pbr_maps_survive_export(tmp_path):
    import numpy as np
    import trimesh
    from conftest import textured_mesh
    from PIL import Image

    from asset3d.export import export_glb

    mesh = textured_mesh()
    mesh.visual.material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.new("RGBA", (8, 8), (200, 10, 20, 255)),
        metallicRoughnessTexture=Image.new("RGB", (8, 8), (0, 80, 200)),
        metallicFactor=1,
        roughnessFactor=1,
    )
    output = tmp_path / "pbr.glb"
    export_glb(mesh, output)
    loaded = trimesh.load(output, force="mesh", process=False)
    assert np.asarray(loaded.visual.material.metallicRoughnessTexture)[0, 0].tolist() == [0, 80, 200]
