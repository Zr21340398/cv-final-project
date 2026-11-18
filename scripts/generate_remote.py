"""两种模式共用的单图预处理与推理执行器。"""
import json
import sys
from copy import deepcopy
from pathlib import Path
from PIL import Image, ImageOps
from asset3d.backends.trellis2 import TrellisBackend
from asset3d.config import load_config
from asset3d.pipeline import Pipeline
from asset3d.job_spec import validate
from asset3d.recording import save_json
from asset3d.viewer_manifest import attach_gso_references


def execute(job):
    spec = json.loads((job/'request.json').read_text(encoding='utf-8'))
    total = validate(spec)
    # 作业脚本先 cd 到服务器项目根目录，直接读取共享数据。
    inputs = Path.cwd()/'datasets/gso-v1/data/raw/gso' if 'dataset' in spec else job/'inputs'
    base = load_config(Path(__file__).resolve().parent/'configs/trellis2_gso_dev.yaml')
    results = job/'results'
    results.mkdir(exist_ok=True)
    viewer = {'schema_version':1,'id':spec['name'],'label':spec['name'],
              'objects':[], 'variants':[], 'runs':[]}
    failures = []
    done = 0
    for i, name in enumerate(spec['images']):
        viewer['objects'].append({'id':f'image_{i:03d}','label':name,'reference':None})
    attach_gso_references(viewer, spec, Path.cwd(), results)
    shared = spec.get('export_plugin') == 'shared_lod'
    for index, variant in enumerate(spec['variants']):
        c = deepcopy(base)
        c['name'] = variant['name']
        for key in ('decimation_target','texture_size'):
            if key in variant:
                c['texture'][key] = variant[key]
        viewer['variants'].append({'id':c['name'],'label':c['name'],'config':c})
        if shared and index > 0:
            continue
        backend = TrellisBackend(c)
        backend.begin()
        backend.load_shape()
        pipeline = Pipeline(c,backend)
        for i, name in enumerate(spec['images']):
            ident = f'image_{i:03d}'
            masked_path = job/'prepared'/f'{ident}.png'
            if not masked_path.exists():
                import torch
                import numpy as np
                with Image.open(inputs/name) as opened:
                    image = ImageOps.exif_transpose(opened).convert('RGBA')
                image.thumbnail((2048,2048))
                # 已有透明前景时保留蒙版；普通照片使用同一个官方抠图模型。
                if image.getchannel('A').getextrema()[0] == 255:
                    with torch.inference_mode():
                        remover = backend.pipeline.rembg_model
                        remover.to(backend.pipeline.device)
                        try:
                            image = remover(image.convert('RGB')).convert('RGBA')
                        finally:
                            remover.cpu()
                if not (np.asarray(image.getchannel('A')) > 204).any():
                    raise ValueError(f'{name}: 未识别出前景')
                masked_path.parent.mkdir(exist_ok=True)
                image.save(masked_path)
            for seed in spec['seeds']:
                relative = f'{c["name"]}/{ident}/seed-{seed}'
                run = {'object':ident,'variant':c['name'],'seed':seed,'status':'failed','models':{}}
                status(job, f'生成 {done+1}/{total}：{name} / {c["name"]} / {seed}')
                try:
                    pipeline.run(masked_path,results/relative,seed=seed)
                    run.update(status='completed',input=relative+'/input.png',
                               models={'asset':relative+'/asset.glb','shape':relative+'/shape_raw.glb'})
                except Exception as error:
                    failures.append({'run':relative,'error':str(error)})
                viewer['runs'].append(run)
                if shared:
                    from asset3d.lod_export import export_levels
                    extra = spec['variants'][1:]
                    if run['status'] == 'completed':
                        derived = export_levels(backend,extra,relative,results,ident,seed)
                    else:
                        derived = (dict(object=ident,variant=v['name'],seed=seed,status='failed',
                                        models={},error='基准生成失败') for v in extra)
                    for item in derived:
                        viewer['runs'].append(item)
                        if item['status'] == 'failed':
                            failures.append({'run':f"{item['variant']}/{ident}/seed-{seed}",'error':item['error']})
                        done += 1
                done += 1
                save_json(results/'viewer-manifest.json',viewer)
                save_json(results/'failures.json',failures)
        # 方案间释放 GPU 内存，避免多套模型同时驻留。
        del pipeline, backend
        import gc
        import torch
        gc.collect()
        torch.cuda.empty_cache()
    save_json(results/'viewer-manifest.json',viewer)
    status(job,'完成',failures=failures)


def status(job,state,**extra):
    save_json(job/'status.json',{'state':state,**extra})


if __name__ == '__main__':
    job = Path(sys.argv[1]).resolve()
    try:
        status(job,'加载模型')
        execute(job)
    except Exception as error:
        status(job,'失败',error=str(error))
        raise
