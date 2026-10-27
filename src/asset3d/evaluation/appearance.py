import csv
import json
import random
import shutil
from pathlib import Path

from ..recording import save_json


def build_study(experiment_root, output, seed=2026):
    root, output = Path(experiment_root), Path(output)
    plan = json.loads((root / "experiment.json").read_text(encoding="utf-8"))["plan"]
    items = []
    for config in plan["configs"]:
        for obj in plan["objects"]:
            for run_seed in plan["seeds"]:
                run = root / config["name"] / obj["id"] / f"seed-{run_seed}"
                if (run / "manifest.json").exists():
                    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                    if m["status"] == "completed":
                        views = sorted((run / "preview").glob("view-*.png"))
                        if not views:
                            raise ValueError(f"Render fixed views before creating the study: {run}")
                        items.append((config["name"], obj["id"], run_seed, run, views))
    if not items:
        raise ValueError("No completed rendered runs")
    random.Random(seed).shuffle(items)
    output.mkdir(parents=True, exist_ok=False)
    key, rows = [], []
    for i, (config, ident, run_seed, run, views) in enumerate(items):
        code = f"sample-{i + 1:04d}"
        folder = output / "public" / code
        folder.mkdir(parents=True)
        shutil.copy2(run / "input.png", folder / "input.png")
        for view in views:
            shutil.copy2(view, folder / view.name)
        key.append({"sample": code, "config": config, "object": ident, "seed": run_seed})
        rows.append(
            {
                "rater": "",
                "sample": code,
                "texture_clarity": "",
                "seams": "",
                "multiview_consistency": "",
                "semantic_match": "",
                "notes": "",
            }
        )
    save_json(output / "private-key.json", key)
    with (output / "public" / "ratings-template.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "public" / "README.txt").write_text(
        "每位评价者复制一份评分表并填写 rater。不要向评价者提供 private-key.json。\n"
        "评分 1–5，全部越高越好：纹理清晰度、接缝不明显程度、多视角协调性、与输入物体语义一致性。\n"
        "1=严重错误；2=明显问题；3=基本可用；4=轻微问题；5=无明显问题。\n"
        "统一显示尺寸，查看全部固定视角；只根据可观察内容评价，不假设背面真值。\n",
        encoding="utf-8",
    )
    return output
