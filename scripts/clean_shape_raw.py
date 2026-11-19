"""列出或删除 experiments 下的白模；默认仅预览。"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "experiments"

def main():
    parser = argparse.ArgumentParser(description="清理实验目录中的 shape_raw.glb")
    parser.add_argument("--delete", action="store_true", help="执行删除；省略时只列出文件")
    args = parser.parse_args()
    files = sorted(p for p in ROOT.rglob("shape_raw.glb") if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(ROOT.resolve()))
    total = 0
    for path in files:
        size = path.stat().st_size
        print(path.relative_to(ROOT), size, "bytes")
        if args.delete:
            path.unlink()
        total += size
    print("Deleted" if args.delete else "Preview", len(files), "files,", total, "bytes")

if __name__ == "__main__":
    main()
