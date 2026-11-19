"""检查历史结果，不修改原始运行记录或绕过源码校验。"""
import json
from pathlib import Path

from .recording import file_hash, object_hash


def verify_archive(results):
    results = Path(results).resolve()
    original = json.loads((results / "experiment.json").read_text(encoding="utf-8"))
    plan = original["plan"]
    if original.get("plan_sha256") and original["plan_sha256"] != object_hash(plan):
        raise ValueError("Archived plan hash mismatch")
    count = 0
    for config in plan["configs"]:
        for obj in plan["objects"]:
            for seed in plan["seeds"]:
                run = (results / config["name"] / obj["id"] / f"seed-{seed}").resolve()
                if not run.is_relative_to(results):
                    raise ValueError("Unsafe archived run path")
                record = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                if record.get("status") != "completed":
                    raise ValueError(f"Incomplete archived run: {run}")
                artifacts = record["artifacts"]
                if not {"asset.glb", "shape_raw.glb"} <= artifacts.keys():
                    raise ValueError(f"Missing model records: {run}")
                for name, digest in artifacts.items():
                    path = (run / name).resolve()
                    if not path.is_relative_to(run) or file_hash(path) != digest:
                        raise ValueError(f"Changed artifact: {path}")
                count += 1
    return count
