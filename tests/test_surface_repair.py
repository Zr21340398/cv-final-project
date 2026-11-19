import numpy as np
from PIL import Image
import trimesh
from asset3d.export import export_glb
from asset3d.surface_repair import repair_surface


def test_repair_keeps_triangles_uv_print_and_material(tmp_path):
    rgba = np.full((9, 9, 4), [190, 180, 135, 255], dtype=np.uint8)
    pbr = np.full((9, 9, 3), [0, 145, 0], dtype=np.uint8)
    rgba[2, 2] = pbr[2, 2] = 0
    rgba[5, 5] = [0, 0, 0, 255]
    rgba[6, 5] = pbr[6, 5] = 0
    material = trimesh.visual.material.PBRMaterial(
        alphaMode="OPAQUE", baseColorTexture=Image.fromarray(rgba),
        metallicRoughnessTexture=Image.fromarray(pbr))
    mesh = trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0],[0,-1,0]],
        faces=[[0,1,2],[0,1,3]], vertex_normals=[[0,0,1]]*4, process=False,
        visual=trimesh.visual.TextureVisuals(uv=[[0,0],[1,0],[0,1],[1,1]], material=material))
    output = repair_surface(mesh)
    path = tmp_path/'asset.glb'
    report = export_glb(output, path)
    stats = report['surface_repair']
    assert (stats['affected_faces'], stats['flipped_corners'], stats['filled_texels']) == (1, 3, 1)
    saved = next(iter(trimesh.load(path, force='scene', process=False).geometry.values()))
    np.testing.assert_allclose(saved.triangles, mesh.triangles)
    np.testing.assert_allclose(saved.visual.uv[saved.faces], mesh.visual.uv[mesh.faces])
    assert np.einsum('fij,fj->fi',saved.vertex_normals[saved.faces], saved.face_normals).min() > .99
    rgba[2,2], pbr[2,2] = rgba[2,1], pbr[2,1]
    np.testing.assert_array_equal(saved.visual.material.baseColorTexture, rgba)
    np.testing.assert_array_equal(saved.visual.material.metallicRoughnessTexture, pbr)
