"""提交作业前核验 10 个开发对象及其原图和参考模型。"""
import argparse
import json
from pathlib import Path

from PIL import Image

from asset3d.data import read_manifest

ROOT = Path(__file__).resolve().parents[1]


def check(manifest):
    expected = json.loads((ROOT / "data/manifests/gso-dev-v1-frozen-hashes.json").read_text(encoding="utf-8"))
    rows = read_manifest(manifest, "dev")
    if len(rows) != 10 or {row["id"] for row in rows} != set(expected):
        raise ValueError("开发集必须与冻结的 10 个 GSO 对象一致")
    for row in rows:
        for field in ("image_sha256", "reference_sha256"):
            if row[field] != expected[row["id"]][field]:
                raise ValueError(f"{row['id']} 的 {field} 与混元开发集记录不一致")
        # TRELLIS.2 需要透明背景；检查透明和可见像素都存在。
        with Image.open(row["image"]) as image:
            low, high = image.convert("RGBA").getchannel("A").getextrema()
            if low == 255 or high == 0:
                raise ValueError(f"{row['id']} 需要包含透明背景和可见前景的 PNG")
    print("开发集检查通过：10 个对象，图片和参考网格与混元记录一致。")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    args = parser.parse_args()
    check(args.manifest)
