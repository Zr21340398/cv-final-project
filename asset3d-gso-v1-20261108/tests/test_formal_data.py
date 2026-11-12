"""Synthetic CPU fixtures for data gates; no real GSO data is generated here."""

import csv
import json

import numpy as np
import pytest
import trimesh
from PIL import Image

from asset3d.data import read_manifest
from asset3d.formal_data import CATEGORIES, audit_formal_dataset, validate_preview


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_views(directory, views=8, resolution=32, clay=False):
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 0))
    image.paste((180, 80, 20, 255), (8, 8, 24, 24))
    frames = []
    for index in range(views):
        name = f"view-{index:03d}.png"
        image.save(directory / name)
        frames.append(
            {"image": name, "camera_to_world": np.eye(4).tolist(), "projection": np.eye(4).tolist()}
        )
    (directory / "cameras.json").write_text(
        json.dumps(
            {
                "resolution": resolution,
                "projection_type": "orthographic",
                "world_up": "Z",
                "ortho_scale": 1.8,
                "render_engine": "CYCLES_CPU",
                "samples": 32,
                "seed": 2026,
                "clay": clay,
                "frames": frames,
            }
        )
    )


@pytest.fixture
def formal_fixture(tmp_path):
    selection, manifest = [], []
    for category_index, category in enumerate(CATEGORIES):
        for index in range(6):
            ident = f"fixture_{category_index}_{index}"
            split = "dev" if index < 2 else "test"
            folder = tmp_path / ident
            source = folder / "source.glb"
            if split == "dev":
                make_views(folder)
                trimesh.creation.box().export(source)
                trimesh.creation.box().export(folder / "reference_normalized.glb")
            selection.append(
                {
                    "id": ident,
                    "gso_id": f"synthetic_{ident}",
                    "source_url": "https://example.invalid/fixture",
                    "license": "synthetic test fixture",
                    "category": category,
                    "duplicate_group": ident,
                    "split": split,
                    "mesh_path": f"{ident}/source.glb" if split == "dev" else "",
                    "status": "accepted" if split == "dev" else "candidate_v1",
                }
            )
            manifest.append(
                {
                    "id": ident,
                    "image": f"{ident}/view-000.png",
                    "reference": f"{ident}/reference_normalized.glb",
                    "split": split,
                }
            )
    selection_path, manifest_path = tmp_path / "selection.csv", tmp_path / "formal.csv"
    write_csv(selection_path, selection)
    write_csv(manifest_path, manifest)
    return manifest_path, selection_path, manifest, selection


def codes(result):
    return {error["code"] for error in result["errors"]}


def test_ready_dev_does_not_require_unprepared_test_files(formal_fixture):
    manifest_path, selection_path, _, _ = formal_fixture
    result = audit_formal_dataset(manifest_path, selection_path)
    assert result["ready"], result["errors"]
    assert result["technical_ready"] and result["human_qa_pending"] == []
    assert result["counts"]["selected_rows"] == result["counts"]["accepted_selected"] == 10
    assert result["counts"]["selection_splits"] == {"dev": 10, "test": 20}
    assert result["accepted_status"] == "accepted"
    assert all(len(item["sha256"]) == 64 for item in result["checked_files"])
    selected = read_manifest(manifest_path, "dev")
    assert len(selected) == 10 and all(row["reference_sha256"] for row in selected)
    with pytest.raises(FileNotFoundError):
        read_manifest(manifest_path)
    unavailable = audit_formal_dataset(manifest_path, selection_path, "test")
    assert not unavailable["ready"]
    assert {"source_not_accepted", "source_mesh_path", "missing_input", "missing_mesh"} <= codes(unavailable)


def test_ai_prepared_sources_are_technically_ready_but_still_need_human_acceptance(formal_fixture):
    manifest_path, selection_path, _, selection = formal_fixture
    for row in selection:
        if row["split"] == "dev":
            row["status"] = "prepared_ai_review"
    write_csv(selection_path, selection)
    before = selection_path.read_bytes()
    result = audit_formal_dataset(manifest_path, selection_path)
    assert result["technical_ready"] and not result["ready"]
    assert codes(result) == {"source_not_accepted"}
    assert result["human_qa_pending"] == sorted(row["id"] for row in selection if row["split"] == "dev")
    assert result["counts"]["accepted_selected"] == 0
    assert selection_path.read_bytes() == before


@pytest.mark.parametrize("problem", ["missing_reference", "split_leakage"])
def test_pending_human_review_does_not_hide_technical_errors(formal_fixture, problem):
    manifest_path, selection_path, manifest, selection = formal_fixture
    selection[0]["status"] = "prepared_ai_review"
    if problem == "missing_reference":
        (manifest_path.parent / manifest[0]["reference"]).unlink()
    else:
        selection[2]["duplicate_group"] = selection[0]["duplicate_group"]
    write_csv(selection_path, selection)
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["technical_ready"] and not result["ready"]
    assert result["human_qa_pending"] == [selection[0]["id"]]
    assert "source_not_accepted" in codes(result)
    assert ("missing_mesh" if problem == "missing_reference" else "split_leakage") in codes(result)


