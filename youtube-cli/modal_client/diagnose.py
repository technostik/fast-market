import modal
from modal_client.app import app, base_image


@app.function(image=base_image)
def run_diagnose():
    import platform
    import subprocess
    import sys

    try:
        ffmpeg_out = subprocess.check_output(
            ["ffmpeg", "-version"], text=True, stderr=subprocess.STDOUT
        ).split("\n")[0]
    except Exception as e:
        ffmpeg_out = f"error: {e}"

    try:
        import faster_whisper
        whisper_ver = faster_whisper.__version__
    except ImportError:
        whisper_ver = "not installed"

    try:
        import moviepy
        moviepy_ver = moviepy.__version__
    except ImportError:
        moviepy_ver = "not installed"

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": ffmpeg_out,
        "faster_whisper": whisper_ver,
        "moviepy": moviepy_ver,
    }
