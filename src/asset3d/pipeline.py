import json
import os
import time
import traceback
from pathlib import Path

from PIL import Image

from .config import validate
from .export import check_glb, export_glb
from .mesh_ops import load_mesh
from .preprocess import prepare_image
from .recording import environment, file_hash, now, object_hash, save_json


class Pipeline:
    def __init__(self, config, backend=None):
        validate(config)
        self.config = config
        # 两个后端共用输入、记录和导出流程，具体生成过程交给各自的官方模型。
        if backend is None:
            if config.get("backend") == "trellis2":
                from .backends.trellis2 import TrellisBackend

                backend = TrellisBackend(config)
            else:
                from .backends.hunyuan2 import HunyuanBackend

                backend = HunyuanBackend(config)
        self.backend = backend

    def run(self, image_path, output_dir, seed=42, resume=False):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be an integer in [0, 2**32)")
        image_path = Path(image_path).resolve()
        # 图片内容、配置和随机种子共同确定一次实验，续跑时逐项核对。
        identity = {
            "input_sha256": file_hash(image_path),
            "config_sha256": object_hash(self.config),
            "seed": seed,
        }
        out = Path(output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        # 独占锁防止两个作业同时写入同一个结果目录。
        lock = out / ".running.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Run is locked: {lock}. Check the job before removing a stale lock.") from exc
        os.close(fd)
        try:
            return self._run(image_path, out, identity, resume)
        finally:
            lock.unlink(missing_ok=True)

    def _run(self, image_path, out, identity, resume):
        manifest_path = out / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not resume:
                raise FileExistsError("Output already exists; use a new directory or --resume")
            if manifest["identity"] != identity:
                raise ValueError("Resume refused: input, configuration or seed changed")
            if manifest["environment"]["source_hash"] != environment()["source_hash"]:
                raise ValueError("Resume refused: project source code changed; start a new run")
        else:
            if any(p.name != ".running.lock" for p in out.iterdir()):
                raise FileExistsError("Output directory must be empty for a new run")
            manifest = {
                "schema_version": 1,
                "created_at": now(),
                "identity": identity,
                "config": self.config,
                "input_path": str(image_path),
                "environment": environment(),
                "artifacts": {},
                "attempts": [],
            }

        def cached(name):
            digest = manifest["artifacts"].get(name)
            if digest is None:
                return False
            path = out / name
            if not path.is_file() or file_hash(path) != digest:
                raise ValueError(f"Cached artifact is missing or changed: {name}")
            return True

        # 校验已保存文件的内容摘要，发现文件被改动时停止复用。
        for name in manifest["artifacts"]:
            cached(name)
        textured = self.config["texture"]["enabled"]
        result_name = "asset.glb" if textured else "shape_raw.glb"
        if manifest.get("status") in ("completed", "shape_only"):
            check_glb(out / result_name, require_texture=textured)
            return out / result_name
        attempt = {"started_at": now(), "timings": {}, "loads": {}, "reused": []}
        manifest["attempts"].append(attempt)
        manifest["status"] = "running"
        save_json(manifest_path, manifest)
        start = time.perf_counter()
        stage = "initialization"
        backend_ready = False

        def remember(name):
            manifest["artifacts"][name] = file_hash(out / name)
            save_json(manifest_path, manifest)

        def timed(name, operation, gpu=False):
            before = time.perf_counter()
            value = operation()
            # GPU 运算通常异步执行；等计算真正结束后再记录该阶段耗时。
            if gpu:
                self.backend.synchronize()
            attempt["timings"][name] = time.perf_counter() - before
            return value

        try:
            attempt["backend"] = self.backend.begin()
            backend_ready = True
            stage = "preprocess"
            # 保存实际送入模型的前景图，方便检查抠图是否误删了物体细节。
            if not cached("foreground.png"):
                image = timed(
                    "preprocess",
                    lambda: prepare_image(
                        image_path, self.config["preprocess"], self.backend.remove_background
                    ),
                )
                image.save(out / "foreground.png")
                with Image.open(image_path) as original:
                    original.save(out / "input.png")
                remember("input.png")
                remember("foreground.png")
            else:
                with Image.open(out / "foreground.png") as opened:
                    image = opened.convert("RGBA")
                attempt["reused"].append("foreground.png")
            stage = "shape"
            # 混元可从已保存的白模继续上色。TRELLIS.2 上色导出还需要内存中的材质数据，
            # 因此中途失败后会重新生成形状与材质，再执行纹理烘焙。
            if cached("shape_raw.glb") and not getattr(self.backend, "joint_generation", False):
                mesh = load_mesh(out / "shape_raw.glb")
                attempt["reused"].append("shape_raw.glb")
            else:
                attempt["loads"]["shape"] = self.backend.load_shape()
                mesh = timed(
                    getattr(self.backend, "generation_stage", "shape"),
                    lambda: self.backend.generate_shape(image, identity["seed"]),
                    gpu=True,
                )
                # 先保留未经最终简化处理的几何模型，用于白模检查和几何指标评估。
                export_glb(mesh, out / "shape_raw.glb", require_texture=False)
                remember("shape_raw.glb")
                # 首次运行和断点续跑都从同一份白模文件读入，统一混元上色阶段的输入。
                mesh = load_mesh(out / "shape_raw.glb")
            # 混元在此调用上色模型；TRELLIS.2 将已生成的材质整理成网格贴图。
            if textured:
                stage = "texture"
                attempt["loads"]["texture"] = self.backend.load_texture()
                mesh = timed(
                    getattr(self.backend, "texture_stage", "texture"),
                    lambda: self.backend.generate_texture(mesh, image),
                    gpu=True,
                )
                stage = "export"
                manifest["export"] = timed("export", lambda: export_glb(mesh, out / "asset.glb"))
                remember("asset.glb")
            else:
                manifest["export"] = check_glb(out / "shape_raw.glb", require_texture=False)
            manifest["status"] = "completed" if textured else "shape_only"
            attempt["status"] = manifest["status"]
        except Exception as exc:
            manifest["status"] = "failed"
            attempt.update(status="failed", failed_stage=stage, error=f"{type(exc).__name__}: {exc}")
            with (out / "run.log").open("a", encoding="utf-8") as stream:
                stream.write(f"\n{now()} {stage}\n{traceback.format_exc()}")
            raise
        finally:
            # 成功和失败都留下耗时、资源及阶段记录，便于排错和统计成功率。
            attempt["wall_seconds"] = time.perf_counter() - start
            attempt["finished_at"] = now()
            if backend_ready:
                try:
                    attempt["resources"] = self.backend.resources()
                except Exception as exc:
                    attempt["resource_error"] = str(exc)
            save_json(manifest_path, manifest)
        return out / result_name
