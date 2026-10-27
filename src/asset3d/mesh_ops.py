from pathlib import Path

import numpy as np
import trimesh


def validate_mesh(mesh):
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) < 3 or len(mesh.faces) == 0:
        raise ValueError("Expected a non-empty triangular mesh")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("Mesh contains non-finite vertices")
    if mesh.faces.min() < 0 or mesh.faces.max() >= len(mesh.vertices):
        raise ValueError("Mesh contains invalid face indices")
    if not np.isfinite(mesh.area) or mesh.area <= 0:
        raise ValueError("Mesh has zero or invalid surface area")
    return {
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "area": float(mesh.area),
        "watertight": bool(mesh.is_watertight),
    }


def load_mesh(path):
    mesh = trimesh.load(Path(path), force="mesh", process=False)
    validate_mesh(mesh)
    return mesh
