"""GPU 作业内执行单图生成，并写出供本地工作台读取的状态。"""
import json
import sys
from pathlib import Path
from PIL import Image, ImageOps
from asset3d.backends.trellis2 import TrellisBackend
from asset3d.config import load_config
from asset3d.pipeline import Pipeline

job = Path(sys.argv[1]).resolve()
def status(state, error=None):
    temporary = job / 'status.tmp'
    temporary.write_text(json.dumps({'state': state, 'error': error}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(job / 'status.json')

try:
    status('加载模型')
    config = load_config(job / 'code/configs/trellis2_gso_dev.yaml')
    backend = TrellisBackend(config)
    backend.begin()
    backend.load_shape()
    status('抠图')
    import torch
    import numpy as np
    with Image.open(job / 'input') as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048))
    image.save(job / 'source.png')
    with torch.inference_mode():
        remover = backend.pipeline.rembg_model
        remover.to(backend.pipeline.device)
        try:
            masked = remover(image).convert('RGBA')
        finally:
            remover.cpu()
    alpha = np.asarray(masked.getchannel('A'))
    if alpha.min() == 255 or not (alpha > 204).any():
        raise ValueError('没有识别出有效前景，请使用主体清楚的图片')
    masked.save(job / 'masked.png')
    status('生成形状与材质并导出')
    Pipeline(config, backend).run(job / 'masked.png', job / 'output', seed=42)
    status('完成')
except Exception as error:
    status('失败', str(error))
    raise
