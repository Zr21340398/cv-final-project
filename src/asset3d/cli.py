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
                    args.manifest, args.configs, args.seeds, args.output, args.split, args.resume
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
            root = Path(args.experiment)
            plan = json.loads((root / "experiment.json").read_text(encoding="utf-8"))["plan"]
            errors = []
            for c in plan["configs"]:
                for obj in plan["objects"]:
                    if not obj["reference"]:
                        continue
                    for seed in plan["seeds"]:
                        run = root / c["name"] / obj["id"] / f"seed-{seed}"
                        if not (run / "manifest.json").exists():
                            continue
                        m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                        if m["status"] != "completed":
                            continue
                        try:
                            evaluate_one(
                                run / "shape_raw.glb",
                                obj["reference"],
                                args.config,
                                run / "metrics.json",
                                args.transform,
                            )
                        except Exception as exc:
                            errors.append({"run": str(run), "error": str(exc)})
            save_json(root / "evaluation-errors.json", errors)
            return 1 if errors else 0
        elif args.command == "summarize":
            from .evaluation.summarize import summarize

            print(json.dumps(summarize(args.experiment, args.output), indent=2))
        elif args.command == "render":
            from .render import render_mesh

            render_mesh(args.mesh, args.output, args.blender, args.views, args.resolution, clay=args.clay)
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
