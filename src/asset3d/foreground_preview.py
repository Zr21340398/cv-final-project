"""Immutable images shared by the single-photo preview and confirmed generation."""

import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .preprocess import prepare_image
from .recording import file_hash, object_hash, save_json


def validate_foreground(image):
    if image.mode != "RGBA":
        raise ValueError("前景图片必须包含透明通道")
    alpha = np.asarray(image.getchannel("A"))
    visible = np.argwhere(alpha > 204)
    if not len(visible):
        raise ValueError("未识别出前景，请重新选图")
    # The pinned official crop uses max - min, rather than an inclusive extent.
    if max(np.ptp(visible[:, 0]), np.ptp(visible[:, 1])) < 2:
        raise ValueError("识别出的前景太小，请重新选图")
    if alpha.min() == 255:
        raise ValueError("前景图片没有透明背景，请重新选图")


def read_prepared(paths, expected=None):
    if not isinstance(paths, dict) or set(paths) != {"foreground", "model_input"}:
        raise ValueError("Prepared input requires foreground and model_input")
    contents, images = {}, {}
    for key, path in paths.items():
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected[key + "_sha256"]:
            raise ValueError("已确认的前景图片发生变化，请重新预览")
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != ("RGBA" if key == "foreground" else "RGB"):
                raise ValueError("前景预览格式无效，请重新预览")
            if min(opened.size) < 2 or max(opened.size) > 2048:
                raise ValueError("前景预览尺寸无效，请重新预览")
            images[key] = opened.copy()
        contents[key] = data
    validate_foreground(images["foreground"])
    return contents, images


def single_request(job):
    spec = json.loads((Path(job) / "request.json").read_text(encoding="utf-8"))
    from .job_spec import validate

    validate(spec)
    if (spec["images"] != ["input.png"] or len(spec["seeds"]) != 1
            or len(spec["variants"]) != 1 or "dataset" in spec):
        raise ValueError("前景确认仅适用于单张图片任务")
    return spec


def prepared_paths(job):
    root = Path(job) / "prepared"
    return {"foreground": root / "foreground.png", "model_input": root / "model_input.png"}


def validate_preview(job, config, confirmed_hash):
    job = Path(job)
    single_request(job)
    if not isinstance(confirmed_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", confirmed_hash):
        raise ValueError("缺少有效的前景确认记录")
    data = (job / "preview.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != confirmed_hash:
        raise ValueError("前景确认记录发生变化，请重新预览")
    record = json.loads(data)
    expected = {
        "schema_version": 1,
        "input_sha256": file_hash(job / "inputs/input.png"),
        "request_sha256": file_hash(job / "request.json"),
        "config_sha256": object_hash(config),
    }
    if (set(record) != set(expected) | {"foreground_sha256", "model_input_sha256"}
            or any(record.get(key) != value for key, value in expected.items())):
        raise ValueError("原图或生成设置发生变化，请重新预览")
    paths = prepared_paths(job)
    read_prepared(paths, record)
    return paths


def prepare_preview(job, config, backend):
    """Run only masking and image preparation; never call a 3D generation method."""
    job = Path(job)
    single_request(job)
    lock = job / ".preview.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError("前景预览正在处理中") from error
    os.close(fd)
    try:
        if (job / "preview.json").is_file():
            validate_preview(job, config, file_hash(job / "preview.json"))
            return
        source = job / "inputs/input.png"
        record = {"schema_version": 1, "input_sha256": file_hash(source),
                  "request_sha256": file_hash(job / "request.json"),
                  "config_sha256": object_hash(config)}
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        if min(image.size) < 32:
            raise ValueError("图片每边至少需要 32 像素")
        image.info.clear()  # The orientation has already been applied.
        image.thumbnail((2048, 2048))
        backend.begin()
        backend.load_shape()
        masked = backend.prepare_foreground(image)
        validate_foreground(masked)
        paths = prepared_paths(job)
        paths["foreground"].parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".foreground-", dir=paths["foreground"].parent) as temp:
            masked_path = Path(temp) / "masked.png"
            masked.info.clear()
            masked.save(masked_path)
            foreground = prepare_image(masked_path, config["preprocess"])
        validate_foreground(foreground)
        model_input = backend.prepare_model_input(foreground)
        if model_input.mode != "RGB" or min(model_input.size) < 2:
            raise ValueError("模型输入为空，请重新选图")
        for key, image in (("foreground", foreground), ("model_input", model_input)):
            image.info.clear()
            image.save(paths[key])
            record[key + "_sha256"] = file_hash(paths[key])
        if (file_hash(source) != record["input_sha256"]
                or file_hash(job / "request.json") != record["request_sha256"]):
            raise ValueError("原图或设置在预览过程中发生变化，请重新选图")
        read_prepared(paths, record)
        save_json(job / "preview.json", record)
    finally:
        lock.unlink(missing_ok=True)
