"""Offline, prompted object segmentation for the single-photo review workflow.

Prompt coordinates refer to the EXIF-oriented image, before foreground cropping.
Keep module imports stdlib-only: the local web server validates selections without
installing the remote inference environment.
"""

import gc
import hashlib
import math
import os
import subprocess
import sys
from pathlib import Path

SAM2_CODE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_CHECKPOINT_REVISION = "de431c4043854a71d8101e17995dfe596bf101a5"
SAM2_CHECKPOINT_SHA256 = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
SAM2_CHECKPOINT_SIZE = 156_008_466
SAM2_CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"
SAM2_CHECKPOINT_URL = (
    "https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/"
    + SAM2_CHECKPOINT_REVISION
    + "/sam2.1_hiera_tiny.pt"
)


def _unit(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("主体选择坐标必须是 0 到 1 之间的数字")
    try:
        value = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("主体选择坐标无效") from error
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("主体选择坐标必须是 0 到 1 之间的有限数字")
    return value


def validate_selection(value):
    """Validate a normalized box and optional positive/negative image points."""
    if not isinstance(value, dict) or set(value) - {"box", "include_points", "exclude_points"}:
        raise ValueError("主体选择格式无效或包含未知字段")
    box = value.get("box")
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("请用矩形框选要保留的主体")
    box = [_unit(v) for v in box]
    if box[2] - box[0] < 0.02 - 1e-12 or box[3] - box[1] < 0.02 - 1e-12:
        raise ValueError("主体框的宽和高至少应占图片的 2%")
    result = {"box": box}
    for name in ("include_points", "exclude_points"):
        points = value.get(name, [])
        if not isinstance(points, list) or len(points) > 16:
            raise ValueError("保留点和排除点分别最多为 16 个")
        clean = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("每个主体选择点必须包含两个坐标")
            clean.append([_unit(v) for v in point])
        result[name] = clean
    return result


def _verify_code(root):
    root = Path(root).resolve()
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(root), *args],
                text=True,
                stderr=subprocess.PIPE,
                timeout=15,
                env=env,
            ).strip()

        if git("rev-parse", "HEAD") != SAM2_CODE_REVISION:
            raise RuntimeError("SAM 2.1 源码版本不匹配，请安装固定版本后重试")
        if git("status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("SAM 2.1 源码已被修改，无法生成可复核的前景")
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("无法核验 SAM 2.1 源码，请检查离线安装目录") from error
    return root


def _verify_checkpoint():
    configured = os.environ.get("ASSET3D_SAM2_CHECKPOINT")
    if not configured:
        raise RuntimeError("未配置 SAM 2.1 离线权重；请设置 ASSET3D_SAM2_CHECKPOINT")
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or path.stat().st_size != SAM2_CHECKPOINT_SIZE:
        raise RuntimeError("SAM 2.1 离线权重缺失或不完整")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SAM2_CHECKPOINT_SHA256:
        raise RuntimeError("SAM 2.1 离线权重 SHA256 校验失败")
    return path


def _load_predictor():
    """Load only the pinned local source and checkpoint, without hub/network calls."""
    checkpoint = _verify_checkpoint()
    configured = os.environ.get("ASSET3D_SAM2_CODE_DIR")
    root = _verify_code(Path(configured).expanduser()) if configured else None
    if root is not None:
        sys.path.insert(0, str(root))
    try:
        try:
            import sam2
        except ImportError as error:
            raise RuntimeError("未安装 SAM 2.1，请先准备离线主体分割环境") from error
        actual = Path(sam2.__file__).resolve().parent.parent
        if root is not None and actual != root:
            raise RuntimeError("SAM 2.1 实际导入路径与配置目录不一致，请重启并检查环境")
        _verify_code(actual)
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        # Optional CUDA connected-component kernels are deliberately unnecessary.
        # Keep the model's discrete candidates; never fill holes or remove parts
        # automatically before the user checks the visible object boundary.
        model = build_sam2(SAM2_CONFIG, str(checkpoint), device="cuda", apply_postprocessing=False)
        return SAM2ImagePredictor(model, max_hole_area=0.0, max_sprinkle_area=0.0)
    finally:
        if root is not None:
            sys.path.remove(str(root))


def _predict_masks(rgb, box, points, labels):
    import numpy as np
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("主体精修需要 CUDA GPU，不会回退到 CPU 或自动联网下载")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("主体精修需要支持 BF16 的 CUDA GPU")
    predictor = None
    try:
        predictor = _load_predictor()
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            # PIL's array view can be read-only; torchvision converts this array
            # to a tensor, so provide owned, writable storage explicitly.
            predictor.set_image(np.array(rgb, copy=True))
            masks, scores, _ = predictor.predict(
                box=np.asarray(box, dtype=np.float32),
                point_coords=np.asarray(points, dtype=np.float32) if points else None,
                point_labels=np.asarray(labels, dtype=np.int32) if labels else None,
                multimask_output=True,
            )
        return np.asarray(masks).copy(), np.asarray(scores).copy()
    finally:
        if predictor is not None:
            predictor.reset_predictor()
        del predictor
        gc.collect()
        torch.cuda.empty_cache()


def segment_target(image, selection):
    """Return original visible RGB pixels with the selected object's alpha mask.

    This is visible-object segmentation: it does not synthesize pixels hidden by
    a hand or another occluder, and does not certify that the result is QA-ready.
    """
    import numpy as np
    from PIL import Image

    selection = validate_selection(selection)
    if image.mode != "RGBA" or min(image.size) < 32:
        raise ValueError("主体精修需要已经转正、每边至少 32 像素的 RGBA 原图")
    width, height = image.size
    scale = (width - 1, height - 1)
    box = [value * scale[i % 2] for i, value in enumerate(selection["box"])]
    point_groups = [selection["include_points"], selection["exclude_points"]]
    points = [[x * scale[0], y * scale[1]] for group in point_groups for x, y in group]
    labels = [1] * len(point_groups[0]) + [0] * len(point_groups[1])
    masks, scores = _predict_masks(image.convert("RGB"), box, points, labels)
    masks, scores = np.asarray(masks), np.asarray(scores)
    if masks.ndim != 3 or masks.shape[1:] != (height, width) or scores.shape != (len(masks),):
        raise RuntimeError("主体分割结果尺寸异常，请重新预览")
    if masks.dtype.kind not in "bufi" or not np.isfinite(masks).all() or not np.isin(masks, [0, 1]).all():
        raise RuntimeError("主体分割结果不是有效的离散蒙版")
    if scores.dtype.kind not in "ufi":
        raise RuntimeError("主体分割质量分数无效")
    source_alpha = np.asarray(image.getchannel("A"))
    best = None
    for index, (candidate, score) in enumerate(zip(masks, scores)):
        if not np.isfinite(score):
            continue
        visible = np.asarray(candidate, dtype=bool) & (source_alpha > 204)
        if not visible.any() or visible.all():
            continue
        if any(bool(visible[round(y), round(x)]) != bool(label) for (x, y), label in zip(points, labels)):
            continue
        if best is None or float(score) > best[0]:
            best = (float(score), index, np.asarray(candidate, dtype=bool))
    if best is None:
        raise ValueError("未找到满足保留点和排除点的主体，请调整框选或标记后重新预览")
    score, index, mask = best
    alpha = np.where(mask, source_alpha, 0).astype(np.uint8)
    result = image.convert("RGB").convert("RGBA")
    result.putalpha(Image.fromarray(alpha))
    result.info.clear()
    metadata = {
        "method": "sam2.1-target",
        "code_revision": SAM2_CODE_REVISION,
        "checkpoint_revision": SAM2_CHECKPOINT_REVISION,
        "checkpoint_sha256": SAM2_CHECKPOINT_SHA256,
        "model_config": SAM2_CONFIG,
        "selection": selection,
        "image_size": [width, height],
        "candidate_index": index,
        "predicted_mask_score": score,
        "foreground_pixels": int((alpha > 204).sum()),
        "quality_review_required": True,
    }
    return result, metadata
