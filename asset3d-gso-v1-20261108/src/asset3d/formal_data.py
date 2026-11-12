"""Read-only checks for the frozen 10-dev/20-test GSO dataset.

Selection ``status=accepted`` means a person has inspected the source geometry,
textures and orientation. This audit never assigns that status itself. Relative
mesh paths are resolved against the selection CSV; input/reference paths against
the formal manifest CSV. Only the requested split needs files and acceptance,
while IDs, stratification and leakage checks always cover the complete dataset.
"""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from .mesh_ops import load_mesh, validate_mesh
from .recording import file_hash, object_hash

CATEGORIES = ("simple_solid", "thin_or_hollow", "asymmetric", "patterned", "complex_shape")
SPLIT_COUNTS = {"dev": 10, "test": 20}
ACCEPTED_STATUS = "accepted"
ROSTER_FIELDS = ("id", "gso_id", "source_url", "license", "category", "duplicate_group", "split")
RENDER_FIELDS = (
    "resolution",
    "projection_type",
    "world_up",
    "ortho_scale",
    "render_engine",
    "samples",
    "seed",
    "clay",
)


def _error(errors, code, message, path=None, object_id=None):
    item = {"code": code, "message": message}
    if path is not None:
        item["path"] = str(path)
    if object_id is not None:
        item["object_id"] = object_id
    errors.append(item)


def _record(path, kind, **details):
    return {
        "path": str(path),
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": file_hash(path),
        **details,
    }


def _image_details(path, require_foreground=False, resolution=None):
    with Image.open(path) as image:
        image.load()
        if image.format != "PNG":
            raise ValueError("Expected an actual PNG image")
        if resolution is not None and image.size != (resolution, resolution):
            raise ValueError(f"Image size {image.size} differs from cameras.json resolution {resolution}")
        details = {"width": image.width, "height": image.height, "mode": image.mode}
        if require_foreground:
            if image.mode != "RGBA":
                raise ValueError("Generation input must be RGBA with a transparent background")
            low, high = image.getchannel("A").getextrema()
            if low != 0 or high == 0:
                raise ValueError(
                    "Generation input must contain visible foreground and fully transparent pixels"
                )
            details["alpha_range"] = [low, high]
        return details


