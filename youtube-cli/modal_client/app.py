import modal

APP_NAME = "fast-market"

app = modal.App(APP_NAME)

base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "faster-whisper>=1.0",
        "moviepy>=2.0",
        "numpy>=1.24",
    )
)
