import numpy as np
from scipy.spatial import cKDTree

from ..mesh_ops import load_mesh, validate_mesh


def normalize_mesh(mesh, mode):
    mesh = mesh.copy()
    if mode == "none":
        return mesh
    if mode != "unit_bbox":
        raise ValueError("normalization must be none or unit_bbox")
    # 将包围盒中心移到原点、最长边缩放为 1，按统一尺度比较形状。
    center = mesh.bounds.mean(axis=0)
    scale = float(mesh.extents.max())
    if scale <= 0:
        raise ValueError("Degenerate bounding box")
    mesh.vertices = (mesh.vertices - center) / scale
    return mesh


def sample_surface(mesh, count, seed):
    validate_mesh(mesh)
    if count < 1:
        raise ValueError("samples must be positive")
    rng = np.random.default_rng(seed)
    triangles = mesh.triangles
    areas = mesh.area_faces
    # 按三角形面积决定抽样概率，再在三角形内均匀取点，得到表面点云。
    chosen = rng.choice(len(triangles), size=count, p=areas / areas.sum())
    uv = rng.random((count, 2))
    folded = uv.sum(axis=1) > 1
    uv[folded] = 1 - uv[folded]
    tri = triangles[chosen]
    return tri[:, 0] + uv[:, :1] * (tri[:, 1] - tri[:, 0]) + uv[:, 1:] * (tri[:, 2] - tri[:, 0])


def point_distances(pred, ref):
    pred, ref = np.asarray(pred), np.asarray(ref)
    for points in (pred, ref):
        if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
            raise ValueError("Point arrays must be finite, non-empty Nx3 arrays")
    # 双向寻找最近点：生成模型到参考模型，以及参考模型到生成模型。
    # Chamfer 取两个方向平均距离的均值；Hausdorff 取最大距离，HD95 看 95% 分位。
    p_to_r = cKDTree(ref).query(pred, workers=1)[0]
    r_to_p = cKDTree(pred).query(ref, workers=1)[0]
    return {
        "chamfer_l2": float((p_to_r.mean() + r_to_p.mean()) / 2),
        "hausdorff_sampled": float(max(p_to_r.max(), r_to_p.max())),
        "hd95_sampled": float(max(np.percentile(p_to_r, 95), np.percentile(r_to_p, 95))),
    }


def silhouette_iou(pred_mask, ref_mask):
    a, b = np.asarray(pred_mask, dtype=bool), np.asarray(ref_mask, dtype=bool)
    if a.shape != b.shape or a.ndim != 2:
        raise ValueError("Masks must be two-dimensional and have the same resolution")
    union = np.logical_or(a, b).sum()
    if union == 0:
        raise ValueError("Both masks are empty")
    return float(np.logical_and(a, b).sum() / union)


def evaluate_meshes(
    pred_path, ref_path, samples=100000, seed=2026, normalization="unit_bbox", transform=None
):
    pred, ref = load_mesh(pred_path), load_mesh(ref_path)
    # 先应用实验前确定的坐标变换，再统一尺度；旋转方向应通过校准样例确定。
    if transform is not None:
        transform = np.asarray(transform, dtype=float)
        if (
            transform.shape != (4, 4)
            or not np.isfinite(transform).all()
            or not np.allclose(transform[3], [0, 0, 0, 1])
        ):
            raise ValueError("Transform must be a finite homogeneous 4x4 matrix")
        r = transform[:3, :3]
        if not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1):
            raise ValueError("Only rigid, orientation-preserving prediction transforms are accepted")
        pred.apply_transform(transform)
    pred, ref = normalize_mesh(pred, normalization), normalize_mesh(ref, normalization)
    # 两个表面独立抽样，避免因使用相同采样位置而把误差估计得过低。
    scores = point_distances(sample_surface(pred, samples, seed), sample_surface(ref, samples, seed + 1))
    return {
        **scores,
        "protocol": {
            "samples_per_mesh": samples,
            "seed": seed,
            "normalization": normalization,
            "distance": "unsquared Euclidean; Chamfer = mean of two directional means",
            "hausdorff": "point-sample approximation, not exact surface Hausdorff",
            "transform_applied_before_normalization": None if transform is None else transform.tolist(),
            "alignment": "no automatic rotational alignment",
        },
    }
