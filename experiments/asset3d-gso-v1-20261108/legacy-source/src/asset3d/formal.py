"""Explicit development-to-test handoff for the Hunyuan GSO experiment."""

import json
from pathlib import Path

from .config import load_config
from .data import read_manifest
from .export import check_glb
from .recording import environment, file_hash, object_hash

DEFAULT_CONFIGS = [f"configs/hunyuan2_formal_{steps}.yaml" for steps in (50, 30, 20)]


def development_evidence(root, configs, seeds, manifest, *, roster_sha256, render_protocol_sha256):
    """Require complete matching development runs before selecting test settings."""
    root = Path(root).resolve()
    document = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    plan = document["plan"]
    if document.get("plan_sha256") != object_hash(plan):
        raise ValueError("Development plan was changed")
    if plan.get("split") != "dev" or plan.get("source_hash") != environment()["source_hash"]:
        raise ValueError("Use a development experiment from the same source version")
    if not plan.get("context", {}).get("formal_gso"):
        raise ValueError("Development evidence must come from formal-run with GSO checks")
    context = plan["context"]
    if not roster_sha256 or context.get("roster_sha256") != roster_sha256:
        raise ValueError("The complete development/test object roster changed")
    if not render_protocol_sha256 or context.get("render_protocol_sha256") != render_protocol_sha256:
        raise ValueError("Test reference rendering differs from the development protocol")
    current = read_manifest(manifest, "dev")
    if len(current) != 10:
        raise ValueError("Development evidence requires all 10 GSO development objects")

    # Compare content identities rather than paths, so copied immutable data are portable.
    def identities(objects):
        return {o["id"]: (o["image_sha256"], o["reference_sha256"], o["split"]) for o in objects}

    if identities(plan["objects"]) != identities(current):
        raise ValueError("Development inputs or references changed")
    if set(seeds) != set(plan["seeds"]):
        raise ValueError("Use the same seeds as the completed development experiment")
    available = {c["name"]: c for c in plan["configs"]}
    for config in configs:
        if available.get(config["name"]) != config:
            raise ValueError(f"Configuration was not validated on development data: {config['name']}")
        for obj in current:
            for seed in seeds:
                run = root / config["name"] / obj["id"] / f"seed-{seed}"
                record = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                identity = {
                    "input_sha256": obj["image_sha256"],
                    "config_sha256": object_hash(config),
                    "seed": seed,
                }
                if (
                    record.get("status") != "completed"
                    or record.get("identity") != identity
                    or record.get("environment", {}).get("source_hash") != plan["source_hash"]
                ):
                    raise ValueError(f"Incomplete or mismatched development result: {run}")
                artifacts = record.get("artifacts", {})
                if not {"input.png", "foreground.png", "shape_raw.glb", "asset.glb"} <= artifacts.keys():
                    raise ValueError(f"Missing development artifacts: {run}")
                for name, digest in artifacts.items():
                    path = (run / name).resolve()
                    if not path.is_relative_to(run) or file_hash(path) != digest:
                        raise ValueError(f"Development artifact changed: {run / name}")
                check_glb(run / "shape_raw.glb", require_texture=False)
                check_glb(run / "asset.glb", require_texture=True)
    return document["plan_sha256"]


def run_formal(
    manifest,
    selection,
    configs,
    seeds,
    output,
    split="dev",
    *,
    development_experiment=None,
    run_approval=None,
    resume=False,
    timeout=3600,
    limit=None,
    retry_failed=False,
    dry_run=False,
):
    from .experiments import run_experiments
    from .formal_data import audit_formal_dataset

    if split not in ("dev", "test"):
        raise ValueError("Formal experiments require dev or test split")
    if split == "test" and (not configs or not development_experiment):
        raise ValueError("Test requires explicit --configs and --development-experiment; tune on dev first")
    paths = configs if configs else DEFAULT_CONFIGS
    resolved = [load_config(p) for p in paths]
    for c in resolved:
        if (
            c.get("backend", "hunyuan2") != "hunyuan2"
            or not c["model"]["local_files_only"]
            or c["preprocess"]["background"] != "keep"
            or not c["texture"]["enabled"]
            or not c["texture"].get("max_faces_before_paint")
        ):
            raise ValueError(
                "Formal Hunyuan configs require offline loading, shared masks and a Paint face cap"
            )
    audit = audit_formal_dataset(manifest, selection, split=split)
    approval_sha256 = None
    if run_approval is not None:
        from .run_approval import validate_run_approval

        approval_sha256 = validate_run_approval(run_approval, manifest, selection, audit, split)
    if not audit["ready"] and approval_sha256 is None:
        print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)
        raise ValueError("Formal dataset is not ready; resolve the reported data checks first")
    context = {
        "formal_gso": True,
        "selection_sha256": file_hash(selection),
        "roster_sha256": audit["roster_sha256"],
        "render_protocol_sha256": audit["render_protocol_sha256"],
    }
    if approval_sha256 is not None:
        from .run_approval import REVIEW_BASIS

        context.update(
            run_approval_sha256=approval_sha256,
            run_approval_review_basis=REVIEW_BASIS,
            human_visual_qa_completed=False,
            human_qa_pending=audit["human_qa_pending"],
        )
        print(
            "Run authorized after technical and AI review; "
            f"human source QA remains pending for {len(audit['human_qa_pending'])} object(s).",
            flush=True,
        )
    if split == "test":
        context["development_plan_sha256"] = development_evidence(
            development_experiment,
            resolved,
            seeds,
            manifest,
            roster_sha256=context["roster_sha256"],
            render_protocol_sha256=context["render_protocol_sha256"],
        )
    return run_experiments(
        manifest,
        paths,
        seeds,
        output,
        split,
        resume,
        timeout=timeout,
        limit=limit,
        retry_failed=retry_failed,
        dry_run=dry_run,
        context=context,
    )
