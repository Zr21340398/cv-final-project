"""Small paired pilot, with separate environments and one fresh process per run."""

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from .config import load_config
from .data import read_manifest
from .preprocess import prepare_image
from .recording import environment, file_hash, now, object_hash, save_json


def read_plan(root):
    root = Path(root).resolve()
    document = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    plan = document["plan"]
    if document["plan_sha256"] != object_hash(plan):
        raise ValueError("Experiment plan was changed")
    # 实验开始后固定代码、图片和配置；内容有改动时新建实验目录，保留旧结果。
    if plan["source_hash"] != environment()["source_hash"]:
        raise ValueError("Project source changed since pilot-init; create a new experiment")
    for row in plan["objects"]:
        for key in ("image", "reference"):
            if row.get(key) and file_hash(row[key]) != row[key + "_sha256"]:
                raise ValueError(f"Frozen {key} changed for {row['id']}")
    return root, plan


def prepare(manifest, output, split="real"):
    rows = read_manifest(manifest, split)
    if not rows:
        raise ValueError("No selected objects")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = None
    background_hash = None

    def remove(image):
        nonlocal session, background_hash
        import rembg

        cache = Path(os.environ.get("U2NET_HOME", "~/.u2net")).expanduser() / "u2net.onnx"
        if not cache.is_file():
            raise RuntimeError("Cache background model first: asset3d download --background")
        if session is None:
            # 抠图只在 CPU 上统一做一次，两种三维模型随后读取同一批透明前景 PNG。
            session = rembg.new_session("u2net", providers=["CPUExecutionProvider"])
            background_hash = file_hash(cache)
        return rembg.remove(image, session=session)

    prepared, audit = [], []
    # 统一图片尺寸及留白，让两组从相同的物体范围开始生成。
    options = {"background": "auto", "size": 1024, "padding": 0.05}
    start = time.perf_counter()
    for row in rows:
        image = prepare_image(row["image"], options, remove)
        alpha = np.asarray(image.getchannel("A"))
        if alpha.min() == 255 or not np.any(alpha > 204):
            raise ValueError(f"Invalid foreground mask for {row['id']}; supply a corrected transparent PNG")
        dest = output / f"{row['id']}.png"
        image.save(dest)
        prepared.append(
            {"id": row["id"], "image": dest.name, "reference": row["reference"] or "", "split": row["split"]}
        )
        audit.append(
            {
                "id": row["id"],
                "source_sha256": row["image_sha256"],
                "foreground_sha256": file_hash(dest),
                "source": row["image"],
            }
        )
    with (output / "objects.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "image", "reference", "split"])
        writer.writeheader()
        writer.writerows(prepared)
    save_json(
        output / "preparation.json",
        {
            "inputs": audit,
            "preprocess": options,
            "background_sha256": background_hash,
            "wall_seconds": time.perf_counter() - start,
        },
    )
    return output / "objects.csv"


def initialize(manifest, configs, seeds, output, split="real"):
    rows = read_manifest(manifest, split)
    if not rows:
        raise ValueError("No objects selected")
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds)
    ):
        raise ValueError("Seeds must be unique integers in [0,2**32)")
    resolved = [load_config(p) for p in configs]
    if len(resolved) != 2 or len({c["name"] for c in resolved}) != 2:
        raise ValueError("Pilot requires exactly two distinct configuration names")
    if {c.get("backend", "hunyuan2") for c in resolved} != {"trellis2", "hunyuan2"}:
        raise ValueError("Pilot compares TRELLIS.2 and Hunyuan3D 2.0")
    for c in resolved:
        if c["preprocess"]["background"] != "keep" or not c["model"]["local_files_only"]:
            raise ValueError("Pilot requires shared masks and offline model loading")
    for row in rows:
        with Image.open(row["image"]) as image:
            if image.mode != "RGBA" or np.asarray(image.getchannel("A")).min() == 255:
                raise ValueError(f"Use pilot-prepare first: {row['id']}")
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    # 冻结对象清单、模型参数、种子和源代码摘要，形成这次比较的完整实验条件。
    plan = {
        "objects": rows,
        "split": split,
        "configs": resolved,
        "seeds": seeds,
        "manifest_sha256": file_hash(manifest),
        "source_hash": environment()["source_hash"],
        "protocol": "paired native single-image pipelines; fresh process per object/seed",
        "prepared_input_only": True,
    }
    for c in resolved:
        path = root / "configs" / (c["name"] + ".yaml")
        path.parent.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")
    save_json(root / "experiment.json", {"created_at": now(), "plan_sha256": object_hash(plan), "plan": plan})
    return root


