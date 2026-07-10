import modal

APP_NAME = "fast-market"

app = modal.App(APP_NAME)


def _download_whisper_models():
    """Runs during image build — bakes model weights into the image cache."""
    from faster_whisper import WhisperModel
    WhisperModel("medium", device="cpu", compute_type="int8")


base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "faster-whisper>=1.0",
        "moviepy>=2.0",
        "numpy>=1.24",
        "requests>=2.28",
    )
    .run_function(_download_whisper_models)
)


import os
import signal
from typing import Any

_active_function_call = None


def _install_cancel_handler() -> None:
    """Install a SIGTERM/SIGINT handler that cancels the in-flight Modal
    function call. This lets an external stop (e.g. webux Short Publish
    sending SIGTERM to the video CLI) interrupt a remote Modal job instead of
    leaving it orphaned."""
    def _handler(signum, _frame):
        global _active_function_call
        if _active_function_call is not None:
            try:
                _active_function_call.cancel()
            except Exception:
                pass
        # Restore the default disposition and re-raise so the process exits.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
    except ValueError:
        # signal only works in the main thread
        pass


def spawn_and_get(func, *args, **kwargs) -> Any:
    """Spawn a Modal function call and block for its result, registering it so
    a SIGTERM/SIGINT can cancel the remote call."""
    global _active_function_call
    _install_cancel_handler()
    call = func.spawn(*args, **kwargs)
    _active_function_call = call
    try:
        return call.get()
    finally:
        _active_function_call = None

