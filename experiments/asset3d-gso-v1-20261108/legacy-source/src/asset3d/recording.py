import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 完整写入临时 JSON 后再替换正式文件，降低中断造成记录损坏的风险。
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def environment():
    versions = {}
    for package in [
        "maie5421-asset3d",
        "numpy",
        "scipy",
        "Pillow",
        "trimesh",
        "torch",
        "diffusers",
        "transformers",
        "gradio",
    ]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    project_root = Path(__file__).resolve().parents[2]

    def git(*args):
        try:
            return subprocess.check_output(
                ["git", "-C", str(project_root), *args], stderr=subprocess.DEVNULL, text=True, timeout=10
            ).strip()
        except (OSError, subprocess.SubprocessError):
            return None

    # 对源文件的完整内容计算摘要，注释改动也会改变摘要；更新后应新建实验计划。
    source_files = sorted(project_root.glob("src/asset3d/**/*.py"))
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": versions,
        "project_commit": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain"),
        "source_hash": object_hash({str(p.relative_to(project_root)): file_hash(p) for p in source_files}),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "host": platform.node(),
    }
