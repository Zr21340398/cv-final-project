# TRELLIS.2 与混元 3D 2.0：从第一次运行到选出模型

更新：2026-10-27。

这份说明带你完成一个小实验：给两个模型输入同样的物体图片，比较生成的三维模型，
再决定课程项目采用哪一个。先阅读第 1～3 节理解流程，然后从第 4 节开始操作。

目前已经写好运行程序和实验记录工具。第 6～9 节先在 CPU 上完成准备，
第 10 节再申请 L20 安装并运行首个样例。以下命令已按现有代码入口核对，
学校服务器上的安装、模型加载和真实生成仍需通过首次样例验收。

## 1. 先理解：我们把一张图片变成什么

以“一张印有图案的马克杯照片”为例，最后要得到一个可以旋转查看的三维杯子。

这个结果包含三部分：

| 内容 | 杯子的例子 | 代码里的名称 |
|---|---|---|
| 形状 | 杯身、杯口、杯柄的三维结构 | geometry / mesh |
| 表面的颜色和图案 | 白色杯身、杯上的文字或花纹 | texture |
| 表面对光的反应 | 釉面的反光、粗糙程度 | material / PBR |

**网格（mesh）**用许多小三角形拼出物体表面。三角形越贴合物体，轮廓和细节越容易保留。
本项目把只看形状、使用统一灰白颜色显示的结果叫作**白模**。

**贴图（texture）**是一张或多张二维图片，用来存放物体表面的颜色、花纹等信息。
**UV 坐标**告诉程序“三角形表面上的位置，对应贴图上的哪里”。
**烘焙（baking）**在这里指把模型内部预测的表面信息写入这些贴图。

**GLB 文件**可以把网格、贴图和材质放在同一个文件里。我们最终下载的 asset.glb 就是它。
用 Blender 打开后，可以旋转、缩放，查看正面和背面。

### 1.1 照片没有拍到的背面从哪里来

模型在训练时见过大量三维物体及其图片，学会了形状和外观的规律。
运行时，它结合当前照片与这些经验，推测背面和被遮挡部分。

例如，看到杯身与部分杯柄，它会推测杯子的深度、杯柄连接方式以及背面外观。
因此我们要观察多个方向：正面像原图的模型，背面仍可能出现结构错误。

本次使用作者已经训练好的**权重**。权重是训练得到的参数文件。
我们下载并加载它们，然后执行**推理**，也就是“输入图片，让已有模型生成结果”。
当前阶段的工作是安装、运行、比较和记录。

形状生成可以粗略理解为：先从一组随机数出发，以图片特征为条件，经过多次迭代，
逐步得到表示三维物体的数值，最后解码成网格。这里的随机种子决定初始随机状态，
推理步数控制迭代次数。正式比较先使用提供的默认设置，跑通后再单独研究参数影响。

### 1.2 两个模型分别怎么工作

**混元 3D 2.0：先做形状，再给形状上色。**

```text
物体图片
   ↓ 去背景，突出要建模的物体
Hunyuan3D-DiT：预测三维形状
   ↓
保存白模 shape_raw.glb
   ↓
Hunyuan3D-Paint：参考图片，给网格生成颜色和图案
   ↓
保存带纹理模型 asset.glb
```

Paint 在上色时会利用从不同方向看到的物体表面，把颜色覆盖到网格上。
这里的处理发生在白模已经生成之后。

**TRELLIS.2：先确定物体在空间中的位置，再补形状细节和材质。**

```text
物体图片
   ↓ 图像编码器提取轮廓、局部外观等视觉特征
预测物体表面分布在哪些三维小格子附近
   ↓
预测这些位置的形状细节
   ↓
预测相应表面的颜色、粗糙度、金属度等材质信息
   ↓
解码成网格和表面属性
   ├─ 保存白模 shape_raw.glb
   └─ 整理贴图和材质，导出 asset.glb
```

论文里的几个术语可以这样理解：

- **稀疏结构**：只记录与物体有关的三维小格子，节省空间和计算。
- **潜变量**：模型内部使用的一组压缩数值，用来表示形状或材质。
- **解码**：把这些压缩数值还原成可用的三维数据。
- **O-Voxel**：TRELLIS.2 存放三维形状和表面属性的一种数据结构。
- **DINOv3**：负责把输入图片转换成视觉特征的辅助模型。
- **PBR 材质**：用颜色、粗糙度、金属度等参数描述表面对光的反应。

代码调用官方生成程序完成这些步骤。你需要理解输入、输出和关键设置；
初次运行时直接使用预设配置即可。

TRELLIS.2 的官方 run() 会在一次调用里完成形状和材质生成。
所以它的 native_shape_material 记录的是这段完整调用的时间。
混元的 shape 与 texture 分别记录形状生成和上色时间。

