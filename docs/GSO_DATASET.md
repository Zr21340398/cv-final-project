# GSO 正式实验数据方案

更新：2026-11-06。正式评估数据确定为 Google Scanned Objects（GSO）。
当前先准备数据，模型和参数等待同学的预实验结果。对象 ID 尚未逐项选定，仓库中的 CSV 是待填写模板。

## 1. 本轮范围与依据

本轮选择 GSO 的 30 个不同对象：10 个开发对象、20 个测试对象。
ABO、Toys4K、OmniObject3D 和实拍照片暂不加入正式统计，后续有需要再单独定义展示集。

GSO 提供日常物体的扫描网格、颜色贴图和元数据，可以从参考模型渲染出输入图片，再评价生成模型。
- [Google 官方介绍与下载入口](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/)
- [GSO 论文，ICRA 2022](https://arxiv.org/abs/2204.11918)
- [MS3D，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Luo_MS3D_High-Quality_3D_Generation_via_Multi-Scale_Representation_Modeling_ICCV_2025_paper.pdf)：使用 GSO 和 OmniObject3D 评价单图三维生成。
- [Cue3D 预印本](https://arxiv.org/html/2511.22121v1)：分析光照、轮廓、遮挡和投影方式对生成的影响，可作为开发集输入条件实验的依据。

这些研究支持数据和实验设计，项目的真实效果仍由正式运行评估。基础模型训练数据与 GSO 可能有重叠，报告应写明这是公开数据集上的应用评估。

规划记录在 configs/gso_dataset.yaml。该文件用于人工审查，当前 CLI 读取的是四列 CSV 清单，模型配置仍使用各自的 YAML。

## 2. 怎样挑选 30 个对象

| 主类别（category） | 开发 | 测试 | 示例及观察重点 |
|---|---:|---:|---|
| simple_solid | 2 | 4 | 紧凑玩具、容器，观察整体轮廓 |
| thin_or_hollow | 2 | 4 | 带柄器皿、细部件，观察孔洞与连接 |
| asymmetric | 2 | 4 | 单侧附件、前后不同的物体 |
| patterned | 2 | 4 | 有图案的物体，观察颜色和纹理位置 |
| complex_shape | 2 | 4 | 多部件、不规则轮廓和凹凸 |
| 合计 | 10 | 20 | 30 个不同对象 |

先从官方页面进入模型目录，下载少量候选对象检查，再扩充到完整清单。一个对象归一个主类别，其他难点可写在备注。
同款不同颜色、相似包装和同一对象的多个扫描使用相同 duplicate_group，整组放在同一划分。

在查看任何生成结果之前完成选样。开发集用于调整输入、参数和坐标，测试集用于最终评价。正式运行后保留困难和失败样例。

下载后先检查：
- 使用带纹理的可视网格，保留 OBJ、MTL、图片的相对目录；SDF 中的碰撞网格常为简化几何。
- 物体完整，贴图可读，没有明显扫描破损、悬浮杂物或多余地面。
- 能以统一规则转正，正面可识别，主体完整进入画面。
- 包装盒占比适中，细结构、非对称和明显图案都有覆盖。
- 首轮主集避免透明玻璃、镜面和大面积缺失扫描；若以后研究这些情况，单列挑战集。

GSO 的扫描贴图可能带有原始光照，先检查是否影响观察。当前主指标围绕形状、颜色和图案，金属度与粗糙度评价需要额外材质真值。

## 3. 来源记录和上传

首次准备时，在项目根目录复制模板：

~~~bash
cp -n data/manifests/gso-selection.example.csv data/manifests/gso-selection.csv
cp -n data/manifests/gso-formal.example.csv data/manifests/gso-formal-v1.csv
~~~

模板只有表头，需要填写真实对象信息。来源表各列：
- id：项目使用的唯一短名，只用字母、数字、下划线和短横线。
- gso_id、source_url：数据集原始标识及实际下载页面。
- license：记录下载包的许可与署名要求；官方介绍为 CC BY 4.0。
- category：上表五个类别之一。
- duplicate_group：同款或近似重复对象的共同标识；独立对象可填写自己的 id。
- split：dev 或 test。
- mesh_path：实际可视网格位置，建议相对 CSV 所在目录。
- orientation_notes：旋转方向、正面约定与处理记录。
- selection_notes：选入原因、参考质量及替换原因。

原始文件放在 data/raw/gso/<id>/，保持下载包内部结构。大文件不提交到 Git。
源码打包仅包含 data/manifests，原始模型和渲染文件单独上传。

笔记本 PowerShell，以下目录须先准备好：

~~~powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
scp -r '.\data\raw\gso' hkust-hpc4:~/asset3d-formal/data/raw/
~~~

服务器端先创建 ~/asset3d-formal/data/raw。模型文件、环境和数据使用自己的账户目录。

## 4. 在开发对象上确认渲染条件

CPU 准备环境与 Blender 4.x 配置参考 [HPC 操作说明](HKUST_HPC4_L20_GUIDE.md)，其中 Python 版本按本项目选择 3.10 或 3.11。
准备环境使用 .venv-prepare，三维生成的 GPU 环境在选型后安装。

在开发对象上先确定朝向、取景和投影方式。现有 blender_render.py 使用正交相机，从负 Y 方向略高处取景。
可在少量开发对象上研究透视投影，之后固定同一规则处理整个测试集；透视切换需要后续代码支持。
不要根据某个测试对象的生成好坏单独更换输入视角。

当前可执行的参考渲染示例（网格路径按实际文件修改）：

~~~bash
asset3d render --mesh data/raw/gso/object001/meshes/model.obj --output data/rendered/gso-formal-v1/object001 --views 8 --resolution 1024
~~~

输出 view-000.png 至 view-007.png、reference_normalized.glb 和 cameras.json。
生成模型只接收 view-000.png，其余图用于检查。原始参考模型先居中、统一尺度；相机条件保存在 cameras.json。
渲染目录使用新目录。先逐张检查一个开发对象，确认贴图和几何正常，再批量准备。
已有透明背景的渲染图保留蒙版；最终输入预处理在模型选定后统一确定。

## 5. 运行清单和文件校验

gso-formal-v1.csv 只使用四列，路径相对清单所在目录。
下面两个对象名仅为格式示例，实际清单须填写完整的 10 个 dev 和 20 个 test：

~~~csv
id,image,reference,split
object001,../rendered/gso-formal-v1/object001/view-000.png,../rendered/gso-formal-v1/object001/reference_normalized.glb,dev
object002,../rendered/gso-formal-v1/object002/view-000.png,../rendered/gso-formal-v1/object002/reference_normalized.glb,test
~~~

在服务器准备环境中检查路径与摘要：

~~~bash
python - <<'PY'
from collections import Counter
from asset3d.data import read_manifest
from asset3d.recording import save_json
rows = read_manifest("data/manifests/gso-formal-v1.csv")
counts = Counter(row["split"] for row in rows)
assert counts == {"dev": 10, "test": 20}, counts
save_json("data/manifests/gso-formal-v1.audit.json", rows)
print("清单检查通过：", dict(counts))
PY
~~~

此外人工核对：来源表和运行清单的 ID、split 一致；每类满足 2/4；duplicate_group 没有跨 dev/test；图片与参考 GLB 属于同一物体。
运行清单保留相对路径便于迁移；audit 文件含本账户解析后的绝对路径和哈希，应在实际执行账户生成。
审核后将来源表和运行清单提交 Git，渲染条件变更时重新生成并版本化数据。

## 6. 选型结果之后

模型选择和正式变量尚未冻结。优先研究输入规范化与质量/成本权衡中的一个主方向。
若选混元，可以沿用步数对比；若选 TRELLIS.2，再确定生成分辨率等参数并更新正式入口。
种子暂拟 42 和 123；例如两配置时，20 个测试对象 × 2 配置 × 2 种子为 80 次生成。
具体规模按预实验完整耗时调整，并在测试开始前确定。

真实 GPU 单例、生成结果与参考模型的坐标校准通过后，再建立正式计划。
当前 slurm/experiments.sbatch 仍是旧混元三档步数脚本，正式代码更新前不提交它。
几何、盲评和汇总规则见 [EXPERIMENTS.md](EXPERIMENTS.md)。

数据准备完成标志：真实来源与 ID 齐全、数量及类别正确、路径检查通过、渲染人工检查通过、原始数据另有备份。
