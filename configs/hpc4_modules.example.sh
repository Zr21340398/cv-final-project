#!/usr/bin/env bash
# 复制到 local/hpc4_modules.sh，根据 module spider 的输出填写。
# 在 GPU 作业中已自动启用 Spack Edge；如有前置编译器模块，在下面先加载。
# module load <学校要求的前置模块>
# module load python/<实际可用的 3.10 或 3.11 版本>
# module load cuda/<实际可用的 12.4 版本>
# 以下行只是占位提醒；填写后删除它，否则作业会主动停止。
echo '请在 local/hpc4_modules.sh 中填写 Python 和 CUDA 模块，并删除占位退出行。' >&2
return 1
