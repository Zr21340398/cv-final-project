"""Package source only, leaving user course files and local environments untouched."""

import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["src", "configs", "scripts", "slurm", "app", "tests", "docs", "data/manifests"]
FILES = [
    "README.md",
    "pyproject.toml",
    "requirements-hpc.txt",
    "requirements-trellis2.txt",
    "requirements-local.lock.txt",
    ".gitignore",
    ".gitattributes",
]


def main():
    target = ROOT / "dist/asset3d-source.tar.gz"
    target.parent.mkdir(exist_ok=True)
    paths = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    for name in FOLDERS:
        paths.extend(
            p
            for p in (ROOT / name).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and not p.name.endswith(".pyc")
            and not any(part.endswith(".egg-info") for part in p.parts)
        )
    with tarfile.open(target, "w:gz") as archive:
        for path in sorted(set(paths)):
            archive.add(path, arcname="asset3d/" + path.relative_to(ROOT).as_posix(), recursive=False)
    print(target)


if __name__ == "__main__":
    main()
