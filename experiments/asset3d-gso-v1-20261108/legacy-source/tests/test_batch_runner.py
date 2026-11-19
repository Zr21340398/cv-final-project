import builtins
import fcntl
import json
import subprocess
from pathlib import Path

import pytest
from conftest import FakeBackend

from asset3d import experiments as exp
from asset3d import pipeline as pipeline_module
from asset3d.config import load_config
from asset3d.pipeline import Pipeline
from asset3d.recording import object_hash, save_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def batch(tmp_path, picture, monkeypatch):
    manifest = tmp_path / "input.csv"
    manifest.write_text(f"id,image,reference,split\na,{picture.name},,real\n", encoding="utf-8")
    output = tmp_path / "results"
    state = {"source": "test-source", "mode": "success", "calls": [], "kills": []}
    monkeypatch.setattr(exp, "environment", lambda: {"source_hash": state["source"]})
    monkeypatch.setattr(pipeline_module, "environment", lambda: {"source_hash": state["source"]})

    class Child:
        def __init__(self, command, **kwargs):
            self.command, self.env = command, kwargs["env"]
            self.pid, self.returncode = 50000 + len(state["calls"]), None
            state["calls"].append(self)
            assert command[:4] == [exp.sys.executable, "-m", "asset3d.cli", "generate"]
            assert kwargs["start_new_session"] is True

        def arg(self, name):
            return self.command[self.command.index(name) + 1]

        def wait(self, timeout=None):
            if timeout is None:
                self.returncode = -9
                return self.returncode
            if "timeout" in state["mode"]:
                directory = Path(self.arg("--output"))
                directory.mkdir(parents=True, exist_ok=True)
                token = self.env["ASSET3D_RUN_TOKEN"] if state["mode"] == "timeout" else "foreign"
                save_json(directory / ".running.lock", {"pid": self.pid, "run_token": token})
                raise subprocess.TimeoutExpired(self.command, timeout)
            if state["mode"] == "failed":
                self.returncode = 1
                return 1
            config = load_config(self.arg("--config"))
            try:
                Pipeline(config, FakeBackend(fail_texture=state["mode"] == "texture_failure")).run(
                    self.arg("--image"),
                    self.arg("--output"),
                    int(self.arg("--seed")),
                    "--resume" in self.command,
                )
            except RuntimeError:
                self.returncode = 1
            else:
                self.returncode = 0
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(exp.subprocess, "Popen", Child)
    monkeypatch.setattr(exp.os, "killpg", lambda pid, sig: state["kills"].append((pid, sig)))

    def run(**kwargs):
        options = {"split": "real", **kwargs}
        return exp.run_experiments(manifest, [ROOT / "configs/baseline.yaml"], [42, 123], output, **options)

    def record(seed=42):
        return json.loads((output / "process-logs/baseline" / f"a-seed-{seed}.json").read_text())

    return run, state, output, manifest, record


def test_dry_run_is_read_only_and_does_not_import_gpu(batch, capsys, monkeypatch):
    run, state, output, _, _ = batch
    real_import = builtins.__import__

    def without_gpu(name, *args, **kwargs):
        assert name.split(".")[0] not in {"torch", "hy3dgen", "trellis2"}
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_gpu)
    assert run(dry_run=True, limit=1, timeout=17) == []
    assert not output.exists() and not state["calls"]
    assert "2 planned, 1 selected, timeout=17s" in capsys.readouterr().out


def test_frozen_plan_and_idempotent_resume_preserve_generation_attempts(batch):
    run, state, output, _, record = batch
    assert run(context={"development_plan_sha256": "dev"}) == []
    plan = json.loads((output / "experiment.json").read_text())["plan"]
    assert plan["source_hash"] == "test-source" and plan["protocol"] == exp.PROTOCOL
    assert plan["context"] == {"development_plan_sha256": "dev"}
    assert (output / "configs/baseline.yaml").exists()
    original = record()["attempts"][0]
    assert run(resume=True, context=plan["context"]) == []
    assert len(state["calls"]) == 2
    attempts = record()["attempts"]
    assert attempts[0] == original
    assert attempts[1]["status"] == "skipped" and attempts[1]["reason"] == "already_completed"
    m = json.loads((output / "baseline/a/seed-42/manifest.json").read_text())
    assert len(m["attempts"]) == 1
    assert len(json.loads((output / "failures.json").read_text())) == 2


def test_dry_run_rejects_nonempty_unplanned_output_without_writing(batch):
    run, state, output, _, _ = batch
    output.mkdir()
    existing = output / "notes.txt"
    existing.write_text("keep existing results")
    with pytest.raises(FileExistsError, match="output must be empty"):
        run(dry_run=True)
    assert list(output.iterdir()) == [existing]
    assert existing.read_text() == "keep existing results"
    assert not state["calls"]


def test_limit_counts_planned_cells_including_skips(batch):
    run, state, _, _, _ = batch
    assert run(limit=1) == []
    assert len(state["calls"]) == 1
    assert run(resume=True, limit=1) == []
    assert len(state["calls"]) == 1
    assert run(resume=True, limit=2) == []
    assert len(state["calls"]) == 2


def test_failure_requires_explicit_retry_and_preserves_history(batch):
    run, state, _, _, record = batch
    state["mode"] = "failed"
    assert len(run(limit=1)) == 1
    state["mode"] = "success"
    assert len(run(resume=True, limit=1)) == 1
    assert len(state["calls"]) == 1
    assert record()["attempts"][-1]["reason"] == "previous_failure_requires_retry"
    assert run(resume=True, retry_failed=True, limit=1) == []
    assert [a["status"] for a in record()["attempts"]] == ["failed", "skipped", "completed"]


