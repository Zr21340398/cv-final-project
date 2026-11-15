# 混元 GSO 正式实验执行说明

2026-11-08。正式入口为 `asset3d formal-run`，默认从开发集开始。
30 个 GSO 原始对象、30 个带贴图参考 GLB、240 张参考视图和正式 CSV 已准备齐全，开发/测试集 CPU 技术检查均通过；人工来源验收仍待确认。详见 [准备与检查报告](GSO_PREPARATION_V1.md)。
pilot03 的 20 项结果继续保留，新的代码、配置和数据必须使用新的实验目录。
按用户要求，数据准备和 CPU 检查通过、推进到需要学校 GPU 的步骤时，先提醒用户，再安排正式 GPU 首例。

用户随后明确指示“给学校gpu提交任务”。本次以 `data/manifests/gso-run-approval-v1.json` 记录基于技术检查和 AI 审阅的开发集运行授权，绑定来源表、输入表、全部数据校验清单及审阅证据的 SHA256。使用 `--run-approval` 时仍必须通过所有技术检查；这个授权仅适用于 dev，不代替人工几何/贴图/朝向验收，也不将来源表写为 `accepted`。人工 QA 表继续留空。本次只提交首例，剩余开发矩阵不自动提交。

## 本轮研究变量

开发集先比较 50、30、20 个形状推理步数，种子为 42、123。
三个新配置为 `configs/hunyuan2_formal_50.yaml`、`hunyuan2_formal_30.yaml`、`hunyuan2_formal_20.yaml`。
它们继承 pilot03 已跑通的配置，除名称和步数外完全相同：

- 共用已验收的透明前景，`background: keep`；尺寸 512、padding 0.2。
- `octree_resolution: 384`，形状 guidance 5.0。
- Paint 前仅将纹理副本减至 40,000 面，保留原始白模；渲染和纹理尺寸均为 2048。
- 固定官方源码和权重版本，离线加载。

这轮只测步数与质量/成本的关系。面数、纹理尺寸或输入留白的消融应另开计划，避免把多个变量的效果混在一起。
旧 `baseline/medium/fast` 仍保留作旧功能兼容，不是正式提交入口的默认配置。

## 先完成 CPU 数据准备

按 `GSO_DATASET.md` 下载可视网格、材质与贴图，检查扫描质量和朝向，再渲染 8 个统一视角。
正式 CSV 为 `data/manifests/gso-formal-v1.csv`，包含全部 30 个对象；不能直接把 `.draft.csv` 当成验收结果。
准备好一个 split 后，填写来源表实际 `mesh_path`，逐项完成几何、贴图和朝向检查，再将该项 `status` 记为 `accepted`。
这个值表示实际验收已经完成，预检程序不会自动替人填写。

```bash
asset3d check-formal-data \
  --manifest data/manifests/gso-formal-v1.csv \
  --selection data/manifests/gso-selection.csv --split dev \
  --output logs/gso-dev-audit.json
```

预检检查来源表与运行表 ID/split、10 dev/20 test、五类各 2 dev/4 test、近似重复组不跨集合。
仅所选 split 要求文件已经准备好，因此可以先准备开发集；检查透明输入、参考/原始网格、8 张可读 PNG 与相机记录。
元数据一致和文件通过不能代替人工扫描质量验收。正式测试前同样检查 test split。

## 开发集单例和完整对照

所有命令从项目根目录执行。先在 CPU 环境验证计划，不使用 GPU，也不创建结果目录：

```bash
asset3d formal-run --manifest data/manifests/gso-formal-v1.csv \
  --run-approval data/manifests/gso-run-approval-v1.json \
  --output results/hunyuan-gso-dev01 --split dev --limit 1 --dry-run
```

数据通过后再提交 GPU 首例。`logs/` 必须在 sbatch 前创建。
账户特定的 CUDA 模块和缓存可写在已忽略的 `configs/hpc4-session.local.sh`，复用学校上已验证的混元环境；脚本不安装依赖、不下载权重。

```bash
mkdir -p logs
sbatch slurm/experiments.sbatch data/manifests/gso-formal-v1.csv \
  results/hunyuan-gso-dev01 --split dev --limit 1 \
  --run-approval data/manifests/gso-run-approval-v1.json

# 确认首例状态、GLB与贴图通过且原作业已结束后，续跑同一冻结计划。
sbatch slurm/experiments.sbatch data/manifests/gso-formal-v1.csv \
  results/hunyuan-gso-dev01 --split dev --resume \
  --run-approval data/manifests/gso-run-approval-v1.json
```

