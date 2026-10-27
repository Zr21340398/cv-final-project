import subprocess
from pathlib import Path


def render_mesh(mesh, output, blender="blender", views=8, resolution=512, clay=False):
    if views < 1 or resolution < 32:
        raise ValueError("views >= 1 and resolution >= 32 required")
    script = Path(__file__).with_name("blender_render.py")
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python",
            str(script),
            "--",
            "--mesh",
            str(Path(mesh).resolve()),
            "--output",
            str(Path(output).resolve()),
            "--views",
            str(views),
            "--resolution",
            str(resolution),
        ]
        + (["--clay"] if clay else []),
        check=True,
    )
    if not (Path(output) / "cameras.json").is_file():
        raise RuntimeError("Blender exited without producing cameras.json")
