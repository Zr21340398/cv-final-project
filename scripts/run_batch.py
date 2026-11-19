"""从批次配置选择共享数据并运行；--prepare-only 可在 CPU 上提前检查。"""
import argparse
from pathlib import Path

import yaml

from asset3d.batch_definition import prepare_batch
from asset3d.config import load_config
from asset3d.experiments import run_experiments

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("definition", help="例如 experiments/trellis2-gso-dev-v1/batch.yaml")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--backend", choices=["trellis2", "hunyuan2"], help="限制本作业使用的模型后端")
    args = parser.parse_args()
    definition = Path(args.definition).resolve()
    spec = yaml.safe_load(definition.read_text(encoding="utf-8"))
    if spec.get("archived"):
        from asset3d.archive import verify_archive
        from asset3d.viewer_manifest import write_viewer_manifest

        results = definition.parent / "results"
        count = verify_archive(results)
        root = Path(__file__).resolve().parents[1]
        references = root / "datasets/gso-v1/data/rendered/gso-formal-v1"
        write_viewer_manifest(results, results / "viewer-manifest.json", references, overwrite=True)
        print(f"历史批次核验完成：{count} 次运行；viewer 预设已更新。")
        raise SystemExit(0)
    selection, configs, seeds, output, split = prepare_batch(args.definition, Path(__file__).resolve().parents[1])
    if args.backend and any(load_config(c).get("backend", "hunyuan2") != args.backend for c in configs):
        raise SystemExit("批次模型与当前作业环境不匹配")
    print(f"批次准备完成：{output.parent}；配置数 {len(configs)}，种子 {seeds}", flush=True)
    if not args.prepare_only:
        raise SystemExit(1 if run_experiments(selection, configs, seeds, output, split, resume=True) else 0)
