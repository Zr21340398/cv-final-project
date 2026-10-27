"""Pinned official TRELLIS.2 inference and native PBR export."""

import json
import os
import re
import subprocess
import time
from pathlib import Path

from ..recording import object_hash, save_json


def validate_config(c):
    if set(c) != {"name", "backend", "model", "preprocess", "generation", "texture"}:
        raise ValueError("Invalid TRELLIS.2 configuration keys")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(c["name"])):
        raise ValueError("Invalid configuration name")
    if set(c["model"]) != {"repo_id", "revision", "code_revision", "local_files_only", "auxiliary"}:
        raise ValueError("Invalid model keys")
    if set(c["model"]["auxiliary"]) != {"sparse_decoder", "image_encoder", "background"}:
        raise ValueError("Missing pinned auxiliary models")
    pins = [c["model"]["revision"], c["model"]["code_revision"]]
    for dep in c["model"]["auxiliary"].values():
        if set(dep) != {"repo_id", "revision"}:
            raise ValueError("Auxiliary model requires repo_id and revision")
        pins.append(dep["revision"])
    if any(not re.fullmatch(r"[0-9a-f]{40}", str(pin)) for pin in pins):
        raise ValueError("All revisions must be full commit SHAs")
    if set(c["preprocess"]) != {"background", "size", "padding"}:
        raise ValueError("Invalid preprocessing keys")
    if c["preprocess"]["background"] != "keep":
        raise ValueError("Use shared foreground PNGs from pilot-prepare")
    if not 0 <= c["preprocess"]["padding"] <= 1:
        raise ValueError("padding must be in [0,1]")
    if set(c["generation"]) != {"pipeline_type", "max_num_tokens", "low_vram"}:
        raise ValueError("Invalid generation keys")
    if c["generation"]["pipeline_type"] not in ("512", "1024", "1024_cascade", "1536_cascade"):
        raise ValueError("Invalid pipeline_type")
    if set(c["texture"]) != {"enabled", "texture_size", "decimation_target", "remesh"}:
        raise ValueError("Invalid texture keys")
    if c["texture"]["enabled"] is not True:
        raise ValueError("TRELLIS.2 pilot uses full native shape+material generation")
    for v in (c["model"]["local_files_only"], c["generation"]["low_vram"], c["texture"]["remesh"]):
        if type(v) is not bool:
            raise ValueError("Expected boolean setting")
    for v in (
        c["preprocess"]["size"],
        c["generation"]["max_num_tokens"],
        c["texture"]["texture_size"],
        c["texture"]["decimation_target"],
    ):
        if type(v) is not int or v < 1:
            raise ValueError("Size/token/face limits must be positive integers")


def localize_pipeline(config, bundle, roots):
    """Upstream prepends bundle to checkpoint paths; resolve all pinned weights locally."""
    # 将官方配置里的模型名称替换为已下载的固定版本路径，供计算节点离线读取。
    config = json.loads(json.dumps(config))
    args = config["args"]
    external = "microsoft/TRELLIS-image-large/"
    for name, value in args["models"].items():
        if value.startswith(external):
            target = Path(roots["sparse_decoder"]) / value[len(external) :]
        elif value.startswith("ckpts/"):
            target = Path(roots["main"]) / value
        else:
            raise ValueError(f"Unrecognized checkpoint: {value}")
        args["models"][name] = os.path.relpath(target, bundle).replace(os.sep, "/")
    args["image_cond_model"]["args"]["model_name"] = str(Path(roots["image_encoder"]).resolve())
    args["rembg_model"]["args"]["model_name"] = str(Path(roots["background"]).resolve())
    return config


def snapshot(model, download=False):
    from huggingface_hub import snapshot_download

    def fetch(dep, patterns):
        return snapshot_download(
            repo_id=dep["repo_id"],
            revision=dep["revision"],
            local_files_only=not download,
            allow_patterns=patterns,
        )

    # 主生成模型之外，还需稀疏结构解码器、图片特征编码器和背景处理模型。
    roots = {"main": fetch(model, ["pipeline.json", "ckpts/*", "LICENSE*", "README.md"])}
    for key, dep in model["auxiliary"].items():
        patterns = (
            ["ckpts/ss_dec_conv3d_16l8_fp16.*", "LICENSE*"]
            if key == "sparse_decoder"
            else ["*.json", "*.safetensors", "*.py", "*.txt", "LICENSE*", "README.md"]
        )
        roots[key] = fetch(dep, patterns)
    cache = Path(os.environ.get("ASSET3D_MODEL_CACHE", os.environ.get("HF_HOME", "~/.cache/huggingface")))
    bundle = cache.expanduser().resolve() / "asset3d-bundles" / object_hash(model)
    bundle.mkdir(parents=True, exist_ok=True)
    original = json.loads((Path(roots["main"]) / "pipeline.json").read_text(encoding="utf-8"))
    save_json(bundle / "pipeline.json", localize_pipeline(original, bundle, roots))
    save_json(bundle / "sources.json", {"model": model, "roots": roots})
    return str(bundle)


