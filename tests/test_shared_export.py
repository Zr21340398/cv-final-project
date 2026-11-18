"""真实 GLB 编解码，使用小型带 UV 网格代替 GPU 烘焙。"""
import json
import trimesh
import numpy as np
from PIL import Image
from asset3d.export import export_glb
from asset3d.lod_export import export_levels
from asset3d.job_spec import validate


def test_shared_export(tmp_path):
    source = tmp_path/'base'
    source.mkdir()
    (source/'manifest.json').write_text(json.dumps({'config':{'texture':{}},'identity':{'seed':42}}))
    for name in ('input.png','foreground.png'):
        Image.new('RGB',(16,16)).save(source/name)
    calls = []
    class Backend:
        def bake_native(self, settings):
            calls.append(settings)
            mesh = trimesh.creation.box()
            mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),image=Image.new('RGB',(16,16)))
            return mesh
    variants=[dict(name='small',decimation_target=100000,texture_size=2048)]
    run, = export_levels(Backend(),variants,'base',tmp_path,'image_000',42)
    assert run['status']=='completed', run
    assert calls==[{'decimation_target':100000,'texture_size':2048}]
    assert run['models']['shape']=='base/shape_raw.glb'
    m=json.loads((tmp_path/'small/image_000/seed-42/manifest.json').read_text())
    assert m['export']['meshes'][0]['faces']==12
    assert m['export']['file_bytes']>0
