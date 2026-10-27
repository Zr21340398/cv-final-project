"""Run with Blender 4.x, not with the project Python interpreter."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--clay", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    path = Path(args.mesh)
    if path.suffix.lower() in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif path.suffix.lower() == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif path.suffix.lower() == ".ply":
        bpy.ops.wm.ply_import(filepath=str(path))
    else:
        raise ValueError("Supported input formats: GLB, glTF, OBJ, PLY")
    # 这里读取已经生成的模型，用 Blender 从不同角度拍预览图。
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objects:
        raise ValueError("Input has no mesh")
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector([min(v[i] for v in corners) for i in range(3)])
    hi = Vector([max(v[i] for v in corners) for i in range(3)])
    scale = max(hi - lo)
    if scale <= 0:
        raise ValueError("Degenerate model")
    # 统一物体中心和尺度，让两组预览使用相同的取景范围。
    transform = Matrix.Scale(1 / scale, 4) @ Matrix.Translation(-(lo + hi) / 2)
    worlds = [(o, o.matrix_world.copy()) for o in objects]
    for o, world in worlds:
        o.parent = None
        o.matrix_world = transform @ world
    # 清除导入文件自带的灯光与相机，随后统一布光和拍摄位置。
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(output / "reference_normalized.glb"), export_format="GLB", use_selection=True
    )
    # 白模预览统一使用灰色哑光材质，便于观察轮廓、凹凸和孔洞。
    if args.clay:
        material = bpy.data.materials.new("NeutralGeometry")
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (0.65, 0.65, 0.65, 1)
        bsdf.inputs["Metallic"].default_value = 0
        bsdf.inputs["Roughness"].default_value = 0.7
        for obj in objects:
            obj.data.materials.clear()
            obj.data.materials.append(material)
            for polygon in obj.data.polygons:
                polygon.material_index = 0
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 32
    scene.cycles.seed = 2026
    scene.render.resolution_x = scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("EvaluationWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7
    scene.world = world
    for location, energy, size in [((3, -4, 5), 350, 4), ((-4, -1, 2), 150, 3)]:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.data.energy, light.data.shape, light.data.size = energy, "DISK", size
        light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 1.8
    scene.camera = camera
    frames = []
    # 相机绕物体等角度拍摄；默认八张，所有模型使用相同光照和相机设置。
    for i in range(args.views):
        angle = 2 * math.pi * i / args.views
        camera.location = (2.5 * math.sin(angle), -2.5 * math.cos(angle), 1.1)
        camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        name = f"view-{i:03d}.png"
        scene.render.filepath = str(output / name)
        bpy.ops.render.render(write_still=True)
        frames.append(
            {
                "image": name,
                "camera_to_world": [list(row) for row in camera.matrix_world],
                "projection": [
                    list(row)
                    for row in camera.calc_matrix_camera(
                        bpy.context.evaluated_depsgraph_get(), x=args.resolution, y=args.resolution
                    )
                ],
            }
        )
    metadata = {
        "blender_version": bpy.app.version_string,
        "resolution": args.resolution,
        "projection_type": "orthographic",
        "ortho_scale": 1.8,
        "world_up": "Z",
        "first_camera_direction": "from negative Y, elevated",
        "input_to_render_space": [list(row) for row in transform],
        "render_engine": "CYCLES_CPU",
        "clay": args.clay,
        "samples": 32,
        "seed": 2026,
        "frames": frames,
    }
    (output / "cameras.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
