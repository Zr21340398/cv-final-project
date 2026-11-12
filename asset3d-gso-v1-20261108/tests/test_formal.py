from copy import deepcopy

import pytest

from asset3d.formal import DEFAULT_CONFIGS, run_formal
from asset3d.recording import file_hash, object_hash, save_json
from asset3d.run_approval import DATA_CHECKSUMS, REVIEW_BASIS


@pytest.fixture
def approved_dataset(tmp_path, monkeypatch):
    import asset3d.experiments as experiments
    import asset3d.formal_data as formal_data
    import asset3d.run_approval as approval_module

    manifest = tmp_path / "manifest.csv"
    selection = tmp_path / "selection.csv"
    manifest.write_text("id,image,reference,split\ngso_01,input.png,reference.glb,dev\n")
    selection.write_text("id,status\ngso_01,prepared_ai_review\n")
    inventory = tmp_path / DATA_CHECKSUMS
    inventory.parent.mkdir(parents=True)
    inventory.write_text("Frozen inventory; full data verification belongs to the CPU preflight.\n")
    evidence = {}
    for role in ("cpu", "ai"):
        path = tmp_path / "data/manifests/gso-run-evidence" / (role + ".json")
        save_json(path, {"role": role, "human_visual_qa_completed": False})
        evidence[role] = {"path": str(path.relative_to(tmp_path)), "sha256": file_hash(path)}
    audit = {
        "ready": False,
        "technical_ready": True,
        "errors": [{"code": "source_not_accepted", "object_id": "gso_01"}],
        "human_qa_pending": ["gso_01"],
        "roster_sha256": object_hash({"roster": "all thirty objects"}),
        "render_protocol_sha256": object_hash({"render": "fixed eight views"}),
    }
    approval = {
        "schema_version": 1,
        "scope": "dev",
        "user_instruction": "给学校gpu提交任务",
        "authorized_by": "user",
        "review_basis": REVIEW_BASIS,
        "human_visual_qa_completed": False,
        "manifest_sha256": file_hash(manifest),
        "selection_sha256": file_hash(selection),
        "roster_sha256": audit["roster_sha256"],
        "render_protocol_sha256": audit["render_protocol_sha256"],
        "data_checksums_sha256": file_hash(inventory),
        "evidence": evidence,
    }
    approval_path = tmp_path / "run-approval.json"
    save_json(approval_path, approval)
    calls = []
    monkeypatch.setattr(approval_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(formal_data, "audit_formal_dataset", lambda *a, **kw: audit)
    monkeypatch.setattr(experiments, "run_experiments", lambda *a, **kw: calls.append((a, kw)) or [])

    def invoke(**options):
        return run_formal(manifest, selection, None, [42, 123], tmp_path / "out", **options)

    return {
        "invoke": invoke,
        "audit": audit,
        "approval": approval,
        "approval_path": approval_path,
        "manifest": manifest,
        "selection": selection,
        "inventory": inventory,
        "root": tmp_path,
        "calls": calls,
    }


def test_pending_human_qa_still_blocks_without_explicit_run_approval(approved_dataset):
    data = approved_dataset
    with pytest.raises(ValueError, match="dataset is not ready"):
        data["invoke"](dry_run=True, limit=1)
    assert data["calls"] == []


@pytest.mark.parametrize("technical_ready", [False, True])
def test_run_approval_cannot_bypass_technical_errors(approved_dataset, technical_ready):
    data = approved_dataset
    data["audit"]["technical_ready"] = technical_ready
    data["audit"]["errors"].append({"code": "missing_input", "object_id": "gso_01"})
    with pytest.raises(ValueError, match="cannot bypass technical"):
        data["invoke"](run_approval=data["approval_path"], dry_run=True)
    assert data["calls"] == []


@pytest.mark.parametrize(
    "changed", ["manifest", "selection", "inventory", "cpu", "ai", "roster", "render_protocol"]
)
def test_approval_rejects_changed_data_or_review_evidence(approved_dataset, changed):
    data = approved_dataset
    if changed in ("manifest", "selection", "inventory"):
        data[changed].write_text("changed after approval\n")
    elif changed in ("cpu", "ai"):
        (data["root"] / data["approval"]["evidence"][changed]["path"]).write_text("changed review\n")
    else:
        data["audit"][changed + "_sha256"] = object_hash({"changed": True})
    with pytest.raises(ValueError, match="SHA256 does not match"):
        data["invoke"](run_approval=data["approval_path"], dry_run=True)
    assert data["calls"] == []


@pytest.mark.parametrize("invalid", ["missing", "outside", "human_claim", "instruction", "actor", "scope"])
def test_approval_requires_real_scoped_evidence_without_human_claim(approved_dataset, invalid):
    data = approved_dataset
    approval = data["approval"]
    if invalid == "missing":
        (data["root"] / approval["evidence"]["ai"]["path"]).unlink()
    elif invalid == "outside":
        approval["evidence"]["ai"]["path"] = "../outside.json"
    elif invalid == "human_claim":
        approval["human_visual_qa_completed"] = True
    elif invalid == "instruction":
        approval["user_instruction"] = "  "
    elif invalid == "actor":
        approval["authorized_by"] = "assistant"
    else:
        approval["scope"] = "test"
    save_json(data["approval_path"], approval)
    with pytest.raises(ValueError, match="Run approval"):
        data["invoke"](run_approval=data["approval_path"], dry_run=True)
    assert data["calls"] == []


def test_test_split_cannot_use_dev_run_approval(approved_dataset):
    data = approved_dataset
    with pytest.raises(ValueError, match="restricted to the dev split"):
        run_formal(
            data["manifest"],
            data["selection"],
            [DEFAULT_CONFIGS[0]],
            [42, 123],
            data["root"] / "out",
            "test",
            development_experiment=data["root"] / "dev",
            run_approval=data["approval_path"],
            dry_run=True,
        )
    assert data["calls"] == []


def test_valid_approval_freezes_provenance_and_preserves_human_qa_pending(approved_dataset):
    data = approved_dataset
    original_audit = deepcopy(data["audit"])
    original_selection = data["selection"].read_bytes()
    assert data["invoke"](run_approval=data["approval_path"], limit=1, dry_run=True) == []
    args, options = data["calls"][0]
    assert args[1] == DEFAULT_CONFIGS
    assert args[2] == [42, 123]
    assert options["limit"] == 1
    assert options["context"]["run_approval_sha256"] == file_hash(data["approval_path"])
    assert options["context"]["run_approval_review_basis"] == REVIEW_BASIS
    assert options["context"]["human_visual_qa_completed"] is False
    assert options["context"]["human_qa_pending"] == ["gso_01"]
    assert data["audit"] == original_audit
    assert data["selection"].read_bytes() == original_selection
    assert not (data["root"] / "out").exists()


def test_cli_forwards_explicit_approval_without_enabling_it_by_default(monkeypatch, tmp_path):
    import asset3d.formal as formal
    from asset3d.cli import main

    calls = []
    monkeypatch.setattr(formal, "run_formal", lambda *a, **kw: calls.append((a, kw)) or [])
    common = ["formal-run", "--manifest", "unused.csv", "--output", str(tmp_path), "--limit", "1"]
    assert main(common + ["--run-approval", "approval.json", "--dry-run"]) == 0
    assert calls[0][1]["run_approval"] == "approval.json"
    assert calls[0][1]["limit"] == 1
    assert main(common + ["--dry-run"]) == 0
    assert calls[1][1]["run_approval"] is None
