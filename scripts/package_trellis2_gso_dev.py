"""将已核验的 10 个开发对象打包，供独立服务器账户上传。"""
import argparse
import csv
import io
import tarfile
from pathlib import Path

from check_trellis2_gso_dev import check


def package(manifest, output):
    rows = check(manifest)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # 重新生成只含开发集的清单，路径相对于解压后的 data/manifests。
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["id", "image", "reference", "split"], lineterminator="\n")
    writer.writeheader()
    for row in rows:
        ident = row["id"]
        writer.writerow({"id": ident, "image": f"../rendered/gso-formal-v1/{ident}/view-000.png",
                         "reference": f"../rendered/gso-formal-v1/{ident}/reference_normalized.glb",
                         "split": "dev"})
    content = buffer.getvalue().encode("utf-8")
    with tarfile.open(output, "w:gz") as archive:
        info = tarfile.TarInfo("data/manifests/gso-dev-v1.csv")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
        for row in rows:
            for key, filename in (("image", "view-000.png"), ("reference", "reference_normalized.glb")):
                target = f"data/rendered/gso-formal-v1/{row['id']}/{filename}"
                archive.add(row[key], arcname=target, recursive=False)
    print(f"数据包已生成：{output}（{output.stat().st_size / 1048576:.1f} MiB）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="打包已核验的 GSO 开发集")
    parser.add_argument("--manifest", required=True, help="原始 30 对象清单")
    parser.add_argument("--output", default="dist/trellis2-gso-dev-data.tar.gz")
    args = parser.parse_args()
    package(args.manifest, args.output)
