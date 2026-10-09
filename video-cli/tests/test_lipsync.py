"""Tests for `video lipsync` (SadTalker backend). Network/GPU-free."""

import sys
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.lipsync import sadtalker as st
from commands.lipsync.register import register


def _make_cmd():
    return register({}).click_command


def test_resolve_device_auto(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _x: "/usr/bin/nvidia-smi")
    assert st.resolve_device("auto") == "cuda"
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    assert st.resolve_device("auto") == "cpu"
    assert st.resolve_device("cuda") == "cuda"


def test_build_inference_cmd_defaults():
    cmd = st.build_inference_cmd(
        Path("/h/venv/bin/python"), Path("/h/SadTalker/inference.py"),
        "p.png", "a.wav", Path("/tmp/r"), Path("/h/SadTalker/checkpoints"),
    )
    assert cmd[:2] == ["/h/venv/bin/python", "/h/SadTalker/inference.py"]
    assert "--still" in cmd
    assert "--size" in cmd and "256" in cmd
    assert "--enhancer" not in cmd
    assert "--cpu" not in cmd
    assert cmd[cmd.index("--checkpoint_dir") + 1] == "/h/SadTalker/checkpoints"


def test_build_inference_cmd_enhancer_and_512():
    cmd = st.build_inference_cmd(
        Path("py"), Path("inf.py"), "p.png", "a.wav", Path("/tmp/r"), Path("ckpt"),
        size=512, still=False, enhancer="gfpgan", cpu=True,
    )
    assert "--still" not in cmd
    assert cmd[cmd.index("--size") + 1] == "512"
    assert cmd[cmd.index("--enhancer") + 1] == "gfpgan"
    assert "--cpu" in cmd


def test_find_newest_mp4(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"old")
    sub = tmp_path / "sub"
    sub.mkdir()
    newest = sub / "b.mp4"
    newest.write_bytes(b"new")
    import os
    import time

    old = time.time() - 100
    os.utime(tmp_path / "a.mp4", (old, old))
    assert st.find_newest_mp4(tmp_path) == newest


def test_find_newest_mp4_empty(tmp_path):
    try:
        st.find_newest_mp4(tmp_path)
    except st.LipsyncError:
        pass
    else:
        raise AssertionError("expected LipsyncError for empty dir")


def test_missing_files_reports_checkout(tmp_path):
    missing = st.missing_files(tmp_path / "nope", 256, "none")
    assert any("checkout" in m for m in missing)


def test_filter_requirements_drops_torch(tmp_path):
    src = tmp_path / "req.txt"
    src.write_text("torch==1.12.1\ngradio\nnumpy>=1.0\n# comment\ntorchvision\nfoo\n")
    dst = tmp_path / "out.txt"
    n = st.filter_requirements(src, dst)
    text = dst.read_text()
    assert "torch" not in text
    assert "gradio" not in text.split()
    assert n == 2


def test_cli_requires_photo_audio():
    result = CliRunner().invoke(_make_cmd(), [])
    assert result.exit_code != 0


def test_cli_success_path_mocked(tmp_path, monkeypatch):
    photo = tmp_path / "me.png"
    photo.write_bytes(b"png")
    audio = tmp_path / "voix.wav"
    audio.write_bytes(b"wav")

    def fake_run(**kwargs):
        out = Path(kwargs["output"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"video")
        assert kwargs["size"] == 256
        return str(out)

    monkeypatch.setattr(st, "run_lipsync", lambda **kw: fake_run(**kw))
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            _make_cmd(), [str(photo), str(audio), "-o", "deep/nested/out.mp4"]
        )
    assert result.exit_code == 0, result.output
    assert result.output.strip().endswith("deep/nested/out.mp4")


def test_cli_setup_only_calls_setup(monkeypatch):
    seen = {}

    def fake_setup(home, cb, *, device="auto"):
        seen["home"] = str(home)
        return home

    monkeypatch.setattr(st, "setup", fake_setup)
    result = CliRunner().invoke(_make_cmd(), ["--setup"])
    assert result.exit_code == 0, result.output
    assert seen["home"].endswith("sadtalker")


def test_base_python_prefers_concrete_310(tmp_path, monkeypatch):
    import os
    import sys

    fake_root = tmp_path / "pyenv"
    (fake_root / "versions" / "3.10.14" / "bin").mkdir(parents=True)
    (fake_root / "versions" / "3.10.14" / "bin" / "python").touch()
    monkeypatch.setenv("PYENV_ROOT", str(fake_root))
    monkeypatch.delenv("SADTALKER_PYTHON", raising=False)
    assert st.base_python().endswith("3.10.14/bin/python")
    (tmp_path / "custom").touch()
    monkeypatch.setenv("SADTALKER_PYTHON", str(tmp_path / "custom"))
    assert st.base_python() == str(tmp_path / "custom")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
