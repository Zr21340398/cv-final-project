import math
import re
from copy import deepcopy
from pathlib import Path

import yaml


def merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        result[key] = (
            merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else value
        )
    return result


def load_config(path, _seen=None):
    path = Path(path).resolve()
    seen = set() if _seen is None else set(_seen)
    if path in seen:
        raise ValueError(f"Circular config inheritance: {path}")
    seen.add(path)
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError("Config must be a mapping")
    parent = config.pop("extends", None)
    if parent:
        config = merge(load_config(path.parent / parent, seen), config)
    validate(config)
    return config


def validate(c):
    if c.get("backend") == "trellis2":
        from .backends.trellis2 import validate_config

        validate_config(c)
        return
    expected = {
        "model": {
            "repo_id",
            "revision",
            "code_revision",
            "shape_subfolder",
            "texture_subfolder",
            "local_files_only",
        },
        "preprocess": {"background", "size", "padding"},
        "shape": {"steps", "guidance_scale", "octree_resolution", "num_chunks"},
        "texture": {"enabled", "render_size", "texture_size"},
    }
    if set(c) != {"name", *expected}:
        raise ValueError("Config must contain name, model, preprocess, shape, texture only")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(c["name"])):
        raise ValueError("Invalid configuration name")
    for section, keys in expected.items():
        if not isinstance(c[section], dict) or set(c[section]) != keys:
            raise ValueError(f"Invalid keys in {section}; expected {sorted(keys)}")
    for key in ("revision", "code_revision"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(c["model"][key])):
            raise ValueError(f"model.{key} must be a full commit SHA")
    for section, key in [
        ("preprocess", "size"),
        ("shape", "steps"),
        ("shape", "octree_resolution"),
        ("shape", "num_chunks"),
        ("texture", "render_size"),
        ("texture", "texture_size"),
    ]:
        value = c[section][key]
        if type(value) is not int or value < 1:
            raise ValueError(f"{section}.{key} must be a positive integer")
    if c["preprocess"]["background"] not in ("auto", "remove", "keep"):
        raise ValueError("background must be auto, remove or keep")
    if not 0 <= c["preprocess"]["padding"] <= 1:
        raise ValueError("padding must be in [0, 1]")
    if not math.isfinite(c["shape"]["guidance_scale"]):
        raise ValueError("guidance_scale must be finite")
    if type(c["texture"]["enabled"]) is not bool or type(c["model"]["local_files_only"]) is not bool:
        raise ValueError("enabled and local_files_only must be booleans")