def _audit_preview(
    directory, expected_views=8, *, expected_resolution=None, expected_clay=None, reference_protocol=None
):
    directory = Path(directory).resolve()
    errors, checked = [], []
    if type(expected_views) is not int or expected_views < 1:
        _error(errors, "view_count", "expected_views must be a positive integer", directory)
        return {"errors": errors, "views": [], "cameras": None, "checked_files": checked}
    names = [f"view-{index:03d}.png" for index in range(expected_views)]
    actual = {path.name for path in directory.glob("view-*.png") if path.is_file()}
    missing, extra = sorted(set(names) - actual), sorted(actual - set(names))
    if missing:
        _error(errors, "missing_views", "Missing rendered views: " + ", ".join(missing), directory)
    if extra:
        _error(errors, "extra_views", "Unexpected rendered views: " + ", ".join(extra), directory)
    camera_path = directory / "cameras.json"
    cameras, resolution, protocol = None, None, None
    try:
        cameras = json.loads(camera_path.read_text(encoding="utf-8"))
        if not isinstance(cameras, dict):
            raise ValueError("cameras.json must contain an object")
        checked.append(_record(camera_path, "cameras"))
        resolution = cameras.get("resolution")
        if type(resolution) is not int or resolution < 32:
            _error(errors, "camera_resolution", "cameras.json needs an integer resolution >= 32", camera_path)
            resolution = None
        if expected_resolution is not None and resolution != expected_resolution:
            _error(
                errors,
                "expected_resolution",
                f"Expected render resolution {expected_resolution}",
                camera_path,
            )
        for field, expected in (
            ("projection_type", "orthographic"),
            ("world_up", "Z"),
            ("render_engine", "CYCLES_CPU"),
        ):
            if cameras.get(field) != expected:
                _error(
                    errors, "render_metadata", f"Renderer metadata requires {field}={expected!r}", camera_path
                )
        scale = cameras.get("ortho_scale")
        if type(scale) not in (int, float) or not np.isfinite(scale) or scale <= 0:
            _error(
                errors,
                "render_metadata",
                "Renderer metadata needs a positive finite ortho_scale",
                camera_path,
            )
        for field, minimum in (("samples", 1), ("seed", 0)):
            if type(cameras.get(field)) is not int or cameras[field] < minimum:
                _error(
                    errors,
                    "render_metadata",
                    f"Renderer metadata needs integer {field} >= {minimum}",
                    camera_path,
                )
        if type(cameras.get("clay")) is not bool:
            _error(
                errors,
                "render_metadata",
                "Renderer metadata must explicitly record boolean clay",
                camera_path,
            )
        elif expected_clay is not None and cameras["clay"] != expected_clay:
            _error(errors, "expected_clay", f"Expected clay={expected_clay} for this render", camera_path)
        frames = cameras.get("frames")
        if not isinstance(frames, list) or len(frames) != expected_views:
            _error(
                errors,
                "camera_frames",
                f"cameras.json must record exactly {expected_views} frames",
                camera_path,
            )
        else:
            recorded_names = [frame.get("image") if isinstance(frame, dict) else None for frame in frames]
            if any(not isinstance(name, str) for name in recorded_names) or sorted(recorded_names) != names:
                _error(
                    errors,
                    "camera_view_names",
                    "Camera frames must name every expected view exactly once",
                    camera_path,
                )
            for index, frame in enumerate(frames):
                for key in ("camera_to_world", "projection"):
                    try:
                        matrix = np.asarray(frame[key], dtype=float)
                        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
                            raise ValueError("invalid matrix")
                    except (KeyError, TypeError, ValueError):
                        _error(
                            errors, "camera_matrix", f"Frame {index} needs a finite 4x4 {key}", camera_path
                        )
        if not errors:
            by_name = {frame["image"]: frame for frame in frames}
            # Object centering/scaling is intentionally excluded: compare only
            # the common camera and rendering conditions, never source paths.
            protocol = {field: cameras[field] for field in RENDER_FIELDS}
            protocol["frames"] = [
                {key: by_name[name][key] for key in ("camera_to_world", "projection")} for name in names
            ]
            if reference_protocol is not None and protocol != reference_protocol:
                _error(
                    errors,
                    "render_protocol",
                    "Camera/render protocol differs from the other selected objects",
                    camera_path,
                )
    except (OSError, UnicodeError, ValueError) as exc:
        _error(errors, "camera_file", f"Cannot read valid cameras.json: {exc}", camera_path)
    for name in names:
        path = directory / name
        if not path.is_file():
            continue
        try:
            checked.append(_record(path, "rendered_view", **_image_details(path, resolution=resolution)))
        except (OSError, ValueError) as exc:
            _error(errors, "view_image", f"Cannot read valid rendered PNG: {exc}", path)
    return {
        "errors": errors,
        "views": [str(directory / name) for name in names],
        "cameras": cameras,
        "protocol": protocol,
        "checked_files": checked,
    }


def validate_preview(
    directory, expected_views=8, *, expected_resolution=None, expected_clay=None, reference_protocol=None
):
    """Validate complete PNG views and the renderer's frame/matrix metadata.

    Returns ``views`` (absolute paths), parsed ``cameras``, canonical ``protocol``
    and file hashes. Pass a previous result's protocol to require common viewing
    conditions; object-specific normalization and paths are excluded.
    Raises ValueError before callers copy or reuse incomplete render directories.
    """
    result = _audit_preview(
        directory,
        expected_views,
        expected_resolution=expected_resolution,
        expected_clay=expected_clay,
        reference_protocol=reference_protocol,
    )
    if result["errors"]:
        raise ValueError(
            f"Invalid preview {Path(directory)}: " + "; ".join(e["message"] for e in result["errors"])
        )
    return {key: result[key] for key in ("views", "cameras", "protocol", "checked_files")}


def _read_csv(path, required, errors, checked):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if len(set(fields)) != len(fields) or not required <= set(fields):
                raise ValueError("Required unique columns: " + ", ".join(sorted(required)))
            rows = list(reader)
            if any(None in row or any(row.get(key) is None for key in required) for row in rows):
                raise ValueError("Rows must have the declared columns and required fields")
        checked.append(_record(path, "csv"))
        return [
            {key: value.strip() if isinstance(value, str) else value for key, value in row.items()}
            for row in rows
        ]
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        _error(errors, "csv_file", f"Cannot read dataset CSV: {exc}", path)
        return None


