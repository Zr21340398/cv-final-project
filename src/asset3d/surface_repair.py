"""修复 TRELLIS 不透明表面烘焙后的局部采样空点和反向光照法线。"""
from time import perf_counter

import numpy as np
from PIL import Image
import trimesh


def _fill_empty_samples(material):
    # 仅处理官方烘焙器生成的不透明 RGBA + 金属度/粗糙度图。
    color = material.baseColorTexture
    pbr = material.metallicRoughnessTexture
    if (material.alphaMode != "OPAQUE" or color is None or pbr is None
            or color.mode != "RGBA" or pbr.mode != "RGB" or color.size != pbr.size):
        return 0

    rgba = np.asarray(color)
    surface = np.asarray(pbr)
    empty = ~rgba.any(axis=2) & ~surface.any(axis=2)
    y, x = np.nonzero(empty)
    # 图集边缘或大片空白没有可靠的四邻域，避免从另一块材质借色。
    interior = (y > 0) & (y + 1 < rgba.shape[0]) & (x > 0) & (x + 1 < rgba.shape[1])
    y, x = y[interior], x[interior]
    fixed_color = fixed_surface = None
    count = 0
    for start in range(0, len(y), 65536):
        rows, cols = y[start:start + 65536], x[start:start + 65536]
        ny = rows[:, None] + np.array([-1, 1, 0, 0])
        nx = cols[:, None] + np.array([0, 0, -1, 1])
        colors, materials = rgba[ny, nx], surface[ny, nx]
        agree = ((colors[:, :, 3].min(axis=1) >= 250)
                 & (np.ptp(colors[:, :, :3], axis=1).max(axis=1) <= 24)
                 & (np.ptp(materials, axis=1).max(axis=1) <= 24))
        if not agree.any():
            continue
        if fixed_color is None:
            fixed_color, fixed_surface = rgba.copy(), surface.copy()
        # 只填四周颜色与材质一致的孤立空点，保留本来就是黑色的印字。
        pixels = rows[agree], cols[agree]
        fixed_color[pixels] = np.median(colors[agree], axis=1).round().astype(np.uint8)
        fixed_surface[pixels] = np.median(materials[agree], axis=1).round().astype(np.uint8)
        count += int(agree.sum())
    if count:
        material.baseColorTexture = Image.fromarray(fixed_color)
        material.metallicRoughnessTexture = Image.fromarray(fixed_surface)
    return count


def repair_surface(mesh):
    """在最终网格上修正烘焙缺陷，结果继续使用原三角形、UV 和 PBR 材质。"""
    started = perf_counter()
    faces = np.asarray(mesh.faces)
    normals = np.asarray(mesh.vertex_normals)
    face_normals = np.asarray(mesh.face_normals)
    # 朝向相差超过 120 度的顶点可能让窄三角形在光照下显出暗线。
    # 分列计算，避免一次展开整个网格的三个顶点法线。
    inverted = np.column_stack([
        np.einsum("ij,ij->i", normals[faces[:, corner]], face_normals) < -0.5
        for corner in range(3)
    ])
    material = mesh.visual.material
    samples = _fill_empty_samples(material)
    if inverted.any():
        # 相邻三角形共享同一顶点。仅为需要翻转的角复制顶点，以免影响另一侧的光照。
        extra, mapping = np.unique(faces[inverted], return_inverse=True)
        new_faces = faces.copy()
        new_faces[inverted] = len(normals) + mapping
        vertices = np.asarray(mesh.vertices)
        uv = np.asarray(mesh.visual.uv)
        mesh = trimesh.Trimesh(
            vertices=np.concatenate((vertices, vertices[extra])), faces=new_faces,
            vertex_normals=np.concatenate((normals, -normals[extra])),
            visual=trimesh.visual.TextureVisuals(uv=np.concatenate((uv, uv[extra])), material=material),
            metadata=mesh.metadata.copy(), process=False,
        )
    # 用时只写入实验记录，避免同一模型的 GLB 因计时差异而改变摘要。
    mesh.surface_repair_report = {
        "flipped_corners": int(inverted.sum()),
        "affected_faces": int(inverted.any(axis=1).sum()),
        "filled_texels": samples,
        "seconds": perf_counter() - started,
    }
    return mesh
