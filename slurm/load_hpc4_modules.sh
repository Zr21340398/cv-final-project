#!/usr/bin/env bash
# 在非交互作业中重建用户选定的模块环境；安装和推理使用同一配置。
: "${SLURM_SUBMIT_DIR:?请从项目根目录提交作业}"
# 学校初始化脚本可能引用尚未设置的变量，加载时临时放宽 nounset。
set +u
source /opt/shared/.spack-edge/dist/bin/setup-env.sh -y
set -u
HPC4_MODULE_FILE="${HPC4_MODULE_FILE:-$SLURM_SUBMIT_DIR/local/hpc4_modules.sh}"
if [[ ! -f "$HPC4_MODULE_FILE" ]]; then
  echo "缺少模块配置 $HPC4_MODULE_FILE；请按 docs/SERVER_SETUP.md 准备。" >&2
  return 1
fi
source "$HPC4_MODULE_FILE"
