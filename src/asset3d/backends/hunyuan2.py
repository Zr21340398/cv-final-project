"""Adapter for the pinned upstream 2.0 APIs; no fabricated GPU fallback."""

import os
import subprocess
import time
from pathlib import Path


def snapshot(model, download=False):
    from huggingface_hub import snapshot_download

    # 按固定版本下载形状、上色和去光照权重；正式作业从本地缓存读取。
    return snapshot_download(
        repo_id=model["repo_id"],
        revision=model["revision"],
        local_files_only=not download,
        allow_patterns=[
            f"{model['shape_subfolder']}/*",
            f"{model['texture_subfolder']}/*",
            "hunyuan3d-delight-v2-0/*",
            "LICENSE*",
            "NOTICE*",
        ],
    )


class HunyuanBackend:
    def __init__(self, config):
        self.config = config
        self.shape = None
        self.paint = None
        self.remover = None
        self.background_sha256 = None
        self.root = None

    def begin(self):
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU is required. On HPC4, request a gpu-l20 compute node first.")
        import hy3dgen

        source = Path(hy3dgen.__file__).resolve().parent.parent
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != self.config["model"]["code_revision"]:
            raise RuntimeError(f"Upstream code revision mismatch: {actual}. Run scripts/install_hpc.sh.")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True
        ).strip():
            raise RuntimeError(
                "Upstream tracked files were modified; restore or explicitly version changes first."
            )
        if self.root is None:
            self.root = snapshot(self.config["model"], download=not self.config["model"]["local_files_only"])
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        return {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "code_revision": actual,
            "weights_revision": self.config["model"]["revision"],
            "texture_multiview_seed": 0,
            "texture_delight_seed": 42,
            "texture_steps": 30,
        }

    def remove_background(self, image):
        if self.remover is None:
            cache = Path(os.environ.get("U2NET_HOME", "~/.u2net")).expanduser() / "u2net.onnx"
            if self.config["model"]["local_files_only"] and not cache.is_file():
                raise RuntimeError("Background model is not cached. Run asset3d download --background first.")
            from hy3dgen.rembg import BackgroundRemover

            from ..recording import file_hash

            self.remover = BackgroundRemover()
            if cache.is_file():
                self.background_sha256 = file_hash(cache)
        return self.remover(image)

    def load_shape(self):
        start = time.perf_counter()
        cold = self.shape is None
        if cold:
            import torch
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

            # 加载预训练的形状模型；fp16 用半精度数值减少 GPU 内存占用。
            self.shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                self.root,
                subfolder=self.config["model"]["shape_subfolder"],
                use_safetensors=True,
                variant="fp16",
                device="cuda",
                dtype=torch.float16,
            )
        self.synchronize()
        return {"cold": cold, "seconds": time.perf_counter() - start}

    def generate_shape(self, image, seed):
        import torch

        # 单张图片提供外观线索；形状模型结合训练时学到的规律推测完整三维物体。
        # steps 控制迭代次数，octree_resolution 控制提取表面时的空间分辨率。
        c = self.config["shape"]
        with torch.inference_mode():
            return self.shape(
                image=image,
                num_inference_steps=c["steps"],
                guidance_scale=c["guidance_scale"],
                octree_resolution=c["octree_resolution"],
                num_chunks=c["num_chunks"],
                # 固定初始随机数便于复现；预实验用多个种子观察生成结果的变化。
                generator=torch.Generator(device="cuda").manual_seed(seed),
                output_type="trimesh",
            )[0]

    def load_texture(self):
        start = time.perf_counter()
        cold = self.paint is None
        if cold:
            from hy3dgen.texgen.pipelines import Hunyuan3DPaintPipeline, Hunyuan3DTexGenConfig

            c = self.config["model"]
            # 上色阶段同时使用去光照模型和纹理生成模型，并单独设置渲染、贴图尺寸。
            texture_config = Hunyuan3DTexGenConfig(
                str(Path(self.root) / "hunyuan3d-delight-v2-0"),
                str(Path(self.root) / c["texture_subfolder"]),
                c["texture_subfolder"],
            )
            texture_config.render_size = self.config["texture"]["render_size"]
            texture_config.texture_size = self.config["texture"]["texture_size"]
            self.paint = Hunyuan3DPaintPipeline(texture_config)
        self.synchronize()
        return {"cold": cold, "seconds": time.perf_counter() - start}

    def generate_texture(self, mesh, image):
        import torch

        # 输入是已生成的白模和原图；官方 Paint 流程通过多个视角为表面生成并融合颜色。
        # 官方去光照种子固定为 42，多视角种子固定为 0；本实验变化的是形状种子。
        with torch.inference_mode():
            return self.paint(mesh, image=image)

    def synchronize(self):
        import torch

        torch.cuda.synchronize()

    def resources(self):
        import torch

        return {
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "background_model_sha256": self.background_sha256,
            "note": "PyTorch allocator metrics; not total driver-visible GPU memory",
        }
