"""两种模式共用的单图预处理与推理执行器。"""
import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from PIL import Image, ImageOps

from asset3d.backends.trellis2 import TrellisBackend
from asset3d.config import load_config
from asset3d.foreground_preview import prepare_preview, single_request, validate_preview
from asset3d.job_spec import validate
from asset3d.pipeline import Pipeline
from asset3d.recording import save_json
from asset3d.viewer_manifest import attach_gso_references


def variant_config(base, spec, variant):
    config = deepcopy(base)
    config['name'] = variant['name']
    if spec.get('export_plugin') == 'surface_repair':
        config['texture']['repair_surface'] = True
    for key in ('decimation_target', 'texture_size'):
        if key in variant:
            config['texture'][key] = variant[key]
    return config


def base_config():
    directory = Path(__file__).resolve().parent
    # Deployed releases place configs beside this script; the checkout uses ../configs.
    if not (directory / 'configs').is_dir():
        directory = directory.parent
    return load_config(directory / 'configs/trellis2_gso_dev.yaml')


def prepare(job):
    spec = single_request(job)
    config = variant_config(base_config(), spec, spec['variants'][0])
    prepare_preview(job, config, TrellisBackend(config))
    status(job, '前景待确认', preview=True)


def execute(job, confirmed_preview=None):
    spec = json.loads((job/'request.json').read_text(encoding='utf-8'))
    total = validate(spec)
    # 作业脚本先 cd 到服务器项目根目录，直接读取共享数据。
    inputs = Path.cwd()/'datasets/gso-v1/data/raw/gso' if 'dataset' in spec else job/'inputs'
    base = base_config()
    prepared = None
    preview_record = None
    if confirmed_preview is None and (job/'preview-status.json').exists():
        raise ValueError('请先检查前景并确认，再提交 3D 生成')
    if confirmed_preview is not None:
        single_request(job)
        config = variant_config(base, spec, spec['variants'][0])
        preview_bytes = (job/'preview.json').read_bytes()
        if hashlib.sha256(preview_bytes).hexdigest() != confirmed_preview:
            raise ValueError('前景确认记录发生变化，请重新预览')
        preview_record = json.loads(preview_bytes)
        prepared = validate_preview(job, config, confirmed_preview)
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
        c = variant_config(base, spec, variant)
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
            if prepared is None and not masked_path.exists():
                import numpy as np
                import torch
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
                    if prepared is None:
                        pipeline.run(masked_path,results/relative,seed=seed)
                    else:
                        pipeline.run(inputs/name,results/relative,seed=seed,
                                     prepared_input=prepared, prepared_sha256=preview_record)
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


def status(job,state,preview=False,**extra):
    save_json(job/('preview-status.json' if preview else 'status.json'),{'state':state,**extra})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--confirmed-preview', metavar='SHA256')
    args = parser.parse_args()
    job = args.job.resolve()
    try:
        status(job,'准备前景' if args.prepare else '加载模型', preview=args.prepare)
        if args.prepare:
            prepare(job)
        else:
            execute(job, args.confirmed_preview)
    except Exception as error:
        status(job,'失败',preview=args.prepare,error=str(error))
        raise
