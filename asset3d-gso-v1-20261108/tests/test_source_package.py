import importlib.util
import tarfile
from pathlib import Path


def test_source_package_excludes_account_local_setup(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/package_project.py"
    spec = importlib.util.spec_from_file_location("source_packager", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "hpc4-session.local.sh").write_text("# Test-only account settings\n")
    (configs / "hunyuan2_formal_50.yaml").write_text("name: synthetic_fixture\n")
    module.main()
    with tarfile.open(tmp_path / "dist/asset3d-source.tar.gz") as archive:
        names = archive.getnames()
    assert "asset3d/configs/hunyuan2_formal_50.yaml" in names
    assert not any(name.endswith(".local.sh") for name in names)