开发矩阵为 10 对象 × 3 配置 × 2 种子，共 60 项。`--limit` 计算计划前 N 项，包含恢复时跳过的项。
每项独立进程，默认 3600 秒超时；源码、配置、输入/参考和来源表摘要均冻结。
完成项校验后跳过，不把跳过耗时当作生成时间。失败项保留记录，普通 `--resume` 不自动重试；确认原因并需要再尝试时，显式添加 `--retry-failed`。
更改源码、配置或输入时新建实验，不修改已有实验记录来绕过检查。

提交脚本申请 1 张 L20、16 CPU、64 GiB 主机内存，默认 4 小时作业上限；这些是资源申请设置，不是实测完成时间。
按 pilot03 混元约 121 秒/项粗估，60 项约 2 小时、80 项约 2.7 小时，但 GSO 难度和步数不同，必须以开发集实测更新预算。
可通过 `sbatch --time=...` 调整作业上限；超时后的剩余项仍在计划内，未完成不能算成功。
被调度器强杀可能留下锁，先确认原作业终态再处理；程序不会删除无法确认归属的锁。

## 冻结测试配置

开发阶段校准生成坐标与参考坐标，比较完整结果，决定保留哪些步数。
测试必须显式指定配置及已完成开发实验；所选配置和种子必须与开发记录一致，10 个开发对象的对应成品及哈希都通过后才允许生成测试集。
从开发阶段起冻结全部 30 对象的来源身份、分层和划分，测试入口核对同一名单及同一相机/渲染协议；补齐测试数据的验收状态或迁移本地路径不会改变名单身份。
下面的 50/30 步只是命令格式示例，不能替代开发集选型结论：

```bash
asset3d formal-run --manifest data/manifests/gso-formal-v1.csv \
  --output results/hunyuan-gso-test01 --split test \
  --configs configs/hunyuan2_formal_50.yaml configs/hunyuan2_formal_30.yaml \
  --development-experiment results/hunyuan-gso-dev01 --dry-run

sbatch slurm/experiments.sbatch data/manifests/gso-formal-v1.csv \
  results/hunyuan-gso-test01 --split test \
  --configs configs/hunyuan2_formal_50.yaml configs/hunyuan2_formal_30.yaml \
  --development-experiment results/hunyuan-gso-dev01
```

两配置测试为 20 × 2 × 2 = 80 项；保留三配置则是 120 项，需相应扩大作业预算。
开发与测试使用各自目录，测试结果不参与选择配置。

## 几何评价和外观盲评

几何评价前先在开发对象上确认统一坐标。`axis-transform.json` 必须来自坐标校准；如果已经一致，可明确使用单位刚性矩阵，但不能凭猜测选择旋转。

```bash
asset3d evaluate-batch --experiment results/hunyuan-gso-test01 \
  --transform data/manifests/axis-transform.json
# 要研究最终减面资产，再另算一份指标，不覆盖白模指标。
asset3d evaluate-batch --experiment results/hunyuan-gso-test01 \
  --transform data/manifests/axis-transform.json --artifact asset.glb
asset3d summarize --experiment results/hunyuan-gso-test01 \
  --output results/hunyuan-gso-test01/summary
```

白模指标保存为 `metrics.json`，最终资产指标保存为 `metrics_asset.json`，汇总中分列报告。
程序会核对预测与参考的记录哈希；损坏或不一致的成品不再算成功。
报告保留全计划成功率、失败/未运行条目，并给出共同成功样本的配对差值；耗时配对只使用完整、未复用中间产物的成功尝试，避免不同成功样本造成偏差。

现有 Chamfer 为双向未平方欧氏距离均值；Hausdorff/HD95 是表面采样近似。照片无真值时不生成几何分数。
对每个最终资产渲染相同的 8 张预览到其 `preview/`，完整视图及相机记录通过后再运行 `asset3d blind-study`。
可复用 `asset3d pilot-render --experiment results/hunyuan-gso-test01 --blender blender --views 8` 批量生成白模及材质预览；渲染在 CPU 作业中进行。已有预览不完整时明确报错，保留原目录供排查。
至少 3 位评价者独立填写评分；自动文件检查和 AI 主观审阅不能当作已经完成的人工盲评。

## 验证范围

CPU 单元测试覆盖执行控制、冻结/恢复、数据检查和指标记录；它们不证明新 GSO GPU 结果的画质或运行时间。
正式 GPU 验收仍需真实开发集首例。已发布 pilot03 的源码快照与结果保持独立，新源码不会改写旧的冻结实验。