def test_explicit_retry_can_resume_failed_texture_without_replacing_raw_shape(batch):
    run, state, output, _, record = batch
    state["mode"] = "texture_failure"
    assert len(run(limit=1)) == 1
    raw_path = output / "baseline/a/seed-42/shape_raw.glb"
    original = raw_path.read_bytes()
    state["mode"] = "success"
    assert len(run(resume=True, limit=1)) == 1
    assert run(resume=True, retry_failed=True, limit=1) == []
    manifest = json.loads((raw_path.parent / "manifest.json").read_text())
    assert raw_path.read_bytes() == original
    assert "shape_raw.glb" in manifest["attempts"][-1]["reused"]
    assert [a["status"] for a in record()["attempts"]] == ["failed", "skipped", "completed"]


@pytest.mark.parametrize("mode,cleared", [("timeout", True), ("foreign_timeout", False)])
def test_timeout_waits_then_only_cleans_owned_lock(batch, mode, cleared):
    run, state, output, _, record = batch
    state["mode"] = mode
    assert len(run(limit=1, timeout=3)) == 1
    attempt = record()["attempts"][-1]
    assert attempt["status"] == "timeout" and attempt["lock_cleaned"] is cleared
    assert state["calls"][0].returncode == -9 and state["kills"]
    assert (output / "baseline/a/seed-42/.running.lock").exists() is not cleared


def test_preexisting_lock_is_not_removed_or_launched_over(batch):
    run, state, output, _, record = batch
    state["mode"] = "failed"
    run(limit=1)
    lock = output / "baseline/a/seed-42/.running.lock"
    save_json(lock, {"pid": 999, "run_token": "someone-else"})
    assert len(run(resume=True, retry_failed=True, limit=1)) == 1
    assert len(state["calls"]) == 1 and lock.exists()
    assert record()["attempts"][-1]["phase"] == "validation"


def test_corrupt_old_success_records_failure_instead_of_skipping(batch):
    run, state, output, _, record = batch
    run(limit=1)
    (output / "baseline/a/seed-42/asset.glb").write_bytes(b"changed")
    assert len(run(resume=True, limit=1)) == 1
    assert len(state["calls"]) == 1
    last = record()["attempts"][-1]
    assert last["status"] == "failed" and "changed" in last["error"]
    assert last["phase"] == "validation"


def test_source_change_rejects_entire_matrix_before_new_cells(batch):
    run, state, _, _, record = batch
    run(limit=1)
    state["source"] = "new-source"
    with pytest.raises(ValueError, match="source code changed"):
        run(resume=True)
    assert len(state["calls"]) == 1 and len(record()["attempts"]) == 1


def test_input_mutation_or_frozen_config_tamper_rejects_entire_resume(batch):
    run, state, output, _, _ = batch
    run(limit=1)
    config_path = output / "configs/baseline.yaml"
    config_path.write_text(config_path.read_text().replace("steps: 50", "steps: 49"))
    with pytest.raises(ValueError, match="configuration changed"):
        run(resume=True)
    assert len(state["calls"]) == 1


def test_reference_input_context_and_plan_hash_are_frozen(batch, picture):
    run, state, output, _, _ = batch
    run(limit=1, context={"selection_sha256": "a"})
    with pytest.raises(ValueError, match="plan/input/reference/configuration changed"):
        run(resume=True, context={"selection_sha256": "b"})
    picture.write_bytes(b"different-input")
    with pytest.raises(ValueError, match="plan/input/reference/configuration changed"):
        run(resume=True, context={"selection_sha256": "a"})
    assert len(state["calls"]) == 1


def test_reference_mutation_rejects_resume_before_any_child(batch, tmp_path):
    run, state, _, manifest, _ = batch
    reference = tmp_path / "reference.glb"
    reference.write_bytes(b"reference-placeholder-not-used-by-generation")
    manifest.write_text(manifest.read_text().replace(",,real", ",reference.glb,real"))
    run(limit=1)
    reference.write_bytes(b"changed-reference")
    with pytest.raises(ValueError, match="plan/input/reference/configuration changed"):
        run(resume=True)
    assert len(state["calls"]) == 1


def test_legacy_plan_and_corrupt_plan_hash_refused(batch):
    run, state, output, _, _ = batch
    output.mkdir()
    save_json(output / "experiment.json", {"plan": {"configs": []}, "plan_sha256": "legacy"})
    with pytest.raises(ValueError, match="Legacy.*new output directory"):
        run(resume=True)
    assert not state["calls"]


def test_overlapping_batch_is_rejected(batch):
    run, state, output, _, _ = batch
    output.mkdir()
    with (output / ".batch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="locked by another batch"):
            run()
    assert not state["calls"]


def test_plan_hash_tampering_refused_before_child(batch):
    run, state, output, _, _ = batch
    run(limit=1)
    path = output / "experiment.json"
    record = json.loads(path.read_text())
    record["plan"]["protocol"] = "tampered"
    assert record["plan_sha256"] != object_hash(record["plan"])
    save_json(path, record)
    with pytest.raises(ValueError, match="plan hash changed"):
        run(resume=True)
    assert len(state["calls"]) == 1
