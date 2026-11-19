"""验证局部替换的范围与失败恢复，不加载 GPU 模型。"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


spec = importlib.util.spec_from_file_location(
    "front_rerun", Path(__file__).resolve().parents[1] / "scripts/rerun_trellis2_front.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def setup_dirs(tmp_path):
    work = tmp_path / ".front-work"
    work.mkdir()
    staged = work / "gso_01"
    destination = tmp_path / "gso_01"
    staged.mkdir()
    destination.mkdir()
    (staged / "new").write_text("new")
    (destination / "old").write_text("old")
    return staged, destination


def test_replace_only_selected_object(tmp_path):
    staged, destination = setup_dirs(tmp_path)
    other = tmp_path / "gso_02"
    other.mkdir()
    (other / "untouched").write_text("keep")
    module.replace_object(staged, destination)
    assert (destination / "new").read_text() == "new"
    assert not (destination / "old").exists()
    assert (other / "untouched").read_text() == "keep"


def test_failed_publish_restores_old_results(tmp_path):
    staged, destination = setup_dirs(tmp_path)
    rename = Path.rename

    def fail_new(source, target):
        if source == staged:
            raise OSError("simulated rename failure")
        return rename(source, target)

    with patch.object(Path, "rename", fail_new), pytest.raises(OSError):
        module.replace_object(staged, destination)
    assert (destination / "old").read_text() == "old"
    assert (staged / "new").read_text() == "new"
