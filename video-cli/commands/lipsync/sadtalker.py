from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO_URL = "https://github.com/OpenTalker/SadTalker.git"

#: Checkpoints required for a run (relative to the SadTalker checkout).
#: The 512 safetensors is only needed for --size 512.
REQUIRED_CHECKPOINTS_256 = [
    "checkpoints/SadTalker_V0.0.2_256.safetensors",
    "checkpoints/mapping_00109-model.pth.tar",
    "checkpoints/mapping_00229-model.pth.tar",
]
REQUIRED_CHECKPOINTS_512_EXTRA = [
    "checkpoints/SadTalker_V0.0.2_512.safetensors",
]

GFPGAN_WEIGHTS_DIR = "gfpgan/weights"

#: PyTorch CUDA builds tried in order (newest first). cu121 supports Ada
#: (RTX 4060, sm_89) while staying closer to SadTalker's dependency era.
TORCH_CUDA_INDEXES = [
    "https://download.pytorch.org/whl/cu121",
    "https://download.pytorch.org/whl/cu118",
]


class LipsyncError(RuntimeError):
    """Setup or inference failure with an actionable message."""


def default_home() -> Path:
    """SadTalker data home: ~/.local/share/fast-market/video/sadtalker."""
    try:
        from common.core.paths import get_tool_data_dir

        return get_tool_data_dir("video") / "sadtalker"
    except Exception:
        return (
            Path.home() / ".local" / "share" / "fast-market" / "video" / "sadtalker"
        )


def base_python() -> str:
    """Interpreter used to create the isolated venv.

    Prefers a concrete python3.10 (all SadTalker pins ship cp310 wheels).
    Pyenv shims can be ambiguous when several versions provide python3.10,
    so concrete ``<PYENV_ROOT>/versions/3.10.*/bin/python`` binaries are
    preferred over shims. ``SADTALKER_PYTHON`` overrides everything.
    """
    override = os.environ.get("SADTALKER_PYTHON")
    if override and Path(override).exists():
        return override
    pyenv_root = Path(os.environ.get("PYENV_ROOT", Path.home() / ".pyenv"))
    versions_dir = pyenv_root / "versions"
    if versions_dir.is_dir():
        for vdir in sorted(versions_dir.glob("3.10.*")):
            candidate = vdir / "bin" / "python"
            if candidate.exists():
                return str(candidate)
    shim = shutil.which("python3.10")
    if shim:
        probe = subprocess.run(
            [shim, "--version"], capture_output=True, text=True, timeout=30
        )
        if probe.returncode == 0:
            return shim
    return sys.executable


def venv_python(home: Path) -> Path:
    return home / "checkout" / "venv" / "bin" / "python"


def inference_script(home: Path) -> Path:
    return home / "checkout" / "SadTalker" / "inference.py"


def checkout_dir(home: Path) -> Path:
    return home / "checkout" / "SadTalker"


def resolve_device(requested: str) -> str:
    """Resolve auto|cuda|cpu. auto = cuda when nvidia-smi exists, else cpu."""
    if requested in ("cuda", "cpu"):
        return requested
    return "cuda" if shutil.which("nvidia-smi") is not None else "cpu"


def missing_files(home: Path, size: int, enhancer: str) -> list[str]:
    """Return relative paths of setup artifacts that are absent."""
    missing: list[str] = []
    co = checkout_dir(home)
    if not inference_script(home).exists():
        return ["SadTalker checkout (inference.py not found)"]
    if not venv_python(home).exists():
        missing.append("python venv (checkout/venv)")
    want = list(REQUIRED_CHECKPOINTS_256)
    if size == 512:
        want += REQUIRED_CHECKPOINTS_512_EXTRA
    for rel in want:
        if not (co / rel).exists():
            missing.append(rel)
    if enhancer not in ("none", None):
        weights = co / GFPGAN_WEIGHTS_DIR
        if not weights.exists() or not any(weights.iterdir()):
            missing.append(f"{GFPGAN_WEIGHTS_DIR}/ (needed for --enhancer)")
    return missing