def _index_rows(rows, path, errors):
    indexed = {}
    for row in rows:
        ident = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ident) or ident in indexed:
            _error(errors, "object_id", "Unsafe or duplicate object ID", path, ident)
        indexed[ident] = row
        if row["split"] not in SPLIT_COUNTS:
            _error(errors, "split", "Formal split must be dev or test", path, ident)
    counts = dict(Counter(row["split"] for row in rows))
    if len(rows) != 30 or counts != SPLIT_COUNTS:
        _error(errors, "split_counts", f"Expected 30 rows with dev=10/test=20; found {counts}", path)
    return indexed


def _check_mesh(path, kind, errors, checked, ident):
    if not path.is_file():
        _error(errors, "missing_mesh", f"Missing {kind}", path, ident)
        return
    try:
        mesh = load_mesh(path)
        details = validate_mesh(mesh)
        checked.append(_record(path, kind, **details))
    except Exception as exc:
        # Mesh importers have format-specific exception classes; report each bad
        # object and continue auditing the other objects rather than aborting.
        _error(errors, "invalid_mesh", f"Cannot read valid {kind}: {exc}", path, ident)


def audit_formal_dataset(manifest_path, selection_path, split="dev"):
    """Accumulate readiness errors without writing, downloading or rendering.

    ``ready`` requires accepted source rows and valid files for the selected
    split, plus the global 30-object structure. This does not establish model
    coordinate calibration or replace a person's source-material inspection.
    ``technical_ready`` ignores only pending human acceptance; it is not a
    generation authorization and never changes the meaning of ``ready``.
    Errors contain ``code``, ``message`` and, when applicable, ``path``/``object_id``.
    """
    manifest_path, selection_path = Path(manifest_path).resolve(), Path(selection_path).resolve()
    errors, checked = [], []
    if split not in SPLIT_COUNTS:
        _error(errors, "selected_split", "Selected formal split must be dev or test")
    if manifest_path.name.lower().endswith(".draft.csv"):
        _error(errors, "draft_manifest", "A .draft.csv is not a frozen formal manifest", manifest_path)
    selection = _read_csv(
        selection_path,
        {
            "id",
            "gso_id",
            "source_url",
            "license",
            "category",
            "duplicate_group",
            "split",
            "mesh_path",
            "status",
        },
        errors,
        checked,
    )
    manifest = _read_csv(manifest_path, {"id", "image", "reference", "split"}, errors, checked)
    source_index, manifest_index = {}, {}
    roster_sha256 = None
    if selection is not None:
        source_error_count = len(errors)
        source_index = _index_rows(selection, selection_path, errors)
        strata = Counter((row["category"], row["split"]) for row in selection)
        expected = {
            (category, part): 2 if part == "dev" else 4 for category in CATEGORIES for part in SPLIT_COUNTS
        }
        if dict(strata) != expected:
            _error(
                errors,
                "category_counts",
                "Each of the five categories needs 2 dev and 4 test objects",
                selection_path,
            )
        groups = defaultdict(set)
        for row in selection:
            for field in ("gso_id", "source_url", "license", "duplicate_group"):
                if not row[field]:
                    _error(errors, "source_field", f"Missing source field {field}", selection_path, row["id"])
            if row["duplicate_group"]:
                groups[row["duplicate_group"]].add(row["split"])
        for group, splits in groups.items():
            if len(splits) > 1:
                _error(errors, "split_leakage", f"duplicate_group {group!r} crosses dev/test", selection_path)
        if len({row["gso_id"] for row in selection}) != len(selection):
            _error(
                errors, "duplicate_gso_id", "Each selected GSO object must appear only once", selection_path
            )
        if len(errors) == source_error_count:
            roster_sha256 = object_hash(
                [
                    {field: row[field] for field in ROSTER_FIELDS}
                    for row in sorted(selection, key=lambda row: row["id"])
                ]
            )
    if manifest is not None:
        manifest_index = _index_rows(manifest, manifest_path, errors)
        for row in manifest:
            for field in ("image", "reference"):
                if not row[field]:
                    _error(errors, "manifest_path", f"Missing {field} path", manifest_path, row["id"])
    if selection is not None and manifest is not None:
        if set(source_index) != set(manifest_index):
            _error(
                errors,
                "manifest_ids",
                "Source and formal manifest IDs differ: "
                f"missing={sorted(set(source_index) - set(manifest_index))}, "
                f"extra={sorted(set(manifest_index) - set(source_index))}",
                manifest_path,
            )
        for ident in source_index.keys() & manifest_index.keys():
            if source_index[ident]["split"] != manifest_index[ident]["split"]:
                _error(
                    errors, "manifest_split", "Source and formal manifest split differ", manifest_path, ident
                )
    for row in selection or []:
        if row["split"] != split:
            continue
        ident = row["id"]
        if row["status"] != ACCEPTED_STATUS:
            _error(
                errors,
                "source_not_accepted",
                "Source status must be accepted after human geometry/texture/orientation QA; "
                f"found {row['status']!r}",
                selection_path,
                ident,
            )
        if not row["mesh_path"]:
            _error(errors, "source_mesh_path", "Source mesh_path is empty", selection_path, ident)
        else:
            _check_mesh(
                (selection_path.parent / row["mesh_path"]).resolve(), "source_mesh", errors, checked, ident
            )
    reference_protocol, valid_previews = None, 0
    for row in manifest or []:
        if row["split"] != split:
            continue
        ident = row["id"]
        image = (manifest_path.parent / row["image"]).resolve() if row["image"] else None
        reference = (manifest_path.parent / row["reference"]).resolve() if row["reference"] else None
        if image is not None:
            if image.name != "view-000.png":
                _error(errors, "input_view", "Formal generation input must be view-000.png", image, ident)
            if not image.is_file():
                _error(errors, "missing_input", "Missing rendered generation input", image, ident)
            else:
                try:
                    checked.append(
                        _record(image, "generation_input", **_image_details(image, require_foreground=True))
                    )
                except (OSError, ValueError) as exc:
                    _error(errors, "input_image", f"Invalid RGBA foreground input: {exc}", image, ident)
            preview = _audit_preview(
                image.parent, expected_views=8, expected_clay=False, reference_protocol=reference_protocol
            )
            for problem in preview["errors"]:
                errors.append({**problem, "object_id": ident})
            checked.extend(preview["checked_files"])
            if not preview["errors"]:
                valid_previews += 1
                if reference_protocol is None:
                    reference_protocol = preview["protocol"]
        if reference is not None:
            if reference.name != "reference_normalized.glb" or (
                image is not None and reference.parent != image.parent
            ):
                _error(
                    errors,
                    "reference_location",
                    "Reference must be reference_normalized.glb beside view-000.png",
                    reference,
                    ident,
                )
            _check_mesh(reference, "reference_mesh", errors, checked, ident)
    selected = [row for row in manifest or [] if row["split"] == split]
    # Generation input and view-000 share a file; retain both roles without
    # counting the same bytes twice in the audit's inventory.
    inventory = {}
    for item in checked:
        previous = inventory.get(item["path"])
        roles = previous["roles"] if previous else []
        if item["kind"] not in roles:
            roles = [*roles, item["kind"]]
        inventory[item["path"]] = {**(previous or {}), **item, "roles": roles}
    return {
        "ready": not errors,
        "technical_ready": not any(error["code"] != "source_not_accepted" for error in errors),
        "human_qa_pending": sorted(
            {error["object_id"] for error in errors if error["code"] == "source_not_accepted"}
        ),
        "split": split,
        "manifest": str(manifest_path),
        "selection": str(selection_path),
        "accepted_status": ACCEPTED_STATUS,
        "roster_sha256": roster_sha256,
        "render_protocol_sha256": (
            object_hash(reference_protocol)
            if reference_protocol is not None and valid_previews == len(selected) == SPLIT_COUNTS.get(split)
            else None
        ),
        "acceptance_meaning": "Human inspection of source geometry, textures and orientation; never assigned by this audit",
        "errors": errors,
        "counts": {
            "selection_rows": len(selection or []),
            "manifest_rows": len(manifest or []),
            "selected_rows": len(selected),
            "selection_splits": dict(Counter(r["split"] for r in selection or [])),
            "manifest_splits": dict(Counter(r["split"] for r in manifest or [])),
            "accepted_selected": sum(
                r["split"] == split and r["status"] == ACCEPTED_STATUS for r in selection or []
            ),
            "checked_files": len(inventory),
        },
        "checked_files": list(inventory.values()),
    }
