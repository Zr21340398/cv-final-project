import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from .config import load_config
from .recording import environment, file_hash, save_json


def doctor(check_gpu=False, backend="hunyuan2"):
    result = environment()
    result["executables"] = {key: shutil.which(key) for key in ("git", "nvcc", "nvidia-smi", "blender")}
    result["modules"] = {
        key: importlib.util.find_spec(key) is not None
        for key in ("torch", "hy3dgen", "trellis2", "o_voxel", "rembg", "gradio")
    }
    if check_gpu:
        import torch

        result["cuda_available"] = torch.cuda.is_available()
        result["cuda_runtime"] = torch.version.cuda
        if not result["cuda_available"]:
            raise RuntimeError("No CUDA GPU. Run doctor --gpu inside a Slurm GPU allocation.")
        result["gpu_name"] = torch.cuda.get_device_name(0)
        if backend == "trellis2":
            import cumesh  # noqa: F401
            import o_voxel  # noqa: F401
            from trellis2.pipelines import Trellis2ImageTo3DPipeline  # noqa: F401

            result["trellis2_imports"] = "ok"
        else:
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: F401
            from hy3dgen.texgen import Hunyuan3DPaintPipeline  # noqa: F401

            result["hunyuan_imports"] = "ok"
        if result["executables"]["nvidia-smi"]:
            result["nvidia_smi"] = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv"], text=True
            )
    return result


