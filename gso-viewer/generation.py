"""本地工作台通过 SSH 自动部署、提交与收取单图任务。"""
import json
import hashlib
import sys
import base64
import re
import shlex
import subprocess
import tarfile
import threading
import time
import logging
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
from asset3d.job_spec import validate as validate_spec
STORE = ROOT / 'local/generation-jobs'
LOCK = threading.Lock()
ACTIVE = set()
CONFIRM_LOCK = threading.Lock()

def command(args, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode == 255:
        raise ConnectionError((result.stderr or 'SSH 连接中断')[-1000:])
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return result.stdout.strip()

def config():
    path = ROOT / 'local/generation.json'
    c = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    return {
        'host': c.get('host', 'hkust-hpc4'),
        'project': c.get('project', '/home/rzhoubf/projects/cv-final-project'),
        'time_limit': c.get('time_limit', '02:00:00'),
        'download_shape': c.get('download_shape', False),
    }


def validate_options(options):
    host = options.get('host', '')
    root = options.get('project', '')
    duration = options.get('time_limit', '')
    shape = options.get('download_shape', False)
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', host):
        raise ValueError('SSH 别名无效')
    if not isinstance(root, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', root) or '..' in root.split('/'):
        raise ValueError('请输入不含空格的服务器项目绝对路径')
    match = re.fullmatch(r'(\d{1,3}):([0-5]\d):([0-5]\d)', duration) if isinstance(duration, str) else None
    if not match or not 0 < int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3]) <= 168 * 3600:
        raise ValueError('运行时间请填写 HH:MM:SS，范围为 1 秒至 168 小时')
    if type(shape) is not bool:
        raise ValueError('下载白模设置无效')
    return host, root.rstrip('/'), duration, shape

def ssh(host, script):
    return command(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host, script])

def scp(host, source, destination, download=False):
    remote = host + ':' + (source if download else destination)
    return command(['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', remote if download else str(source), str(destination) if download else remote], 600)

def folder(ident):
    if not re.fullmatch(r'[0-9a-f]{32}', ident):
        raise ValueError('Invalid task ID')
    return STORE / ident

def read(ident):
    return json.loads((folder(ident) / 'task.json').read_text(encoding='utf-8'))

def save(task):
    path = folder(task['id']) / 'task.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)

def launch(ident, action, *, claimed=False):
    if not claimed:
        with LOCK:
            if ident in ACTIVE:
                return
            ACTIVE.add(ident)
    def worker():
        try:
            task = read(ident)
            try:
                action(task)
                task.pop('error', None)
                task.pop('retry_at', None)
            except (ConnectionError, subprocess.TimeoutExpired) as error:
                task['error'] = str(error)
                if action is update and active_job(task):
                    task['state'] = '连接中断，稍后自动重查'
                    task['retry_at'] = time.time() + 30
                else:
                    task['state'] = '连接或执行异常'
            except Exception as error:
                task['error'] = str(error)
                task['state'] = '连接或执行异常'
            save(task)
        finally:
            with LOCK:
                ACTIVE.discard(ident)
    threading.Thread(target=worker, daemon=True).start()

def location(task):
    return ROOT/task['local_dir'] if task.get('local_dir') else folder(task['id'])


