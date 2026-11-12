import csv
import json
import statistics
from datetime import datetime
from itertools import combinations
from pathlib import Path

from ..recording import object_hash, save_json
from .batch import ARTIFACT_METRICS, verify_run

GEOMETRY_METRICS = ("chamfer_l2", "hausdorff_sampled", "hd95_sampled")
TIMING_METRICS = ("inference_seconds", "wall_seconds", "process_wall_seconds")
METRICS = (*GEOMETRY_METRICS, *(f"asset_{k}" for k in GEOMETRY_METRICS), *TIMING_METRICS)
SUCCESS = {"completed", "shape_only"}


def _process_timing(attempts, manifest):
    completed = [a for a in attempts if a["status"] == "completed"]
    if not completed:
        return None
    # Old pilot ledgers called a resume cache hit "completed". Match the actual
    # successful generation window rather than reporting that short cache check.
    finished = next(
        (a.get("finished_at") for a in reversed(manifest.get("attempts", [])) if a.get("status") in SUCCESS),
        None,
    )
    if finished:
        try:
            target = datetime.fromisoformat(finished)
            for a in reversed(completed):
                if (
                    datetime.fromisoformat(a["started_at"])
                    <= target
                    <= datetime.fromisoformat(a["finished_at"])
                ):
                    return a.get("wall_seconds")
        except (KeyError, TypeError, ValueError):
            pass
    return completed[0].get("wall_seconds")


def _load_reports(root):
    reports = {}
    for artifact, suffix in (("shape_raw.glb", ""), ("asset.glb", "-asset")):
        path = root / f"evaluation-report{suffix}.json"
        if path.exists():
            reports[artifact] = json.loads(path.read_text(encoding="utf-8"))
    return reports


def _read_metrics(directory, row, manifest, obj, plan, reports):
    if row["status"] not in SUCCESS:
        return
    for artifact, filename in ARTIFACT_METRICS.items():
        path = directory / filename
        if not path.exists() or artifact not in manifest["artifacts"] or not obj.get("reference_sha256"):
            continue
        prefix = "asset_" if artifact == "asset.glb" else ""
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            valid = (
                values.get("prediction_sha256") == manifest["artifacts"][artifact]
                and values.get("reference_sha256") == obj["reference_sha256"]
                and values.get("artifact", artifact) == artifact
                and values.get("plan_sha256", object_hash(plan)) == object_hash(plan)
            )
            report = reports.get(artifact)
            if report:
                # Failed re-evaluation cannot silently resurrect scores from an old protocol.
                valid = valid and not any(e["run"] == str(directory) for e in report["errors"])
                valid = valid and all(
                    values.get(k) == report.get(k)
                    for k in ("plan_sha256", "evaluation_config_sha256", "transform_sha256")
                )
            if not valid:
                raise ValueError("Metric provenance or latest evaluation protocol does not match")
            row.update({prefix + k: values[k] for k in GEOMETRY_METRICS})
            row[prefix + "geometry_protocol_sha256"] = object_hash(values.get("protocol", {}))
        except (KeyError, ValueError, TypeError) as exc:
            row[prefix + "metrics_error"] = str(exc)


def _paired_comparisons(records, config_names):
    by_config = {
        name: {(r["object"], r["seed"]): r for r in records if r["config"] == name} for name in config_names
    }
    result = []
    for a, b in combinations(config_names, 2):
        left, right = by_config[a], by_config[b]
        common = [
            key
            for key in left.keys() & right.keys()
            if left[key]["status"] in SUCCESS and right[key]["status"] in SUCCESS
        ]
        clean = [key for key in common if left[key].get("clean_timing") and right[key].get("clean_timing")]
        entry = {
            "config_a": a,
            "config_b": b,
            "difference": "b minus a",
            "common_successful_runs": len(common),
            "common_clean_runs": len(clean),
            "metrics": {},
        }
        for metric in METRICS:
            pairs = clean if metric in TIMING_METRICS else common
            values = {}
            count = 0
            for key in sorted(pairs):
                first, second = left[key], right[key]
                if metric not in first or metric not in second:
                    continue
                if metric not in TIMING_METRICS:
                    protocol = (
                        "asset_geometry_protocol_sha256"
                        if metric.startswith("asset_")
                        else "geometry_protocol_sha256"
                    )
                    if first.get(protocol) != second.get(protocol):
                        continue
                values.setdefault(key[0], []).append(second[metric] - first[metric])
                count += 1
            if values:
                means = [statistics.mean(v) for v in values.values()]
                entry["metrics"][metric] = {
                    "mean_object_mean_difference": statistics.mean(means),
                    "std_across_objects": statistics.stdev(means) if len(means) > 1 else 0,
                    "paired_runs": count,
                    "objects_with_values": len(means),
                }
        result.append(entry)
    return result


