# 正式实验准备指南：独立账户，等待模型选型
更新：2026-11-06。适用目录：D:\AIEproject\MAIE5421_CV\Final Project。

你和同学使用不同的学校账户。同学负责预实验，且未修改代码；你现在准备自己的环境与正式数据。模型选定后，我们再调整正式实验代码、配置和 GPU 任务脚本，并上传更新。

本文只需要登录节点和 CPU 计算节点。完成第 1～7 节后即可等待选型结果；当前阶段无需提交三维生成任务。本文命令尚未在你的服务器账户中实际执行。

## 1. 现在做什么，哪些留到选型后

| 现在可以做 | 完成标志 |
|---|---|
| 建立个人项目目录并上传现有源码 | 能看到 src、configs、scripts、docs |
| 建立独立 CPU Python 环境 | pip check 通过，asset3d --help 正常 |
| 确认 Blender 4.x | 能把一个开发对象渲染成 PNG |
| 整理参考网格、贴图和来源 | 每个对象可完整打开、来源可追溯 |
| 确定开发集、测试集及实拍案例 | 有正式清单，近似重复对象在同一组 |
| 统一参考模型朝向和输入视角 | 图片、参考 GLB、相机记录对应 |
| 保存安装记录、校验上传文件 | 下次登录可恢复相同环境 |

以下工作等选型结果出来再做：
- 安装最终使用的 GPU 模型环境与 CUDA 扩展，下载该模型及其辅助权重。
- 修改正式实验参数、作业脚本和最终展示页面。
- 校准生成模型到参考模型的坐标变换。
- 建立正式生成计划、测试 GPU 单例、提交整批生成。

当前 slurm/experiments.sbatch 默认执行混元 50/30/20 步；现在先保留它，等正式实验设计确认后更新。当前步骤也不调用 pilot-init 或 pilot-run。

## 2. 上传代码：先建一个长期使用的项目目录

代码和 CPU 环境放在个人目录，模型缓存放到 scratch。每次 GPU/CPU 作业结束后，共享磁盘上的文件仍可访问。scratch 无备份，并有未访问文件清理规则，因此正式数据和重要结果另外保存一份。[学校存储说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4/fileandstorage)

推荐目录：

~~~text
~/asset3d-formal/
  src/ configs/ scripts/ docs/       当前源码，之后更新
  .venv-prepare/                    你的 CPU 环境
  local/                           你的账户环境设置
  logs/                            安装与运行记录
  data/raw/gso/                    原始参考模型及配套贴图
  data/rendered/formal-v1/         渲染图片、标准化参考模型、相机记录
  data/manifests/                  数据清单、来源和选样记录
  results/                        后续正式生成结果
~~~

**笔记本 PowerShell：打包和上传。**

~~~powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
.\.venv\Scripts\python.exe scripts/package_project.py
scp '.\dist\asset3d-source.tar.gz' hkust-hpc4:~/asset3d-formal-source.tar.gz
ssh hkust-hpc4
~~~

源码包包含代码、配置、文档和 data/manifests；data/raw、data/rendered、虚拟环境和模型权重需要单独处理。现在无需上传预实验的五张照片。

**服务器登录节点：首次创建目录。整块执行。**

~~~bash
if [ -e "$HOME/asset3d-formal" ]; then
  echo "目录已存在：先检查内容，本次跳过解压"
else
  mkdir "$HOME/asset3d-formal"
  tar -xzf "$HOME/asset3d-formal-source.tar.gz" -C "$HOME/asset3d-formal" --strip-components=1
fi
cd ~/asset3d-formal
mkdir -p local logs data/raw/gso data/rendered data/manifests results
ls
~~~

检查能看到 src、pyproject.toml 和 scripts。若目录原本存在，先确认其中是否已有可用代码。

## 3. 只建立 CPU 准备环境

### 3.1 申请 CPU

**登录节点：单独执行，等待出现计算节点提示符。**

~~~bash
srun --account=mscaiehpc42026 --partition=amd --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=16G --time=01:00:00 --pty bash
~~~

这是起步资源设置；调度系统若提示账户或资源限制，按实际提示调整。获分配后：

~~~bash
cd ~/asset3d-formal
hostname
echo "$SLURM_JOB_ID"
source /opt/shared/.spack-edge/dist/bin/setup-env.sh
module spider python
~~~