def create(data, options=None, spec=None, images=None):
    host, root, duration, shape = validate_options(options if options is not None else config())
    ident = uuid.uuid4().hex
    batch = spec is not None
    if not batch:
        spec = {'name': ident, 'seeds': [42], 'images': ['input.png'],
                'export_plugin': 'surface_repair',
                'variants': [{'name': 'trellis2', 'decimation_target': 500000, 'texture_size': 2048}]}
        images = {'input.png':data}
    count = validate_spec(spec)
    expected_uploads = set() if 'dataset' in spec else set(spec['images'])
    if set(images) != expected_uploads:
        raise ValueError('选择的图片必须与配置中的 images 完全一致')
    for image in images.values():
        if not 0 < len(image) <= 20*1024*1024 or not (image.startswith(b'\x89PNG\r\n\x1a\n') or image.startswith(b'\xff\xd8\xff')):
            raise ValueError('图片须为 20 MiB 以内的 JPG 或 PNG')
    local_dir = 'experiments/'+spec['name'] if batch else 'local/web-jobs/'+ident
    local = ROOT/local_dir
    local.mkdir(parents=True, exist_ok=False)
    (local/'inputs').mkdir()
    for name, image in images.items():
        (local/'inputs'/name).write_bytes(image)
    (local/'request.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    folder(ident).mkdir(parents=True)
    task = {'id':ident,'mode':'batch' if batch else 'single','name':spec['name'],
            'host':host,'root':root,'remote':root+'/'+local_dir,'local_dir':local_dir,
            'state':'上传图片和代码','time_limit':duration,'download_shape':shape,'count':count}
    if not batch:
        task.update(preview_required=True, phase='preview', state='上传照片，准备前景预览')
    save(task)
    launch(ident,submit)
    return task


def deploy(task):
    # 以文件内容生成版本号。任务仅引用共享版本，更新源码也不会改变旧作业。
    files = [p for base in ('src/asset3d','configs') for p in (ROOT/base).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.yaml')]
    files.append(ROOT/'scripts/generate_remote.py')
    digest = hashlib.sha256()
    for p in sorted(files):
        digest.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes())
    version = digest.hexdigest()
    remote = task['root']+'/local/code-releases/'+version
    task['code_version'] = version
    save(task)
    q = shlex.quote
    if ssh(task['host'], 'test -f '+q(remote+'/.ready')+' && echo ready || true') == 'ready':
        return remote
    archive = location(task)/'code.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for p in files:
            name = p.relative_to(ROOT).as_posix()
            if name == 'scripts/generate_remote.py':
                name = 'generate_remote.py'
            tar.add(p,arcname=name)
    staging = remote+'-'+task['id']
    ssh(task['host'],'mkdir -p '+q(staging))
    scp(task['host'],archive,staging+'/code.tar.gz')
    ssh(task['host'],f'cd {q(staging)} && tar -xzf code.tar.gz && rm code.tar.gz && touch .ready && if test -f {q(remote+"/.ready")}; then rm -r {q(staging)}; else mv -T {q(staging)} {q(remote)}; fi')
    archive.unlink()
    return remote

def submit(task):
    host, root, remote = task['host'], task['root'], task['remote']
    local = location(task)
    code = deploy(task)
    q = shlex.quote
    # 同名实验禁止覆盖。单图采用唯一任务编号。
    ssh(host, f'mkdir -p {q(str(Path(remote).parent).replace(chr(92),"/"))} && mkdir {q(remote)} && mkdir {q(remote+"/inputs")}')
    spec = json.loads((local/'request.json').read_text(encoding='utf-8'))
    scp(host,local/'request.json',remote+'/request.json')
    if spec.get('dataset') == 'gso-v1':
        # 在登录节点检查每张图可读，通过后才申请 GPU。
        for name in spec['images']:
            path = q(root + '/datasets/gso-v1/data/raw/gso/' + name)
            ssh(host, f'test -r {path} || {{ echo "缺少图片" {path} >&2; exit 1; }}')
    else:
        for name in spec['images']:
            scp(host,local/'inputs'/name,remote+'/inputs/'+name)
    preview = task.get('preview_required', False)
    submit_script(task, code, preview=preview)


def submit_script(task, code, *, preview=False, confirmed_preview=None):
    host, root, remote = task['host'], task['root'], task['remote']
    local, q = location(task), shlex.quote
    script_name = 'preview-job.sh' if preview else 'job.sh'
    log_name = 'preview-job.log' if preview else 'job.log'
    arguments = ' --prepare' if preview else (
        ' --confirmed-preview ' + q(confirmed_preview) if confirmed_preview else '')
    script = '\n'.join([
        '#!/bin/bash', '#SBATCH --account=mscaiehpc42026', '#SBATCH --partition=gpu-l20',
        '#SBATCH --nodes=1', '#SBATCH --ntasks=1', '#SBATCH --gpus-per-node=1', '#SBATCH --time=' + task.get('time_limit', '02:00:00'),
        'set -euo pipefail', 'cd ' + q(root), 'export SLURM_SUBMIT_DIR="$PWD"',
        'source slurm/load_hpc4_modules.sh', 'source .venv-trellis2/bin/activate',
        'export HF_HOME="$PWD/models/huggingface"',
        'export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"',
        'export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1',
        'export PYTHONPATH=' + q(code + '/src'),
        'python ' + q(code + '/generate_remote.py') + ' ' + q(remote) + arguments, ''
    ])
    (local / script_name).write_text(script, encoding='utf-8', newline='\n')
    scp(host, local / script_name, remote + '/' + script_name)
    # 单独保存提交返回值；网络中断时不会自动重复提交收费作业。
    output = ssh(host, f'cd {q(remote)} && sbatch --parsable --job-name={"preview" if preview else "web"}-{task["id"][:8]} --output={q(remote + "/" + log_name)} {script_name}')
    job_id = output.splitlines()[-1].split(';')[0]
    if not job_id.isdigit():
        raise ValueError('提交返回信息异常：' + output)
    if preview:
        task.update(preview_job_id=job_id, state='前景预处理排队等待 GPU')
    else:
        task.update(job_id=job_id, state='排队等待 GPU')

def active_job(task):
    return task.get('preview_job_id') if task.get('phase') == 'preview' else task.get('job_id')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_preview(task):
    """Bind confirmation to the exact files downloaded from this task's preparation job."""
    local = location(task)
    record = json.loads((local/'preview.json').read_text(encoding='utf-8'))
    if record.get('schema_version') != 1:
        raise ValueError('前景预览版本无效，请重新选图')
    paths = {
        'input_sha256': local/'inputs/input.png',
        'request_sha256': local/'request.json',
        'foreground_sha256': local/'prepared/foreground.png',
        'model_input_sha256': local/'prepared/model_input.png',
    }
    for key, path in paths.items():
        if not re.fullmatch(r'[0-9a-f]{64}', str(record.get(key, ''))) or sha256(path) != record[key]:
            raise ValueError('照片或前景预览已改变，请重新选图并预处理')
    if not re.fullmatch(r'[0-9a-f]{64}', str(record.get('config_sha256', ''))):
        raise ValueError('前景配置摘要无效')
    return sha256(local/'preview.json')


def preview_info(ident):
    task = read(ident)
    if not task.get('preview_required') or task.get('phase') != 'awaiting_confirmation':
        raise ValueError('前景尚未准备好，或已经提交生成')
    digest = validate_preview(task)
    if digest != task.get('preview_sha256'):
        raise ValueError('前景预览记录已改变，请重新选图')
    prefix = '/api/generation-preview/' + ident
    return dict(id=ident, preview_sha256=digest, original_url=prefix+'/original',
                foreground_url=prefix+'/foreground', model_input_url=prefix+'/model-input')


def confirm_preview(ident, payload):
    if not isinstance(payload, dict) or payload.get('confirmed') is not True:
        raise ValueError('请先检查前景并确认主体完整、背景无残留')
    # Persist the transition before launching. Repeated clicks or a lost HTTP response
    # return the same task and never submit a second generation job.
    with CONFIRM_LOCK:
        task = read(ident)
        digest = payload.get('preview_sha256')
        if not task.get('preview_required') or not digest or digest != task.get('preview_sha256'):
            raise ValueError('确认与当前预览不匹配，请重新检查前景')
        if task.get('phase') == 'generation':
            return task
        if task.get('phase') != 'awaiting_confirmation':
            raise ValueError('前景尚未准备好')
        with LOCK:
            if ident in ACTIVE:
                raise ValueError('前景正在同步，请稍后确认')
            if validate_preview(task) != digest:
                raise ValueError('前景预览记录已改变，请重新选图')
            task.update(phase='generation', state='提交已确认的前景', confirmed_at=time.time())
            task.pop('error', None)
            task.pop('retry_at', None)
            save(task)
            ACTIVE.add(ident)
        launch(ident, submit_confirmed, claimed=True)
        return task


def submit_confirmed(task):
    if task.get('phase') != 'generation' or not task.get('confirmed_at'):
        raise ValueError('生成前必须确认前景')
    if task.get('job_id'):
        return
    digest = validate_preview(task)
    if digest != task.get('preview_sha256'):
        raise ValueError('确认后的前景已改变')
    version = task.get('code_version', '')
    if not re.fullmatch(r'[0-9a-f]{64}', version):
        raise ValueError('预处理代码版本缺失，请重新选图')
    code = task['root']+'/local/code-releases/'+version
    # Use the original immutable code release; do not redeploy a changed local version.
    submit_script(task, code, confirmed_preview=digest)


def update_preview(task):
    if not task.get('preview_job_id'):
        return
    host, remote, q = task['host'], task['remote'], shlex.quote
    raw = ssh(host, f'if test -f {q(remote+"/preview-status.json")}; then cat {q(remote+"/preview-status.json")}; fi')
    state = json.loads(raw) if raw else {}
    task['checked_at'] = time.time()
    if state.get('error'):
        raise RuntimeError('前景预处理失败：' + str(state['error']))
    # A status file may be written before the Slurm allocation exits. Only expose a
    # confirmable preview after successful completion, releasing the GPU while the user checks.
    accounting = ssh(host, 'sacct -n -X -j ' + task['preview_job_id'] + ' --format=State,ExitCode --parsable2')
    rows = [line.strip().split('|') for line in accounting.splitlines() if line.strip()]
    success = any(row[:2] == ['COMPLETED', '0:0'] for row in rows)
    if success and state.get('state') == '前景待确认':
        local = location(task)
        (local/'prepared').mkdir(exist_ok=True)
        for name in ('preview.json', 'prepared/foreground.png', 'prepared/model_input.png'):
            dest = local/name
            temp = dest.with_suffix(dest.suffix+'.part')
            scp(host, remote+'/'+name, temp, download=True)
            temp.replace(dest)
        digest = validate_preview(task)
        task.update(phase='awaiting_confirmation', state='前景待确认', preview_sha256=digest)
        return
    if any(row[0].split()[0] in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY',
                                  'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE') for row in rows):
        log = ssh(host, 'tail -c 2500 '+q(remote+'/preview-job.log'))
        raise RuntimeError('前景预处理未成功完成：'+accounting+'\n'+log)
    task['state'] = state.get('state', '前景预处理排队等待 GPU')
    if task['state'] == '前景待确认':
        task['state'] = '前景已处理，正在等待作业结束'


