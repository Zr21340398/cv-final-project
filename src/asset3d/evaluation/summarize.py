import csv
import json
import statistics
from pathlib import Path

from ..recording import save_json


def summarize(root, output):
    root, output = Path(root), Path(output)
    experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))["plan"]
    records = []
    # 从完整实验计划逐项建表，失败和未执行的样例都保留在统计中。
    for config in experiment["configs"]:
        for obj in experiment["objects"]:
            for seed in experiment["seeds"]:
                directory = root / config["name"] / obj["id"] / f"seed-{seed}"
                row = {"config": config["name"], "object": obj["id"], "seed": seed, "status": "not_run"}
                path = directory / "manifest.json"
                if path.exists():
                    m = json.loads(path.read_text(encoding="utf-8"))
                    attempts = m["attempts"]
                    row["status"] = m["status"]
                    row["attempts"] = len(attempts)
                    row["total_attempt_wall_seconds"] = sum(
                        a["wall_seconds"] for a in attempts if "wall_seconds" in a
                    )
                    # 正常耗时只采用首次完整成功、没有复用中间文件的运行。
                    clean = len(attempts) == 1 and m["status"] == "completed" and not attempts[0]["reused"]
                    row["clean_timing"] = clean
                    if clean:
                        row["wall_seconds"] = attempts[0]["wall_seconds"]
                        row.update({f"{k}_seconds": v for k, v in attempts[0]["timings"].items()})
                        row["cold_model_load"] = any(v["cold"] for v in attempts[0]["loads"].values())
                        # 汇总模型推理时间；TRELLIS.2 的 PBR 烘焙和文件导出单独列出。
                        row["inference_seconds"] = sum(
                            attempts[0]["timings"].get(k, 0)
                            for k in ("shape", "texture", "native_shape_material")
                        )
                    peaks = [a.get("resources", {}).get("peak_allocated_bytes", 0) for a in attempts]
                    row["peak_allocated_bytes"] = max(peaks, default=0)
                    row["file_bytes"] = m.get("export", {}).get("file_bytes")
                process_path = root / "process-logs" / config["name"] / f"{obj['id']}-seed-{seed}.json"
                if process_path.exists():
                    proc = json.loads(process_path.read_text(encoding="utf-8"))["attempts"][-1]
                    row["process_status"] = proc["status"]
                    row["process_wall_seconds"] = proc.get("wall_seconds")
                    if row["status"] in ("not_run", "running"):
                        row["status"] = "failed" if proc["status"] == "completed" else proc["status"]
                metrics = directory / "metrics.json"
                if metrics.exists():
                    values = json.loads(metrics.read_text(encoding="utf-8"))
                    from ..recording import file_hash

                    pred_path = directory / "shape_raw.glb"
                    if values.get("prediction_sha256") == file_hash(pred_path) and values.get(
                        "reference_sha256"
                    ) == obj.get("reference_sha256"):
                        row.update(
                            {k: values[k] for k in ("chamfer_l2", "hausdorff_sampled", "hd95_sampled")}
                        )
                records.append(row)
    output.mkdir(parents=True, exist_ok=True)
    fields = sorted(set().union(*(r.keys() for r in records))) if records else ["status"]
    with (output / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    summary = {}
    for config in experiment["configs"]:
        selected = [r for r in records if r["config"] == config["name"]]
        entry = {
            "planned": len(selected),
            "completed": sum(r["status"] == "completed" for r in selected),
            "not_run": sum(r["status"] == "not_run" for r in selected),
            "metrics": {},
        }
        # 成功率以全部计划任务为分母，配合成功样例的质量分数一起解读。
        entry["success_rate"] = entry["completed"] / entry["planned"] if entry["planned"] else None
        for metric in (
            "chamfer_l2",
            "hausdorff_sampled",
            "hd95_sampled",
            "inference_seconds",
            "wall_seconds",
        ):
            # 先对同一物体的多个种子求平均，再对物体求平均，使各物体权重相同。
            per_object = []
            for obj in experiment["objects"]:
                values = [
                    r[metric]
                    for r in selected
                    if r["object"] == obj["id"] and metric in r and r["status"] == "completed"
                ]
                if values:
                    per_object.append(statistics.mean(values))
            if per_object:
                entry["metrics"][metric] = {
                    "mean_object_mean": statistics.mean(per_object),
                    "std_across_objects": statistics.stdev(per_object) if len(per_object) > 1 else 0,
                    "objects_with_values": len(per_object),
                }
        summary[config["name"]] = entry
    save_json(
        output / "summary.json",
        {
            "configs": summary,
            "notes": "All planned runs in denominator; quality conditional on success. Average seeds within each object first. Resumed/failed timings excluded from clean inference/wall statistics. Cold loads flagged in runs.csv.",
        },
    )
    return summary
