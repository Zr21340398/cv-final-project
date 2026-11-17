"""自动管线的本地测试：远端命令使用模拟，避免提交 GPU 作业。"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'gso-viewer'))
import generation


def test_upload_submit_and_asset_download(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, 'STORE', tmp_path)
    ident = 'a' * 32
    local = generation.folder(ident)
    local.mkdir()
    (local / 'input').write_bytes(b'image')
    task = {'id': ident, 'host': 'test', 'root': '/project', 'remote': '/project/job', 'state': 'upload'}
    calls = []
    def ssh(host, script):
        calls.append(script)
        return '12345' if 'sbatch' in script else ''
    def transfer(host, source, target, download=False):
        calls.append((source, str(target), download))
        if download:
            Path(target).write_bytes(b'downloaded')
    monkeypatch.setattr(generation, 'ssh', ssh)
    monkeypatch.setattr(generation, 'scp', transfer)
    generation.submit(task)
    assert task['job_id'] == '12345'
    assert 'PYTHONPATH=/project/job/code/src' in (local / 'job.sh').read_text()
    monkeypatch.setattr(generation, 'ssh', lambda *args: json.dumps({'state': '完成'}))
    generation.update(task)
    assert task['state'] == '完成'
    assert (local / 'asset.glb').is_file()
    assert not (local / 'shape_raw.glb').exists()
    assert not any('shape_raw' in str(c) for c in calls)


def test_task_path_cannot_escape():
    import pytest
    with pytest.raises(ValueError):
        generation.folder('../outside')


def test_failed_scheduler_job_reports_log(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, 'STORE', tmp_path)
    replies = iter(['', '', 'TIMEOUT', 'last log'])
    monkeypatch.setattr(generation, 'ssh', lambda *a: next(replies))
    import pytest
    with pytest.raises(RuntimeError, match='TIMEOUT'):
        generation.update({'id':'b'*32,'host':'test','remote':'/job','job_id':'123','state':'排队'})