def run(root, name, resume=False, timeout=1800, limit=None):
    root, plan = read_plan(root)
    configs = [c for c in plan["configs"] if c["name"] == name]
    if len(configs) != 1:
        raise ValueError("Unknown configuration name")
    if timeout <= 0 or (limit is not None and limit < 1):
        raise ValueError("timeout and limit must be positive")
    config_path = root / "configs" / (name + ".yaml")
    if load_config(config_path) != configs[0]:
        raise ValueError("Frozen configuration changed")
    lock = root / f".pilot-{name}.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    failures, count = [], 0
    try:
        for obj in plan["objects"]:
            for seed in plan["seeds"]:
                if limit is not None and count >= limit:
                    return failures
                count += 1
                directory = root / name / obj["id"] / f"seed-{seed}"
                # 每个物体和种子启动独立 Python 进程，结束后释放模型状态与 GPU 内存。
                # sys.executable 继承当前虚拟环境，确保两组分别使用各自的依赖。
                command = [
                    sys.executable,
                    "-m",
                    "asset3d.cli",
                    "generate",
                    "--image",
                    obj["image"],
                    "--config",
                    str(config_path),
                    "--output",
                    str(directory),
                    "--seed",
                    str(seed),
                ]
                if resume:
                    command.append("--resume")
                # 进程日志放在结果目录外，生成流程仍可严格检查结果目录是否为空。
                log_dir = root / "process-logs" / name
                log_dir.mkdir(parents=True, exist_ok=True)
                record_path = log_dir / f"{obj['id']}-seed-{seed}.json"
                record = (
                    json.loads(record_path.read_text(encoding="utf-8"))
                    if record_path.exists()
                    else {"attempts": []}
                )
                if record["attempts"] and not resume:
                    raise FileExistsError("Pilot already attempted; use --resume or a new experiment")
                attempt = {"started_at": now(), "status": "running", "command": command}
                record["attempts"].append(attempt)
                save_json(record_path, record)
                start = time.perf_counter()
                log = log_dir / f"{obj['id']}-seed-{seed}.log"
                try:
                    with log.open("a", encoding="utf-8") as stream:
                        result = subprocess.run(
                            command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False
                        )
                    attempt.update(
                        returncode=result.returncode,
                        status="completed" if result.returncode == 0 else "failed",
                    )
                # 超时和报错也记入实验记录，再继续处理剩余样例。
                except subprocess.TimeoutExpired:
                    attempt.update(status="timeout", returncode=None)
                except OSError as exc:
                    attempt.update(status="failed", returncode=None, error=str(exc))
                finally:
                    attempt["wall_seconds"] = time.perf_counter() - start
                    attempt["finished_at"] = now()
                    save_json(record_path, record)
                if attempt["status"] != "completed":
                    failures.append({"object": obj["id"], "seed": seed, "log": str(log)})
                print(f"{name}/{obj['id']}/{seed}: {attempt['status']}", flush=True)
        return failures
    finally:
        lock.unlink(missing_ok=True)


