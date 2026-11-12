# 预实验方法依据

TRELLIS.2 论文：Xiang 等，Native and Compact Structured Latents for 3D Generation。
本次核对的 arXiv 页面最新列出 v1（2025-12-16）：
https://arxiv.org/abs/2512.14692
正文：https://arxiv.org/html/2512.14692v1
代码：https://github.com/microsoft/TRELLIS.2

采用第 3.3 节的稀疏结构、几何潜变量、材质潜变量三阶段及官方预训练权重。
不重新训练/实现 DiT 或 SC-VAE。官方 run() 执行三阶段，适配器保存解码后的原始网格，
再调用官方 O-Voxel 导出 PBR 材质。不是第一代 TRELLIS，也不是六视角重建。

部署设置：1024_cascade、官方默认各阶段采样参数、low_vram=true；
贴图 2048、简化目标 100 万面、remesh=false。原始网格在导出简化前保存。
这些是课程预实验设置，不声称完整复现论文全部实验。
普通嵌入贴图 GLB，不启用示例中的 WebP 扩展，便于通用查看器读取。

混元 3D 2.0：https://arxiv.org/abs/2501.12202
代码：https://github.com/Tencent-Hunyuan/Hunyuan3D-2
保持原项目的普通 DiT-v2-0 与 Paint-v2-0，不换 Turbo、2mv 或 2.1。
几何 50 步、guidance 5、octree 384，纹理 2048。纹理内部种子沿用官方固定值。
混元先生成白模，再在纹理阶段利用多个视角为表面上色。

## 可复现性

TRELLIS.2 代码：75fbf0183001ed9876c8dbb35de6b68552ee08bd。
主权重：af44b45f2e35a493886929c6d786e563ec68364d。
辅助模型 SHA 在 configs/trellis2.yaml；所有加载路径指向本地固定快照。
CUDA 扩展提交在 scripts/install_trellis2_hpc.sh；实际依赖写入 freeze 日志。
这套安装组合需要在 HPC4 的 L20 上通过真实样例验收，步骤见 PILOT_GUIDE.md 第 6～10 节。

比较的是最终系统，训练数据、模型规模、表示和采样器不同。
同一前景输入，各自原生预处理；预实验样本用于选型，后续需独立测试样本。

## 时间、内存、坐标

混元推理计时是 shape+texture；TRELLIS 是 native_shape_material，
包含官方流程的形状、材质及内部预处理，不能称为纯白模时间。
TRELLIS 的 pbr_bake 另列，完整开销还包括加载、预处理、文件导出；
外层 process_wall_seconds 包含 Python 启动。不能只比较局部阶段就宣布整体更快。

PyTorch allocator 峰值不包括所有原生 CUDA 内存，不代表驱动可见的显卡总峰值。
每样例新进程、缓存权重、禁止运行时下载；共享抠图成本另行记录。
失败、超时、未运行均保留在成功率分母。

TRELLIS 官方 GLB 使用 (x,y,z)→(x,z,-y)，白模也采用相同刚性轴变换，不改拓扑。
最终 GLB 保留颜色与金属度/粗糙度贴图。
两模型与真值之间的相机/坐标对应仍需实测标定，不凭名称猜测。
统一灰白材质观察几何，带材质结果观察外观，避免颜色掩盖形状问题。