def test_missing_manifest_and_unaccepted_sources_accumulate_errors(formal_fixture):
    manifest_path, selection_path, _, selection = formal_fixture
    for row in selection:
        row["status"], row["mesh_path"] = "candidate_v1", ""
    write_csv(selection_path, selection)
    manifest_path.unlink()
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"]
    assert {"csv_file", "source_not_accepted", "source_mesh_path"} <= codes(result)
    assert len([e for e in result["errors"] if e["code"] == "source_not_accepted"]) == 10


def test_draft_manifest_and_global_split_leakage_are_rejected(formal_fixture):
    manifest_path, selection_path, manifest, selection = formal_fixture
    draft = manifest_path.with_name("formal.draft.csv")
    write_csv(draft, manifest)
    selection[2]["duplicate_group"] = selection[0]["duplicate_group"]
    selection[0]["category"] = "patterned"
    write_csv(selection_path, selection)
    result = audit_formal_dataset(draft, selection_path)
    assert not result["ready"]
    assert {"draft_manifest", "split_leakage", "category_counts"} <= codes(result)


def test_manifest_identity_and_split_must_match_sources(formal_fixture):
    manifest_path, selection_path, manifest, _ = formal_fixture
    manifest[2]["id"] = "unknown_fixture"
    manifest[3]["split"] = "dev"
    write_csv(manifest_path, manifest)
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"]
    assert {"manifest_ids", "manifest_split", "split_counts"} <= codes(result)


@pytest.mark.parametrize(
    "mode,color", [("RGB", (10, 20, 30)), ("RGBA", (10, 20, 30, 255)), ("RGBA", (0, 0, 0, 0))]
)
def test_input_must_have_rgba_visible_foreground_and_transparency(formal_fixture, mode, color):
    manifest_path, selection_path, manifest, _ = formal_fixture
    Image.new(mode, (32, 32), color).save(manifest_path.parent / manifest[0]["image"])
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"] and "input_image" in codes(result)


def test_bad_mesh_and_incomplete_preview_both_reported(formal_fixture):
    manifest_path, selection_path, manifest, selection = formal_fixture
    source = selection_path.parent / selection[0]["mesh_path"]
    source.write_bytes(b"This is not a mesh")
    folder = (manifest_path.parent / manifest[0]["image"]).parent
    (folder / "view-007.png").unlink()
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"] and {"invalid_mesh", "missing_views"} <= codes(result)


@pytest.mark.parametrize("change", ["resolution", "camera"])
def test_selected_objects_need_the_same_render_protocol(formal_fixture, change):
    manifest_path, selection_path, manifest, _ = formal_fixture
    folder = (manifest_path.parent / manifest[1]["image"]).parent
    if change == "resolution":
        make_views(folder, resolution=64)
    else:
        camera_path = folder / "cameras.json"
        cameras = json.loads(camera_path.read_text())
        cameras["frames"][0]["camera_to_world"][0][3] = 1
        camera_path.write_text(json.dumps(cameras))
    # Each directory is complete on its own, but cannot share a comparison.
    validate_preview(folder)
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"] and "render_protocol" in codes(result)
    assert result["render_protocol_sha256"] is None


def test_roster_fingerprint_ignores_row_order_acceptance_and_local_paths(formal_fixture):
    manifest_path, selection_path, _, selection = formal_fixture
    before = audit_formal_dataset(manifest_path, selection_path)
    assert len(before["roster_sha256"]) == len(before["render_protocol_sha256"]) == 64
    selection[0]["status"] = "candidate_v1"
    selection[0]["mesh_path"] = "new-local-directory/source.glb"
    write_csv(selection_path, list(reversed(selection)))
    after = audit_formal_dataset(manifest_path, selection_path)
    assert not after["ready"]
    assert after["roster_sha256"] == before["roster_sha256"]


@pytest.mark.parametrize("field,new_value", [("gso_id", "changed-test-source"), ("id", "changed_test_id")])
def test_dev_roster_fingerprint_also_freezes_test_object_identity(formal_fixture, field, new_value):
    manifest_path, selection_path, _, selection = formal_fixture
    before = audit_formal_dataset(manifest_path, selection_path)["roster_sha256"]
    assert selection[2]["split"] == "test"
    selection[2][field] = new_value
    write_csv(selection_path, selection)
    after = audit_formal_dataset(manifest_path, selection_path)["roster_sha256"]
    assert after is not None and after != before


def test_render_fingerprint_tracks_a_common_protocol_change(formal_fixture):
    manifest_path, selection_path, manifest, _ = formal_fixture
    before = audit_formal_dataset(manifest_path, selection_path)["render_protocol_sha256"]
    for row in manifest:
        if row["split"] == "dev":
            camera_path = (manifest_path.parent / row["image"]).with_name("cameras.json")
            cameras = json.loads(camera_path.read_text())
            cameras["seed"] += 1
            camera_path.write_text(json.dumps(cameras))
    result = audit_formal_dataset(manifest_path, selection_path)
    assert result["ready"]
    assert result["render_protocol_sha256"] != before


