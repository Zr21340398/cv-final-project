from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def prepare_image(path, config, remover=None):
    # 先按照片的方向信息转正，再统一成 RGBA；A 通道保存物体与透明背景的边界。
    with Image.open(Path(path)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    if min(image.size) < 32:
        raise ValueError("Input image must be at least 32 pixels on each side")
    alpha = np.asarray(image.getchannel("A"))
    if alpha.max() == 0:
        raise ValueError("Input image is fully transparent")
    # A=0 表示透明，A=255 表示完全可见；已有透明背景的图片可以跳过抠图。
    masked = alpha.min() < 255 and alpha.max() > 0
    mode = config["background"]
    if mode == "remove" or (mode == "auto" and not masked):
        if remover is None:
            raise RuntimeError(
                "Background removal is required; install the Hunyuan environment or supply a masked PNG"
            )
        image = remover(image.convert("RGB")).convert("RGBA")
    # 找到可见物体的范围，裁掉多余背景；这里处理的是二维图片。
    box = image.getchannel("A").getbbox()
    if box is None:
        raise ValueError("No foreground remains after background removal")
    image = image.crop(box)
    # 先居中放入正方形透明画布再缩放，保留物体长宽比例，并留出少量边距。
    side = max(1, round(max(image.size) * (1 + 2 * config["padding"])))
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas.resize((config["size"], config["size"]), Image.Resampling.LANCZOS)
