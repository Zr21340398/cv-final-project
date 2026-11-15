# HPC4 环境安装

当前代码目录是 `~/project/cv-final-project/`。代码、共享数据与权重获取统一见 [DATA_AND_MODELS.md](DATA_AND_MODELS.md)。安装和推理分别使用计算节点，以下命令尚未在你的账户执行。

## GPU 环境

登录节点申请一张 L20：

```bash
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --ntasks=1 --gpus-per-node=1 --time=02:00:00 --pty bash
```

在计算节点按学校当前模块列表加载 Python 3.10 或 3.11、CUDA 12.4 及编译工具。先检查：

```bash
cd ~/project/cv-final-project
python3 --version
nvcc --version
nvidia-smi
```

TRELLIS.2 执行：

```bash
bash scripts/install_trellis2_hpc.sh
source .venv-trellis2/bin/activate
asset3d doctor --gpu --backend trellis2
```

混元执行：

```bash
bash scripts/install_hpc.sh
source .venv-hpc/bin/activate
asset3d doctor --gpu --backend hunyuan2
```

两个环境分别保存，第三方 CUDA 扩展位于被 Git 忽略的 `third_party/`。安装需要网络与编译时间，失败时保存完整日志。账户模块、配额或驱动问题可参考 [HKUST_HPC4_L20_GUIDE.md](HKUST_HPC4_L20_GUIDE.md)。权重请按统一准备指南下载，保持下载与作业缓存路径一致。长时间等权限或查资料时退出 GPU 分配。