@pytest.mark.parametrize("clay", [True, None])
def test_reference_render_must_explicitly_preserve_materials(formal_fixture, clay):
    manifest_path, selection_path, manifest, _ = formal_fixture
    camera_path = (manifest_path.parent / manifest[0]["image"]).with_name("cameras.json")
    cameras = json.loads(camera_path.read_text())
    if clay is None:
        cameras.pop("clay")
    else:
        cameras["clay"] = clay
    camera_path.write_text(json.dumps(cameras))
    result = audit_formal_dataset(manifest_path, selection_path)
    assert not result["ready"] and {"expected_clay", "render_metadata"} & codes(result)


def test_all_table_ids_and_required_references_checked_before_split(formal_fixture):
    manifest_path, _, manifest, _ = formal_fixture
    manifest[2]["id"] = manifest[0]["id"]
    write_csv(manifest_path, manifest)
    with pytest.raises(ValueError, match="duplicate"):
        read_manifest(manifest_path, "dev")
    manifest[2]["id"] = "unique_test_id"
    manifest[2]["reference"] = ""
    write_csv(manifest_path, manifest)
    with pytest.raises(ValueError, match="Reference mesh required"):
        read_manifest(manifest_path, "dev")


def test_preview_respects_requested_view_count_and_camera_mapping(tmp_path):
    make_views(tmp_path, views=4)
    assert len(validate_preview(tmp_path, expected_views=4)["views"]) == 4
    with pytest.raises(ValueError, match="Missing rendered views"):
        validate_preview(tmp_path)
    camera_path = tmp_path / "cameras.json"
    cameras = json.loads(camera_path.read_text())
    cameras["frames"][0]["image"] = "../elsewhere.png"
    camera_path.write_text(json.dumps(cameras))
    with pytest.raises(ValueError, match="exactly once"):
        validate_preview(tmp_path, expected_views=4)


def test_preview_rejects_invalid_matrix_and_image_size(tmp_path):
    make_views(tmp_path)
    camera_path = tmp_path / "cameras.json"
    cameras = json.loads(camera_path.read_text())
    cameras["frames"][3]["projection"][0][0] = float("nan")
    camera_path.write_text(json.dumps(cameras))
    Image.new("RGBA", (64, 64)).save(tmp_path / "view-006.png")
    with pytest.raises(ValueError, match="finite 4x4") as failure:
        validate_preview(tmp_path)
    assert "Image size" in str(failure.value)


def test_render_resume_does_not_skip_partial_views_with_camera_file(tmp_path, monkeypatch):
    from asset3d import pilot

    root = tmp_path / "experiment"
    run = root / "hunyuan/object/seed-42"
    run.mkdir(parents=True)
    # render_all only needs source existence to reach its reuse gate; rendering
    # is forbidden in this test, and no source mesh is opened or generated.
    (run / "shape_raw.glb").write_bytes(b"fixture existence marker")
    make_views(run / "white_preview", views=4)
    (run / "white_preview/view-003.png").unlink()
    plan = {"configs": [{"name": "hunyuan"}], "objects": [{"id": "object"}], "seeds": [42]}
    monkeypatch.setattr(pilot, "read_plan", lambda _: (root, plan))
    errors = pilot.render_all(root, blender="not-invoked", views=4)
    assert len(errors) == 1 and "view-003.png" in errors[0]["error"]


@pytest.mark.parametrize(
    "resolution,clay,expected", [(32, False, "resolution 512"), (512, True, "clay=False")]
)
def test_render_cache_checks_resolution_and_material_mode(tmp_path, monkeypatch, resolution, clay, expected):
    from asset3d import pilot

    root = tmp_path / "experiment"
    run = root / "hunyuan/object/seed-42"
    run.mkdir(parents=True)
    (run / "asset.glb").write_bytes(b"fixture existence marker")
    make_views(run / "preview", views=4, resolution=resolution, clay=clay)
    plan = {"configs": [{"name": "hunyuan"}], "objects": [{"id": "object"}], "seeds": [42]}
    monkeypatch.setattr(pilot, "read_plan", lambda _: (root, plan))
    errors = pilot.render_all(root, blender="not-invoked", views=4)
    assert len(errors) == 1 and expected in errors[0]["error"]


def test_new_render_output_is_validated_too(tmp_path, monkeypatch):
    from asset3d import pilot, render

    root = tmp_path / "experiment"
    run = root / "hunyuan/object/seed-42"
    run.mkdir(parents=True)
    (run / "asset.glb").write_bytes(b"fixture existence marker")
    plan = {"configs": [{"name": "hunyuan"}], "objects": [{"id": "object"}], "seeds": [42]}
    monkeypatch.setattr(pilot, "read_plan", lambda _: (root, plan))
    monkeypatch.setattr(render, "render_mesh", lambda mesh, out, *args, **kwargs: make_views(out, views=4))
    errors = pilot.render_all(root, blender="not-invoked", views=4)
    assert len(errors) == 1 and "resolution 512" in errors[0]["error"]
