"""从同一份 TRELLIS 原生形状与材质烘焙额外的展示网格。"""
import json
import os
import time
from pathlib import Path

from .export import export_glb
from .recording import file_hash, save_json


def export_levels(backend, variants, baseline, results, ident, seed):
    """逐档返回 viewer 记录。额外导出失败时仍可检查基准和其他档位。"""
    source = Path(results) / baseline
    source_manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    for variant in variants:
        relative = f"{variant['name']}/{ident}/seed-{seed}"
        out = Path(results) / relative
        run = dict(object=ident, variant=variant['name'], seed=seed, status='failed', models={})
        try:
            out.mkdir(parents=True, exist_ok=False)
            settings = dict(source_manifest['config']['texture'])
            settings.update({k:variant[k] for k in ('texture_size','decimation_target') if k in variant})
            start = time.perf_counter()
            mesh = backend.bake_native(settings)
            report = export_glb(mesh, out / 'asset.glb')
            seconds = time.perf_counter() - start
            # 同一 Linux 文件系统内硬链接小图，白模在清单中直接引用基准。
            for name in ('input.png','foreground.png'):
                os.link(source / name, out / name)
            save_json(out / 'manifest.json', {
                'status':'completed', 'source_run':baseline, 'source_identity':source_manifest['identity'],
                'texture':settings, 'export':report, 'export_seconds':seconds,
                'asset_sha256':file_hash(out / 'asset.glb'),
            })
            run.update(status='completed',input=relative+'/input.png',
                       models={'asset':relative+'/asset.glb','shape':baseline+'/shape_raw.glb'})
        except Exception as exc:
            run['error'] = str(exc)
        yield run
