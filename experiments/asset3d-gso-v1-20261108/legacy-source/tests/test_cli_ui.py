from pathlib import Path

import pytest
import trimesh

from asset3d.cli import main


def test_evaluate_cli_writes_real_metrics(tmp_path):
    path = tmp_path / "mesh.glb"
    trimesh.creation.box().export(path)
    config = tmp_path / "eval.yaml"
    config.write_text("samples: 1000\nseed: 42\nnormalization: unit_bbox\n", encoding="utf-8")
    target = tmp_path / "metrics.json"
    assert (
        main(
            [
                "evaluate",
                "--pred",
                str(path),
                "--reference",
                str(path),
                "--config",
                str(config),
                "--output",
                str(target),
            ]
        )
        == 0
    )
    assert target.is_file()


def test_generate_records_missing_gpu_error(config, picture, tmp_path, monkeypatch):
    from asset3d.backends.hunyuan2 import HunyuanBackend
    from asset3d.pipeline import Pipeline

    def unavailable(self):
        raise RuntimeError("No CUDA GPU")

    monkeypatch.setattr(HunyuanBackend, "begin", unavailable)
    output = tmp_path / "gpu"
    with pytest.raises(RuntimeError, match="CUDA"):
        Pipeline(config).run(picture, output)
    assert (output / "manifest.json").is_file()
    assert not (output / "asset.glb").exists()


def test_missing_background_cache_fails_before_network(config, picture, tmp_path, monkeypatch):
    from asset3d.backends.hunyuan2 import HunyuanBackend

    monkeypatch.setenv("U2NET_HOME", str(tmp_path / "empty-cache"))
    with pytest.raises(RuntimeError, match="not cached"):
        HunyuanBackend(config).remove_background(picture)


def test_ui_http_without_gpu(tmp_path):
    gr = pytest.importorskip("gradio")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from asset3d.demo import build_app

    root = Path(__file__).resolve().parents[1]
    blocks = build_app(root / "configs", tmp_path / "results")
    app = gr.mount_gradio_app(FastAPI(), blocks, path="/")
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        config = client.get("/config").json()
        assert any(c["type"] == "model3d" for c in config["components"])
    blocks.close()
