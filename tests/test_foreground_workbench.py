"""The web service must not submit inference until an intact preview is confirmed."""
import hashlib
import importlib.util
import io
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'gso-viewer'))
import generation


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, 'ROOT', tmp_path)
    monkeypatch.setattr(generation, 'STORE', tmp_path/'local/generation-jobs')
    calls = []
    monkeypatch.setattr(generation, 'ACTIVE', set())
    monkeypatch.setattr(generation, 'launch', lambda ident, action, **kwargs: calls.append((ident, action)))
    image = io.BytesIO()
    Image.new('RGB', (64, 64), 'orange').save(image, format='PNG')
    task = generation.create(image.getvalue(), dict(host='test', project='/project',
                                                  time_limit='00:30:00', download_shape=False))
    return task, calls


def ready(task):
    local = generation.location(task)
    (local/'prepared').mkdir()
    Image.new('RGBA', (64, 64), (255, 100, 10, 100)).save(local/'prepared/foreground.png')
    Image.new('RGB', (64, 64), 'orange').save(local/'prepared/model_input.png')
    record = {'schema_version': 1, 'config_sha256': 'c'*64}
    for key, name in (('input', 'inputs/input.png'), ('request', 'request.json'),
                      ('foreground', 'prepared/foreground.png'), ('model_input', 'prepared/model_input.png')):
        record[key+'_sha256'] = hashlib.sha256((local/name).read_bytes()).hexdigest()
    (local/'preview.json').write_text(json.dumps(record))
    task.update(phase='awaiting_confirmation', state='前景待确认', preview_job_id='100',
                preview_sha256=generation.sha256(local/'preview.json'), code_version='b'*64)
    generation.save(task)
    generation.ACTIVE.discard(task['id'])  # The preparation worker has finished.
    return {'confirmed': True, 'preview_sha256': task['preview_sha256']}


def test_single_create_does_not_start_generation(service):
    task, calls = service
    assert task['phase'] == 'preview'
    assert calls == [(task['id'], generation.submit)]
    with pytest.raises(ValueError):
        generation.confirm_preview(task['id'], {'confirmed': True, 'preview_sha256': 'a'*64})
    assert len(calls) == 1


def test_target_selection_is_saved_with_single_request_and_invalid_input_is_rejected(service):
    task, calls = service
    original = (generation.location(task)/'inputs/input.png').read_bytes()
    options = dict(host='test', project='/project', time_limit='00:30:00', download_shape=False)
    selection = {'box':[0.1, 0.2, 0.9, 0.8], 'include_points':[[0.5, 0.4]],
                 'exclude_points':[[0.2, 0.7]]}
    targeted = generation.create(original, options, foreground_selection=selection)
    request = json.loads((generation.location(targeted)/'request.json').read_text())
    assert request['foreground_selection'] == selection
    assert targeted['phase'] == 'preview' and 'job_id' not in targeted
    for bad in ({'box':[0.8, 0.1, 0.2, 0.9]}, {'box':[0, 0, 1, 1], 'mode':'unexpected'}):
        with pytest.raises(ValueError):
            generation.create(original, options, foreground_selection=bad)
    assert len(calls) == 2


def test_targeted_local_confirmation_verifies_segmentation_record(service):
    task, _ = service
    ready(task)
    local = generation.location(task)
    request = json.loads((local/'request.json').read_text())
    request['foreground_selection'] = {'box':[0.1, 0.1, 0.9, 0.9], 'include_points':[], 'exclude_points':[]}
    (local/'request.json').write_text(json.dumps(request))
    (local/'segmentation.json').write_text(json.dumps({'method':'sam2', 'test_fixture':True}))
    record = json.loads((local/'preview.json').read_text())
    record.update(schema_version=2, request_sha256=generation.sha256(local/'request.json'),
                  segmentation_sha256=generation.sha256(local/'segmentation.json'))
    (local/'preview.json').write_text(json.dumps(record))
    task['preview_sha256'] = generation.sha256(local/'preview.json')
    generation.save(task)
    assert generation.validate_preview(task) == task['preview_sha256']
    (local/'segmentation.json').write_text('{}')
    with pytest.raises(ValueError):
        generation.confirm_preview(task['id'], {'confirmed':True, 'preview_sha256':task['preview_sha256']})


