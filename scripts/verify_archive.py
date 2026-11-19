"""在 CPU 上核验归档实验的全部生成文件。"""
import argparse

from asset3d.archive import verify_archive

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    args = parser.parse_args()
    print(f"已核验 {verify_archive(args.results)} 次完成的运行；所有产物哈希一致。")