def filter_requirements(src: Path, dst: Path) -> int:
    """Copy requirements.txt minus torch lines (we install CUDA torch first).

    Returns the number of remaining requirement lines.
    """
    kept: list[str] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().lower()
        if not stripped or stripped.startswith("#"):
            continue
        name = stripped.split("=")[0].split(">")[0].split("<")[0].split()[0]
        # CUDA torch is installed first (see setup); gradio only serves the
        # demo app, inference.py never imports it.
        if name in ("torch", "torchvision", "torchaudio", "gradio"):
            continue
        kept.append(line)
    dst.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(kept)


def _run(cmd: list[str], cwd: Path | None, progress_cb, env_extra: dict | None = None,
          timeout: float | None = None) -> None:
    progress_cb("$ " + " ".join(cmd))
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None

    def _pump() -> None:
        for line in proc.stdout:
            progress_cb(line.rstrip())

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    try:
        ret = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise LipsyncError(
            f"command timed out after {timeout:.0f}s: {' '.join(cmd[:4])}…"
        )
    pump.join(timeout=10)
    if ret != 0:
        raise LipsyncError(f"command failed (exit {ret}): {' '.join(cmd[:4])}…")


def _patch_basicsr_torchvision(venv_py: Path, progress_cb) -> None:
    """Compat shim: basicsr 1.4.2 imports functional_tensor, gone in tv>=0.15."""
    import glob as _glob

    for cand in _glob.glob(
        str(venv_py.parent.parent / "lib" / "python*" / "site-packages"
            / "basicsr" / "data" / "degradations.py")
    ):
        text = Path(cand).read_text(encoding="utf-8")
        old = "from torchvision.transforms.functional_tensor import rgb_to_grayscale"
        if old in text and "except ImportError" not in text:
            text = text.replace(
                "try:  # torchvision>=0.15 removed functional_tensor\n"
                "    from torchvision.transforms.functional_tensor import rgb_to_grayscale\n"
                "except ImportError:\n"
                "    from torchvision.transforms.functional import rgb_to_grayscale",
            )
            Path(cand).write_text(text, encoding="utf-8")
            progress_cb("patched basicsr for torchvision>=0.15 compat")
            return