def test_new_preview_is_claimed_before_worker_launch(service, monkeypatch):
    task, _ = service
    launched = []

    def inspect_before_worker_start(ident, action, *, claimed=False):
        launched.append(ident)
        assert claimed and ident in generation.ACTIVE
        observed = next(item for item in generation.tasks() if item['id'] == ident)
        assert observed['state'] == '上传照片，准备前景预览'
        assert 'error' not in observed

    monkeypatch.setattr(generation, 'launch', inspect_before_worker_start)
    original = (generation.location(task)/'inputs/input.png').read_bytes()
    created = generation.create(original, dict(host='test', project='/project',
                                              time_limit='00:30:00', download_shape=False))
    assert launched == [created['id']]


def test_preview_restart_reports_unknown_submission_without_retry(service):
    task, calls = service
    assert generation.tasks()[0]['state'] == '上传照片，准备前景预览'
    generation.ACTIVE.clear()  # The service exited before saving preview_job_id.
    observed, = generation.tasks()
    assert observed['state'] == '提交结果未知，请核对服务器队列'
    assert 'preview-'+task['id'][:8] in observed['error']
    assert '预处理作业号' in observed['error']
    assert not generation.active_job(observed)
    with pytest.raises(ValueError):
        generation.confirm_preview(task['id'], {'confirmed': True, 'preview_sha256': 'a'*64})

    class OneCycle:
        done = False
        def is_set(self):
            return self.done
        def wait(self, _):
            self.done = True

    generation.monitor(OneCycle())
    assert calls == [(task['id'], generation.submit)]
    assert generation.read(task['id']) == observed


def test_confirmation_is_required_and_concurrent_requests_are_idempotent(service):
    task, calls = service
    payload = ready(task)
    with pytest.raises(ValueError, match='确认'):
        generation.confirm_preview(task['id'], {**payload, 'confirmed': False})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: generation.confirm_preview(task['id'], payload), range(12)))
    assert all(result['id'] == task['id'] and result['phase'] == 'generation' for result in results)
    assert [action for _, action in calls].count(generation.submit_confirmed) == 1
    with pytest.raises(ValueError):
        generation.confirm_preview(task['id'], {**payload, 'preview_sha256': 'a'*64})


@pytest.mark.parametrize('name', ['inputs/input.png', 'prepared/foreground.png',
                                  'prepared/model_input.png', 'request.json', 'preview.json'])
def test_modified_file_invalidates_preview(service, name):
    task, calls = service
    payload = ready(task)
    path = generation.location(task)/name
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):
        generation.confirm_preview(task['id'], payload)
    assert len(calls) == 1


def test_confirm_uses_preparation_code_version_without_redeployment(service, monkeypatch):
    task, _ = service
    payload = ready(task)
    confirmed = generation.confirm_preview(task['id'], payload)
    monkeypatch.setattr(generation, 'deploy', lambda task: pytest.fail('must reuse original version'))
    monkeypatch.setattr(generation, 'scp', lambda *args, **kwargs: None)
    commands = []
    monkeypatch.setattr(generation, 'ssh', lambda host, cmd: commands.append(cmd) or '200')
    generation.submit_confirmed(confirmed)
    script = (generation.location(task)/'job.sh').read_text()
    assert '--confirmed-preview '+payload['preview_sha256'] in script
    assert '/local/code-releases/'+'b'*64+'/generate_remote.py' in script
    assert '--prepare' not in script
    assert confirmed['job_id'] == '200'
    assert confirmed['preview_job_id'] == '100'
    generation.submit_confirmed(confirmed)
    assert len(commands) == 1