### 1.3 生成和渲染各做什么

**生成**：从图片得到可以旋转的三维资产，由两个大模型完成。

**渲染**：把已经生成的三维资产放到虚拟相机前，拍成二维预览图，由 Blender 完成。
后面生成八张预览图，是为了从相同角度检查两个结果。
这些预览图属于评价阶段，输入仍是最初那一张物体图片。

## 2. 这次实验怎么比较

先挑五个物体，每个物体用两个随机种子生成：

**5 个物体 × 2 个种子 × 2 个模型 = 20 次生成。**

随机种子控制生成过程中的随机状态。这里用 42 和 123，观察同一模型两次结果是否稳定。
两种模型各有自己的随机过程，我们用相同编号组织实验记录。

建议五个物体覆盖这些情况：

| 类型 | 可以选择的物体 | 主要观察什么 |
|---|---|---|
| 简单实体 | 玩具、收纳盒 | 整体轮廓是否完整 |
| 细结构或孔洞 | 带把手的杯子、小凳子 | 细杆、杯柄、空隙是否保留 |
| 非对称结构 | 一侧有附件的玩具车 | 左右结构是否被错误补成对称 |
| 明显图案 | 有花纹的盒子 | 图案位置和清晰度 |
| 明显材质 | 金属外观的小物件、陶瓷摆件 | 颜色、反光和表面感觉 |

先选好图片，再看输出。所有样本和失败记录都保留。
第一次排查环境时，选背景简单、物体完整的图片；透明玻璃、镜面和严重遮挡可以留到后续挑战集。

两组共用同一份去背景后的图片，图片路径和种子写入实验计划。
两种模型随后各自执行适合自己的裁剪和缩放。

本轮比较的是两套系统的最终可用效果。它们的训练数据、结构和计算量各有特点；
报告中把这些配置一起写清楚。

## 3. 操作前先分清三个地方

| 地方 | 怎么进入 | 主要做什么 |
|---|---|---|
| 笔记本 PowerShell | Windows 本地终端 | 打包、上传、下载结果 |
| HPC 登录节点 | ssh hkust-hpc4 | 整理文件、提交任务、查看队列；按学校规定下载权重 |
| HPC 计算节点 | srun 分配，或 sbatch 调度 | CPU 节点做安装准备、下载和抠图；GPU 节点编译验证并跑模型 |

SSH 连上后，先进入的是登录节点。
执行 srun 并等到分配成功，才进入计算节点。终端可能仍然长得相似，可以用
hostname 查看机器名，用 echo "$SLURM_JOB_ID" 查看当前计算任务编号。

另外记住三个动作：

- **安装环境**：准备 Python 库和 CUDA 扩展，通常在初次配置时完成。
- **下载权重**：把模型参数保存到磁盘，后续运行直接读取。
- **激活环境**：用 source 选择当前终端使用哪一套 Python，每次换终端或换模型时执行。

本版使用一个准备环境和两个生成环境，三个目录都保存在项目中：

| 用途 | 环境目录 | 激活命令 |
|---|---|---|
| 下载、CPU 抠图、计划和统计 | .venv-prepare | source .venv-prepare/bin/activate |
| 混元三维生成 | .venv-hpc | source .venv-hpc/bin/activate |
| TRELLIS.2 三维生成 | .venv-trellis2 | source .venv-trellis2/bin/activate |

下面所有服务器命令默认在 ~/asset3d-pilot 项目目录执行。
其中 ~ 是你的服务器个人目录，$USER 会自动替换成服务器用户名。

## 4. 把代码上传到服务器

**在哪里：笔记本 PowerShell。**

```powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
.\.venv\Scripts\python.exe scripts/package_project.py
scp '.\dist\asset3d-source.tar.gz' hkust-hpc4:~/asset3d-pilot-source.tar.gz
ssh hkust-hpc4
```

前三条命令分别完成：进入项目、打包源码、上传压缩包。
最后一条进入服务器。hkust-hpc4 使用你之前配置的 SSH 别名。

**在哪里：服务器登录节点。**

以下是第一次创建 ~/asset3d-pilot 时的操作。
如果已有这个目录，先确认它的内容和代码版本，再决定更新原目录还是换新目录。

```bash
if [ -e ~/asset3d-pilot ]; then
  echo '已有项目目录：请先检查其中的代码和结果'
else
  mkdir ~/asset3d-pilot
  tar -xzf ~/asset3d-pilot-source.tar.gz -C ~/asset3d-pilot --strip-components=1
fi
cd ~/asset3d-pilot
mkdir -p logs data/raw
ls
```

**完成后检查：**ls 输出中能看到 configs、src、scripts、slurm、docs、README.md。
服务器会重新安装 Linux 环境，上传包里只装源码和说明。