def update(task):
    if task.get('phase') == 'awaiting_confirmation':
        return
    if task.get('phase') == 'preview':
        return update_preview(task)
    if task.get('state') == '完成' or not task.get('job_id'):
        return
    host, remote = task['host'], task['remote']
    q = shlex.quote
    raw = ssh(host, f'if test -f {q(remote + "/status.json")}; then cat {q(remote + "/status.json")}; fi')
    task['checked_at'] = time.time()
    state = json.loads(raw) if raw else {}
    task['state'] = state.get('state', '排队等待 GPU')
    if state.get('error'):
        raise RuntimeError(state['error'])
    if task['state'] == '完成' and not task.get('local_dir'):
        # 兼容升级前已提交的单图任务，它们仍使用 output/ 布局。
        task['state'] = '下载带纹理模型'
        task.pop('error', None)
        save(task)
        for name in ['asset.glb','manifest.json','foreground.png'] + (['shape_raw.glb'] if task.get('download_shape') else []):
            dest = folder(task['id'])/name
            temp = dest.with_suffix(dest.suffix+'.part')
            scp(host,remote+'/output/'+name,temp,download=True)
            temp.replace(dest)
        task['state'] = '完成'
        return
    if task['state'] == '完成':
        task['state'] = '下载带纹理模型'
        task.pop('error', None)
        save(task)
        local = location(task)
        results = local/'results'
        results.mkdir(exist_ok=True)
        scp(host,remote+'/results/viewer-manifest.json',results/'viewer-manifest.pending',download=True)
        viewer = json.loads((results/'viewer-manifest.pending').read_text(encoding='utf-8'))
        # 兼容远端旧作业的 null 引用，收取结果时按本地共享数据布局重建。
        from asset3d.viewer_manifest import attach_gso_references
        request = local/'request.json'
        if request.is_file():
            attach_gso_references(viewer,json.loads(request.read_text(encoding='utf-8')),ROOT,results)
        files = ['failures.json']
        for run in viewer['runs']:
            if run['status'] != 'completed':
                continue
            names = [run['models']['asset'],run['input']]
            if task.get('download_shape'):
                names.append(run['models']['shape'])
            else:
                run['models'].pop('shape',None)
            parent = str(Path(run['input']).parent).replace(chr(92),'/')
            names += [parent+'/manifest.json',parent+'/foreground.png']
            if task.get('preview_required'):
                names.append(parent+'/model_input.png')
            files.extend(names)
        from result_transfer import collect
        collect(host,remote+'/results',results,files)
        (results/'viewer-manifest.json').write_text(json.dumps(viewer,ensure_ascii=False,indent=2),encoding='utf-8')
        (results/'viewer-manifest.pending').unlink()
        task['failures'] = state.get('failures',[])
        task['state'] = '完成'
    else:
        queue = ssh(host, 'squeue -h -j ' + task['job_id'] + ' -o %T')
        if not queue:
            accounting = ssh(host, 'sacct -n -X -j ' + task['job_id'] + ' --format=State --parsable2')
            if any(s in accounting for s in ('FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'COMPLETED', 'NODE_FAIL')):
                log = ssh(host, 'tail -c 2500 ' + q(remote + '/job.log'))
                raise RuntimeError(accounting + '\n' + log)

def tasks():
    STORE.mkdir(parents=True, exist_ok=True)
    result = []
    for p in sorted(STORE.glob('*/task.json'), key=lambda p:p.stat().st_mtime, reverse=True):
        task = json.loads(p.read_text(encoding='utf-8'))
        if (task.get('phase') == 'generation' and not task.get('job_id')
                and task['state'] == '提交已确认的前景'):
            with LOCK:
                # A submission worker may have saved its job ID after the first
                # read and released ACTIVE. Never overwrite that newer record.
                task = read(task['id'])
                if (task['id'] not in ACTIVE and task.get('phase') == 'generation'
                        and not task.get('job_id') and task['state'] == '提交已确认的前景'):
                    task['state'] = '提交结果未知，请核对服务器队列'
                    task['error'] = ('本地服务在记录生成作业号前中断。请核对服务器队列中 web-'
                                     + task['id'][:8] + ' 的作业；为避免重复生成，不会自动重新提交。')
                    save(task)
        if task['state'] == '下载带纹理模型':
            progress = location(task)/'results/.received.json'
            if progress.is_file():
                names = json.loads(progress.read_text())
                task['downloaded_models'] = sum(name.endswith('/asset.glb') for name in names)
        result.append(task)
    return result


def monitor(stop):
    # 页面仅读取快照；SSH 查询和下载随本地服务持续运行。
    while not stop.is_set():
        try:
            for task in tasks():
                if (active_job(task) and task.get('phase') != 'awaiting_confirmation' and task['state'] not in ('完成', '连接或执行异常')
                        and task.get('retry_at', 0) <= time.time()):
                    launch(task['id'], update)
        except (ValueError, OSError):
            logging.exception('读取生成任务失败')
        stop.wait(10)
