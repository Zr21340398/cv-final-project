"""用一个 SSH 会话接收清单选中的文件。已完整接收的文件可在断线后复用。"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def collect(host, remote, results, names):
    results = results.resolve()
    receipts = results / '.received.json'
    saved = json.loads(receipts.read_text()) if receipts.is_file() else {}
    pending = {}
    for name in dict.fromkeys(names):
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', name) or name.startswith('-') or '..' in PurePosixPath(name).parts:
            raise ValueError('非法结果路径')
        dest = (results / name).resolve()
        if not dest.is_relative_to(results):
            raise ValueError('结果路径越界')
        if dest.is_file() and name in saved and dest.stat().st_size == saved[name]:
            continue
        pending[name] = dest
    if not pending:
        return
    # 文件列表走标准输入，二进制 tar 走标准输出；未选择的白模不会传输。
    command = 'cd ' + shlex.quote(remote) + ' && tar --hard-dereference -cf - --verbatim-files-from -T -'
    with tempfile.TemporaryFile() as listing, tempfile.TemporaryFile() as errors:
        listing.write(('\n'.join(pending)+'\n').encode())
        listing.seek(0)
        with subprocess.Popen(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=15',
                               '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                               host,command],stdin=listing,stdout=subprocess.PIPE,stderr=errors) as proc:
            try:
                with tarfile.open(fileobj=proc.stdout,mode='r|*') as archive:
                    for member in archive:
                        dest = pending.pop(member.name, None)
                        if dest is None or not member.isfile():
                            raise ValueError('远端返回了清单以外的内容')
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        temp = dest.with_suffix(dest.suffix+'.incoming')
                        with temp.open('wb') as stream:
                            shutil.copyfileobj(archive.extractfile(member),stream)
                        if temp.stat().st_size != member.size:
                            raise EOFError(member.name)
                        os.replace(temp,dest)
                        saved[member.name] = member.size
                        tmp = receipts.with_suffix('.tmp')
                        tmp.write_text(json.dumps(saved))
                        tmp.replace(receipts)
                # 读完 tar 的尾部填充，避免 SSH 写满管道。
                proc.stdout.read()
                if proc.wait() or pending:
                    raise EOFError('结果传输不完整')
            except (EOFError,tarfile.TarError,OSError) as exc:
                proc.kill()
                proc.wait()
                errors.seek(0)
                raise ConnectionError(errors.read().decode(errors='replace') or str(exc)) from exc
            finally:
                if proc.poll() is None:
                    proc.kill()
