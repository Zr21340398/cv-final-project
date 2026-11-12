import gc
import json
import sys
from pathlib import Path

from .config import load_config
from .data import read_manifest
from .pipeline import Pipeline
from .recording import file_hash, now, object_hash, save_json
from .viewer_manifest import write_viewer_manifest


def _update_viewer_manifest(output):
    """展示索引只提供便利，更新失败时保留训练或生成任务的执行结果。"""
    viewer_path = output / "viewer-manifest.json"
    try:
        if viewer_path.exists():
            viewer = json.loads(viewer_path.read_text(encoding="utf-8"))
            if (viewer.get("schema_version") != 1 or viewer.get("id") != output.name
                    or viewer.get("generated_by") != "asset3d.viewer_manifest"):
                raise ValueError("Existing viewer-manifest.json has an incompatible format")
        write_viewer_manifest(output, viewer_path, overwrite=True)
    except Exception as exc:
        print(f"Viewer index update failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


def run_experiments(manifest_path, config_paths, seeds, output, split="test", resume=False):
    rows = read_manifest(manifest_path, split)
    if not rows:
        raise ValueError(f"No objects in split {split}")
    configs = [load_config(p) for p in config_paths]
    if len({c["name"] for c in configs}) != len(configs) or len(set(seeds)) != len(seeds):
        raise ValueError("Configuration names and seeds must be unique")
    if not seeds or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds):
        raise ValueError("Seeds must be distinct integers in [0, 2**32)")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = {
        "manifest_sha256": file_hash(manifest_path),
        "objects": rows,
        "split": split,
        "configs": configs,
        "seeds": seeds,
    }
    plan_path = output / "experiment.json"
    if plan_path.exists():
        previous = json.loads(plan_path.read_text(encoding="utf-8"))
        if not resume or previous["plan_sha256"] != object_hash(plan):
            raise ValueError("Experiment already exists or its plan changed; choose a new output directory")
    else:
        save_json(plan_path, {"created_at": now(), "plan_sha256": object_hash(plan), "plan": plan})
    # 独立生成展示索引，不修改冻结的 experiment.json 或原始模型。
    _update_viewer_manifest(output)
    failures = []
    for config in configs:
        pipeline = Pipeline(config)
        for row in rows:
            for seed in seeds:
                directory = output / config["name"] / row["id"] / f"seed-{seed}"
                try:
                    pipeline.run(row["image"], directory, seed, resume)
                except Exception as exc:
                    failure = {"config": config["name"], "object": row["id"], "seed": seed, "error": str(exc)}
                    failures.append(failure)
                    print(f"FAILED {failure}", flush=True)
                save_json(output / "failures.json", failures)
                _update_viewer_manifest(output)
        del pipeline
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    return failures