def test_restart_after_confirmation_reports_unknown_submission_without_retry(service):
    task, calls = service
    payload = ready(task)
    generation.confirm_preview(task['id'], payload)
    assert generation.tasks()[0]['state'] == '提交已确认的前景'
    generation.ACTIVE.clear()  # Simulate a service restart before job_id was saved.
    observed, = generation.tasks()
    assert observed['state'] == '提交结果未知，请核对服务器队列'
    assert 'web-'+task['id'][:8] in observed['error']
    repeated = generation.confirm_preview(task['id'], payload)
    assert repeated['state'] == observed['state']
    assert [action for _, action in calls].count(generation.submit_confirmed) == 1


@pytest.mark.parametrize('phase,job_field', [('preview', 'preview_job_id'), ('generation', 'job_id')])
def test_task_poll_preserves_job_id_saved_after_its_initial_snapshot(service, monkeypatch, phase, job_field):
    task, _ = service
    submitting = task if phase == 'preview' else generation.confirm_preview(task['id'], ready(task))
    task_path = generation.folder(task['id'])/'task.json'
    original_read = Path.read_text
    finished = False

    def finish_submission_after_read(path, *args, **kwargs):
        nonlocal finished
        snapshot = original_read(path, *args, **kwargs)
        if path == task_path and not finished:
            finished = True
            generation.save({**submitting, job_field: '200', 'state': '排队等待 GPU'})
            generation.ACTIVE.discard(task['id'])
        return snapshot

    monkeypatch.setattr(Path, 'read_text', finish_submission_after_read)
    observed, = generation.tasks()
    assert finished
    assert observed[job_field] == '200'
    assert observed['state'] == '排队等待 GPU'
    persisted = generation.read(task['id'])
    assert persisted[job_field] == '200'
    assert 'error' not in persisted


def test_preview_waits_for_slurm_completion_and_fetches_exact_artifacts(service, monkeypatch):
    task, _ = service
    ready(task)
    task.update(phase='preview', state='前景处理中')
    downloaded = []
    monkeypatch.setattr(generation, 'scp', lambda host, source, dest, download: (
        downloaded.append(source), dest.write_bytes(dest.with_suffix('').read_bytes())))
    accounting = ['RUNNING|0:0']
    def ssh(host, cmd):
        return accounting[0] if 'sacct' in cmd else json.dumps({'state': '前景待确认'})
    monkeypatch.setattr(generation, 'ssh', ssh)
    generation.update(task)
    assert task['phase'] == 'preview' and not downloaded
    accounting[0] = 'COMPLETED|0:0'
    generation.update(task)
    assert task['phase'] == 'awaiting_confirmation'
    assert len(downloaded) == 3
    generation.update(task)  # Awaiting user input must not poll or generate.
    assert len(downloaded) == 3


def test_failed_preparation_never_enables_confirmation(service, monkeypatch):
    task, _ = service
    task['preview_job_id'] = '100'
    monkeypatch.setattr(generation, 'ssh', lambda host, cmd: 'FAILED|1:0' if 'sacct' in cmd else '')
    with pytest.raises(RuntimeError, match='未成功'):
        generation.update(task)
    assert task['phase'] == 'preview'


def test_preview_http_routes_and_cross_origin_confirmation(service):
    task, _ = service
    payload = ready(task)
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('foreground_viewer_server', root/'gso-viewer/server.py')
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    server = ThreadingHTTPServer(('127.0.0.1', 0), viewer.make_handler(viewer.Datasets(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/api/generation-preview/'+task['id']) as response:
            info = json.load(response)
        with urlopen(base+info['foreground_url']) as response:
            assert response.read() == (generation.location(task)/'prepared/foreground.png').read_bytes()
        request = Request(base+'/api/generation-confirm/'+task['id'], data=json.dumps(payload).encode(),
                          headers={'X-Asset3D': 'workbench', 'Origin': 'https://other.example'})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
        request.headers['Origin'] = base
        with urlopen(request) as response:
            assert json.load(response)['phase'] == 'generation'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
