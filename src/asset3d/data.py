import csv
import random
import re
from pathlib import Path

from .recording import file_hash


def read_manifest(path, split=None):
    path = Path(path).resolve()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", "image", "reference", "split"} <= set(reader.fieldnames or []):
            raise ValueError("Manifest columns required: id,image,reference,split")
        rows = list(reader)
    ids = set()
    for row in rows:
        ident = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ident) or ident in ids:
            raise ValueError(f"Unsafe or duplicate object ID: {ident}")
        ids.add(ident)
        if row["split"] not in ("dev", "test", "real"):
            raise ValueError(f"Unknown split for {ident}")
        if not row["image"]:
            raise ValueError(f"Missing image for {ident}")
        for key in ("image", "reference"):
            if row[key]:
                p = (path.parent / row[key]).resolve()
                if not p.is_file():
                    raise FileNotFoundError(p)
                row[key] = str(p)
                row[key + "_sha256"] = file_hash(p)
            else:
                row[key] = None
        if row["split"] != "real" and row["reference"] is None:
            raise ValueError(f"Reference mesh required for {ident}")
    return [r for r in rows if split is None or r["split"] == split]


def split_catalog(catalog, output, dev_count=10, seed=2026):
    """Catalog has unique object IDs, image and reference paths; never randomly split views."""
    catalog, output = Path(catalog).resolve(), Path(output).resolve()
    with catalog.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", "image", "reference"} <= set(reader.fieldnames or []):
            raise ValueError("Catalog requires id,image,reference")
        rows = list(reader)
    if not 0 < dev_count < len(rows):
        raise ValueError("dev_count must leave at least one development and one test object")
    rows = sorted(rows, key=lambda r: r["id"])
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("One row per unique object is required")
    for row in rows:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["id"]):
            raise ValueError(f"Unsafe object ID: {row['id']}")
        for key in ("image", "reference"):
            if not row[key] or not (catalog.parent / row[key]).is_file():
                raise FileNotFoundError(f"Missing {key} for {row['id']}")
    random.Random(seed).shuffle(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "image", "reference", "split"])
        writer.writeheader()
        for i, row in enumerate(rows):
            writer.writerow(
                {
                    "id": row["id"],
                    "split": "dev" if i < dev_count else "test",
                    **{k: str((catalog.parent / row[k]).resolve()) for k in ("image", "reference")},
                }
            )
    return output
