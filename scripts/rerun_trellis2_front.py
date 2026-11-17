"""用原始正面缩略图重跑两个对象；成功后替换同一批次中的结果。"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from asset3d.backends.trellis2 import TrellisBackend
from asset3d.config import validate
from asset3d.pipeline import Pipeline
from asset3d.recording import file_hash, now, save_json
from asset3d.viewer_manifest import write_viewer_manifest


ROOT = Path(__file__).resolve().parents[1]
OBJECTS = ("gso_01", "gso_02")
SEEDS = (42, 123)


def replace_object(staged, destination):
    """同一文件系统内换目录；替换失败时恢复原目录。"""
    backup = staged.parent / "previous"
    if destination.exists():
        destination.rename(backup)
    try:
        staged.rename(destination)
    except BaseException:
        if backup.exists():
            backup.rename(destination)
        raise
    # 新结果已经就位，旧模型按用户要求直接覆盖。
    if backup.exists():
        shutil.rmtree(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="检查文件和参数，不加载 GPU 模型")
    args = parser.parse_args()
    results = ROOT / "experiments/trellis2-gso-dev-v1/results"
    plan = json.loads((results / "experiment.json").read_text(encoding="utf-8"))["plan"]
    configs = [c for c in plan["configs"] if c.get("name") == "trellis2_gso_dev"]
    if len(configs) != 1 or configs[0].get("backend") != "trellis2":
        raise ValueError("原实验缺少唯一的 trellis2_gso_dev 配置")
    config = configs[0]
    validate(config)
    if plan["seeds"] != list(SEEDS):
        raise ValueError("原实验种子应为 42、123")
    sources = {obj: ROOT / f"datasets/gso-v1/data/raw/gso/{obj}/thumbnails/2.jpg" for obj in OBJECTS}
    for obj, source in sources.items():
        with Image.open(source) as image:
            image.verify()
        destination = results / config["name"] / obj
        if not destination.is_dir():
            raise FileNotFoundError(f"请先保留服务器原实验结果：{destination}")
        if list(destination.rglob(".running.lock")):
            raise RuntimeError(f"对象正在运行或有遗留锁：{destination}")
        print(f"{obj}: {source} -> {destination}; seeds={SEEDS}", flush=True)
    if args.check_only:
        return

    # 独占本次局部重跑。提交前应等待原来的完整批次作业结束。
    lock = results / ".front-rerun.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(now())
    try:
        backend = TrellisBackend(config)
        backend.begin()
        backend.load_shape()
        pipeline = Pipeline(config, backend=backend)
        for obj, source in sources.items():
            # 临时目录属于原批次，不注册为新实验。失败时保留旧模型和临时诊断文件。
            work = Path(tempfile.mkdtemp(prefix=f".front-{obj}-", dir=results))
            staged = work / obj
            import numpy as np
            import torch

            with Image.open(source) as opened:
                original = ImageOps.exif_transpose(opened).convert("RGB")
            # 复用官方已下载的 RMBG-2.0，只生成透明蒙版，保留照片中的颜色和细节。
            remover = backend.pipeline.rembg_model
            with torch.inference_mode():
                remover.to(backend.pipeline.device)
                try:
                    foreground = remover(original).convert("RGBA")
                finally:
                    remover.cpu()
            alpha = np.asarray(foreground.getchannel("A"))
            if alpha.min() == 255 or not (alpha > 204).any():
                raise ValueError(f"{obj} 抠图异常，请检查 {source}")
            masked_path = work / "masked.png"
            foreground.save(masked_path)
            for seed in SEEDS:
                run = staged / f"seed-{seed}"
                pipeline.run(masked_path, run, seed=seed)
                # 输入来源与实际前景分别保存；viewer 展示原始照片。
                shutil.copy2(source, run / "source.jpg")
                original.save(run / "input.png")
                shutil.copy2(masked_path, run / "masked.png")
                manifest_path = run / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["input_path"] = str(results / config["name"] / obj / run.name / "masked.png")
                manifest["input_override"] = {
                    "source": source.relative_to(ROOT).as_posix(),
                    "source_sha256": file_hash(source),
                    "method": "official RMBG-2.0; original generation config and seeds",
                    "created_at": now(),
                    "note": "Local input replacement; original frozen experiment plan describes the earlier render inputs",
                }
                for name in ("input.png", "source.jpg", "masked.png"):
                    manifest["artifacts"][name] = file_hash(run / name)
                save_json(manifest_path, manifest)
            replace_object(staged, results / config["name"] / obj)
            # viewer 从各次运行读取 input.png 和模型路径，直接刷新原实验。
            write_viewer_manifest(
                results, results / "viewer-manifest.json",
                ROOT / "datasets/gso-v1/data/rendered/gso-formal-v1", overwrite=True,
            )
            shutil.rmtree(work)
            print(f"已覆盖 {obj} 的两个种子并更新 viewer 预设", flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
