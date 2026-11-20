"""无 GPU 的应用/批次共用管线验证。"""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gso-viewer'))
import generation

PNG = b'\x89PNG\r\n\x1a\nexample'
OPTIONS = {'host':'test','project':'/project','time_limit':'03:15:00','download_shape':True}
SPEC = {'name':'sample','seeds':[42,123],'images':['cup.png'],
        'variants':[{'name':'fine','decimation_target':1000000},{'name':'small','decimation_target':200000}]}

@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(generation,'ROOT',tmp_path)
    monkeypatch.setattr(generation,'STORE',tmp_path/'local/generation-jobs')
    monkeypatch.setattr(generation,'launch',lambda *a:None)
    return tmp_path


def test_modes_separate_data_and_snapshot_options(local):
    single=generation.create(PNG,OPTIONS)
    batch=generation.create(None,OPTIONS,SPEC,{'cup.png':PNG})
    assert generation.location(single).parent == local/'local/web-jobs'
    assert generation.location(batch) == local/'experiments/sample'
    single_spec = json.loads((generation.location(single)/'request.json').read_text())
    assert single['count'] == 1
    assert single_spec['variants'] == [{'name':'trellis2','decimation_target':500000,'texture_size':2048}]
    assert single_spec['export_plugin'] == 'surface_repair'
    assert batch['count']==4
    assert generation.read(batch['id'])['download_shape'] is True
    with pytest.raises(FileExistsError):
        generation.create(None,OPTIONS,SPEC,{'cup.png':PNG})


def test_input_validation(local):
    for key,value in [('host','-oBad'),('project','/a/../b'),('time_limit','01:99:00')]:
        with pytest.raises(ValueError):
            generation.create(PNG,{**OPTIONS,key:value})
    with pytest.raises(ValueError):
        generation.create(None,OPTIONS,{**SPEC,'name':'../x'},{'cup.png':PNG})
    with pytest.raises(ValueError):
        generation.create(None,OPTIONS,SPEC,{'wrong.png':PNG})
    with pytest.raises(ValueError):
        generation.folder('../x')


def test_submission_uses_shared_code(local,monkeypatch):
    task=generation.create(PNG,OPTIONS)
    monkeypatch.setattr(generation,'deploy',lambda t:'/project/local/code-releases/hash')
    calls=[]
    monkeypatch.setattr(generation,'scp',lambda *a,**kw: calls.append(a))
    monkeypatch.setattr(generation,'ssh',lambda h,s:'1234' if 'sbatch' in s else '')
    generation.submit(task)
    script=(generation.location(task)/'preview-job.sh').read_text()
    assert '#SBATCH --time=03:15:00' in script
    assert 'code-releases/hash/src' in script
    assert '--prepare' in script
    assert task['preview_job_id']=='1234'
    assert 'job_id' not in task
    assert not any('code.tar.gz' in str(c) for c in calls)


def test_batch_collection_and_viewer(local,monkeypatch):
    task=generation.create(None,{**OPTIONS,'download_shape':False},SPEC,{'cup.png':PNG})
    task['job_id']='123'
    viewer={'runs':[{'status':'completed','input':'fine/image_000/seed-42/input.png',
                    'models':{'asset':'fine/image_000/seed-42/asset.glb','shape':'fine/image_000/seed-42/shape_raw.glb'}}]}
    calls=[]
    def copy(h,src,dest,download=False):
        calls.append(src)
        Path(dest).write_text(json.dumps(viewer) if src.endswith('viewer-manifest.json') else '[]')
    monkeypatch.setattr(generation,'scp',copy)
    import result_transfer
    monkeypatch.setattr(result_transfer,'collect',lambda h,r,d,names:calls.extend(names))
    monkeypatch.setattr(generation,'ssh',lambda *a:json.dumps({'state':'完成'}))
    generation.update(task)
    output=generation.location(task)/'results/viewer-manifest.json'
    assert output.exists()
    assert 'shape' not in json.loads(output.read_text())['runs'][0]['models']
    assert not any('shape_raw' in n for n in calls)


def test_code_cache_hit(local,monkeypatch):
    (local/'scripts').mkdir()
    (local/'scripts/generate_remote.py').write_text('code')
    task=generation.create(PNG,OPTIONS)
    monkeypatch.setattr(generation,'ssh',lambda *a:'ready')
    monkeypatch.setattr(generation,'scp',lambda *a:pytest.fail('cache should skip upload'))
    assert 'code-releases/' in generation.deploy(task)

def test_server_dataset_submission(local,monkeypatch):
    config_path = Path(__file__).resolve().parents[1]/'configs/gso_lod_six.json'
    spec = json.loads(config_path.read_text(encoding='utf-8'))['experiment']
    task = generation.create(None,OPTIONS,spec,{})
    assert task['count'] == 24
    assert spec['images'][0] == 'gso_01/thumbnails/2.jpg'
    monkeypatch.setattr(generation,'deploy',lambda task:'/project/release')
    commands, uploads = [], []
    def ssh(host, cmd):
        commands.append(cmd)
        return '12345' if 'sbatch' in cmd else ''
    monkeypatch.setattr(generation,'ssh',ssh)
    monkeypatch.setattr(generation,'scp',lambda host,source,dest:uploads.append(dest))
    generation.submit(task)
    assert all('/inputs/' not in dest for dest in uploads)
    assert all(any('test -r' in cmd and name in cmd for cmd in commands) for name in spec['images'])
    with pytest.raises(ValueError):
        generation.create(None,OPTIONS,{**spec,'images':['../outside.jpg']},{})
def test_result_transfer_reuses_completed_files(local,monkeypatch):
    import io
    import tarfile
    import subprocess
    import result_transfer
    out = local/'received'
    out.mkdir()
    real_popen = subprocess.Popen
    calls=[]
    def fake_ssh(args, **kwargs):
        listing=kwargs['stdin']
        names=listing.read().decode().splitlines()
        calls.append(names)
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            for name in names:
                data=name.encode()
                info=tarfile.TarInfo(name)
                info.size=len(data)
                archive.addfile(info,io.BytesIO(data))
        source=local/'test_payload.tar'
        source.write_bytes(stream.getvalue())
        return real_popen([sys.executable,'-c','import sys;sys.stdout.buffer.write(open(sys.argv[1],"rb").read())',str(source)],**kwargs)
    monkeypatch.setattr(result_transfer.subprocess,'Popen',fake_ssh)
    result_transfer.collect('host','/results',out,['v/asset.glb','v/input.png'])
    result_transfer.collect('host','/results',out,['v/asset.glb','v/input.png','failures.json'])
    assert calls == [['v/asset.glb','v/input.png'],['failures.json']]
    assert (out/'v/asset.glb').read_bytes()==b'v/asset.glb'