class TrellisBackend:
    # 官方流程依次生成形状与材质；本适配器把这整段计为 native_shape_material。
    joint_generation = True
    generation_stage = "native_shape_material"
    texture_stage = "pbr_bake"

    def __init__(self, config):
        self.config = config
        self.pipeline = None
        self.native = None

    def begin(self):
        os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        import torch
        import trellis2

        if not torch.cuda.is_available():
            raise RuntimeError("TRELLIS.2 requires a CUDA compute node")
        source = Path(trellis2.__file__).resolve().parent.parent
        # 固定官方代码版本，让不同作业使用相同的实现。
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != self.config["model"]["code_revision"]:
            raise RuntimeError(f"TRELLIS.2 code revision mismatch: {actual}")
        if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True
        ).strip():
            raise RuntimeError("TRELLIS.2 tracked files were modified")
        self.root = snapshot(self.config["model"], download=not self.config["model"]["local_files_only"])
        self.native = None
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        return {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "code_revision": actual,
            "weights_revision": self.config["model"]["revision"],
            "auxiliary": self.config["model"]["auxiliary"],
            "geometry_coordinates": "GLB axes: native (x,y,z) -> (x,z,-y)",
            "timing_note": "native_shape_material includes geometry AND material inference",
        }

    def remove_background(self, image):
        raise RuntimeError("Use pilot-prepare for shared foreground inputs")

    def load_shape(self):
        start = time.perf_counter()
        cold = self.pipeline is None
        if cold:
            from trellis2.pipelines import Trellis2ImageTo3DPipeline

            # 载入别人训练好的权重，再放到 GPU；本项目执行推理，无需重新训练模型。
            self.pipeline = Trellis2ImageTo3DPipeline.from_pretrained(self.root)
            self.pipeline.low_vram = self.config["generation"]["low_vram"]
            self.pipeline.cuda()
        self.synchronize()
        return {"cold": cold, "seconds": time.perf_counter() - start}

    def generate_shape(self, image, seed):
        import numpy as np
        import torch
        import trimesh

        if image.mode != "RGBA" or np.asarray(image.getchannel("A")).min() == 255:
            raise ValueError("Provide a transparent foreground PNG from pilot-prepare")
        c = self.config["generation"]
        # 官方 run 内部提取图片特征，生成稀疏空间布局，再生成并解码形状、材质表示。
        # native 同时保留几何和材质数据，后面的 GLB 导出会继续使用这些信息。
        with torch.inference_mode():
            self.native = self.pipeline.run(
                image,
                seed=seed,
                num_samples=1,
                preprocess_image=True,
                pipeline_type=c["pipeline_type"],
                max_num_tokens=c["max_num_tokens"],
            )[0]
        # 先取出顶点和三角面保存白模，保留导出简化、重建网格之前的几何结果。
        vertices = self.native.vertices.detach().cpu().numpy().copy()
        # 与官方 GLB 导出采用同一坐标方向：(x,y,z) 转为 (x,z,-y)。
        vertices = vertices[:, [0, 2, 1]]
        vertices[:, 2] *= -1
        return trimesh.Trimesh(
            vertices=vertices, faces=self.native.faces.detach().cpu().numpy(), process=False
        )

    def load_texture(self):
        # 材质已在 run 中生成，这一步直接进入后续烘焙，无需再加载上色模型。
        return {"cold": False, "seconds": 0.0}

    def generate_texture(self, mesh, image):
        import o_voxel
        import torch

        if self.native is None:
            raise RuntimeError("Native material state missing; restart TRELLIS.2 generation")
        c, native = self.config["texture"], self.native
        with torch.inference_mode():
            # 原始白模已保存；这里先满足官方光栅化器的面数上限。
            native.simplify(16777216)
            # 烘焙把空间中的材质属性转换成网格贴图，连同 UV 对应关系封装进 GLB。
            # UV 描述三维表面各位置应读取贴图的哪个位置。
            return o_voxel.postprocess.to_glb(
                vertices=native.vertices,
                faces=native.faces,
                attr_volume=native.attrs,
                coords=native.coords,
                attr_layout=native.layout,
                voxel_size=native.voxel_size,
                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                decimation_target=c["decimation_target"],
                texture_size=c["texture_size"],
                remesh=c["remesh"],
                remesh_band=1,
                remesh_project=0,
                verbose=True,
            )

    def synchronize(self):
        import torch

        torch.cuda.synchronize()

    def resources(self):
        import torch

        return {
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "note": "PyTorch allocator only; native CUDA allocations may be additional",
        }
