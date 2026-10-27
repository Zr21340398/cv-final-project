# 实验协议

## 对象与划分

从 [Google Scanned Objects](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/) 选择约 30 个对象并记录来源/许可。手动下载所选对象，保留原始贴图、材质路径，不下载整个数据集作为默认操作。目标为 10 个开发对象、20 个测试对象，再加 5–10 个真实照片案例。

每个对象渲染 8 个固定视角，**只将 view-000.png 作为生成输入**；其他图用于视觉检查。`asset3d render` 输出归一化参考 mesh、PNG 与相机矩阵。旋转轴采用 Blender 的 Z-up；Hunyuan 输出轴约定需在开发集上校准。

```bash
asset3d render --mesh data/raw/object_001/model.obj --output data/rendered/object_001
```

建立清单（路径相对于 CSV 所在目录），`id` 只允许字母、数字、下划线和短横线，同一物体只出现一次：

```csv
id,image,reference,split
object_001,../rendered/object_001/view-000.png,../rendered/object_001/reference_normalized.glb,dev
object_002,../rendered/object_002/view-000.png,../rendered/object_002/reference_normalized.glb,test
photo_001,../raw/photo_001.png,,real
```

也可建立 `id,image,reference` 三列 catalog 后使用 `asset3d split-data --catalog ... --output ... --dev-count 10`。输出采用本机绝对路径，所以在服务器生成或迁移后重新整理路径。开发/测试按物体划分，不能把同一物体不同视角随机分开。预训练数据可能重叠，不声称测试对象从未被基础模型见过。

## 主要对比

基线 50 步、中档 30 步、快速 20 步，其他参数固定。对所有对象使用相同的两个形状 seed，例如 42、123。纹理步骤与种子由固定上游实现决定；这组实验不改变纹理配置。先在开发集验证三档参数确实可运行，再冻结配置做正式测试。

```bash
asset3d batch --manifest data/manifests/objects.csv --split dev --seeds 42 --output results/dev01
asset3d batch --manifest data/manifests/objects.csv --split test --seeds 42 123 --output results/test01
```

批处理计划会在开始前保存完整矩阵；如果失败或任务未跑完，汇总仍保留相应条目，成功率分母不缩小。测试失败不能通过删除目录/数据清单而从报告中消失。配置、输入和源码变更应建立新实验。

## 几何评价

三项已实现指标均从网格表面按面积随机采样点后计算，默认每个 mesh 100,000 点：

- Chamfer L2：两个方向最近邻欧氏距离均值的平均值，**不平方**。
- 采样 Hausdorff：两个方向最大最近邻距离的较大值。
- 采样 HD95：两个方向最近邻距离 95% 分位数的较大值。

采样参考/预测使用独立固定种子，因此即使同一个 mesh 对自身比较也有小的采样误差。Hausdorff 标注为采样近似，不能声称是精确连续表面距离。

默认各自将包围盒中心移动到原点，并把最长边缩放到 1；不自动改变旋转、不做镜像、不做非刚性修正。这个协议不测量绝对物理尺寸。若需要保留真实尺度，将 evaluation.yaml 的 normalization 改为 none 并另开实验。

预测与参考的固定轴变换可存为 JSON 4×4 刚性矩阵。`--transform` 先应用于预测，再做中心/尺度归一化。矩阵必须是旋转+平移，不允许缩放、镜像或变形。第一版不实现 ICP；在报告中披露采用的坐标变换。未标定朝向前的距离仅用于排错。

```bash
asset3d evaluate --pred results/first/shape_raw.glb --reference data/rendered/object_001/reference_normalized.glb --output results/first/metrics.json
asset3d evaluate-batch --experiment results/test01 --transform data/manifests/axis-transform.json
asset3d summarize --experiment results/test01 --output results/test01/summary
```

没有轴变换文件时可以省略 `--transform`，但必须确认朝向可比。真实照片没有 reference 时跳过几何评价，不生成假分数。轮廓 IoU 提供为 Python 函数，仅在相机对齐、蒙版尺寸一致时调用；第一版没有自动相机估计，因此不自动输出轮廓分数。

## 纹理与语义盲评

先对每个成功运行渲染固定视图到其 `preview` 子目录：

```bash
asset3d render --mesh results/test01/baseline/object_002/seed-42/asset.glb --output results/test01/baseline/object_002/seed-42/preview
asset3d blind-study --experiment results/test01 --output results/study01
```

将 `study01/public` 提供给至少 3 位评价者，隐藏 `private-key.json`。每个人填写自己的一份 CSV。四项均 1–5 分、越高越好：纹理清晰度、无明显接缝、多视角一致性、语义符合输入。统一查看尺寸、观察全部角度，不因背面与未知真值不同就主观扣分。

当前版本输出盲评材料与评分模板。填写后可用电子表格按隐藏对应表汇总；不得将几何距离当作纹理/语义指标。报告至少列出每档的均值与评价者差异，并展示失败案例。

## 结果解释

`summary/runs.csv` 包括计划内的成功、失败、未运行记录；`summary.json` 先平均同一物体的种子，再统计物体间均值与标准差。恢复任务和失败尝试不进入 clean 时间统计，所有尝试仍保留总耗时。冷启动在 CSV 中标注，端到端均值包含其真实开销；比较纯推理时使用 inference_seconds。

质量统计是成功样本上的条件均值，必须和成功率一起报告。若不同方法失败对象不同，做方法差异比较时另取共同成功对象，并报告数量，避免把不相同样本的差异归因于方法。

先小规模测真实用时再扩大；不提前写“提升了多少百分比”。不要只挑好看的对象，不把调参或官方预处理称为新的基础模型。