## 5. 在网页上申请辅助模型的访问权限

**在哪里：笔记本浏览器。可以在等待服务器资源时处理。**

用自己的 Hugging Face 账户打开：

- [DINOv3-L](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m)：按页面要求申请访问。
- [RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0)：按页面要求接受条款并取得访问权限。

DINOv3 用于提取图片特征。RMBG 用于去背景；我们会提前准备透明图片，
同时保留官方加载程序需要的 RMBG 文件。

主模型 TRELLIS.2 还会读取第一代 TRELLIS 的一个辅助解码器。
后面的下载命令会把配置里列出的模型一起缓存，代码中已固定各自版本。

**完成后检查：**网页显示你的账户可以访问相应模型文件。
如果正在等待审批，可以先继续安装环境和准备图片。

## 6. 先用 CPU 做准备：模块、环境和卡时

本版按下面的顺序执行：

```text
登录节点：查看模块、上传源码、确认模型权限
   ↓
CPU 计算节点：建准备环境 → 下载权重 → 抠图 → 建立实验计划（第 6～9 节）
   ↓ 结束 CPU 分配
GPU 计算节点：安装三维模型环境与扩展 → 检查 GPU → 立即生成首个样例（第 10 节）
   ↓ 结束 GPU 分配
登录节点：提交余下实验；笔记本：查看结果
```

这样把体积较大的模型下载和图片准备放到申请 GPU 之前。先在笔记本选好五张图片、
完成第 5 节的访问申请，再开始下面的操作，减少占用计算节点等待人工准备的时间。

### 6.1 哪些操作需要 GPU，怎样计算资源占用

| 操作 | 本指南安排在哪里 | 原因 |
|---|---|---|
| 查看模块、编辑配置、提交任务 | 登录节点 | 操作轻量 |
| 创建准备环境、下载模型、抠图 | CPU 计算节点 | 这些步骤使用 CPU、磁盘和网络 |
| 安装三维模型环境、编译 CUDA 扩展 | 首次放在 L20 节点 | 部分安装程序会检测显卡，便于现场验证 |
| 加载三维模型、生成白模和材质 | L20 节点 | 需要 GPU 运算 |
| 查看结果、填写评分 | 笔记本 | 可以先结束服务器的交互分配 |

CUDA 扩展的编译主要由 CPU 完成；部分构建程序还会查询 GPU 型号或测试 CUDA。
当前两个安装脚本把依赖安装、扩展编译和 GPU 检查放在一起，所以第 10 节仍在 L20 上运行它们。
本次指南调整首先把权重下载和数据准备提前；GPU 安装阶段仍可能下载 Python 包及第三方源码，
这部分部署时间也会占用卡时。

**GPU 已分配给作业后，即使正在安装、等待下载或阅读说明，也会持续占用资源。**
做预算时可按“GPU 张数 × 分配后实际占用时间”估算卡时。例如一张卡占用半小时，
对应 0.5 GPU 小时的资源占用。账户实际扣减、价格和计费粒度以学校记录为准。
CPU 作业使用对应的 CPU 配额；申请 CPU 节点时也应及时结束已完成的任务。

