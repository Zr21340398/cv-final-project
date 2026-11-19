"""在下载完成的 results 上汇总真实体积与三角面数，输出 UTF-8 CSV。"""
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
viewer = json.loads((root/'viewer-manifest.json').read_text(encoding='utf-8'))
objects = {o['id']:o['label'] for o in viewer['objects']}
configs = {v['id']:v['config']['texture'] for v in viewer['variants']}
sizes = {}
rows = []
for run in viewer['runs']:
    key = run['object'], run['seed']
    row = dict(image=objects[key[0]], seed=key[1], variant=run['variant'], status=run['status'],
               target=configs[run['variant']]['decimation_target'], texture_size=configs[run['variant']]['texture_size'])
    if run['status'] == 'completed':
        asset = root/run['models']['asset']
        report = json.loads((asset.parent/'manifest.json').read_text(encoding='utf-8'))['export']
        size = asset.stat().st_size
        if run['variant'] == viewer['variants'][0]['id']:
            sizes[key] = size
        row.update(bytes=size,MiB=round(size/2**20,3),faces=sum(m['faces'] for m in report['meshes']))
    rows.append((key,row))
with (root/'lod-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer = csv.DictWriter(f,fieldnames='image seed variant target texture_size status faces bytes MiB reduction_pct'.split())
    writer.writeheader()
    for key,row in rows:
        if key in sizes and 'bytes' in row:
            row['reduction_pct']=round(100*(1-row['bytes']/sizes[key]),2)
        writer.writerow(row)