def evaluate(root, config, transforms=None):
    from .cli import evaluate_one

    root, plan = read_plan(root)
    mapping = json.loads(Path(transforms).read_text(encoding="utf-8")) if transforms else {}
    errors = []
    for c in plan["configs"]:
        transform = None
        if c["name"] in mapping:
            transform = root / "evaluation-transforms" / f"{c['name']}.json"
            save_json(transform, mapping[c["name"]])
        for obj in plan["objects"]:
            # 只有配备参考三维模型的样例才能计算几何距离；普通实拍图走人工评估。
            if not obj["reference"]:
                continue
            for seed in plan["seeds"]:
                directory = root / c["name"] / obj["id"] / f"seed-{seed}"
                manifest = directory / "manifest.json"
                if not manifest.exists():
                    continue
                m = json.loads(manifest.read_text(encoding="utf-8"))
                if m["status"] != "completed":
                    continue
                pred = directory / "shape_raw.glb"
                try:
                    if file_hash(pred) != m["artifacts"]["shape_raw.glb"]:
                        raise ValueError("Raw geometry was changed")
                    evaluate_one(pred, obj["reference"], config, directory / "metrics.json", transform)
                except Exception as exc:
                    errors.append({"run": str(directory), "error": str(exc)})
    save_json(root / "evaluation-errors.json", errors)
    return errors


def report(root, output):
    from .evaluation.summarize import summarize

    root, plan = read_plan(root)
    output = Path(output).resolve()
    summary = summarize(root, output)
    # 直接比较外观时使用两组都成功的同物体、同种子样例；完整成功率仍统计全部计划任务。
    pairs, ratings = [], []
    for obj in plan["objects"]:
        for seed in plan["seeds"]:
            cells = []
            for c in plan["configs"]:
                run_dir = root / c["name"] / obj["id"] / f"seed-{seed}"
                mp = run_dir / "manifest.json"
                if not mp.exists():
                    break
                m = json.loads(mp.read_text(encoding="utf-8"))
                if m["status"] != "completed":
                    break
                cells.append({"config": c["name"], "run": str(run_dir)})
            if len(cells) == 2:
                pairs.append({"object": obj["id"], "seed": seed, "runs": cells})
            for c in plan["configs"]:
                ratings.append(
                    {
                        "object": obj["id"],
                        "seed": seed,
                        "model": c["name"],
                        "geometry_1to5": "",
                        "appearance_1to5": "",
                        "input_match_1to5": "",
                        "usable_yes_no": "",
                        "notes": "",
                    }
                )
    save_json(
        output / "paired.json",
        {
            "paired_successes": pairs,
            "configs": summary,
            "note": "No automatic winner. Rate all attempts, include failures, compare geometry and final GLBs.",
        },
    )
    rating_path = output / "ratings.csv"
    # 评分表由人检查白模和带纹理模型后填写；再次汇总时保留已填的分数。
    if not rating_path.exists():
        with rating_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(ratings[0]))
            writer.writeheader()
            writer.writerows(ratings)
    return {
        "paired_successes": len(pairs),
        "planned_pairs": len(plan["objects"]) * len(plan["seeds"]),
        "output": str(output),
    }


def render_all(root, blender="blender", views=8):
    from .render import render_mesh

    root, plan = read_plan(root)
    errors = []
    for c in plan["configs"]:
        for obj in plan["objects"]:
            for seed in plan["seeds"]:
                directory = root / c["name"] / obj["id"] / f"seed-{seed}"
                # 从已经生成的三维模型拍摄预览图：白模看形状，带纹理模型看最终外观。
                for source, dest, clay in (
                    ("shape_raw.glb", "white_preview", True),
                    ("asset.glb", "preview", False),
                ):
                    if not (directory / source).is_file():
                        continue
                    target = directory / dest
                    if target.exists():
                        if (target / "cameras.json").is_file():
                            continue
                        errors.append(
                            {"run": str(target), "error": "Incomplete rendering; use a new directory"}
                        )
                        continue
                    try:
                        render_mesh(directory / source, target, blender, views, 512, clay=clay)
                    except Exception as exc:
                        errors.append({"run": str(target), "error": str(exc)})
    save_json(root / "render-errors.json", errors)
    return errors
