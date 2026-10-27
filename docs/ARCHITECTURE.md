# 代码结构与数据流

```text
configs/                  三档形状步数和独立的评价参数
src/asset3d/
  cli.py                  命令入口与参数校验
  config.py               YAML 继承、字段检查、版本锁定
  pipeline.py             生成状态、缓存、恢复、输出目录锁
  backends/hunyuan2.py     真实模型调用；延迟导入 GPU 依赖
  preprocess.py           透明蒙版识别、去背景、裁剪居中
  mesh_ops.py             网格有效性检查；第一版不做激进拓扑简化
  export.py               GLB 原子写入、重载、纹理与 UV 验证
  recording.py            哈希、时间、源代码/依赖版本、运行清单
  data.py                 数据清单、对象级划分
  experiments.py          完整配置×对象×种子矩阵
  evaluation/geometry.py  采样几何指标、轮廓 IoU 函数
  evaluation/summarize.py 含失败/未运行样本的汇总
  evaluation/appearance.py 随机化盲评材料与匿名对应表
  render.py               启动 Blender 的受控命令
  blender_render.py       Blender 内执行的固定相机与光照渲染
  demo.py                 Gradio 界面，复用 Pipeline
slurm/                    单例、批量、CPU 评价任务
scripts/                  安装、打包和兼容命令入口
tests/                    已知几何与测试后端的功能验证
```

## 为什么这样分

只有 `backends/hunyuan2.py` 依赖官方模型 API；笔记本可以安装基础包并运行评价，而无需导入 PyTorch。用户界面与批量实验都调用 `Pipeline.run`，防止两套处理逻辑产生不同结果。Blender 是独立外部进程，不与 PyTorch 共用 Python 环境。

第一版只检查有效网格，不自动删“小碎片”或降低面数，避免误删细腿、杯柄等真实部分。若后续增加简化，须成为显式配置，并在贴纹理之前执行。

## 状态和恢复

运行目录中的 manifest 记录 `running / failed / completed / shape_only`。完整带纹理输出才标记 completed。shape_only 仅用于排错，不能视为最终课程交付。

输入图片、配置和随机种子定义一次运行；源代码哈希也必须一致才能恢复。已登记的中间文件重新读取前核对 SHA256。首次输出不能覆盖已有非空目录；运行锁阻止同一个单例目录并发写入。

每个阶段成功才登记缓存。纹理失败后保留形状并追加错误日志；再次执行使用相同的配置和种子并传 `--resume`。官方模型代码也检查固定提交和受版本管理的修改。手动修改上游不应悄悄进入同一实验。

## 计时和随机性

每次尝试分别记录模型加载、前景处理、形状、纹理、导出与总墙钟时间。CUDA 阶段完成后同步再计时。峰值显存记录 PyTorch 分配器的 allocated/reserved；驱动显示的进程占用还包含其他 CUDA 库分配的内存。

形状 seed 可变；上游纹理内部固定 seed，日志披露其实际值。所有输入应使用相同处理规则。GPU 非确定性与环境差异仍可能导致结果不逐位相同。

第一次模型加载是冷启动，后续是热运行；汇总 CSV 保留标记。恢复后的耗时不与一次完整生成混在一起作公平速度比较；仍保存所有尝试的总耗时用于成本分析。

## 当前不包含

基础模型训练/微调、自动获取全部 GSO 数据、自动推断真实相机、非刚性对齐、新的纹理算法、公开部署、账户额度查询。这些都不应被描述为已实现。

