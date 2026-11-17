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
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
from asset3d.job_spec import validate as validate_spec
STORE = ROOT / 'local/generation-jobs'
LOCK = threading.Lock()
ACTIVE = set()

def command(args, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
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

def launch(ident, action):
    with LOCK:
        if ident in ACTIVE:
            return
        ACTIVE.add(ident)
    def worker():
        task = read(ident)
        try:
            action(task)
            task.pop('error', None)
        except Exception as error:
            task['error'] = str(error)
            task['state'] = '连接或执行异常'
        finally:
            save(task)
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
        spec = {'name':ident,'seeds':[42],'variants':[{'name':'trellis2'}],'images':['input.png']}
        images = {'input.png':data}
    count = validate_spec(spec)
    if set(images) != set(spec['images']):
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
    for name in spec['images']:
        scp(host,local/'inputs'/name,remote+'/inputs/'+name)
    script = '\n'.join([
        '#!/bin/bash', '#SBATCH --account=mscaiehpc42026', '#SBATCH --partition=gpu-l20',
        '#SBATCH --nodes=1', '#SBATCH --ntasks=1', '#SBATCH --gpus-per-node=1', '#SBATCH --time=' + task.get('time_limit', '02:00:00'),
        'set -euo pipefail', 'cd ' + q(root), 'export SLURM_SUBMIT_DIR="$PWD"',
        'source slurm/load_hpc4_modules.sh', 'source .venv-trellis2/bin/activate',
        'export HF_HOME="$PWD/models/huggingface"',
        'export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"',
        'export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1',
        'export PYTHONPATH=' + q(code + '/src'),
        'python ' + q(code + '/generate_remote.py') + ' ' + q(remote), ''
    ])
    (local / 'job.sh').write_text(script, encoding='utf-8', newline='\n')
    scp(host, local / 'job.sh', remote + '/job.sh')
    # 单独保存提交返回值；网络中断时不会自动重复提交收费作业。
    output = ssh(host, f'cd {q(remote)} && sbatch --parsable --job-name=web-{task["id"][:8]} --output={q(remote + "/job.log")} job.sh')
    job_id = output.splitlines()[-1].split(';')[0]
    if not job_id.isdigit():
        raise ValueError('提交返回信息异常：' + output)
    task.update(job_id=job_id, state='排队等待 GPU')

def update(task):
    if task.get('state') == '完成' or not task.get('job_id'):
        return
    host, remote = task['host'], task['remote']
    q = shlex.quote
    raw = ssh(host, f'if test -f {q(remote + "/status.json")}; then cat {q(remote + "/status.json")}; fi')
    state = json.loads(raw) if raw else {}
    task['state'] = state.get('state', '排队等待 GPU')
    if state.get('error'):
        raise RuntimeError(state['error'])
    if task['state'] == '完成' and not task.get('local_dir'):
        # 兼容升级前已提交的单图任务，它们仍使用 output/ 布局。
        task['state'] = '下载带纹理模型'
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
        save(task)
        local = location(task)
        results = local/'results'
        results.mkdir(exist_ok=True)
        scp(host,remote+'/results/viewer-manifest.json',results/'viewer-manifest.pending',download=True)
        viewer = json.loads((results/'viewer-manifest.pending').read_text(encoding='utf-8'))
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
            for name in names:
                dest = (results/name).resolve()
                if not dest.is_relative_to(results.resolve()):
                    raise ValueError('服务器返回的文件路径越界')
                dest.parent.mkdir(parents=True,exist_ok=True)
                temp = dest.with_suffix(dest.suffix+'.part')
                scp(host,remote+'/results/'+name,temp,download=True)
                temp.replace(dest)
        (results/'viewer-manifest.json').write_text(json.dumps(viewer,ensure_ascii=False,indent=2),encoding='utf-8')
        (results/'viewer-manifest.pending').unlink()
        scp(host,remote+'/results/failures.json',results/'failures.json',download=True)
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
        result.append(task)
        if task.get('job_id') and task['state'] not in ('完成', '连接或执行异常'):
            launch(task['id'], update)
    return result