`--time=02:00:00` 设置作业最多运行两小时。工作完成后可以提前退出。
学校建议结束交互会话以停止计费资源占用，见[交互作业说明](https://hkust-hpc-docs.readthedocs.io/stable/kb/slurm/slurm-how-to-request-interactive-sessi-HV7WS9.html)。

### 6.2 “加载模块”要执行哪些命令

**在哪里：服务器登录节点。**

学校已安装多个版本的软件。`module load` 会让当前终端选用指定版本，
自动设置程序搜索路径和库路径。先查看：

```bash
module avail cuda
module avail gcc
module avail python
module list
```

`avail` 列出可用模块，`list` 列出当前已加载的模块。
学校文档列出过下面的名称；**只有你当前列表也包含这些完整名称时，才照抄这两条命令**：

```bash
module load gcc/12.3.0-5x7uqys
module load cuda/12.4.0-uhdfj7w
```

如果名称不同，从实际列表复制对应的完整名称。也可用下面的命令进一步查找：

```bash
module spider cuda
module spider gcc
```

加载后检查：

```bash
module list
nvcc --version
gcc --version
g++ --version
python3 --version
```

- `nvcc` 是 CUDA 编译工具。现有安装脚本要求输出中包含 `release 12.4`。
- `gcc` 和 `g++` 用于编译 C/C++ 代码；上面的 GCC 12.3 是本次候选组合。
- Python 使用 3.10 或 3.11。若当前版本不同，先从学校模块中选择对应版本，再检查。
- `nvidia-smi` 在获得 GPU 后查看显卡和驱动；编译工具版本通过 `nvcc --version` 查看。

如果列表里找不到需要的版本，先解决模块选择，再启动安装脚本。
模块名称和用法参考[HPC4 模块说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4/software-module-system)。
实际扩展兼容性将在第 10 节验证。

### 6.3 把每次需要恢复的设置保存下来

**在哪里：服务器项目目录，用 VS Code 新建文件。**

新建 `configs/hpc4-session.local.sh`。下面是内容示例，前两行使用刚刚确认过的模块名称；
如果 Python 也通过模块选择，把对应的 `module load` 行一并写入：

```bash
# 使用本机 module avail 已确认的完整名称
module load gcc/12.3.0-5x7uqys
module load cuda/12.4.0-uhdfj7w

# 所有环境共用磁盘上的模型缓存
export HF_HOME=/scratch/$USER/project3/cache/huggingface
export U2NET_HOME=/scratch/$USER/project3/cache/rembg
export PIP_CACHE_DIR=/scratch/$USER/project3/cache/pip
export MAX_JOBS=2
```

模型文件放在 `HF_HOME`，抠图模型放在 `U2NET_HOME`，Python 安装包缓存放在 `PIP_CACHE_DIR`。
`MAX_JOBS=2` 限制扩展编译的并行任务数。

每次新开终端，执行：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
module list
```

这里用 `source`，让设置作用于当前终端。再按任务激活需要的 Python 环境。
这个文件保存模块名和路径即可，Hugging Face token 交给登录工具管理。

### 6.4 申请 CPU 节点，建立轻量准备环境

**在哪里：先在登录节点申请 CPU，等待分配成功后再执行安装。**

```bash
srun --account=mscaiehpc42026 --partition=amd --nodes=1 --ntasks=1 --cpus-per-task=4 --time=02:00:00 --pty bash
```

得到计算节点终端后：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
hostname
echo "$SLURM_JOB_ID"
python3 --version

python3 -m venv .venv-prepare
source .venv-prepare/bin/activate
python -m pip install 'pip<26' 'setuptools<76' wheel
python -m pip install -e '.[download]' 'huggingface-hub==0.36.2' 'rembg==2.0.61' 'onnxruntime==1.20.1'
python -m pip check
asset3d --help
```

这个 `.venv-prepare` 环境只负责下载、CPU 抠图、实验计划和统计。
其中的 ONNX Runtime 使用 CPU 运行抠图模型。三维生成所需的 PyTorch、CUDA 扩展和官方模型代码，
由第 10 节的两个安装脚本装入各自环境。

**完成后检查：**`pip check` 正常结束，`asset3d --help` 能列出项目命令。
接着在同一个 CPU 会话完成第 7～9 节。以后复用这个环境时，执行
`source .venv-prepare/bin/activate` 即可。

若该计算节点无法联网，先结束当前分配，按学校允许的联网安装方式处理。
耗资源的安装、编译和抠图安排在计算节点，见[学校入门说明](https://hkust-hpc-docs.readthedocs.io/latest/quick-start/index.html)。

### 6.5 退出以后，哪些内容会保留

| 内容 | 执行 exit 后 | 下次要做什么 |
|---|---|---|
| 项目代码、三个虚拟环境、编译好的扩展 | 保存在项目磁盘目录 | 进入项目并激活所需环境 |
| 下载好的模型权重 | 保存在共享缓存目录 | 设置相同的缓存路径后读取 |
| 当前终端的模块、export 变量、环境激活状态 | 随该会话结束 | source 设置文件，再激活环境 |
| 计算任务使用的内存、显存和 GPU 分配 | 随任务结束释放 | 下次通过 Slurm 重新申请资源 |

`~/asset3d-pilot` 位于服务器个人目录。HPC4 的个人目录、组目录和 `/scratch`
从各计算节点都能访问，因此下一次分配到另一台机器，也能读取已经安装的文件。
学校对 `/scratch` 有清理规则：连续 60 天未访问的文件会被清理。
源码和重要结果保留在个人目录，并下载副本到笔记本。
见[学校存储说明](https://itso.hkust.edu.hk/services/academic-teaching-support/high-performance-computing/hpc4/fileandstorage)。

这里的 `exit` 指退出 `srun --pty bash` 创建的计算节点 shell，返回登录节点。
如果你又在里面开了一层 bash，第一次 exit 只会退出内层 shell。
回到登录节点后用 `squeue -u "$USER"` 确认刚才的交互作业已结束。
仍有自己不再需要的作业时，用 `scancel 作业编号` 结束对应任务。
关闭终端窗口后，也应通过队列确认资源是否已经释放。

## 7. 在 CPU 会话中登录 Hugging Face 并下载权重

**在哪里：继续使用第 6.4 节的 CPU 计算节点，确认该节点可以联网。**

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
source .venv-prepare/bin/activate
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
hf auth login
```

按终端提示输入 Hugging Face token。token 在 Hugging Face 账户设置中创建，
需要能读取第 5 节已获准的模型。首次登录后，相同缓存位置下可以复用登录状态。

在同一个准备环境中下载两组权重：

```bash
asset3d download --config configs/hunyuan2_pilot.yaml --background
asset3d download --config configs/trellis2.yaml
```

第一条下载混元的形状、纹理等权重，`--background` 还会准备共用的抠图模型。
第二条下载 TRELLIS.2 和它的辅助模型。下载入口只把文件存到磁盘，此时无需启动三维生成模型。
第 10 节的两个 GPU 环境会从同一个 `HF_HOME` 读取这些文件。

**完成后检查：**两条命令都正常结束并打印本地路径。遇到 401/403 时，
检查账户、token 和访问权限。审批尚未通过时，先退出计算分配，待权限齐全后继续。
下载中断后可在相同缓存路径下重新执行命令，下载工具会复用完整文件。

把权重下载完整，再申请 GPU。下载完成后可以继续第 8 节；
若需要较长时间挑选图片或处理人工操作，先退出 CPU 分配，之后重新申请 CPU 即可。

## 8. 上传五张图片，做一次共用抠图

本地 `data/raw/` 已准备陶罐、带柄杯、茶壶、魔方、铜铃五张 JPG，`data/manifests/pilot.csv` 已填写。图片来源和观察重点见 [SOURCES.md](../data/raw/SOURCES.md)。下面先把图片和清单一起上传。

**在哪里：笔记本 PowerShell。可在申请 CPU 之前提前完成本节上传。**

如果服务器 CPU 会话正在运行，用另一个本地 PowerShell 窗口上传。
把五张选好的图片放在本地项目的 data/raw，命名与下面清单对应。
例如这五个文件都准备好后：

```powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
scp '.\data\raw\simple.jpg' '.\data\raw\thin.jpg' '.\data\raw\asymmetric.jpg' '.\data\raw\pattern.jpg' '.\data\raw\material.jpg' hkust-hpc4:~/asset3d-pilot/data/raw/
scp '.\data\manifests\pilot.csv' hkust-hpc4:~/asset3d-pilot/data/manifests/pilot.csv
```

**在哪里：服务器项目目录。**

```bash
cp -n data/manifests/pilot.example.csv data/manifests/pilot.csv
```

用 VS Code 打开服务器上的 data/manifests/pilot.csv，检查内容：

```csv
id,image,reference,split
simple,../raw/simple.jpg,,real
thin,../raw/thin.jpg,,real
asymmetric,../raw/asymmetric.jpg,,real
pattern,../raw/pattern.jpg,,real
material,../raw/material.jpg,,real
```

四列的含义：

- id：物体的短名字，会成为结果文件夹名称。
- image：图片路径，起点是 CSV 所在目录，所以 ../raw 指向 data/raw。
- reference：已知的真实三维模型路径；本轮用普通照片时留空。
- split：real 表示这组照片用于观察实际生成效果。

如果第 7 节的 CPU 会话还在，继续使用它。若已经退出，先在登录节点重新申请 CPU：

```bash
srun --account=mscaiehpc42026 --partition=amd --nodes=1 --ntasks=1 --cpus-per-task=4 --time=00:30:00 --pty bash
```

在 CPU 计算节点执行：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
source .venv-prepare/bin/activate
asset3d pilot-prepare --manifest data/manifests/pilot.csv --split real --output data/prepared/pilot01
```

这一步会：

1. 读取图片，分离物体与背景。
2. 把背景设为透明，裁掉多余边缘。
3. 把物体居中，统一输出为 1024×1024 的 PNG。
4. 生成新的图片清单和处理记录。

**完成后检查：**在 VS Code 中逐张打开 data/prepared/pilot01/*.png，
观察杯柄、细杆、边缘有没有被抠掉。透明区域通常显示为棋盘格。
已经带透明背景的输入会直接使用它的蒙版。

如果蒙版有明显错误，修正原始输入，再输出到一个新目录，例如 pilot02。
两模型后续要用同一份检查通过的图片。

## 9. 固定本轮实验计划

**在哪里：继续使用上一步的 CPU 节点。**

```bash
asset3d pilot-init --manifest data/prepared/pilot01/objects.csv --split real --seeds 42 123 --output results/pilot01
```

pilot-init 把“比较哪些物体、哪些模型配置、哪些种子”写入 experiment.json，
并保存配置副本。还会记录图片和源码的文件指纹，后面恢复运行时用来确认实验条件。

**完成后检查：**results/pilot01 中出现 experiment.json 和 configs 文件夹。
图片、配置和源码此后保持固定；需要改实验条件时，建立新实验目录。

程序按源码文件内容计算指纹，修改 Python 代码或其中的注释后，应新建计划，
例如 results/pilot02，旧结果继续保留。本次仅更新指南，已有计划可以继续配合相同版本的源码使用。

执行 exit，结束 CPU 交互分配，返回登录节点。

## 10. 申请 L20：完成安装，随即运行首个样例

到这里应已具备：模型访问权限、完整权重缓存、检查过的前景图片，以及
`results/pilot01/experiment.json`。先把这些准备齐，再申请 GPU。

### 10.1 首次安装三维模型环境

**在哪里：登录节点申请 GPU，再在分配到的计算节点操作。**

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
srun --account=mscaiehpc42026 --partition=gpu-l20 --nodes=1 --ntasks=1 --gpus-per-node=1 --time=02:00:00 --pty bash
```

等待分配成功后：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
hostname
echo "$SLURM_JOB_ID"
nvidia-smi
nvcc --version
python3 --version
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
```

`nvidia-smi` 应显示分配到的 L20，`nvcc` 应为 12.4，Python 应为 3.10 或 3.11。
然后逐条执行安装，每条成功结束后再继续：

```bash
bash scripts/install_hpc.sh
bash scripts/install_trellis2_hpc.sh
```

脚本分别创建 `.venv-hpc` 和 `.venv-trellis2`，安装各自的依赖和 CUDA 扩展，
最后用 `doctor --gpu` 检查 GPU 与组件导入。两个脚本结束后，
`logs/environment-hpc.json` 和 `logs/environment-trellis2.json` 应已生成，
同目录还有依赖版本记录。

安装脚本尚未在学校 L20 上完成实机验收。出现编译或导入错误时，先记录完整错误；
如果接下来需要较长时间查资料，结束当前 GPU 分配，分析后再申请资源。
保留现有环境和日志，按失败步骤处理。

本节两小时是首次作业的时间上限，覆盖安装和随后样例运行。按实测调整后续申请时长。
如果环境已经安装并通过 GPU 检查，后续会话仍先申请 GPU、恢复第 10.3 节的环境设置，
然后执行第 10.2 节的样例命令，复用已安装的文件。

### 10.2 在同一次 GPU 分配中，马上生成首个样例

**在哪里：继续使用刚才的 GPU 终端。**

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

source .venv-trellis2/bin/activate
asset3d doctor --gpu --backend trellis2
asset3d pilot-run --experiment results/pilot01 --name trellis2 --limit 1

source .venv-hpc/bin/activate
asset3d doctor --gpu --backend hunyuan2
asset3d pilot-run --experiment results/pilot01 --name hunyuan2 --limit 1
```

两个 OFFLINE 设置让模型加载只读取已经下载好的权重。
`doctor` 检查当前环境；`pilot-run` 真正生成三维模型。
`--limit 1` 表示各组只跑第一项：`simple`、`seed 42`。

如果某个样例之前已经尝试过，按第 11 节确认旧任务结束并处理遗留锁，
然后在对应的 `pilot-run` 命令末尾加 `--resume`。
已经完成的样例会检查文件完整性后跳过。

**完成后检查：**日志应显示 `completed`，并生成以下文件：

```text
results/pilot01/trellis2/simple/seed-42/asset.glb
results/pilot01/hunyuan2/simple/seed-42/asset.glb
```

对应目录还应有 `shape_raw.glb` 和 `manifest.json`，其中记录了样例耗时。

生成结束后，在计算节点执行：

```bash
exit
```

回到登录节点后确认作业已结束：

```bash
squeue -u "$USER"
```

接着按第 12 节下载模型，在笔记本的 Blender 中检查能否打开、旋转，以及颜色和图案。
查看结果的这段时间可以释放 GPU。两组样例通过检查后，按第 11 节提交剩余任务。
首个样例已经属于正式计划，后面的 `--resume` 会跳过成功项。

### 10.3 下次重新进入 GPU 节点时

再次申请 GPU 后，恢复设置并激活所需环境即可。以 TRELLIS.2 为例：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
source .venv-trellis2/bin/activate
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
asset3d doctor --gpu --backend trellis2
```

随后执行对应的生成或续跑命令。只有依赖有变动或环境需要修复时，才处理安装步骤。

## 11. 提交剩余样本，查看进度

**在哪里：服务器登录节点。**

先恢复第 6 节保存的设置，随后提交：

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
mkdir -p logs
sbatch slurm/pilot.sbatch trellis2 results/pilot01 --resume
sbatch slurm/pilot.sbatch hunyuan2 results/pilot01 --resume
squeue -u "$USER"
```

sbatch 把任务交给学校调度系统。系统分配显卡后，脚本会选择正确环境并依次生成。
两次提交分别返回一个作业编号。记下编号，用来查看任务状态。
默认 sbatch 会继承提交终端导出的环境；提供的脚本还会选择对应虚拟环境和缓存路径。
如果两组同时开始运行，会各占用一张 GPU。希望每次只占一张卡时，等第一组结束再提交第二组。

squeue 中常见状态：PD 表示排队，R 表示运行。
任务从队列消失后，检查 logs 中的作业日志和实验目录里的结果。

单样例详细日志在：
```text
results/pilot01/process-logs/trellis2/
results/pilot01/process-logs/hunyuan2/
```

可以用 tail -n 50 日志路径 查看末尾信息，也可直接在 VS Code 打开。
队列作业运行期间可以关闭笔记本连接，服务器继续执行。

默认每样例最多等待 1800 秒，每个作业最多运行两小时。
根据第 10 节实测耗时调整时限。例如需要更长作业时间，可在提交时加 --time：
```bash
sbatch --time=04:00:00 slurm/pilot.sbatch trellis2 results/pilot01 --resume
```
先确认学校对该分区的时限与配额要求，再选择合适数值。

### 中断以后怎样继续

确认旧任务已结束，再用相同的提交命令和 --resume 恢复。

- 混元若已经保存白模，会从后面的纹理步骤继续。
- TRELLIS.2 需要内存中的原生材质数据，失败后会重新执行该样例的原生生成。
- 已完成的结果会检查文件完整性，然后跳过。

为避免两个进程写同一个结果，程序会创建锁文件。
强制结束可能留下 .pilot-模型名.lock 或单例 .running.lock。
先查 squeue，确认对应作业结束，再删除明确属于该次中断的锁文件。
日志保留每次尝试的时间和状态。

## 12. 下载结果，先看白模，再看颜色与材质

**在哪里：笔记本 PowerShell。**

```powershell
Set-Location 'D:\AIEproject\MAIE5421_CV\Final Project'
New-Item -ItemType Directory -Force '.\results' | Out-Null
scp -r hkust-hpc4:~/asset3d-pilot/results/pilot01 '.\results\pilot01-server'
```

在 Blender 中选择 File → Import → glTF 2.0，分别打开模型。
查看 asset.glb 时，切换到能显示材质的视口模式，例如 Material Preview。

每个样例的文件用途：

| 文件 | 用来看什么 |
|---|---|
| input.png | 本次生成收到的输入；预实验中是共用前景图 |
| foreground.png | 共用程序裁剪、缩放后交给后端的图片；官方模型内部还会做自己的预处理 |
| shape_raw.glb | 导出简化前的几何；观察轮廓、孔洞、细结构 |
| asset.glb | 最终带纹理/材质的资产 |
| manifest.json | 配置、版本、种子、耗时、显存和运行状态 |
| run.log | 异常时的详细错误信息 |

观察一个模型时，至少转一圈：正面、侧面、背面、顶部。
用白模判断形状，用最终资产判断图案与材质。
例如杯柄是否闭合属于几何问题，杯身花纹是否清晰属于外观问题。

### 可选：用相同相机和灯光批量生成预览图

服务器安装了 Blender 4.x 时，在 CPU 计算节点、已激活项目环境后执行：
```bash
asset3d pilot-render --experiment results/pilot01 --blender blender --views 8
```

每个结果会新增：

- white_preview：统一灰白材质的八个视角。
- preview：带材质的八个视角。

模型已经生成完毕，Blender 此时只负责拍摄预览。
这一步用 CPU 渲染，可以按第 8 节的方式申请 CPU 节点，激活 .venv-prepare，
并按样本数量调整时间。
如果需要校正模型朝向，先在开发样例上统一坐标约定，再比较同一侧的细节。

## 13. 汇总结果，怎样选模型

**在哪里：服务器上已激活项目 Python 环境的终端。此命令汇总记录，通常很快。**

```bash
cd ~/asset3d-pilot
source configs/hpc4-session.local.sh
source .venv-prepare/bin/activate
asset3d pilot-report --experiment results/pilot01 --output results/pilot01/summary
```

输出：

- runs.csv：所有计划项的状态、时间等记录。
- summary.json：每组的汇总。
- paired.json：同一物体、同一种子下，两组都成功的对应结果。
- ratings.csv：人工评分表，重复生成报告会保留已填写内容。

提前约定 1～5 分规则，5 分最好：

| 评分项 | 具体观察 |
|---|---|
| geometry_1to5 | 轮廓、孔洞、部件、细结构 |
| appearance_1to5 | 颜色、图案、接缝、材质 |
| input_match_1to5 | 原图中看得见的特征是否保留 |
| usable_yes_no | 是否可以用来展示课程成果 |
| notes | 记下缺失部件、变形、花纹错误或失败原因 |

同一物体先汇总两个种子，再比较五个物体。
把“完整生成成功的比例”和“两组都成功时的质量”放在一起看。
有些模型可能质量较好但失败较多，这一点也应进入选型判断。

优先看几何与外观是否满足展示需求，再比较完整耗时和维护成本。
五个物体用于初步选择；正式项目评价再准备一组新的物体。

时间字段这样读：

- 混元 shape + texture：形状生成和上色。
- TRELLIS native_shape_material：原生形状与材质生成，包括内部图像预处理。
- pbr_bake：TRELLIS 整理网格、UV 和贴图的额外开销。
- wall_seconds：一次管线尝试的总时间，包含模型加载等步骤。
- process_wall_seconds：外层记录的进程总时间，还包含 Python 启动。

比较使用成本时重点看总时间，同时保留分阶段时间帮助解释原因。
显存记录来自 PyTorch 的分配器，原生 CUDA 库还可能有额外占用。

## 14. 进阶：有真实三维模型时，计算形状误差

第一次只有照片时，可以先完成第 13 节的人工比较。

有真实三维参考模型时，把 CSV 的 reference 填为它的路径，split 设为 dev，
并在 pilot-prepare、pilot-init 中使用 --split dev，建立新的实验。
下面假设新实验目录叫 results/pilot-gt01，并且已经完成两组生成；按实际目录修改命令。

Chamfer Distance 的直观含义是：
从生成模型和真实模型的表面各取很多点，计算两边的点离对方表面有多远。
距离越小，说明两者的表面越接近。

计算前要确认两模型朝向一致。例如一个杯子竖着、另一个横着，直接计算会产生很大误差。
程序支持把标定好的 4×4 刚性变换写入 transforms.json，键为 trellis2、hunyuan2，
值为各自从预测坐标转到参考坐标的矩阵。

```bash
asset3d pilot-evaluate --experiment results/pilot-gt01 --transforms data/transforms.json
asset3d pilot-report --experiment results/pilot-gt01 --output results/pilot-gt01/summary
```

具体采样和归一化设置在 configs/evaluation.yaml。
实际标定完成后再生成 transforms.json；照片缺少三维真值时，程序跳过这一项。

## 15. 出错时先看哪一项

| 现象 | 首先检查 |
|---|---|
| 下载出现 401/403 | Hugging Face 登录、token、模型访问审批 |
| 离线找不到模型 | 本次 HF_HOME 是否与下载时相同，下载是否结束 |
| CUDA 扩展无法导入 | 激活的环境、nvcc、torch 版本、编译日志 |
| module load 提示找不到模块 | module avail / module spider 的完整模块名称 |
| 换节点后命令找不到 | source 设置文件，再激活对应虚拟环境 |
| 退出后仍看见自己的作业 | squeue 中的作业编号，确认是否还有内层 shell 或其他作业 |
| .venv-prepare 里无法生成三维模型 | 按第 10 节进入 GPU 节点并切换到相应生成环境 |
| 显存不足（OOM） | TRELLIS low_vram 设置、当前节点显存占用、输入复杂度 |
| 输入被拒绝为非透明图 | 是否使用 pilot-prepare 产生的清单 |
| --resume 提示条件变更 | 图片、配置、源码是否改动；改动后建立新计划 |
| 提示存在锁文件 | 对应作业是否仍在运行，是否曾被强制结束 |
| 结果看起来横躺 | 模型、GLB 导出和查看器的坐标轴约定 |
| 前景中细杆缺失 | 抠图蒙版；先修正输入再开始比较 |
| 某个种子效果差 | 保留结果，与另一种子一起记录稳定性 |

TRELLIS 还有 configs/trellis2_smoke.yaml 的 512 配置，可单独用于环境诊断。
正式组默认使用 1024_cascade；调整正式配置时另建实验计划，报告中写清设置。

## 16. 想看代码时，从这些文件开始

按下面顺序读，可以跟着一次实验走完：

1. pilot.py：prepare 做共用抠图，initialize 写计划，run 依次启动生成，report 汇总。
2. preprocess.py：怎样利用透明蒙版裁剪和缩放图片。
3. pipeline.py：一次生成从初始化到保存文件的总流程。
4. backends/trellis2.py 或 backends/hunyuan2.py：真正调用官方模型的位置。
5. export.py：检查贴图并保存 GLB。
6. evaluation/geometry.py：有三维真值时怎样计算表面误差。
7. blender_render.py：怎样用统一灯光和相机查看模型。

这些文件位于 src/asset3d 下，关键位置已有中文注释。
论文出处、固定版本和参数选择见 [PILOT_METHOD.md](PILOT_METHOD.md)。
