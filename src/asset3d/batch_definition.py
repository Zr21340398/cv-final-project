"""实验批次引用共享数据；生成独立选择清单和配置快照。"""
import csv
import io
import json
import os
from pathlib import Path

import yaml

from .config import load_config
from .data import read_manifest
from .recording import object_hash, save_json


def prepare_batch(definition, project_root):
    """只做 CPU 文件核验；返回共用 batch runner 所需的参数。"""
    root = Path(project_root).resolve()
    definition = Path(definition).resolve()
    spec = yaml.safe_load(definition.read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1:
        raise ValueError("Unsupported batch schema")
    ids = spec["objects"]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Batch object IDs must be nonempty and unique")
    seeds = spec["seeds"]
    if not seeds or len(seeds) != len(set(seeds)) or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds):
        raise ValueError("Invalid seeds")
    source = (root / spec["dataset_manifest"]).resolve()
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", "image", "reference", "split"} <= set(reader.fieldnames or []):
            raise ValueError("Invalid dataset manifest columns")
        rows = list(reader)
    # 仅核验本批次选中的对象，允许共享清单中其余对象尚未下载。
    selected = [r for r in rows if r["id"] in ids]
    if len(selected) != len(ids) or {r["id"] for r in selected} != set(ids):
        raise ValueError("Missing or duplicate selected objects")
    if any(r["split"] != spec["split"] for r in selected):
        raise ValueError("Selected object split mismatch")
    configs = [load_config(root / path) for path in spec["configs"]]
    if len({c["name"] for c in configs}) != len(configs) or not configs:
        raise ValueError("Configuration names must be unique")
    work = definition.parent
    # 暂存清单按原数据清单解析路径，最终清单使用相对实验目录的路径。
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["id", "image", "reference", "split"], lineterminator="\n")
    writer.writeheader()
    by_id = {r["id"]: r for r in selected}
    for ident in ids:
        row = by_id[ident]
        writer.writerow({"id": ident, "split": row["split"], **{
            key: os.path.relpath((source.parent / row[key]).resolve(), work).replace(os.sep, "/")
            if row[key] else "" for key in ("image", "reference")}})
    # 先验证临时清单，再写正式选择；失败时不会改动已有实验配置。
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".csv", dir=work, delete=False) as temp:
        temp.write(buffer.getvalue())
        temp_path = Path(temp.name)
    try:
        checked = read_manifest(temp_path, spec["split"])
    finally:
        temp_path.unlink()
    if spec.get("expected_hashes"):
        hashes = json.loads((root / spec["expected_hashes"]).read_text(encoding="utf-8"))
        for row in checked:
            for field in ("image_sha256", "reference_sha256"):
                if row[field] != hashes[row["id"]][field]:
                    raise ValueError(f"Dataset content changed: {row['id']} {field}")
    identity = {"spec": spec, "configs": configs,
                "objects": [{k: r.get(k) for k in ("id", "image_sha256", "reference_sha256")} for r in checked]}
    frozen = work / "resolved.json"
    digest = object_hash(identity)
    if frozen.exists() and json.loads(frozen.read_text(encoding="utf-8"))["sha256"] != digest:
        raise ValueError("Batch definition/data changed; create a new batch directory")
    selection = work / "selection.csv"
    if selection.exists() and selection.read_text(encoding="utf-8") != buffer.getvalue():
        raise ValueError("Existing selection differs; use a new batch directory")
    selection.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    save_json(frozen, {"sha256": digest, **identity})
    # 冻结后的模型配置交给 runner，防止后续改动共用配置影响当前批次。
    snapshots = []
    for config in configs:
        target = work / "resolved-configs" / (config["name"] + ".json")
        save_json(target, config)
        snapshots.append(str(target))
    return selection, snapshots, seeds, work / "results", spec["split"]
