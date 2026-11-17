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
    script=(generation.location(task)/'job.sh').read_text()
    assert '#SBATCH --time=03:15:00' in script
    assert 'code-releases/hash/src' in script
    assert task['job_id']=='1234'
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
