#!/usr/bin/env python3
"""Build paired, eight-view contact sheets from existing local pilot renders.

Requires Pillow. No network requests, image rotation, mirroring, or model calls.
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CELL = 224
LABEL_WIDTH = 210
GAP = 8
CAPTION_HEIGHT = 28
HEADER_HEIGHT = CELL + 36
BACKGROUND = (210, 210, 210)
INK = (28, 32, 38)
ROWS = (
    ("hunyuan2", "white_preview", "Hunyuan", "raw white"),
    ("trellis2", "white_preview", "TRELLIS", "raw white"),
    ("hunyuan2", "preview", "Hunyuan", "final textured"),
    ("trellis2", "preview", "TRELLIS", "final textured"),
)
SEED_DIRECTORY = re.compile(r"seed-([0-9]+)$")


def ascii_label(value):
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def font(size):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Older Pillow versions do not accept the size argument.
        return ImageFont.load_default()


def find_pairs(results, evaluation):
    pairs = set()
    for root in (results, evaluation):
        for model in ("hunyuan2", "trellis2"):
            model_dir = root / model
            if not model_dir.is_dir():
                continue
            for object_dir in model_dir.iterdir():
                if not object_dir.is_dir():
                    continue
                for seed_dir in object_dir.iterdir():
                    match = SEED_DIRECTORY.fullmatch(seed_dir.name)
                    if seed_dir.is_dir() and match:
                        pairs.add((object_dir.name, int(match.group(1))))
    return sorted(pairs)


def thumbnail(path):
    """Fit without orientation changes and alpha-composite on the same gray."""
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        rgba.thumbnail((CELL, CELL), Image.Resampling.LANCZOS)
        tile = Image.new("RGBA", (CELL, CELL), (*BACKGROUND, 255))
        tile.alpha_composite(rgba, ((CELL - rgba.width) // 2, (CELL - rgba.height) // 2))
    return tile.convert("RGB")


def atomic_json(path, value):
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_pair(results, evaluation, output, object_id, seed):
    seed_name = f"seed-{seed}"
    required = []
    row_sources = []
    for model, variant, model_label, variant_label in ROWS:
        paths = [Path(model) / object_id / seed_name / variant / f"view-{angle:03d}.png" for angle in range(8)]
        required.extend(paths)
        row_sources.append({
            "model": model, "variant": variant,
            "label": f"{model_label} {variant_label}",
            "views": [{"angle_index": angle, "path": path.as_posix()} for angle, path in enumerate(paths)],
        })
    missing = [path.as_posix() for path in required if not (evaluation / path).is_file()]
    input_candidates = [Path(model) / object_id / seed_name / "input.png" for model in ("hunyuan2", "trellis2")]
    input_relative = next((path for path in input_candidates if (results / path).is_file()), None)
    if missing or input_relative is None:
        return None, {
            "object_id": object_id, "seed": seed, "reason": "missing_files",
            "required_views": 32, "available_views": 32 - len(missing),
            "missing_evaluation_paths": missing,
            "missing_input_candidates": [path.as_posix() for path in input_candidates] if input_relative is None else [],
        }

    width = LABEL_WIDTH + 8 * CELL + 9 * GAP
    row_height = CELL + CAPTION_HEIGHT + GAP
    sheet = Image.new("RGB", (width, HEADER_HEIGHT + 4 * row_height + GAP), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    title_font, row_font, caption_font = font(24), font(19), font(15)
    try:
        sheet.paste(thumbnail(results / input_relative), (GAP, GAP))
        title_x = CELL + 3 * GAP
        draw.text((title_x, 22), f"Object: {ascii_label(object_id)}    Seed: {seed}", fill=INK, font=title_font)
        draw.text((title_x, 70), "Input image", fill=INK, font=row_font)
        draw.text((title_x, 108), "Columns: view 0 to view 7 (source order)", fill=INK, font=caption_font)
        draw.text((title_x, 140), "Same gray alpha background; no mirror or rotation", fill=INK, font=caption_font)
        for row_index, ((_, _, model_label, variant_label), sources) in enumerate(zip(ROWS, row_sources)):
            y = HEADER_HEIGHT + row_index * row_height
            draw.text((GAP, y + CELL // 2 - 30), model_label, fill=INK, font=row_font)
            draw.text((GAP, y + CELL // 2), variant_label, fill=INK, font=row_font)
            for view in sources["views"]:
                angle = view["angle_index"]
                x = LABEL_WIDTH + GAP + angle * (CELL + GAP)
                sheet.paste(thumbnail(evaluation / view["path"]), (x, y))
                draw.text((x + 8, y + CELL + 3), f"view {angle}", fill=INK, font=caption_font)
    except (OSError, ValueError) as exc:
        return None, {
            "object_id": object_id, "seed": seed, "reason": "unreadable_image",
            "available_views": 32, "error": type(exc).__name__,
        }

    filename = f"{object_id}-seed-{seed}.jpg"
    handle = tempfile.NamedTemporaryFile(suffix=".jpg", dir=output, delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        sheet.save(temporary, format="JPEG", quality=92, subsampling=0, optimize=True)
        os.replace(temporary, output / filename)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "object_id": object_id, "seed": seed, "jpeg": filename,
        "width": sheet.width, "height": sheet.height,
        "input": {"root": "results", "path": input_relative.as_posix()},
        "view_root": "evaluation", "rows": row_sources,
    }, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="Local pilot03 result directory")
    parser.add_argument("--evaluation", type=Path, required=True, help="Local pilot03 evaluation render directory")
    parser.add_argument("--output", type=Path, required=True, help="JPEG contact sheet and index destination")
    args = parser.parse_args()
    if not args.results.is_dir() or not args.evaluation.is_dir():
        parser.error("--results and --evaluation must be existing directories")
    args.output.mkdir(parents=True, exist_ok=True)
    sheets, incomplete = [], []
    pairs = find_pairs(args.results, args.evaluation)
    for object_id, seed in pairs:
        sheet, missing = build_pair(args.results, args.evaluation, args.output, object_id, seed)
        if sheet:
            sheets.append(sheet)
        else:
            incomplete.append(missing)
    index = {
        "schema_version": 1, "cell_size_px": CELL, "background_rgb": list(BACKGROUND),
        "view_indices": list(range(8)), "source_roots": ["results", "evaluation"],
        "sources_use_relative_paths": True, "discovered_pairs": len(pairs),
        "generated_sheets": sheets, "incomplete": incomplete,
    }
    atomic_json(args.output / "index.json", index)
    print(json.dumps({
        "generated_count": len(sheets), "incomplete_count": len(incomplete),
        "index": "index.json", "incomplete": incomplete,
        "warning": "No object/seed directories found" if not pairs else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