def evaluate_one(pred, ref, config, output, transform=None):
    from .evaluation.geometry import evaluate_meshes

    with Path(config).open(encoding="utf-8") as stream:
        options = yaml.safe_load(stream)
    matrix = json.loads(Path(transform).read_text(encoding="utf-8")) if transform else None
    result = evaluate_meshes(pred, ref, transform=matrix, **options)
    result["prediction_sha256"] = file_hash(pred)
    result["reference_sha256"] = file_hash(ref)
    save_json(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="MAIE5421 single-image 3D project")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("generate", help="Generate one asset; requires a CUDA compute node")
    p.add_argument("--image", required=True)
    p.add_argument("--config", default="configs/baseline.yaml")
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", action="store_true")
    p = sub.add_parser("batch", help="Run an object/config/seed matrix")
    p.add_argument("--manifest", required=True)
    p.add_argument(
        "--configs", nargs="+", default=["configs/baseline.yaml", "configs/medium.yaml", "configs/fast.yaml"]
    )
    p.add_argument("--seeds", nargs="+", type=int, default=[42, 123])
    p.add_argument("--split", choices=["dev", "test", "real"], default="test")
    p.add_argument("--output", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--timeout", type=int, default=3600, help="Per-run child-process timeout in seconds")
    p.add_argument("--limit", type=int, help="Only the first N planned entries, including resumed entries")
    p.add_argument(
        "--retry-failed", action="store_true", help="Explicitly retry failed entries with --resume"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Validate the plan without creating outputs or using GPU"
    )
    p = sub.add_parser(
        "check-formal-data", help="Audit GSO sources, splits, masks, references and render views"
    )
    p.add_argument("--manifest", required=True)
    p.add_argument("--selection", default="data/manifests/gso-selection.csv")
    p.add_argument("--split", choices=["dev", "test"], default="dev")
    p.add_argument("--output", help="Optional JSON audit output")
    p = sub.add_parser("formal-run", help="Validated Hunyuan development/test experiment")
    p.add_argument("--manifest", required=True)
    p.add_argument("--selection", default="data/manifests/gso-selection.csv")
    p.add_argument("--configs", nargs="+", help="Defaults to 50/30/20-step development configs")
    p.add_argument("--split", choices=["dev", "test"], default="dev")
    p.add_argument("--seeds", nargs="+", type=int, default=[42, 123])
    p.add_argument("--development-experiment", help="Completed matching dev experiment required for test")
    p.add_argument("--run-approval", help="Content-bound user approval JSON for technically ready dev data")
    p.add_argument("--output", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--limit", type=int)
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("evaluate", help="Compare with a known reference mesh (not arbitrary photographs)")
    p.add_argument("--pred", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--config", default="configs/evaluation.yaml")
    p.add_argument("--transform", help="JSON prediction-to-reference rigid 4x4 matrix")
    p.add_argument("--output", required=True)
    p = sub.add_parser("evaluate-batch")
    p.add_argument("--experiment", required=True)
    p.add_argument("--config", default="configs/evaluation.yaml")
    p.add_argument("--transform", help="One calibrated coordinate-convention transform for all predictions")
    p.add_argument("--artifact", choices=["shape_raw.glb", "asset.glb"], default="shape_raw.glb")
    p = sub.add_parser("summarize")
    p.add_argument("--experiment", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("render", help="Render fixed views using an installed Blender 4.x executable")
    p.add_argument("--mesh", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--blender", default="blender")
    p.add_argument("--views", type=int, default=8)
    p.add_argument("--resolution", type=int, default=512)
    p.add_argument("--clay", action="store_true")
    p.add_argument("--obj-z-up", action="store_true", help="Preserve Z-up OBJ axes for GSO inputs")
    p.add_argument("--texture-root", help="Resolve missing OBJ textures under this directory")
    p = sub.add_parser("split-data")
    p.add_argument("--catalog", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--dev-count", type=int, default=10)
    p.add_argument("--seed", type=int, default=2026)
    p = sub.add_parser("blind-study")
    p.add_argument("--experiment", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=2026)
    p = sub.add_parser("download", help="Explicitly download pinned model weights (several GB)")
    p.add_argument("--config", default="configs/baseline.yaml")
    p.add_argument("--background", action="store_true", help="Also cache the rembg default model")
    p = sub.add_parser("doctor")
    p.add_argument("--gpu", action="store_true")
    p.add_argument("--output")
    p.add_argument("--backend", choices=["hunyuan2", "trellis2"], default="hunyuan2")
    p = sub.add_parser("pilot-prepare", help="Create one shared foreground dataset")
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--split", choices=["dev", "test", "real"], default="real")
    p = sub.add_parser("pilot-init", help="Freeze a paired model/seed/input plan")
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--configs", nargs=2, default=["configs/trellis2.yaml", "configs/hunyuan2_pilot.yaml"])
    p.add_argument("--seeds", nargs="+", type=int, default=[42, 123])
    p.add_argument("--split", choices=["dev", "test", "real"], default="real")
    p = sub.add_parser("pilot-run", help="Run one model in its own environment, serially")
    p.add_argument("--experiment", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--limit", type=int, help="Smoke check only the first N planned runs")
    p = sub.add_parser("pilot-evaluate")
    p.add_argument("--experiment", required=True)
    p.add_argument("--config", default="configs/evaluation.yaml")
    p.add_argument("--transforms", help="JSON mapping config names to calibrated rigid 4x4 matrices")
    p = sub.add_parser("pilot-report")
    p.add_argument("--experiment", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("pilot-render")
    p.add_argument("--experiment", required=True)
    p.add_argument("--blender", default="blender")
    p.add_argument("--views", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            from .pipeline import Pipeline

            print(Pipeline(load_config(args.config)).run(args.image, args.output, args.seed, args.resume))
        elif args.command == "batch":
            from .experiments import run_experiments

            return (
                1
                if run_experiments(
                    args.manifest,
                    args.configs,
                    args.seeds,
                    args.output,
                    args.split,
                    args.resume,
                    timeout=args.timeout,
                    limit=args.limit,
                    retry_failed=args.retry_failed,
                    dry_run=args.dry_run,
                )
                else 0
            )
        elif args.command == "check-formal-data":
            from .formal_data import audit_formal_dataset

            result = audit_formal_dataset(args.manifest, args.selection, split=args.split)
            if args.output:
                save_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 1
        elif args.command == "formal-run":
            from .formal import run_formal

            return (
                1
                if run_formal(
                    args.manifest,
                    args.selection,
                    args.configs,
                    args.seeds,
                    args.output,
                    args.split,
                    development_experiment=args.development_experiment,
                    run_approval=args.run_approval,
                    resume=args.resume,
                    timeout=args.timeout,
                    limit=args.limit,
                    retry_failed=args.retry_failed,
                    dry_run=args.dry_run,
                )
                else 0
            )
        elif args.command == "evaluate":
            print(
                json.dumps(
                    evaluate_one(args.pred, args.reference, args.config, args.output, args.transform),
                    indent=2,
                )
            )
        elif args.command == "evaluate-batch":
            from .evaluation.batch import evaluate_batch

            errors = evaluate_batch(args.experiment, args.config, args.transform, args.artifact)
            suffix = "-asset" if args.artifact == "asset.glb" else ""
            report = json.loads(
                (Path(args.experiment) / f"evaluation-report{suffix}.json").read_text(encoding="utf-8")
            )
            print(
                json.dumps(
                    {
                        k: report[k]
                        for k in ("artifact", "planned", "evaluated", "skipped_count", "error_count")
                    },
                    indent=2,
                )
            )
            return 1 if errors or report["evaluated"] == 0 else 0
        elif args.command == "summarize":
            from .evaluation.summarize import summarize

            print(json.dumps(summarize(args.experiment, args.output), indent=2))
        elif args.command == "render":
            from .render import render_mesh

            render_mesh(
                args.mesh,
                args.output,
                args.blender,
                args.views,
                args.resolution,
                clay=args.clay,
                obj_z_up=args.obj_z_up,
                texture_root=args.texture_root,
            )
        elif args.command == "split-data":
            from .data import split_catalog

            print(split_catalog(args.catalog, args.output, args.dev_count, args.seed))
        elif args.command == "blind-study":
            from .evaluation.appearance import build_study

            print(build_study(args.experiment, args.output, args.seed))
        elif args.command == "download":
            c = load_config(args.config)
            if c.get("backend") == "trellis2":
                from .backends.trellis2 import snapshot
            else:
                from .backends.hunyuan2 import snapshot
            print(snapshot(c["model"], download=True))
            if args.background:
                from rembg import new_session

                new_session(providers=["CPUExecutionProvider"])
        elif args.command.startswith("pilot-"):
            from . import pilot

            if args.command == "pilot-prepare":
                print(pilot.prepare(args.manifest, args.output, args.split))
            elif args.command == "pilot-init":
                print(pilot.initialize(args.manifest, args.configs, args.seeds, args.output, args.split))
            elif args.command == "pilot-run":
                return (
                    1 if pilot.run(args.experiment, args.name, args.resume, args.timeout, args.limit) else 0
                )
            elif args.command == "pilot-evaluate":
                return 1 if pilot.evaluate(args.experiment, args.config, args.transforms) else 0
            elif args.command == "pilot-render":
                return 1 if pilot.render_all(args.experiment, args.blender, args.views) else 0
            elif args.command == "pilot-report":
                print(json.dumps(pilot.report(args.experiment, args.output), indent=2))
        elif args.command == "doctor":
            result = doctor(args.gpu, args.backend)
            if args.output:
                save_json(args.output, result)
            print(json.dumps(result, indent=2))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
