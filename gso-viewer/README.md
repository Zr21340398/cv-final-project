# 3D 模型工作台：使用与实验接入

这个工具在本机浏览 GLB，也可以按照实验清单同时展示参考模型和不同方案的生成结果。它只读取已有文件，不会修改模型、计算评价指标或启动 GPU 生成。

## 1. 启动并手动查看模型

Windows 用户双击本目录的 start.bat，程序会启动本地服务并打开浏览器。也可以在项目根目录运行：

~~~powershell
python gso-viewer/server.py --open
~~~

如果浏览器没有自动打开，访问 http://127.0.0.1:8765/。服务窗口需保持打开；结束时在窗口按 Ctrl+C。端口被占用时可添加 --port 8766，并打开对应端口。

页面默认显示三个空窗口。点击窗口中间的加号选择本地 GLB 文件，也可以拖入文件；工具栏可以添加窗口，每个窗口右上角可以替换模型、重置视角或关闭窗口。左键拖动旋转、滚轮缩放、右键拖动平移，各窗口独立控制。手动选择模型无需实验数据或网络连接。

当前手动模式支持 GLB；单独的 OBJ、FBX、GLTF 及其外部贴图需要先转换为 GLB。模型越多、面数越高，浏览器占用的显存和内存越多。

## 2. 查看这次 GSO 开发集

点击 **实验预设**，在“实验”下拉框选择 **asset3d-gso-v1-20261108 / gso-dev-v1**，再选择物体、种子和模型类型，点击 **对比参考模型与所有方案**。页面会放入 GSO 参考模型和 20、30、50 步的三个结果。也可在单个窗口选择一个方案加载。

预设默认从项目根目录下读取：

~~~text
asset3d-gso-v1-20261108/
├── data/rendered/gso-formal-v1/gso_01/reference_normalized.glb
└── results/gso-dev-v1/
    ├── viewer-manifest.json
    └── hunyuan2_steps50/gso_01/seed-42/asset.glb
~~~

模型文件和数据需要单独获取；它们不包含在 Git 仓库中。此目录中没有展示清单时，程序还可以读取这次旧实验的目录布局及 GSO 数据清单，不会修改原始实验记录。缺失的参考或结果文件会在页面中标记。

这次开发集的 viewer-manifest.json 是添加在实验结果目录的独立索引，保留原有 experiment.json 和模型文件。GSO 参考模型是用于比较的扫描网格。生成结果和参考的原始朝向可能不同，预览时需要旋转检查；做几何评价时另需制定统一对齐规则。

## 3. 给新的正式实验提供展示清单

当前项目的 asset3d batch 创建实验计划后，会在实验输出目录写入并更新 viewer-manifest.json。清单记录：

- 对象、参考模型路径和输入图路径；
- 每个实验方案的名称与完整配置；
- 每个对象、方案和随机种子的状态、对应的输入图片及已完成的 GLB 路径。

工作台默认在项目根目录的 results/实验名/，以及 实验包/results/实验名/ 中查找 viewer-manifest.json。放入新的实验目录后，点击工作台上的 **刷新实验列表**，就能选择新实验；同名结果放在不同实验包中会分别列出。清单里记录的是实验方案，选择实验后，对象、种子、模型类型和输入图片来源会随该实验的实际记录变化。

清单路径以清单所在目录为基准，例如 方案名/gso_01/seed-42/asset.glb。参考模型可以放在结果目录之外、同一数据根目录之内，路径可能以 ../../data/ 开头。复制给其他人时，请连同模型与参考数据保持相对目录结构；JSON 本身不包含模型。

打开位于其他目录的实验时，在项目根目录执行：

~~~powershell
python gso-viewer/server.py --data-root "D:\实验数据" --manifest "D:\实验数据\结果\viewer-manifest.json" --open
~~~

--data-root 指向包含清单、生成模型和参考模型的共同父目录。服务只提供该目录内、清单列出的文件。可以重复指定 --manifest 加载多份清单。同名清单以所在路径区分；点击 **刷新实验列表** 会重新读取清单。指定 --manifest 时只读取所列清单；要自动发现新实验，请省略 --manifest。

## 4. 为已有实验生成清单

已有的 experiment.json 可以生成独立展示索引，不需要重新生成 3D 模型。例如，下面的命令以当前本地 GSO 副本为例：

~~~powershell
.\.venv\Scripts\python.exe -m asset3d.cli viewer-index `
  --experiment "asset3d-gso-v1-20261108/results/gso-dev-v1" `
  --reference-dir "asset3d-gso-v1-20261108/data/rendered/gso-formal-v1" `
  --output "asset3d-gso-v1-20261108/results/gso-dev-v1/viewer-manifest.json"
~~~

默认不会覆盖已有索引；确需重建时添加 --overwrite。指定的参考模型与实验记录中的摘要会进行核对。Windows 上清单和对应数据需位于同一盘符，迁移时保留相对布局。

正式生成的配置和权重仍以冻结的实验计划与运行记录为准。代码变化会影响项目的源码指纹；旧实验如需续跑，应先检查续跑校验规则，避免修改冻结记录来绕过校验。

## 5. 运行要求

需要 Python 3.10 或更新版本，以及支持 WebGL 的现代浏览器。Babylon.js 和官方 glTF 加载器 7.54.3 已包含在 vendor 目录，许可证见 vendor/BABYLON-LICENSE.md。本地服务只监听 127.0.0.1。