def summarize(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    document = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    experiment = document["plan"]
    if "plan_sha256" in document and document["plan_sha256"] != object_hash(experiment):
        raise ValueError("Experiment plan was changed")
    reports = _load_reports(root)
    records = []
    # Preserve the entire planned matrix, including missing/invalid/failed rows.
    for config in experiment["configs"]:
        for obj in experiment["objects"]:
            for seed in experiment["seeds"]:
                directory = root / config["name"] / obj["id"] / f"seed-{seed}"
                row = {"config": config["name"], "object": obj["id"], "seed": seed, "status": "not_run"}
                manifest = {}
                path = directory / "manifest.json"
                try:
                    if path.exists():
                        manifest = json.loads(path.read_text(encoding="utf-8"))
                        attempts = manifest["attempts"]
                        row.update(status=manifest["status"], attempts=len(attempts))
                        row["total_attempt_wall_seconds"] = sum(a.get("wall_seconds", 0) for a in attempts)
                        if row["status"] in SUCCESS:
                            verify_run(directory, manifest, config, obj, seed, experiment)
                        clean = (
                            len(attempts) == 1 and row["status"] == "completed" and not attempts[0]["reused"]
                        )
                        row["clean_timing"] = clean
                        if clean:
                            a = attempts[0]
                            row["wall_seconds"] = a["wall_seconds"]
                            row.update({f"{k}_seconds": v for k, v in a["timings"].items()})
                            row["cold_model_load"] = any(v["cold"] for v in a["loads"].values())
                            row["inference_seconds"] = sum(
                                a["timings"].get(k, 0) for k in ("shape", "texture", "native_shape_material")
                            )
                        row["peak_allocated_bytes"] = max(
                            (a.get("resources", {}).get("peak_allocated_bytes", 0) for a in attempts),
                            default=0,
                        )
                        row["file_bytes"] = manifest.get("export", {}).get("file_bytes")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    row.update(status="invalid", validation_error=str(exc), clean_timing=False)
                process_path = root / "process-logs" / config["name"] / f"{obj['id']}-seed-{seed}.json"
                if process_path.exists():
                    try:
                        proc_attempts = json.loads(process_path.read_text(encoding="utf-8"))["attempts"]
                        latest = proc_attempts[-1]
                        row["process_status"] = latest["status"]
                        revalidated = (
                            latest["status"] == "skipped"
                            and latest.get("reason") == "already_completed"
                            and latest.get("artifacts_validated") is True
                            and row["status"] in SUCCESS
                        )
                        effective = [a for a in proc_attempts if a["status"] != "skipped"]
                        if effective and not revalidated:
                            proc = effective[-1]
                            if row["status"] != "invalid":
                                if proc["status"] in {"failed", "timeout", "running"}:
                                    row["status"] = proc["status"]
                                elif row["status"] in {"not_run", "running"}:
                                    row["status"] = "failed"
                        timing = _process_timing(proc_attempts, manifest)
                        if timing is not None:
                            row["process_wall_seconds"] = timing
                    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                        row.update(status="invalid", validation_error=str(exc), clean_timing=False)
                if row["status"] != "completed":
                    row["clean_timing"] = False
                _read_metrics(directory, row, manifest, obj, experiment, reports)
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
        entry = {"planned": len(selected), "metrics": {}}
        for status in ("completed", "shape_only", "not_run", "failed", "timeout", "running", "invalid"):
            entry[status] = sum(r["status"] == status for r in selected)
        entry["success_rate"] = entry["completed"] / entry["planned"] if entry["planned"] else None
        for metric in METRICS:
            per_object = []
            for obj in experiment["objects"]:
                values = [
                    r[metric]
                    for r in selected
                    if r["object"] == obj["id"]
                    and metric in r
                    and r["status"] in SUCCESS
                    and (metric not in TIMING_METRICS or r.get("clean_timing"))
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
            "paired_comparisons": _paired_comparisons(records, [c["name"] for c in experiment["configs"]]),
            "notes": (
                "All planned runs in denominator; success requires recorded artifact hashes to match. "
                "Quality conditional on success. Average seeds within objects first. "
                "Timing excludes resumed/failed runs; cache checks never replace generation process time. "
                "Paired differences use common successful object/seed pairs, additionally clean for timing. "
                "asset_* metrics describe final assets; unprefixed geometry metrics describe raw meshes."
            ),
        },
    )
    return summary
