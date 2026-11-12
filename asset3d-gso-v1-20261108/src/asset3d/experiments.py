"""Frozen matrices with one bounded Python process per sample."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import yaml

from .config import load_config
from .data import read_manifest
from .recording import environment, file_hash, now, object_hash, save_json

PROTOCOL = "fresh Python process per config/object/seed; explicit retries; version 1"


def _verify_inputs(rows):
    for row in rows:
        for key in ("image", "reference"):
            if row.get(key) and file_hash(row[key]) != row[key + "_sha256"]:
                raise ValueError(f"Frozen {key} changed: {row['id']}")


def _verify_plan(root, plan, resume):
    path = root / "experiment.json"
    if not path.exists():
        return False
    previous = json.loads(path.read_text(encoding="utf-8"))
    frozen = previous["plan"]
    if "source_hash" not in frozen:
        raise ValueError("Legacy experiment has no frozen source_hash; choose a new output directory")
    if not resume:
        raise ValueError("Experiment already exists; use --resume or choose a new output directory")
    if previous.get("plan_sha256") != object_hash(frozen):
        raise ValueError("Frozen experiment plan hash changed; choose a new output directory")
    if frozen["source_hash"] != plan["source_hash"]:
        raise ValueError("Experiment source code changed; choose a new output directory")
    if object_hash(frozen) != object_hash(plan):
        raise ValueError(
            "Experiment plan/input/reference/configuration changed; choose a new output directory"
        )
    for config in plan["configs"]:
        if load_config(root / "configs" / f"{config['name']}.yaml") != config:
            raise ValueError(f"Frozen configuration changed: {config['name']}")
    return True


def _validate_artifacts(directory, config, row, seed, source_hash, require_complete=False):
    path = directory / "manifest.json"
    if not path.exists():
        if require_complete:
            raise ValueError("Child returned success without a completed manifest")
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    identity = {"input_sha256": row["image_sha256"], "config_sha256": object_hash(config), "seed": seed}
    if manifest["identity"] != identity or manifest["environment"]["source_hash"] != source_hash:
        raise ValueError("Run identity/source does not match the frozen plan")
    for name, digest in manifest["artifacts"].items():
        if name not in {"input.png", "foreground.png", "shape_raw.glb", "asset.glb"}:
            raise ValueError(f"Unknown cached artifact: {name}")
        if file_hash(directory / name) != digest:
            raise ValueError(f"Cached artifact is missing or changed: {name}")
    complete = manifest.get("status") in ("completed", "shape_only")
    if require_complete and not complete:
        raise ValueError("Child returned success without a completed manifest")
    if complete:
        from .export import check_glb

        textured = config["texture"]["enabled"]
        if manifest["status"] != ("completed" if textured else "shape_only"):
            raise ValueError("Completion status does not match the configured output")
        required = {"input.png", "foreground.png", "shape_raw.glb"}
        if textured:
            required.add("asset.glb")
        if not required <= manifest["artifacts"].keys():
            raise ValueError("Completed run has missing artifact hashes")
        check_glb(directory / "shape_raw.glb", require_texture=False)
        if textured:
            check_glb(directory / "asset.glb", require_texture=True)
    return manifest


def _clear_child_lock(path, child_pid, token, existed):
    """Only after wait(): never remove an unknown or pre-existing lock."""
    if existed or not path.exists():
        return False
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
        if owner.get("pid") == child_pid and owner.get("run_token") == token:
            path.unlink()
            return True
    except (OSError, ValueError, TypeError):
        pass
    return False


def _terminate_child(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # The process may have exited between the timeout and kill.
    child.wait()


def run_experiments(
    manifest_path,
    config_paths,
    seeds,
    output,
    split="test",
    resume=False,
    *,
    timeout=3600,
    limit=None,
    retry_failed=False,
    dry_run=False,
    context=None,
):
    """Run the first ``limit`` planned cells, counting skipped cells too.

    Resume validates/skips successes. Failed or interrupted cells additionally
    require retry_failed. Timeout/limit are operational, not plan mutations.
    """
    if type(timeout) is not int or timeout < 1:
        raise ValueError("timeout must be a positive integer number of seconds")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    if retry_failed and not resume:
        raise ValueError("retry_failed requires resume")
    rows = read_manifest(manifest_path, split)
    if not rows:
        raise ValueError(f"No objects in split {split}")
    configs = [load_config(p) for p in config_paths]
    if not configs:
        raise ValueError("At least one configuration is required")
    if len({c["name"] for c in configs}) != len(configs) or len(set(seeds)) != len(seeds):
        raise ValueError("Configuration names and seeds must be unique")
    if not seeds or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds):
        raise ValueError("Seeds must be distinct integers in [0, 2**32)")
    source_hash = environment()["source_hash"]
    plan = {
        "manifest_sha256": file_hash(manifest_path),
        "objects": rows,
        "split": split,
        "configs": configs,
        "seeds": seeds,
        "source_hash": source_hash,
        "protocol": PROTOCOL,
    }
    if context is not None:
        plan["context"] = context
    object_hash(plan)  # Validate JSON context before making directories.
    root = Path(output).resolve()
    _verify_inputs(rows)
    _verify_plan(root, plan, resume)
    total = len(configs) * len(rows) * len(seeds)
    selected = min(total, limit) if limit is not None else total
    print(
        f"Experiment: {total} planned, {selected} selected, timeout={timeout}s per cell; "
        f"upper generation budget={selected * timeout}s",
        flush=True,
    )
    if dry_run:
        if not (root / "experiment.json").exists() and root.exists() and any(root.iterdir()):
            raise FileExistsError("New experiment output must be empty")
        return []

    root.mkdir(parents=True, exist_ok=True)
    # Keep the inode in place; the OS releases flock even if the parent is killed.
    with (root / ".batch.lock").open("a+", encoding="utf-8") as batch_lock:
        try:
            fcntl.flock(batch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Experiment is locked by another batch: {root / '.batch.lock'}") from exc
        batch_lock.seek(0)
        batch_lock.truncate()
        json.dump(
            {
                "pid": os.getpid(),
                "run_token": uuid.uuid4().hex,
                "started_at": now(),
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            },
            batch_lock,
        )
        batch_lock.flush()
        existed = _verify_plan(root, plan, resume)
        if not existed:
            if any(p.name != ".batch.lock" for p in root.iterdir()):
                raise FileExistsError("New experiment output must be empty")
            for config in configs:
                path = root / "configs" / f"{config['name']}.yaml"
                path.parent.mkdir(exist_ok=True)
                path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            save_json(
                root / "experiment.json",
                {
                    "created_at": now(),
                    "plan_sha256": object_hash(plan),
                    "plan": plan,
                },
            )
        failures = []
        cells = ((c, row, seed) for c in configs for row in rows for seed in seeds)
        for index, (config, row, seed) in enumerate(cells):
            if index == selected:
                break
            if environment()["source_hash"] != source_hash:
                raise ValueError("Experiment source code changed; stop and choose a new output directory")
            directory = root / config["name"] / row["id"] / f"seed-{seed}"
            process_dir = root / "process-logs" / config["name"]
            process_dir.mkdir(parents=True, exist_ok=True)
            record_path = process_dir / f"{row['id']}-seed-{seed}.json"
            record = (
                json.loads(record_path.read_text(encoding="utf-8"))
                if record_path.exists()
                else {"attempts": []}
            )
            previous = [a for a in record["attempts"] if a["status"] != "skipped"]
            token = uuid.uuid4().hex
            command = [
                sys.executable,
                "-m",
                "asset3d.cli",
                "generate",
                "--image",
                row["image"],
                "--config",
                str(root / "configs" / f"{config['name']}.yaml"),
                "--output",
                str(directory),
                "--seed",
                str(seed),
            ]
            if resume:
                command.append("--resume")
            attempt = {
                "started_at": now(),
                "status": "running",
                "command": command,
                "timeout_seconds": timeout,
                "run_token": token,
            }
            record["attempts"].append(attempt)
            save_json(record_path, record)
            start = time.perf_counter()
            child = None
            lock_path = directory / ".running.lock"
            lock_existed = lock_path.exists()
            try:
                attempt["phase"] = "validation"
                if lock_existed:
                    raise RuntimeError(f"Run is locked; inspect the existing job before cleanup: {lock_path}")
                _verify_inputs([row])
                manifest = _validate_artifacts(directory, config, row, seed, source_hash)
                if manifest and manifest["status"] in ("completed", "shape_only"):
                    attempt.update(status="skipped", reason="already_completed", artifacts_validated=True)
                elif (
                    previous or (manifest and manifest.get("status") in ("failed", "running"))
                ) and not retry_failed:
                    attempt.update(status="skipped", reason="previous_failure_requires_retry", blocking=True)
                else:
                    attempt["phase"] = "generation"
                    child_env = dict(os.environ, ASSET3D_RUN_TOKEN=token)
                    with (process_dir / f"{row['id']}-seed-{seed}.log").open("a", encoding="utf-8") as log:
                        child = subprocess.Popen(
                            command,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            env=child_env,
                            start_new_session=True,
                        )
                        attempt["child_pid"] = child.pid
                        save_json(record_path, record)
                        try:
                            code = child.wait(timeout=timeout)
                        except subprocess.TimeoutExpired:
                            _terminate_child(child)
                            attempt.update(status="timeout", returncode=child.returncode)
                            attempt["lock_cleaned"] = _clear_child_lock(
                                lock_path, child.pid, token, lock_existed
                            )
                        else:
                            attempt["returncode"] = code
                            if code:
                                attempt.update(status="failed", error=f"Child exited with code {code}")
                            else:
                                _validate_artifacts(
                                    directory, config, row, seed, source_hash, require_complete=True
                                )
                                attempt["status"] = "completed"
            except Exception as exc:
                attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                if child is not None and child.poll() is None:
                    _terminate_child(child)
                    attempt.update(status="failed", error="Parent interrupted before child completion")
                    attempt["lock_cleaned"] = _clear_child_lock(lock_path, child.pid, token, lock_existed)
                attempt["wall_seconds"] = time.perf_counter() - start
                attempt["finished_at"] = now()
                save_json(record_path, record)
            if attempt["status"] in ("failed", "timeout") or attempt.get("blocking"):
                failures.append(
                    {
                        "config": config["name"],
                        "object": row["id"],
                        "seed": seed,
                        "status": attempt["status"],
                        "error": attempt.get("error", attempt.get("reason", "timeout")),
                        "record": str(record_path),
                    }
                )
            print(
                f"{config['name']}/{row['id']}/{seed}: {attempt['status']} {attempt.get('reason', '')}",
                flush=True,
            )
        history_path = root / "failures.json"
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
        history.append(
            {
                "finished_at": now(),
                "timeout_seconds": timeout,
                "limit": limit,
                "retry_failed": retry_failed,
                "failures": failures,
            }
        )
        save_json(history_path, history)
        return failures
