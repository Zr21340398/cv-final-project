#!/usr/bin/env python3
"""Summarize pilot03's five objects and two seeds into public metrics and CSV.

Usage:
    python scripts/summarize_pilot_records.py --records records.json --output report

The input is a JSON object keyed by relative record paths: experiment.json,
MODEL/OBJECT/seed-N/manifest.json and process-logs/MODEL/OBJECT-seed-N.json.
Only the output directory is written. Python's standard library is sufficient.
"""

import argparse
import csv
import hashlib
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

OBJECTS = ["simple", "thin", "asymmetric", "pattern", "material"]
MODELS = ["hunyuan2", "trellis2"]
SEEDS = [42, 123]
HEADERS = [
    "model", "object_id", "seed", "status", "pipeline_wall_seconds",
    "process_wall_seconds", "preprocess_seconds", "shape_seconds",
    "native_shape_material_seconds", "texture_mesh_reduce_seconds", "texture_seconds",
    "pbr_bake_seconds", "export_seconds", "load_shape_seconds", "load_texture_seconds",
    "gpu_peak_allocated_bytes", "gpu_peak_reserved_bytes", "final_glb_bytes",
    "final_mesh_count", "final_faces", "final_vertices", "texture_mesh_faces_before",
    "texture_mesh_faces_after", "texture_mesh_target_faces", "pipeline_attempt_index",
    "process_attempt_index", "process_attempts_total", "resume_skip_attempts_excluded",
    "asset_glb_sha256", "input_sha256", "config_sha256",
]
FIELDS = HEADERS[4:24]


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rounded(value):
    return round(value, 6) if isinstance(value, float) else value


