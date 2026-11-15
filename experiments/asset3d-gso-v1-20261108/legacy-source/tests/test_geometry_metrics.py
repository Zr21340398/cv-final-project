import numpy as np
import pytest
import trimesh

from asset3d.evaluation.geometry import (
    evaluate_meshes,
    normalize_mesh,
    point_distances,
    sample_surface,
    silhouette_iou,
)


def test_identity_and_known_distance():
    a = np.array([[0, 0, 0], [1, 0, 0]])
    assert all(v == 0 for v in point_distances(a, a).values())
    values = point_distances(a, a + [0, 3, 0])
    assert all(v == pytest.approx(3) for v in values.values())


def test_hd95_not_same_as_max_outlier():
    a = np.zeros((100, 3))
    b = a.copy()
    b[-1, 0] = 100
    scores = point_distances(a, b)
    assert scores["hausdorff_sampled"] == 100
    assert scores["hd95_sampled"] == 0
    assert scores["chamfer_l2"] == 0.5


def test_normalization_scale_translation_invariant():
    a = trimesh.creation.box(extents=[1, 2, 3])
    b = a.copy()
    b.apply_scale(5)
    b.apply_translation([9, 2, -7])
    assert np.allclose(normalize_mesh(a, "unit_bbox").vertices, normalize_mesh(b, "unit_bbox").vertices)


def test_sampling_reproducible():
    mesh = trimesh.creation.box()
    assert np.array_equal(sample_surface(mesh, 100, 42), sample_surface(mesh, 100, 42))
    assert not np.array_equal(sample_surface(mesh, 100, 42), sample_surface(mesh, 100, 43))


def test_reject_nan_and_empty_points():
    for bad in (np.empty((0, 3)), np.array([[np.nan, 0, 0]])):
        with pytest.raises(ValueError):
            point_distances(bad, np.zeros((1, 3)))


def test_silhouette_iou():
    assert silhouette_iou([[1, 0], [0, 0]], [[1, 1], [0, 0]]) == 0.5
    with pytest.raises(ValueError):
        silhouette_iou([[0]], [[0]])


def test_mesh_evaluation_is_sample_approximation(tmp_path):
    path = tmp_path / "box.glb"
    trimesh.creation.box().export(path)
    result = evaluate_meshes(path, path, samples=10000)
    assert 0 < result["chamfer_l2"] < 0.03
    assert result["protocol"]["normalization"] == "unit_bbox"
    with pytest.raises(ValueError, match="rigid"):
        evaluate_meshes(path, path, transform=np.diag([2, 2, 2, 1]))
