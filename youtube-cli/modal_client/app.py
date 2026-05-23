import modal

APP_NAME = "fast-market"

app = modal.App(APP_NAME)


def _download_whisper_models():
    """Runs during image build — bakes model weights into the image cache."""
    from faster_whisper import WhisperModel
    for size in ("medium"):
        WhisperModel(size, device="cpu", compute_type="int8")


base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "faster-whisper>=1.0",
        "moviepy>=2.0",
        "numpy>=1.24",
    )
    .run_function(_download_whisper_models)
)
