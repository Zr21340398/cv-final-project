"""Evaluate frozen generated artifacts without replacing raw geometry scores."""

import json
from pathlib import Path

from ..recording import environment, file_hash, object_hash, save_json

ARTIFACT_METRICS = {"shape_raw.glb": "metrics.json", "asset.glb": "metrics_asset.json"}


def read_evaluation_plan(root):
    document = json.loads((Path(root) / "experiment.json").read_text(encoding="utf-8"))
    plan = document["plan"]
    if document.get("plan_sha256") != object_hash(plan):
        raise ValueError("Experiment plan is missing its hash or was changed")
    if plan.get("source_hash") and plan["source_hash"] != environment()["source_hash"]:
        raise ValueError("Project source changed; evaluate with the experiment's frozen source")
    return plan


def verify_run(directory, manifest, config, obj, seed, plan):
    """Check provenance and all saved bytes before counting a run as valid."""
    directory = Path(directory).resolve()
    identity = manifest["identity"]
    if identity["config_sha256"] != object_hash(config) or identity["seed"] != seed:
        raise ValueError("Run identity differs from the experiment plan")
    if obj.get("image_sha256") and identity["input_sha256"] != obj["image_sha256"]:
        raise ValueError("Run input differs from the experiment plan")
    if plan.get("source_hash") and manifest.get("environment", {}).get("source_hash") != plan["source_hash"]:
        raise ValueError("Run source differs from the experiment plan")
    for key in ("image", "reference"):
        if obj.get(key):
            if file_hash(obj[key]) != obj.get(key + "_sha256"):
                raise ValueError(f"Frozen {key} changed for {obj['id']}")
    artifacts = manifest["artifacts"]
    required = {"shape_raw.glb"}
    if manifest["status"] == "completed" and config["texture"]["enabled"]:
        required.add("asset.glb")
    if not required <= artifacts.keys():
        raise ValueError("Completed run is missing required artifact hashes")
    for name, digest in artifacts.items():
        artifact = (directory / name).resolve()
        if artifact.parent != directory or not artifact.is_file() or file_hash(artifact) != digest:
            raise ValueError(f"Cached artifact is missing or changed: {name}")


def evaluate_batch(root, config, transform=None, artifact="shape_raw.glb"):
    """Return per-run errors; publish counts even when all planned runs are skipped."""
    from ..cli import evaluate_one

    if artifact not in ARTIFACT_METRICS:
        raise ValueError("artifact must be shape_raw.glb or asset.glb")
    root = Path(root).resolve()
    plan = read_evaluation_plan(root)
    options_hash = file_hash(config)
    transform_hash = file_hash(transform) if transform else None
    report = {
        "artifact": artifact,
        "plan_sha256": object_hash(plan),
        "evaluation_config_sha256": options_hash,
        "transform_sha256": transform_hash,
        "planned": len(plan["configs"]) * len(plan["objects"]) * len(plan["seeds"]),
        "evaluated": 0,
        "skipped": [],
        "errors": [],
    }
    for c in plan["configs"]:
        for obj in plan["objects"]:
            for seed in plan["seeds"]:
                run = root / c["name"] / obj["id"] / f"seed-{seed}"
                if not obj.get("reference"):
                    report["skipped"].append({"run": str(run), "reason": "no_reference"})
                    continue
                path = run / "manifest.json"
                if not path.exists():
                    report["skipped"].append({"run": str(run), "reason": "not_run"})
                    continue
                try:
                    m = json.loads(path.read_text(encoding="utf-8"))
                    accepted = {"completed", "shape_only"} if artifact == "shape_raw.glb" else {"completed"}
                    if m["status"] not in accepted:
                        report["skipped"].append({"run": str(run), "reason": m["status"]})
                        continue
                    verify_run(run, m, c, obj, seed, plan)
                    if artifact not in m["artifacts"]:
                        raise ValueError(f"No recorded hash for {artifact}")
                    result = evaluate_one(
                        run / artifact, obj["reference"], config, run / ARTIFACT_METRICS[artifact], transform
                    )
                    result.update(
                        artifact=artifact,
                        plan_sha256=report["plan_sha256"],
                        evaluation_config_sha256=options_hash,
                        transform_sha256=transform_hash,
                    )
                    save_json(run / ARTIFACT_METRICS[artifact], result)
                    report["evaluated"] += 1
                except Exception as exc:
                    report["errors"].append({"run": str(run), "error": str(exc)})
    report["skipped_count"] = len(report["skipped"])
    report["error_count"] = len(report["errors"])
    suffix = "-asset" if artifact == "asset.glb" else ""
    save_json(root / f"evaluation-errors{suffix}.json", report["errors"])
    save_json(root / f"evaluation-report{suffix}.json", report)
    return report["errors"]
