"""Create a portable index of an experiment without changing its frozen plan."""

import json
import os
import re
from pathlib import Path

from .recording import file_hash, save_json

SAFE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _relative(path, anchor):
    """清单路径以清单文件所在目录为基准，搬运数据时保留相对布局即可。"""
    try:
        return Path(os.path.relpath(path, anchor)).as_posix()
    except ValueError as exc:
        raise ValueError("Viewer index and data must be on the same drive") from exc


def build_viewer_manifest(experiment, destination, reference_dir=None):
    root = Path(experiment).resolve()
    dest = Path(destination).resolve()
    plan = json.loads((root / "experiment.json").read_text(encoding="utf-8"))["plan"]
    configs, rows, seeds = plan["configs"], plan["objects"], plan["seeds"]
    labels_path = Path(__file__).resolve().parents[2] / "data/manifests/gso-selection.csv"
    labels = {}
    if labels_path.is_file():
        import csv

        with labels_path.open(encoding="utf-8-sig", newline="") as stream:
            labels = {r["id"]: r.get("display_name") or r["id"] for r in csv.DictReader(stream)}
    objects, runs = [], []
    for row in rows:
        ident = row["id"]
        if not SAFE_ID.fullmatch(ident):
            raise ValueError(f"Unsafe object ID: {ident}")
        # 老实验计划里的服务器绝对路径在本机失效时，可以显式指定本地参考模型根目录。
        ref = (Path(reference_dir) / ident / "reference_normalized.glb") if reference_dir else Path(
            row.get("reference") or ""
        )
        # 显式替换来源时用冻结计划的摘要核对，避免将同名错误模型当作参考真值。
        if reference_dir and ref.is_file() and row.get("reference_sha256"):
            if file_hash(ref) != row["reference_sha256"]:
                raise ValueError(f"Reference SHA256 mismatch for {ident}: {ref}")
        reference = _relative(ref.resolve(), dest.parent) if ref.is_file() else None
        objects.append({"id": ident, "label": labels.get(ident, ident), "reference": reference,
                        "reference_sha256": row.get("reference_sha256"), "input": None})
        for config in configs:
            variant = config["name"]
            if not SAFE_ID.fullmatch(variant):
                raise ValueError(f"Unsafe configuration name: {variant}")
            for seed in seeds:
                if type(seed) is not int or not 0 <= seed < 2**32:
                    raise ValueError(f"Invalid seed: {seed}")
                run = root / variant / ident / f"seed-{seed}"
                manifest = run / "manifest.json"
                status = "pending"
                if manifest.is_file():
                    try:
                        status = json.loads(manifest.read_text(encoding="utf-8")).get("status", "pending")
                    except (OSError, ValueError):
                        status = "unreadable"
                models = {}
                for kind, filename in (("asset", "asset.glb"), ("shape", "shape_raw.glb")):
                    path = run / filename
                    # 中断或失败后可能残留文件；只有成功完成的结果可加入可视化预设。
                    relative = _relative(path, dest.parent) if status == "completed" and path.is_file() else None
                    if relative is not None:
                        models[kind] = relative
                # 每个方案和种子可能使用不同输入，不能只复用对象的第一张图。
                run_input = _relative(run / "input.png", dest.parent) if (run / "input.png").is_file() else None
                if objects[-1]["input"] is None and run_input is not None:
                    objects[-1]["input"] = run_input  # 保留旧版浏览器读取对象输入的能力。
                runs.append({"object": ident, "variant": variant, "seed": seed, "status": status,
                             "input": run_input, "models": models})
    return {"schema_version": 1, "generated_by": "asset3d.viewer_manifest", "id": root.name,
            "label": root.name, "objects": objects,
            "variants": [{"id": c["name"], "label": c["name"], "config": c} for c in configs], "runs": runs}


def write_viewer_manifest(experiment, destination, reference_dir=None, overwrite=False):
    dest = Path(destination)
    if dest.exists() and not overwrite:
        raise FileExistsError(f"Viewer manifest exists: {dest}; choose another file or use --overwrite")
    result = build_viewer_manifest(experiment, dest, reference_dir)
    save_json(dest, result)
    return dest
