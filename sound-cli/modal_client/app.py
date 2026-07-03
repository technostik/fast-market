import modal

APP_NAME = "fast-market"

app = modal.App(APP_NAME)

base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "librosa>=0.10",
        "numpy>=1.24",
        "soundfile>=0.12",
    )
)
