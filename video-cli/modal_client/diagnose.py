import modal
from modal_client.app import app, base_image


@app.function(image=base_image)
def run_file_roundtrip(video_bytes: bytes, input_name: str) -> dict:
    import json
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, input_name)
        output_path = os.path.join(tmpdir, "output.mp4")

        with open(input_path, "wb") as f:
            f.write(video_bytes)

        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path],
            check=True, capture_output=True,
        )

        def probe(path):
            raw = subprocess.check_output(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", path],
                text=True,
            )
            return json.loads(raw)

        info_in = probe(input_path)
        info_out = probe(output_path)

        with open(output_path, "rb") as f:
            output_bytes = f.read()

    return {
        "input_size": len(video_bytes),
        "output_size": len(output_bytes),
        "input_format": info_in["format"]["format_name"],
        "output_format": info_out["format"]["format_name"],
        "duration": round(float(info_in["format"]["duration"]), 2),
        "output_bytes": output_bytes,
    }


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
