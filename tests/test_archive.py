import json

import pytest

from asset3d.archive import verify_archive
from asset3d.recording import file_hash, object_hash


def test_archive_checks_artifacts_without_rewriting_history(tmp_path):
    plan = {"configs": [{"name": "hunyuan2_steps50"}], "objects": [{"id": "gso_01"}], "seeds": [42]}
    record = {"plan": plan, "plan_sha256": object_hash(plan)}
    original = json.dumps(record)
    (tmp_path / "experiment.json").write_text(original, encoding="utf-8")
    run = tmp_path / "hunyuan2_steps50/gso_01/seed-42"
    run.mkdir(parents=True)
    for name in ("asset.glb", "shape_raw.glb"):
        (run / name).write_bytes(b"unchanged model")
    manifest = {"status": "completed", "artifacts": {n: file_hash(run / n) for n in ("asset.glb", "shape_raw.glb")}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_archive(tmp_path) == 1
    assert (tmp_path / "experiment.json").read_text(encoding="utf-8") == original
    (run / "asset.glb").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Changed artifact"):
        verify_archive(tmp_path)
