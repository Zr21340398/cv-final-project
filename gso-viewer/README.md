# GSO 实验：本地 3D 模型浏览器

这个小工具在电脑上启动一个仅供本机访问的网页，将一个对象的 20、30、50 步结果放在一起，支持旋转和缩放。可以查看带纹理模型，也可以切换到生成的原始白模。它直接读取已有 GLB，不会修改结果文件，也不会调用生成模型。

## 使用方法

1. 保持此 `gso-viewer` 文件夹完整，包含 `server.py`、`frontend` 和 `vendor`。
2. 在 Windows 上双击 `start.bat`；它会启动本地服务并打开浏览器。也可以打开终端，进入仓库根目录后运行：

   ```powershell
   python gso-viewer/server.py --open
   ```

3. 如果没有自动打开，在浏览器访问 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)。选择对象、种子和模型类型；拖动模型旋转，滚轮缩放。
4. 使用结束后回到 PowerShell 按 `Ctrl+C`，关闭本地服务。

服务窗口需要保持打开。第一次启动时如果 8765 端口被占用，可以用 `--port 8766`，并打开对应端口的网址。浏览器打开网页前，需要先启动本地服务。

## 数据与范围

默认读取仓库目录下的：

```text
asset3d-gso-v1-20261108/results/gso-dev-v1
```

这些 GLB 结果文件需要另外下载或由同学分享，Git 仓库只包含程序和实验记录。如果结果文件保存在其他位置，可在仓库根目录指定：

```powershell
python gso-viewer/server.py --root "D:\你的路径\results\gso-dev-v1" --open
```

程序目前识别 `hunyuan2_steps步数/gso_编号/seed-种子/asset.glb` 和同目录的 `shape_raw.glb`。如果文件缺失，页面会提示。切换未来的新生成流程时，可增加新的目录适配层，让接口继续返回结果清单和模型文件。

对象中文名称默认读取仓库中的 `data/manifests/gso-selection.csv`；如果要使用其他清单，可以在命令中添加 `--labels "清单路径"`。

这批模型的初始朝向可能各不相同；画面使用自动取景，观察时请旋转检查完整模型。预览页面适合快速检查；进行严格的同角度对照或几何指标计算，还需要单独约定对齐方法。

## 依赖和隐私

- 需要 Python 3.10 或更新版本，以及支持 WebGL 的现代浏览器。
- `vendor` 目录中使用 Babylon.js 和官方 glTF 加载器 7.54.3。代码已放在本地，启动和浏览时无需联网，许可证见 `vendor/BABYLON-LICENSE.md`。
- 服务只监听 `127.0.0.1`，只读取指定实验目录中的符合规则的模型及输入图。
- 切换原始白模时，一个文件可能超过 20 MB，模型切换可能需要一些时间。

Babylon.js 按 Apache License 2.0 分发，项目主页及许可证：https://github.com/BabylonJS/Babylon.js
