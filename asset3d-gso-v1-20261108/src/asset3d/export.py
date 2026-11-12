import os
from pathlib import Path

import numpy as np
import trimesh

from .mesh_ops import validate_mesh


def has_texture(mesh):
    visual = mesh.visual
    # UV 把三维表面映射到二维贴图；同时检查坐标和颜色贴图是否齐全。
    uv = getattr(visual, "uv", None)
    if uv is None or len(uv) != len(mesh.vertices) or not np.isfinite(uv).all():
        return False
    material = getattr(visual, "material", None)
    texture = getattr(material, "baseColorTexture", None)
    if texture is None:
        texture = getattr(material, "image", None)
    return texture is not None and min(texture.size) > 0


def check_glb(path, require_texture=True):
    # 重新打开导出的文件，检查真实保存下来的网格及内嵌贴图。
    scene = trimesh.load(Path(path), force="scene", process=False)
    if not scene.geometry:
        raise ValueError("Exported GLB contains no geometry")
    checks = []
    for mesh in scene.geometry.values():
        check = validate_mesh(mesh)
        check["has_texture"] = has_texture(mesh)
        if require_texture and not check["has_texture"]:
            raise ValueError("GLB is missing UV coordinates or an embedded color texture")
        checks.append(check)
    return {"meshes": checks, "file_bytes": Path(path).stat().st_size}


def export_glb(mesh, path, require_texture=True):
    validate_mesh(mesh)
    if require_texture and not has_texture(mesh):
        raise ValueError("Texture generation did not produce a textured mesh")
    path = Path(path)
    # 先写临时文件并验证，再替换正式文件，避免失败时留下半成品 GLB。
    temp = path.with_name(path.stem + ".tmp.glb")
    try:
        temp.write_bytes(mesh.export(file_type="glb"))
        report = check_glb(temp, require_texture)
        os.replace(temp, path)
        return report
    finally:
        temp.unlink(missing_ok=True)
