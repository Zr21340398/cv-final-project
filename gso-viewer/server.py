"""Local-only viewer for the GSO experiment; no models are modified."""
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
DEFAULT_PROJECT = HERE.parent
DEFAULT_ROOT = DEFAULT_PROJECT / "asset3d-gso-v1-20261108/results/gso-dev-v1"
OBJECT_RE = re.compile(r"gso_[0-9]{2}")
STEP_RE = re.compile(r"hunyuan2_steps([0-9]+)")
SEED_RE = re.compile(r"seed-([0-9]+)")


def within(root: Path, candidate: Path) -> Path:
    """Resolve links and keep reads inside the selected experiment directory."""
    result = candidate.resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Path outside root")
    return result


def labels_from_csv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["id"]: row.get("display_name", row["id"]) for row in csv.DictReader(stream)}


def catalog(root: Path, labels: dict[str, str]) -> dict:
    objects, steps, seeds = set(), set(), set()
    for step_dir in root.iterdir():
        match = STEP_RE.fullmatch(step_dir.name)
        if not match or not step_dir.is_dir():
            continue
        within(root, step_dir)
        steps.add(int(match.group(1)))
        for obj in step_dir.iterdir():
            if not OBJECT_RE.fullmatch(obj.name) or not obj.is_dir():
                continue
            within(root, obj)
            objects.add(obj.name)
            for seed in obj.iterdir():
                match_seed = SEED_RE.fullmatch(seed.name)
                if match_seed and seed.is_dir():
                    within(root, seed)
                    seeds.add(int(match_seed.group(1)))
    return {"objects": [{"id": x, "label": labels.get(x, x)} for x in sorted(objects)],
            "steps": sorted(steps), "seeds": sorted(seeds)}


def resource(root: Path, query: str, image: bool = False) -> Path:
    params = parse_qs(query, keep_blank_values=True)
    def one(name: str) -> str:
        values = params.get(name, [])
        if len(values) != 1:
            raise ValueError("Invalid parameter: " + name)
        return values[0]
    obj, step, seed = one("object"), one("step"), one("seed")
    if not OBJECT_RE.fullmatch(obj) or not re.fullmatch(r"[0-9]{1,3}", step) or not re.fullmatch(r"[0-9]{1,10}", seed):
        raise ValueError("Invalid selection")
    name = "input.png" if image else {"asset": "asset.glb", "shape": "shape_raw.glb"}.get(one("kind"))
    if name is None:
        raise ValueError("Invalid model type")
    return within(root, root / f"hunyuan2_steps{step}" / obj / f"seed-{seed}" / name)


def make_handler(root: Path, labels: dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                if parsed.path == "/api/catalog":
                    payload = json.dumps(catalog(root, labels), ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if parsed.path in ("/api/model", "/api/input"):
                    path = resource(root, parsed.query, image=parsed.path.endswith("input"))
                else:
                    route = {"/": "frontend/index.html", "/index.html": "frontend/index.html",
                             "/style.css": "frontend/style.css", "/app.js": "frontend/app.js",
                             "/vendor/babylon.js": "vendor/babylon.js",
                             "/vendor/babylonjs.loaders.min.js": "vendor/babylonjs.loaders.min.js"}
                    if parsed.path not in route:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    path = within(HERE, HERE / route[parsed.path])
                if not path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "File missing")
                    return
                data = path.read_bytes()
                kind = "model/gltf-binary" if path.suffix == ".glb" else mimetypes.guess_type(path.name)[0]
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", kind or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (ValueError, OSError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid path or selection")
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local GSO GLB viewer")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Experiment result directory")
    parser.add_argument("--labels", type=Path, default=DEFAULT_PROJECT / "data/manifests/gso-selection.csv")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the browser automatically")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"Result directory does not exist: {root}. Use --root to specify it.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(root, labels_from_csv(args.labels)))
    print(f"Open http://127.0.0.1:{server.server_port}/  (Ctrl+C to stop)", flush=True)
    if args.open:
        threading.Timer(0.5, webbrowser.open, args=(f"http://127.0.0.1:{server.server_port}/",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
