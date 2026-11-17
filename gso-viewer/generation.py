"""本地工作台通过 SSH 自动部署、提交与收取单图任务。"""
import json
import re
import shlex
import subprocess
import tarfile
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
    host = c.get('host', 'hkust-hpc4')
    root = c.get('project', '/home/rzhoubf/projects/cv-final-project')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', host) or not root.startswith('/') or not re.fullmatch(r'[/A-Za-z0-9_.-]+', root):
        raise ValueError('服务器配置中的 SSH 别名或绝对路径无效')
    return host, root

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

def create(data):
    host, root = config()
    ident = uuid.uuid4().hex
    local = folder(ident)
    local.mkdir(parents=True)
    (local / 'input').write_bytes(data)
    task = {'id': ident, 'host': host, 'root': root, 'remote': root + '/local/web-jobs/' + ident, 'state': '上传图片和代码'}
    save(task)
    launch(ident, submit)
    return task

def submit(task):
    host, root, remote = task['host'], task['root'], task['remote']
    local = folder(task['id'])
    # 只上传执行所需源码和配置；数据集、权重与实验结果不会随包复制。
    with tarfile.open(local / 'code.tar.gz', 'w:gz') as archive:
        for base in ('src/asset3d', 'configs'):
            for p in (ROOT / base).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py', '.yaml'):
                    archive.add(p, arcname='code/' + p.relative_to(ROOT).as_posix())
        archive.add(ROOT / 'scripts/generate_remote.py', arcname='code/generate_remote.py')
    q = shlex.quote
    ssh(host, f'mkdir -p {q(remote)}')
    scp(host, local / 'input', remote + '/input')
    scp(host, local / 'code.tar.gz', remote + '/code.tar.gz')
    script = '\n'.join([
        '#!/bin/bash', '#SBATCH --account=mscaiehpc42026', '#SBATCH --partition=gpu-l20',
        '#SBATCH --nodes=1', '#SBATCH --ntasks=1', '#SBATCH --gpus-per-node=1', '#SBATCH --time=02:00:00',
        'set -euo pipefail', 'cd ' + q(root), 'export SLURM_SUBMIT_DIR="$PWD"',
        'source slurm/load_hpc4_modules.sh', 'source .venv-trellis2/bin/activate',
        'export HF_HOME="$PWD/models/huggingface"',
        'export ASSET3D_DINOV3_DIR="$PWD/models/dinov3-vitl16-pretrain-lvd1689m"',
        'export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1',
        'export PYTHONPATH=' + q(remote + '/code/src'),
        'python ' + q(remote + '/code/generate_remote.py') + ' ' + q(remote), ''
    ])
    (local / 'job.sh').write_text(script, encoding='utf-8', newline='\n')
    scp(host, local / 'job.sh', remote + '/job.sh')
    # 单独保存提交返回值；网络中断时不会自动重复提交收费作业。
    output = ssh(host, f'cd {q(remote)} && tar -xzf code.tar.gz && sbatch --parsable --job-name=web-{task["id"][:8]} --output={q(remote + "/job.log")} job.sh')
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
    if task['state'] == '完成':
        task['state'] = '下载带纹理模型'
        save(task)
        local = folder(task['id'])
        # 白模仅留在服务器；下载采用临时文件，避免展示未传完的 GLB。
        for name in ('asset.glb', 'manifest.json', 'foreground.png'):
            temp = local / (name + '.part')
            scp(host, remote + '/output/' + name, temp, download=True)
            temp.replace(local / name)
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