def describe(values):
    clean = [value for value in values if value is not None]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(clean), "mean": rounded(statistics.fmean(clean)),
        "median": rounded(statistics.median(clean)), "min": rounded(min(clean)),
        "max": rounded(max(clean)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True, help="Captured record dictionary JSON")
    parser.add_argument("--output", type=Path, required=True, help="Directory for metrics.json and runs.csv")
    args = parser.parse_args()
    raw_bytes = args.records.read_bytes()
    records = json.loads(raw_bytes)
    experiment = records["experiment.json"]
    plan = experiment["plan"]
    assert [item["id"] for item in plan["objects"]] == OBJECTS
    assert plan["seeds"] == SEEDS
    assert all(item["reference"] is None for item in plan["objects"])
    input_hashes = {item["id"]: item["image_sha256"] for item in plan["objects"]}
    rows = []
    environments = {model: {"gpu": set(), "torch": set(), "cuda_runtime": set()} for model in MODELS}
    excluded_total = 0
    for model in MODELS:
        for object_id in OBJECTS:
            for seed in SEEDS:
                manifest_key = f"{model}/{object_id}/seed-{seed}/manifest.json"
                process_key = f"process-logs/{model}/{object_id}-seed-{seed}.json"
                manifest = records[manifest_key]
                assert manifest["status"] == "completed", manifest_key
                assert manifest["identity"]["seed"] == seed
                assert manifest["identity"]["input_sha256"] == input_hashes[object_id]
                completed = [(i, attempt) for i, attempt in enumerate(manifest["attempts"], 1)
                             if attempt.get("status") == "completed"]
                pipeline_index, pipeline = min(completed, key=lambda item: dt(item[1]["started_at"]))
                assert not pipeline.get("reused"), "Expected a fresh, fully generated pipeline"
                process_attempts = records[process_key]["attempts"]
                candidates = [(i, attempt) for i, attempt in enumerate(process_attempts, 1)
                              if attempt.get("status") == "completed" and attempt.get("returncode") == 0
                              and dt(attempt["started_at"]) <= dt(pipeline["started_at"])
                              and dt(attempt["finished_at"]) >= dt(pipeline["finished_at"])]
                assert len(candidates) == 1, (manifest_key, "Ambiguous generation process")
                process_index, process = candidates[0]
                skips = [attempt for i, attempt in enumerate(process_attempts, 1)
                         if i != process_index and attempt.get("status") == "completed"
                         and attempt.get("returncode") == 0 and "--resume" in attempt.get("command", [])
                         and all(not (dt(attempt["started_at"]) <= dt(p["started_at"])
                                      and dt(attempt["finished_at"]) >= dt(p["finished_at"]))
                                 for p in manifest["attempts"])]
                excluded_total += len(skips)
                timings, loads = pipeline["timings"], pipeline.get("loads", {})
                texture_mesh = pipeline.get("texture_mesh", {})
                export = manifest["export"]
                meshes = export["meshes"]
                row = {
                    "model": model, "object_id": object_id, "seed": seed, "status": "completed",
                    "pipeline_wall_seconds": pipeline["wall_seconds"],
                    "process_wall_seconds": process["wall_seconds"],
                    **{f"{field}_seconds": timings.get(field) for field in (
                        "preprocess", "shape", "native_shape_material", "texture_mesh_reduce",
                        "texture", "pbr_bake", "export")},
                    "load_shape_seconds": loads.get("shape", {}).get("seconds"),
                    "load_texture_seconds": loads.get("texture", {}).get("seconds"),
                    "gpu_peak_allocated_bytes": pipeline["resources"]["peak_allocated_bytes"],
                    "gpu_peak_reserved_bytes": pipeline["resources"].get("peak_reserved_bytes"),
                    "final_glb_bytes": export["file_bytes"], "final_mesh_count": len(meshes),
                    "final_faces": sum(mesh["faces"] for mesh in meshes),
                    "final_vertices": sum(mesh["vertices"] for mesh in meshes),
                    "texture_mesh_faces_before": texture_mesh.get("faces_before"),
                    "texture_mesh_faces_after": texture_mesh.get("faces_after"),
                    "texture_mesh_target_faces": texture_mesh.get("target_faces"),
                    "pipeline_attempt_index": pipeline_index,
                    "process_attempt_index": process_index,
                    "process_attempts_total": len(process_attempts),
                    "resume_skip_attempts_excluded": len(skips),
                    "asset_glb_sha256": manifest["artifacts"]["asset.glb"],
                    "input_sha256": manifest["identity"]["input_sha256"],
                    "config_sha256": manifest["identity"]["config_sha256"],
                }
                for field in FIELDS:
                    value = row[field]
                    assert value is None or (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0), field
                assert row["process_wall_seconds"] >= row["pipeline_wall_seconds"]
                assert export["file_bytes"] > 0 and all(mesh["has_texture"] for mesh in meshes)
                if model == "hunyuan2":
                    assert row["texture_mesh_target_faces"] == row["texture_mesh_faces_after"] == 40000
                    assert row["final_faces"] == 40000
                for field in environments[model]:
                    environments[model][field].add(pipeline["backend"][field])
                rows.append(row)

    assert len(rows) == len(set((r["model"], r["object_id"], r["seed"]) for r in rows)) == 20
    assert all(environments[model]["gpu"] == {"NVIDIA L20"} for model in MODELS)

    per_object, summaries = {}, {}
    for model in MODELS:
        model_rows = [row for row in rows if row["model"] == model]
        per_object[model] = {}
        for object_id in OBJECTS:
            pair = [row for row in model_rows if row["object_id"] == object_id]
            assert len(pair) == 2
            per_object[model][object_id] = {
                field: describe([row[field] for row in pair])["mean"] for field in FIELDS
            }
        summaries[model] = {
            "planned_runs": 10, "completed_runs": len(model_rows), "objects": 5, "seeds_per_object": 2,
            "metrics": {
                field: {
                    "object_means": describe([per_object[model][obj][field] for obj in OBJECTS]),
                    "runs": describe([row[field] for row in model_rows]),
                } for field in FIELDS
            },
        }
        for field in FIELDS:
            # The balanced design must give the same mean with either weighting order.
            grouped = summaries[model]["metrics"][field]["object_means"]["mean"]
            pooled = summaries[model]["metrics"][field]["runs"]["mean"]
            assert grouped is None and pooled is None or math.isclose(grouped, pooled, abs_tol=1e-6)

    metrics = {
        "schema_version": 1, "experiment": "pilot03", "planned_runs": 20, "completed_runs": 20,
        "objects": OBJECTS, "seeds": SEEDS,
        "provenance": {
            "source_records_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_record_count": len(records), "plan_sha256": experiment["plan_sha256"],
            "source_hash": plan["source_hash"],
            "source_records": "One experiment record, 20 run manifests and 20 process-attempt logs.",
        },
        "method": {
            "aggregation": "For each model and object, average seeds 42 and 123; then equally average the five object means. object_means dispersion is over five object averages; runs dispersion is over ten individual runs.",
            "pipeline_wall_seconds": "Earliest completed manifest attempt, including model loads and the full pipeline. All selected attempts generated fresh output without reused stages.",
            "process_wall_seconds": "Completed outer process whose recorded start/end enclose the selected pipeline attempt. Commands containing --resume are included when they actually generated a run.",
            "resume_skips_excluded": excluded_total,
            "stage_timings": "TRELLIS native_shape_material combines geometry and material inference; shape_seconds and texture_seconds are unavailable for TRELLIS. Hunyuan texture_seconds covers its Paint pipeline; it has no separately measured pbr_bake_seconds. Unavailable measurements are null, not zero.",
            "gpu_memory": "PyTorch peak allocated/reserved bytes within the selected pipeline attempt; excludes additional native CUDA allocations and is not total driver-visible GPU memory.",
            "geometry": "final_faces/final_vertices sum the final GLB mesh records. Hunyuan reduces a copy of its raw shape to 40,000 faces before Paint; raw shape is preserved. TRELLIS final export targets 1,000,000 faces. Face count is an output/configuration property, not a quality score.",
            "quality": "No 3D ground truth is available. These files contain operational measurements only; visual quality requires subjective review of shared-view renders and assets.",
            "wall_time_exclusions": "Queue waiting, environment installation, weight downloads and resumed no-op checks are excluded. These are successful pilot03 runs, not an all-experiment or first-ever-attempt success rate.",
            "units": "Time: seconds; memory/file size: bytes; faces/vertices: counts. GiB=2^30 bytes, MiB=2^20 bytes.",
            "csv_nulls": "Empty CSV cells represent unavailable measurements; numeric zero is retained when explicitly recorded.",
        },
        "configurations": {config["name"]: config for config in plan["configs"]},
        "environments": {model: {field: sorted(values) for field, values in fields.items()}
                         for model, fields in environments.items()},
        "models": summaries, "per_object_seed_means": per_object,
    }
    encoded = json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    for private in ("/home/", "/Users/", "/scratch/"):
        assert private not in encoded
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(encoded, encoding="utf-8")

    def csv_value(value):
        value = rounded(value)
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return value

    with (args.output / "runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADERS)
        writer.writerows([[csv_value(row.get(field)) for field in HEADERS] for row in rows])

    print(f"Validated 20 completed runs; excluded {excluded_total} resumed no-op process attempts.")
    for model in MODELS:
        values = summaries[model]["metrics"]
        def avg(field):
            return values[field]["object_means"]["mean"]
        print(f"{model}: pipeline={avg('pipeline_wall_seconds'):.3f}s, "
              f"process={avg('process_wall_seconds'):.3f}s, "
              f"allocated={avg('gpu_peak_allocated_bytes') / 2**30:.3f}GiB, "
              f"GLB={avg('final_glb_bytes') / 2**20:.3f}MiB, "
              f"faces={avg('final_faces'):.1f}")


if __name__ == "__main__":
    main()