首次初始化按学校提示操作。选择可用的 Python 3.10 或 3.11，执行对应的 module load，再检查 python3 --version。学校模块会更新，应从当前列表复制名称。[模块说明](https://hkust-hpc-docs.readthedocs.io/latest/software/software-support-overview.html)

### 3.2 保存环境设置

用 VS Code 在服务器创建 local/prepare-env.sh，保存以下内容。将占位模块名替换为上一步实际加载成功的名称，然后再执行。

~~~bash
# 本文件通过 source 调用，使用 Bash、UTF-8、LF 换行。
source /opt/shared/.spack-edge/dist/bin/setup-env.sh -y || return 1
module load REPLACE_WITH_ACTUAL_PYTHON_MODULE || return 1
export HF_HOME="/scratch/$USER/project3/cache/huggingface"
export U2NET_HOME="/scratch/$USER/project3/cache/rembg"
export PIP_CACHE_DIR="/scratch/$USER/project3/cache/pip"
export OMP_NUM_THREADS=4
export PYTHONUNBUFFERED=1
mkdir -p "$HF_HOME" "$U2NET_HOME" "$PIP_CACHE_DIR" || return 1
~~~

例如 module spider 显示并且实际加载成功的名称为 python/3.11.x，就使用那个完整名称。这里保留占位符，以免把示例版本当成你账户上的实际版本。

**仍在 CPU 节点，创建环境：**

~~~bash
source local/prepare-env.sh
python3 --version
python3 -c 'import sys; assert sys.version_info[:2] in [(3,10),(3,11)], "Please select Python 3.10 or 3.11"'
python3 -m venv .venv-prepare
source .venv-prepare/bin/activate
python -m pip install 'pip<26' 'setuptools<76' wheel
python -m pip install -e '.[download]' 'huggingface-hub==0.36.2' 'rembg==2.0.61' 'onnxruntime==1.20.1'
python -m pip check
asset3d --help
python -m pip freeze > logs/prepare-environment.freeze.txt
python --version > logs/prepare-python.txt
module list > logs/prepare-modules.txt 2>&1
~~~

这些包负责图片、网格、统计和 CPU 抠图。安装成功后不必重复创建环境，后续只需：

~~~bash
cd ~/asset3d-formal
source local/prepare-env.sh
source .venv-prepare/bin/activate
~~~

Python 虚拟环境按绝对路径关联程序，保持项目和环境目录位置稳定。安装遇到网络限制时按学校允许的联网方式处理，先保存错误日志。

本阶段可以暂缓下载三维模型权重和抠图权重。由 Blender 输出的透明背景输入可以直接保留蒙版；实拍照片的抠图可在正式预处理规则确定后统一执行。

## 4. 准备 Blender：它负责从三维模型拍图片

Blender 在本项目中承担两个工作：
1. 对参考三维模型拍照，制作输入图片。
2. 对生成结果拍照，供后续评价。

**CPU 节点检查：**

~~~bash
command -v blender
module spider blender
~~~

如有学校提供的 Blender 4.x 模块，加载后执行 blender --version，并把成功的加载命令保存在 local/blender-env.sh，后续渲染时先 source 该文件。

如果没有可用模块，可以先在笔记本安装 Blender 4.x，使用下面同样的渲染命令准备数据，然后把整个渲染输出目录上传。服务器用户目录安装 Linux 版是另一种方案，需先核对服务器架构及官方发行包。本指南先走已有模块或本地渲染路线，节省环境排错时间。

本项目已有渲染器使用 CPU，无需申请 L20。渲染在 CPU 计算节点执行。

## 5. 正式数据怎样选择

### 5.1 主数据：带颜色纹理的 GSO 参考模型

优先选择 Google Scanned Objects（GSO）。它提供日常物体的扫描网格、颜色贴图和元数据，适合构造“参考模型 → 输入图片 → 生成结果 → 参考模型评价”的实验。

入口：
- [Google 官方数据集介绍](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/)
- 从该页面的 Scanned Objects / Gazebo 链接进入模型目录，逐个挑选和下载。
- [GSO 论文](https://arxiv.org/abs/2204.11918)

官方介绍列出的发布许可为 CC BY 4.0。保存每个对象的原始 ID、下载链接、作者与许可信息，报告中标注来源。先下载少量候选对象并确认文件可用，再扩充清单。

下载包可能包含 SDF、可视网格与碰撞网格。我们使用带纹理的可视网格；碰撞网格通常为简化形状。渲染命令支持 OBJ、GLB、glTF、PLY，SDF 用于查找它引用的可视网格路径。保留 OBJ 的 MTL、纹理图片和原有相对目录。

颜色贴图足以评价图案和颜色；扫描模型对粗糙度、金属度等材质参数的覆盖需要逐对象核查。第一轮正式评价以形状、颜色、图案和可用性为主。

### 5.2 数量与分组：建议 30 个参考对象，外加 5 个实拍对象

这是适合本课程规模的建议，实际数量可在正式测试开始前按时间与额度确定。

| 主类别 | 开发对象 | 测试对象 | 重点检查 |
|---|---:|---:|---|
| 简单实体 | 2 | 4 | 整体轮廓、体积感 |
| 细结构或孔洞 | 2 | 4 | 杯柄、细杆、空隙 |
| 非对称结构 | 2 | 4 | 单侧附件、前后差异 |
| 明显图案 | 2 | 4 | 文字、条纹、花纹位置 |
| 不规则或复杂形状 | 2 | 4 | 多部件、凹凸、复杂轮廓 |
| 合计 | 10 | 20 | 每组都有覆盖 |

这些是人工分层标签。每个对象指定一个主类别，也可以附加多个难点标签。相似包装、同款不同颜色、同一物体多个扫描归入同一组，避免开发集和测试集出现近似复制。

开发集用于检查环境、确定参数和坐标。测试集用于配置固定后的最终评价。先分组再看生成结果，测试集对象一旦确定就保留成功和失败记录。参考文件损坏可在生成前替换，并记录原因。

只有 20 个测试物体时，每类别 4 个，分类结果主要用于描述现象；同一物体的多个随机种子按重复测量处理。报告同时写清对象数和生成次数。

### 5.3 下载后逐项筛选

用 Blender 打开候选模型，检查：

- 主体完整，所有部件与贴图可读取。
- 网格表面没有明显扫描破损、悬浮杂物或多余地面。
- 物体可以转正并完整进入画面。
- 图案具有足够清晰度，适合观察颜色和纹理。
- 模型复杂度适合电脑打开及 CPU 渲染。

玻璃、镜面、强反光和严重破损扫描可单列为挑战案例。主测试集先使用参考质量清晰、可以解释评价结果的物体。不同类别自然包含难点，保留细结构和非对称物体。

在 data/manifests/selection.csv 记录：
object_id、source_url、license、category、duplicate_group、split、mesh_path、orientation_notes、selection_notes。
这份表用于来源和选样记录，运行程序读取的是第 7 节规定的四列清单。

### 5.4 实拍照片：另外准备 5 个对象

自己拍摄完整的单个物体，背景简单、清晰、没有严重截断，覆盖上面的几类。保留原图和对象名称。每个对象固定一张输入图；可另拍侧后方照片供人工检查，后续推理只输入选定的那一张。

实拍对象没有对应参考网格时，在运行清单中使用 split=real、reference 留空。这部分评价可用性和视觉效果，几何距离留给有参考网格的 GSO 测试集。

预实验中的五个对象保留作选型记录，正式测试另选对象。GSO 可能与基础模型的训练数据存在重叠，报告将其描述为公开数据集上的应用评估，并加入自采照片补充观察。

## 6. 先渲染一个开发对象，再批量整理数据

### 6.1 上传原始模型

把完整对象目录放到笔记本的 data/raw/gso，例如：

~~~text
data/raw/gso/object001/
  meshes/model.obj
  meshes/model.mtl
  materials/textures/texture.png
~~~

这只是目录示意，实际保留下载包的文件组织。先在 Blender 中把物体竖直方向对齐 Z 轴，并按统一规则确定正面；修正朝向时保留原始文件和记录，不要重塑物体。

**笔记本 PowerShell：**

~~~powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
scp -r '.\data\raw\gso\object001' hkust-hpc4:~/asset3d-formal/data/raw/gso/
~~~

路径包含空格时保留引号。大批上传前先检查一个对象的网格、MTL 和贴图都已到齐。

### 6.2 CPU 节点执行参考渲染

确认已激活准备环境和 Blender；下面的模型路径按实际文件名修改：

~~~bash
cd ~/asset3d-formal
source local/prepare-env.sh
source .venv-prepare/bin/activate
blender --version
asset3d render --mesh data/raw/gso/object001/meshes/model.obj --output data/rendered/formal-v1/object001 --views 8 --resolution 1024
~~~

输出目录必须是新目录。此命令用原有参考模型渲染八张图，并保存标准化参考模型和相机记录；全程使用现有参考数据。

检查：

~~~text
data/rendered/formal-v1/object001/
  view-000.png ... view-007.png
  reference_normalized.glb
  cameras.json
~~~

逐张查看图片：物体完整、颜色存在、没有错误部件。检查保存的 GLB 能打开，形状与原始物体一致。

统一使用 view-000.png 作为后续模型输入，其余图片用于检查。当前相机从物体负 Y 方向、略高位置拍摄，并绕 Z 轴旋转。先在开发对象中确定这套朝向和拍摄规则，再对测试对象统一应用。当前渲染器会居中并统一尺度，几何指标按归一化形状解释。

透明 PNG 可以保留现有蒙版。后续选型后统一决定模型前处理；现在保存原始参考渲染，避免按某个模型单独加工测试图。

也可在笔记本执行同一条 asset3d render 命令：先在 PowerShell 激活本地 .venv，确保 Blender 在 PATH 中；或用 --blender 指定实际 blender.exe 的完整路径。成功后把整个 object001 渲染输出目录上传到服务器 data/rendered/formal-v1/ 下。

CPU 操作结束后执行 exit 返回登录节点；下次继续时重新申请 CPU 并激活环境。

## 7. 整理数据清单与准备验收

在服务器创建 data/manifests/formal-v1.csv，用以下四列。图片和参考路径相对于 CSV 所在目录：

~~~csv
id,image,reference,split
object001,../rendered/formal-v1/object001/view-000.png,../rendered/formal-v1/object001/reference_normalized.glb,dev
object002,../rendered/formal-v1/object002/view-000.png,../rendered/formal-v1/object002/reference_normalized.glb,test
photo001,../raw/photos/photo001.jpg,,real
~~~

示例对象要替换成真实已存在的文件。按第 5 节手动确定分层划分；同一物体只出现一次。所有路径使用服务器可读的相对路径。

**CPU 节点、准备环境中：检查清单及文件。**

~~~bash
python - <<'PY'
from collections import Counter
from asset3d.data import read_manifest
from asset3d.recording import save_json
rows = read_manifest("data/manifests/formal-v1.csv")
print("对象数：", len(rows))
print("划分：", dict(Counter(row["split"] for row in rows)))
save_json("data/manifests/formal-v1.audit.json", rows)
print("已保存路径与图片/参考模型的文件摘要")
PY
~~~

检查器确认文件存在、ID 唯一、划分合法，并计算内容摘要；你仍需人工确认图片与参考模型确实属于同一物体。渲染条件保存在各对象的 cameras.json 中。

准备阶段完成后应有：

- local/prepare-env.sh 和成功使用的 Blender 路径或模块记录。
- .venv-prepare，以及 logs 下的依赖和模块记录。
- 原始三维模型、材质、贴图及来源记录。
- 10 个开发对象、20 个测试对象的统一渲染和参考 GLB，或你们提前确定的较小规模。
- 5 张独立实拍图片。
- formal-v1.csv 与检查后的 audit 文件。
- 至少一份笔记本或其他持久位置的原始数据备份。

如果暂时只完成一个开发对象的完整渲染流程，也已经完成环境准备的关键验证。之后主要是按相同规则扩充数据。

## 8. 选型结果出来后，如何接上正式实验

1. 根据结果确定主模型、正式对比项和种子数。
2. 更新正式代码与配置，上传到当前项目目录；保留 local、.venv-prepare、data、logs、results。
3. 正式 GPU 环境单独创建，采用最终模型要求的 Python、PyTorch、CUDA 和扩展版本。
4. 只下载最终所需的权重。若选 TRELLIS.2，当前代码从自己的 ~/models/dinov3-vitl16-pretrain-lvd1689m 读取 DINOv3，或通过 ASSET3D_DINOV3_DIR 指定路径；按当前 guide 下载并校验。
5. 在开发对象上完成真实 GPU 单例，核对形状、纹理、坐标变换、耗时和显存。
6. 冻结正式计划后运行测试集，最后汇总质量、成功率与成本。

以后更新代码的操作在没有运行中作业时进行。上传新的源码包前保存旧版本副本，新包解压会覆盖同名源码。准备环境使用可编辑安装，源码路径不变时可读取更新；依赖改变时，再激活 .venv-prepare 执行 python -m pip install -e '.[download]' 和 python -m pip check。

当前打包脚本会打包 data/manifests。更新源码时先核查包内清单，保护服务器已经整理好的 formal-v1.csv；数据清单另存备份后再解压。准备阶段生成的 audit 用于追踪数据，正式实验计划在最终代码上传后重新建立。

## 9. 今天可以按这个顺序开始

1. 上传源码到自己的 ~/asset3d-formal。
2. CPU 节点建立 .venv-prepare，保存环境恢复文件。
3. 选取并下载 2～3 个 GSO 开发候选对象，保留来源、网格和贴图。
4. 找到可用的 Blender 4.x，完成一个对象的渲染与检查。
5. 按类别扩充候选清单，确定开发/测试划分，并拍摄实物照片。
6. 整理 formal-v1.csv，执行检查，保存数据备份。
7. 退出 CPU 分配，等待同学的预实验结果。

本指南已经跳过模型选型预实验。完成这些准备后，后续工作集中在最终 GPU 环境、正式实验配置及真实运行上。
