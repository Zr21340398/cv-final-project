import argparse
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .pipeline import Pipeline


def build_app(config_dir="configs", results="results/demo"):
    import gradio as gr

    config_dir, results = Path(config_dir), Path(results).resolve()
    configs = {name: load_config(config_dir / f"{name}.yaml") for name in ("baseline", "medium", "fast")}
    comparable = []
    for config in configs.values():
        shared = deepcopy(config)
        shared.pop("name")
        shared["shape"].pop("steps")
        comparable.append(shared)
    if any(c != comparable[0] for c in comparable[1:]):
        raise ValueError("UI modes must differ only in name and shape steps to share loaded models")
    # Share model weights across modes; only shape steps differ. All callbacks run serially.
    pipeline = Pipeline(configs["baseline"])

    def generate(image, mode, seed, progress=gr.Progress()):
        if image is None:
            raise gr.Error("请先上传一张物体图片。")
        progress(0.05, desc="正在准备图片与模型；首次加载可能较慢")
        seed = int(seed)
        run = results / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        pipeline.config = configs[mode]
        pipeline.backend.config = configs[mode]
        try:
            asset = pipeline.run(image, run, seed=seed)
        except Exception as exc:
            raise gr.Error(f"生成失败：{exc}。运行记录：{run}") from exc
        progress(1, desc="生成完成")
        return str(asset), str(asset), f"已生成带纹理模型。运行记录：{run.name}"

    with gr.Blocks(title="单图 3D 资产生成", analytics_enabled=False) as app:
        gr.Markdown("# 单图 3D 资产生成\n上传一个清晰、完整的物体。背面由模型推测，结果不代表精确扫描。")
        with gr.Row():
            with gr.Column():
                picture = gr.Image(type="filepath", image_mode="RGBA", label="物体图片")
                mode = gr.Dropdown(
                    choices=[
                        ("标准 · 50 步", "baseline"),
                        ("中等 · 30 步", "medium"),
                        ("快速 · 20 步", "fast"),
                    ],
                    value="baseline",
                    label="生成模式",
                )
                seed = gr.Number(value=42, minimum=0, maximum=2**32 - 1, precision=0, label="随机种子")
                button = gr.Button("生成 3D 模型", variant="primary")
            with gr.Column():
                preview = gr.Model3D(label="拖动旋转查看")
                download = gr.File(label="下载 GLB")
                status = gr.Textbox(label="状态", interactive=False)
        button.click(
            generate,
            inputs=[picture, mode, seed],
            outputs=[preview, download, status],
            concurrency_limit=1,
            concurrency_id="gpu",
        )
    return app.queue(default_concurrency_limit=1, max_size=8)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--results", default="results/demo")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    build_app(args.config_dir, args.results).launch(
        server_name="127.0.0.1", server_port=args.port, share=False
    )


if __name__ == "__main__":
    main()
