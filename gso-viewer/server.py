"""Serve the local model workbench and explicitly selected experiment data."""
from __future__ import annotations

import argparse
import csv
import hashlib
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
PROJECT = HERE.parent
DEFAULT_ROOT = PROJECT / "asset3d-gso-v1-20261108/results/gso-dev-v1"
DEFAULT_DATA_ROOT = PROJECT
LEGACY_DATA_ROOT = PROJECT / "asset3d-gso-v1-20261108"
DEFAULT_LABELS = PROJECT / "data/manifests/gso-selection.csv"


def within(root: Path, path: Path) -> Path:
    # 所有清单路径最终都要落在用户指定的数据目录，符号链接也不能越界。
    result = path.resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Path outside data root")
    return result


def load_labels(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {r["id"]: r.get("display_name") or r["id"] for r in csv.DictReader(stream)}


def legacy_manifest(root: Path, data_root: Path, labels: dict[str, str]) -> dict | None:
    """Read the existing GSO results without changing its frozen files."""
    if not root.is_dir():
        return None
    objects, variants, runs = {}, {}, []
    reference_csv = data_root / "data/manifests/gso-formal-v1.csv"
    references = {}
    if reference_csv.is_file():
        with reference_csv.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("reference"):
                    references[row["id"]] = reference_csv.parent / row["reference"]
    for variant in sorted(root.iterdir()):
        match = re.fullmatch(r"hunyuan2_steps([0-9]+)", variant.name)
        if not match or not variant.is_dir():
            continue
        within(data_root, variant)
        variants[variant.name] = {"id": variant.name, "label": f"{match.group(1)} 步"}
        for obj in sorted(variant.iterdir()):
            if not re.fullmatch(r"gso_[0-9]{2}", obj.name) or not obj.is_dir():
                continue
            within(data_root, obj)
            objects[obj.name] = {"id": obj.name, "label": labels.get(obj.name, obj.name),
                                 "reference": str(references.get(obj.name, ""))}
            for seed in sorted(obj.iterdir()):
                m = re.fullmatch(r"seed-([0-9]+)", seed.name)
                if not m or not seed.is_dir():
                    continue
                within(data_root, seed)
                status = "pending"
                try:
                    run_manifest = seed / "manifest.json"
                    if run_manifest.is_file():
                        status = json.loads(run_manifest.read_text(encoding="utf-8")).get("status", "pending")
                except (OSError, ValueError):
                    status = "unreadable"
                runs.append({"object": obj.name, "variant": variant.name, "seed": int(m.group(1)),
                             "status": status, "input": str(seed / "input.png"),
                             "models": ({kind: str(seed / name) for kind, name in
                                         (("asset", "asset.glb"), ("shape", "shape_raw.glb"))
                                         if (seed / name).is_file()} if status == "completed" else {})})
    if not runs:
        return None
    return {"schema_version": 1, "id": "gso-dev-v1", "label": "GSO 开发集：混元步数对照",
            "objects": list(objects.values()), "variants": list(variants.values()), "runs": runs}


def load_dataset(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if data.get("schema_version") != 1 or not all(
        isinstance(data.get(key), list) for key in ("objects", "variants", "runs")
    ) or not isinstance(data.get("id"), str):
        raise ValueError(f"Unsupported viewer manifest: {path}")
    return data


class Datasets:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()
        self.items: dict[str, tuple[dict, Path]] = {}

    def add(self, dataset: dict, base: Path) -> None:
        ident = dataset["id"]
        if not isinstance(ident, str) or not ident or ident in self.items:
            raise ValueError(f"Duplicate or invalid dataset id: {ident}")
        self.items[ident] = (dataset, base.resolve())

    def path(self, base: Path, value: str | None) -> Path | None:
        if not value or not isinstance(value, str):
            return None
        path = Path(value)
        if not path.is_absolute():
            path = base / path
        return within(self.data_root, path)

    def available(self, base: Path, value: str | None) -> bool:
        try:
            path = self.path(base, value)
            return bool(path and path.is_file())
        except (OSError, ValueError):
            return False

    def catalog(self) -> dict:
        output = []
        for data, base in self.items.values():
            objects = [{"id": o["id"], "label": o.get("label") or o["id"],
                        "reference": self.available(base, o.get("reference"))} for o in data["objects"]]
            runs, seeds, kinds = [], set(), set()
            for run in data["runs"]:
                # 无随机种子的确定性后处理也作为可选择的一次运行。
                seed = run.get("seed")
                seed = "None" if seed is None else seed
                seeds.add(seed)
                available = [k for k, p in run.get("models", {}).items()
                             if k != "reference" and self.available(base, p) and Path(p).suffix.lower() == ".glb"]
                kinds.update(available)
                runs.append({"object": run["object"], "variant": run["variant"], "seed": seed,
                             "status": run.get("status", "unknown"), "kinds": available})
            # 类型由清单声明；旧清单保留原来的中文显示名称。
            names = {"asset": "带纹理模型", "shape": "原始白模"}
            names.update(data.get("model_types", {}))
            ordered_kinds = [k for k in names if k in kinds] + sorted(kinds - names.keys())
            output.append({"id": data["id"], "label": data.get("label") or data["id"],
                           "objects": objects, "variants": data["variants"], "runs": runs,
                           "seeds": sorted(seeds, key=lambda value: (not isinstance(value, int), value)),
                           "kinds": [{"id": k, "label": names.get(k, k)} for k in ordered_kinds],
                           "reference": any(o["reference"] for o in objects)})
        return {"datasets": output}

    def resolve(self, query: str, image: bool = False) -> Path:
        params = parse_qs(query, keep_blank_values=True)
        def one(name: str) -> str:
            values = params.get(name, [])
            if len(values) != 1:
                raise ValueError("Invalid parameter: " + name)
            return values[0]
        dataset = one("dataset")
        if dataset not in self.items:
            raise FileNotFoundError("Dataset not found")
        data, base = self.items[dataset]
        obj = one("object")
        matches = [o for o in data["objects"] if o["id"] == obj]
        if len(matches) != 1:
            raise FileNotFoundError("Object not found")
        if not image and one("kind") == "reference":
            value = matches[0].get("reference")
        else:
            variant, seed = one("variant"), one("seed")
            runs = [r for r in data["runs"] if r["object"] == obj and r["variant"] == variant
                    and str(r.get("seed")) == seed]
            if len(runs) != 1:
                raise FileNotFoundError("Run not found")
            if image:
                value = runs[0].get("input")
                # 旧索引只记录了对象的第一张输入图。优先从该次运行的模型目录查找，
                # 避免不同方案或种子使用不同输入时，错误显示另一轮的图片。
                if "input" not in runs[0]:
                    for model in runs[0].get("models", {}).values():
                        model_path = self.path(base, model)
                        if model_path:
                            candidate = within(self.data_root, model_path.parent / "input.png")
                            if candidate.is_file():
                                value = str(candidate)
                                break
            else:
                kind = one("kind")
                if kind not in runs[0].get("models", {}):
                    raise FileNotFoundError("Model kind not available in this run")
                value = runs[0].get("models", {}).get(kind)
        path = self.path(base, value)
        expected = (".png", ".jpg", ".jpeg") if image else (".glb",)
        if not path or path.suffix.lower() not in expected or not path.is_file():
            raise FileNotFoundError("File missing")
        return path


class DiscoveredDatasets(Datasets):
    """Refresh only known results-directory levels; never walk all assets."""

    def __init__(self, data_root: Path, manifests: list[Path] | None = None,
                 legacy_root: Path | None = None, labels: Path = DEFAULT_LABELS):
        super().__init__(data_root)
        self.explicit = manifests or []
        self.legacy_root = legacy_root
        self.labels = labels

    def _candidates(self) -> list[Path]:
        if self.explicit:
            return sorted({within(self.data_root, p) for p in self.explicit})
        candidates = set()
        root = self.data_root
        if not root.is_dir():
            return []
        # 支持 results/实验名 和 实验包/results/批次 两种固定结构。
        result_dirs = [root, root / "results"]
        # 新结构：experiments/<批次>/results/viewer-manifest.json。
        experiments = root / "experiments"
        if experiments.is_dir():
            for batch in experiments.iterdir():
                if batch.is_dir():
                    result_dirs.append(batch / "results")
        for child in root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                result_dirs.append(child / "results")
        for parent in result_dirs:
            try:
                if not parent.is_dir():
                    continue
                within(root, parent)
                direct = parent / "viewer-manifest.json"
                if direct.is_file():
                    candidates.add(within(root, direct))
                for child in parent.iterdir():
                    if child.is_dir():
                        path = child / "viewer-manifest.json"
                        if path.is_file():
                            try:
                                candidates.add(within(root, path))
                            except (OSError, ValueError):
                                continue
            except (OSError, ValueError):
                continue
        return sorted(candidates)

    def refresh(self) -> list[str]:
        # 每次刷新先构建新快照，避免页面同时读取半更新的字典。
        fresh = Datasets(self.data_root)
        problems = []
        for path in self._candidates():
            try:
                data = load_dataset(path)
                relative = path.parent.relative_to(self.data_root).as_posix()
                # 目录相同的清单唯一；不同实验即使内部 id 相同也不会冲突。
                data["id"] = "exp-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
                parts = path.parent.relative_to(self.data_root).parts
                shown = [part for part in parts if part != "results"]
                data["label"] = " / ".join(shown) or path.parent.name
                # 校验单份清单的记录结构；异常时隔离该实验，不影响其他预设。
                probe = Datasets(self.data_root)
                probe.add(data, path.parent)
                probe.catalog()
                fresh.add(data, path.parent)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                problems.append(f"{path.parent.relative_to(self.data_root)}: {exc}")
        if not self.explicit and self.legacy_root:
            old = self.legacy_root.resolve()
            try:
                if not (old / "viewer-manifest.json").is_file() and old.is_dir():
                    source_root = LEGACY_DATA_ROOT if self.data_root == PROJECT.resolve() else self.data_root
                    old_data = legacy_manifest(old, source_root, load_labels(self.labels))
                    if old_data:
                        old_data["id"] = "legacy-gso-dev"
                        old_data["label"] = "asset3d-gso-v1-20261108 / gso-dev-v1"
                        fresh.add(old_data, old)
            except (OSError, ValueError, KeyError) as exc:
                problems.append(f"旧实验: {exc}")
        self.items = fresh.items
        return problems


def make_handler(datasets: Datasets):
    class Handler(BaseHTTPRequestHandler):
        def json_response(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # 浏览器必须来自本机工作台；拒绝其他网站跨站触发 GPU 作业。
            origin = self.headers.get('Origin')
            expected = 'http://127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('X-Asset3D') != 'workbench' or origin not in (None, expected):
                self.json_response({'error': 'Invalid origin'}, 403)
                return
            try:
                import generation
                if urlsplit(self.path).path == '/api/generate':
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 20 * 1024 * 1024:
                        raise ValueError('请选择 20 MiB 以内的 JPG 或 PNG 图片')
                    data = self.rfile.read(size)
                    if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')):
                        raise ValueError('仅支持 JPG 或 PNG 图片')
                    params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    def option(name):
                        values = params.get(name, [])
                        if len(values) != 1:
                            raise ValueError('缺少或重复的设置：' + name)
                        return values[0]
                    shape = option('download_shape')
                    if shape not in ('true', 'false'):
                        raise ValueError('下载白模设置无效')
                    options = {'host': option('host'), 'project': option('project'),
                               'time_limit': option('time_limit'), 'download_shape': shape == 'true'}
                    self.json_response(generation.create(data, options), 202)
                elif self.path == '/api/generate-batch':
                    import base64
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0 < size <= 100*1024*1024:
                        raise ValueError('批次上传请求上限 100 MiB')
                    body = json.loads(self.rfile.read(size))
                    images = {name:base64.b64decode(data,validate=True) for name,data in body['images'].items()}
                    self.json_response(generation.create(None,body['connection'],body['experiment'],images),202)
                elif self.path.startswith('/api/generation-retry/'):
                    ident = self.path.rsplit('/', 1)[-1]
                    task = generation.read(ident)
                    if not task.get('job_id'):
                        raise ValueError('任务未记录作业号，请查看连接错误并检查服务器队列后重新提交')
                    generation.launch(ident, generation.update)
                    self.json_response({'ok': True})
                else:
                    self.send_error(404)
            except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                self.json_response({'error': str(error)}, 400)

        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                if parsed.path == '/api/generation-settings':
                    import generation
                    self.json_response(generation.config())
                    return
                if parsed.path == '/api/generation-jobs':
                    import generation
                    self.json_response(generation.tasks())
                    return
                if parsed.path.startswith('/api/generated/'):
                    import generation
                    task = generation.read(parsed.path.rsplit('/',1)[-1])
                    local = generation.location(task)
                    if task.get('local_dir'):
                        index = json.loads((local/'results/viewer-manifest.json').read_text(encoding='utf-8'))
                        runs = [r for r in index['runs'] if r['status'] == 'completed']
                        if not runs:
                            raise FileNotFoundError()
                        path = within(local,local/'results'/runs[0]['models']['asset'])
                    else:
                        path = local/'asset.glb'
                elif parsed.path == "/api/catalog":
                    problems = datasets.refresh() if isinstance(datasets, DiscoveredDatasets) else []
                    listing = datasets.catalog()
                    listing["warnings"] = problems
                    payload = json.dumps(listing, ensure_ascii=False).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                elif parsed.path in ("/api/model", "/api/input"):
                    path = datasets.resolve(parsed.query, image=parsed.path.endswith("input"))
                else:
                    routes = {"/": "frontend/index.html", "/index.html": "frontend/index.html",
                              "/style.css": "frontend/style.css", "/app.js": "frontend/app.js",
                              "/vendor/babylon.js": "vendor/babylon.js",
                              "/vendor/babylonjs.loaders.min.js": "vendor/babylonjs.loaders.min.js"}
                    if parsed.path not in routes:
                        raise FileNotFoundError()
                    path = within(HERE, HERE / routes[parsed.path])
                if not path.is_file():
                    raise FileNotFoundError()
                content = path.read_bytes()
                content_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else (
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND, "File missing")
            except (ValueError, OSError, KeyError, TypeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid selection")
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local 3D model workbench")
    parser.add_argument("--root", type=Path, help="Legacy GSO results directory")
    parser.add_argument("--data-root", type=Path, help="Allowed root containing result and reference files")
    parser.add_argument("--manifest", type=Path, action="append", default=[], help="Experiment viewer manifest")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    # 没有实验数据也可启动页面，手动打开本地 GLB。
    data_root = (args.data_root or (args.root if args.root else DEFAULT_DATA_ROOT)).resolve()
    legacy_root = args.root or (DEFAULT_ROOT if data_root == PROJECT.resolve() else None)
    datasets = DiscoveredDatasets(data_root, args.manifest, legacy_root, args.labels)
    try:
        datasets.refresh()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(datasets))
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
