"""Conservative cleanup of hallucinated color on large, nearly planar surfaces."""

from copy import deepcopy

import numpy as np
from PIL import Image, ImageDraw


def _color_image(mesh):
    material = getattr(mesh.visual, "material", None)
    if material is None:
        return None, None
    for name in ("baseColorTexture", "image"):
        value = getattr(material, name, None)
        if value is not None:
            return name, value
    return None, None


def _flat_input(image):
    sample = np.asarray(image.convert("RGBA").resize((256, 256)))
    colors = sample[sample[:, :, 3] >= 240, :3].astype(np.float32)
    if len(colors) < 256:
        return False, None
    center = np.median(colors, axis=0)
    spread = float(np.percentile(np.max(np.abs(colors - center), axis=1), 99))
    return spread <= 24, spread


def _planar_components(mesh):
    normals = mesh.face_normals
    centers = mesh.triangles_center
    neighbors = [[] for _ in mesh.faces]
    for a, b in mesh.face_adjacency:
        neighbors[a].append(b)
        neighbors[b].append(a)
    visited = np.zeros(len(mesh.faces), dtype=bool)
    distance = max(float(np.linalg.norm(mesh.extents)) * 0.002, 1e-6)
    cosine = np.cos(np.deg2rad(6))
    for seed in range(len(mesh.faces)):
        if visited[seed]:
            continue
        visited[seed] = True
        group = [seed]
        for face in group:
            for other in neighbors[face]:
                if visited[other]:
                    continue
                if np.dot(normals[seed], normals[other]) < cosine:
                    continue
                if abs(np.dot(centers[other] - centers[seed], normals[seed])) > distance:
                    continue
                visited[other] = True
                group.append(other)
        yield group


def clean_planar_texture(mesh, source_image):
    """Return (mesh, report); change only noisy planes on a nearly solid-color input.

    This deliberately skips patterned source images: a single view cannot prove that
    a pattern on an unseen face is an error. The original mesh is never mutated.
    """
    report = {"applied": False, "reason": None, "regions": []}
    flat, spread = _flat_input(source_image)
    report["input_color_spread"] = spread
    if not flat:
        report["reason"] = "input_has_pattern_or_insufficient_foreground"
        return mesh, report
    name, texture = _color_image(mesh)
    uv = getattr(mesh.visual, "uv", None)
    if name is None or uv is None or len(uv) != len(mesh.vertices) or not np.isfinite(uv).all():
        report["reason"] = "missing_uv_or_color_texture"
        return mesh, report
    if np.min(uv) < 0 or np.max(uv) > 1:
        report["reason"] = "uv_outside_atlas"
        return mesh, report
    original_image = np.asarray(texture)
    atlas = np.asarray(texture.convert("RGB")).copy()
    height, width = atlas.shape[:2]
    cleaned = atlas.copy()
    areas = mesh.area_faces
    for faces in _planar_components(mesh):
        area_fraction = float(np.sum(areas[faces]) / mesh.area)
        if area_fraction < 0.10:
            continue
        mask_image = Image.new("1", (width, height))
        draw = ImageDraw.Draw(mask_image)
        for face in mesh.faces[faces]:
            polygon = [(float(uv[v, 0] * (width - 1)), float((1 - uv[v, 1]) * (height - 1))) for v in face]
            draw.polygon(polygon, fill=1)
        mask = np.asarray(mask_image, dtype=bool)
        if np.count_nonzero(mask) < 1024:
            continue
        colors = atlas[mask].astype(np.float32)
        center = np.median(colors, axis=0)
        spread = float(np.percentile(np.max(np.abs(colors - center), axis=1), 75))
        region = {"faces": len(faces), "area_fraction": area_fraction, "pixels": len(colors), "color_spread": spread}
        if spread > 30:
            cleaned[mask] = np.rint(center).astype(np.uint8)
            region["flattened"] = True
            report["applied"] = True
        else:
            region["flattened"] = False
        report["regions"].append(region)
    if not report["applied"]:
        report["reason"] = "no_large_noisy_plane"
        return mesh, report
    result = deepcopy(mesh)
    if original_image.ndim == 3 and original_image.shape[2] == 4:
        output = np.dstack((cleaned, original_image[:, :, 3]))
    else:
        output = cleaned
    setattr(result.visual.material, name, Image.fromarray(output))
    return result, report
