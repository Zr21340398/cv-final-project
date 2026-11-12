import sys

from asset3d.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["generate", *sys.argv[1:]]))