def setup(home: Path, progress_cb, *, device: str = "auto") -> Path:
    """Clone SadTalker, create venv, install CUDA torch + reqs, fetch weights."""
    home.mkdir(parents=True, exist_ok=True)
    co = checkout_dir(home)

    if not (co / ".git").exists() and not inference_script(home).exists():
        progress_cb(f"cloning SadTalker into {co} …")
        (home / "checkout").mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--depth", "1", REPO_URL, str(co)], None, progress_cb)
    else:
        progress_cb(f"using SadTalker checkout at {co}")

    vpy = venv_python(home)
    if not vpy.exists():
        progress_cb("creating isolated venv (python3.10 preferred, system untouched) …")
        _run([base_python(), "-m", "venv", str(vpy.parent.parent)], None, progress_cb)
        _run([str(vpy), "-m", "pip", "install", "--upgrade", "pip"], None, progress_cb)

    def _torch_ok() -> bool:
        probe = subprocess.run(
            [str(vpy), "-c", "import torch, torchvision; print(torch.cuda.is_available())"],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            return False
        return (not want_cuda) or ("True" in probe.stdout)

    want_cuda = resolve_device(device) == "cuda"
    if _torch_ok():
        progress_cb("PyTorch already installed in the venv, skipping …")
    elif want_cuda:
        progress_cb("installing CUDA PyTorch into the venv …")
        installed = False
        for index in TORCH_CUDA_INDEXES:
            try:
                _run(
                    [str(vpy), "-m", "pip", "install", "torch", "torchvision",
                     "torchaudio", "--index-url", index],
                    None,
                    progress_cb,
                )
                installed = True
                break
            except LipsyncError:
                progress_cb(f"CUDA index {index} failed, trying next …")
        if not installed:
            raise LipsyncError(
                "could not install CUDA PyTorch (tried cu121, cu118). "
                "Re-run with --device cpu for a slow CPU fallback."
            )
    else:
        progress_cb("installing CPU PyTorch into the venv (slow fallback) …")
        _run(
            [str(vpy), "-m", "pip", "install", "torch", "torchvision", "torchaudio"],
            None,
            progress_cb,
        )

    req = co / "requirements.txt"
    sentinel = home / "requirements.ok"
    if req.exists() and not sentinel.exists():
        filtered = Path(tempfile.mkstemp(suffix="-sadtalker-reqs.txt")[1])
        n = filter_requirements(req, filtered)
        progress_cb(f"installing SadTalker requirements ({n} lines, torch/gradio set aside) …")
        try:
            _run([str(vpy), "-m", "pip", "install", "-r", str(filtered)], None, progress_cb)
        finally:
            filtered.unlink(missing_ok=True)
        sentinel.write_text("ok\n", encoding="utf-8")
    elif sentinel.exists():
        progress_cb("requirements already installed, skipping …")
    _patch_basicsr_torchvision(vpy, progress_cb)

    gaps = missing_files(home, 256, "none")
    need_weights = [g for g in gaps if g.startswith("checkpoints/")]
    if need_weights:
        script = co / "scripts" / "download_models.sh"
        if not script.exists():
            raise LipsyncError(
                f"checkpoints missing ({', '.join(need_weights)}) and "
                f"{script} not found. Fetch them manually, see "
                "https://github.com/OpenTalker/SadTalker#2-download-models"
            )
        progress_cb("downloading SadTalker checkpoints (GBs, one time) …")
        _run(["bash", str(script)], co, progress_cb)

    remaining = missing_files(home, 256, "none")
    if remaining:
        raise LipsyncError(
            "setup incomplete, still missing: " + ", ".join(remaining) + ". "
            "Fetch them manually, see "
            "https://github.com/OpenTalker/SadTalker#2-download-models"
        )
    progress_cb(f"SadTalker ready at {co}")
    return home


def build_inference_cmd(
    venv_py: Path,
    script: Path,
    photo: str,
    audio: str,
    result_dir: Path,
    checkpoint_dir: Path,
    *,
    size: int = 256,
    still: bool = True,
    preprocess: str = "full",
    enhancer: str = "none",
    cpu: bool = False,
) -> list[str]:
    """Build the SadTalker inference.py argv (pure, testable)."""
    cmd = [
        str(venv_py), str(script),
        "--driven_audio", str(audio),
        "--source_image", str(photo),
        "--result_dir", str(result_dir),
        "--checkpoint_dir", str(checkpoint_dir),
        "--size", str(size),
        "--preprocess", preprocess,
    ]
    if still:
        cmd.append("--still")
    if enhancer and enhancer != "none":
        cmd += ["--enhancer", enhancer]
    if cpu:
        cmd.append("--cpu")
    return cmd


def find_newest_mp4(result_dir: Path) -> Path:
    """Return the newest .mp4 under result_dir (SadTalker names vary)."""
    cands = sorted(result_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not cands:
        raise LipsyncError(f"SadTalker produced no .mp4 under {result_dir}")
    return cands[-1]


def run_lipsync(
    *,
    photo: str,
    audio: str,
    output: Path,
    home: Path,
    size: int = 256,
    still: bool = True,
    preprocess: str = "full",
    enhancer: str = "none",
    device: str = "auto",
    timeout: float = 900,
    progress_cb=None,
) -> str:
    """Run SadTalker inference and move the result to ``output``."""
    cb = progress_cb or (lambda _m: None)
    gaps = missing_files(home, size, enhancer if enhancer != "none" else "none")
    if gaps:
        raise LipsyncError(
            "SadTalker is not set up (missing: " + ", ".join(gaps) + "). "
            "Run: video lipsync --setup"
        )
    run_dir = home / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    result_dir = Path(tempfile.mkdtemp(prefix="lipsync-", dir=str(run_dir)))
    use_cpu = resolve_device(device) == "cpu"
    cmd = build_inference_cmd(
        venv_python(home), inference_script(home), photo, audio, result_dir,
        checkout_dir(home) / "checkpoints",
        size=size, still=still, preprocess=preprocess, enhancer=enhancer,
        cpu=use_cpu,
    )
    cb("running SadTalker inference (minutes on GPU, longer on CPU) …")
    env_extra = {"CUDA_VISIBLE_DEVICES": ""} if use_cpu else None
    _run(cmd, checkout_dir(home), cb, env_extra, timeout=timeout)
    raw = find_newest_mp4(result_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    shutil.move(str(raw), str(output))
    return str(output)
