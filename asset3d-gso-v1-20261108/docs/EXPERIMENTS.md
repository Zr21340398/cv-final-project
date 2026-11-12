# GSO 正式实验协议

更新：2026-11-06。数据来源已确定，模型与正式参数待预实验结束后冻结。
选样、下载、渲染和清单模板见 [GSO_DATASET.md](GSO_DATASET.md)。

## 对象与划分

本轮正式评估仅使用 GSO：10 个开发对象、20 个测试对象。按简单实体、细结构或孔洞、非对称、明显图案、复杂形状五类分层，各类 2 个开发对象和 4 个测试对象。
第一版对象 ID 与分组已记录在 gso-selection.csv，详情见 [GSO_SELECTION_V1.md](GSO_SELECTION_V1.md)。gso-formal-v1.draft.csv 是预期渲染路径草稿，待下载、渲染和文件校验后再冻结为正式清单。ABO、Toys4K 和实拍案例暂不加入本轮正式统计。

每个对象渲染 8 个固定视角，**只将 view-000.png 作为生成输入**；其他图用于视觉检查。`asset3d render` 输出归一化参考 mesh、PNG 与相机矩阵。旋转轴采用 Blender 的 Z-up；Hunyuan 输出轴约定需在开发集上校准。

```bash
asset3d render --mesh data/raw/gso/object_001/model.obj --output data/rendered/gso-formal-v1/object_001 --views 8 --resolution 1024
```

建立清单（路径相对于 CSV 所在目录），`id` 只允许字母、数字、下划线和短横线，同一物体只出现一次：

```csv
id,image,reference,split
object_001,../rendered/gso-formal-v1/object_001/view-000.png,../rendered/gso-formal-v1/object_001/reference_normalized.glb,dev
object_002,../rendered/gso-formal-v1/object_002/view-000.png,../rendered/gso-formal-v1/object_002/reference_normalized.glb,test
```

将完整清单保存为 data/manifests/gso-formal-v1.csv，手动核对每类数量及近似重复组。当前 split-data 为简单随机划分，本轮按类别和 duplicate_group 审核后的划分填写清单。相似对象整组放在同一划分。预训练数据可能与 GSO 重叠，报告说明这一背景。

## 主要对比

模型选定后，在开发集确定正式参数与资源预算，再冻结测试方案。
候选方向为输入规范化或质量/成本权衡。混元可研究形状推理步数，TRELLIS.2 可研究生成分辨率。
同一轮控制一个变量，配置数量按实测耗时确定，种子暂拟 42 和 123。

混元正式入口现为 `formal-run`，使用新的 `hunyuan2_formal_50/30/20.yaml`，统一启用 pilot03 已验证的 Paint 前 40,000 面副本简化，原始白模保留。
`slurm/experiments.sbatch` 先进行数据与计划检查，默认运行开发集；测试要求显式配置和已完成的对应开发记录。旧 baseline/medium/fast 仅保留兼容。
数据仍需下载、渲染、验收，完整执行顺序与失败恢复见 [HUNYUAN_FORMAL.md](HUNYUAN_FORMAL.md)。

正式矩阵例如 20 个测试对象 × 2 配置 × 2 种子为 80 次生成。失败和未完成条目保留在完整矩阵中。
在开发集上完成单例、坐标校准与参数选择后，再运行测试集。配置、图片、源码变更时建立新实验。

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

