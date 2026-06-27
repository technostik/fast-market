from __future__ import annotations

import os
from pathlib import Path

import numpy as np


def ken_burns_clip(
    image_path: str,
    audio_path: str,
    output_path: str,
    zoom_from: float = 1.0,
    zoom_to: float = 1.3,
    fps: int = 24,
) -> str:
    """Render a Ken Burns animated clip from a still image + audio.

    Zooms slowly from zoom_from to zoom_to over the audio duration.
    Output is always 1280x720 H.264/AAC MP4.

    Returns output_path.
    """
    from moviepy import VideoClip, AudioFileClip
    from PIL import Image

    TARGET_W, TARGET_H = 1280, 720

    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Upscale source image to max-zoom size so we always have pixels to crop from
    src_w = int(TARGET_W * zoom_to) + 4
    src_h = int(TARGET_H * zoom_to) + 4

    pil_img = Image.open(image_path).convert("RGB")
    # Letterbox / pad to fill src dimensions without distortion
    pil_img.thumbnail((src_w, src_h), Image.LANCZOS)
    canvas = Image.new("RGB", (src_w, src_h), (0, 0, 0))
    ox = (src_w - pil_img.width) // 2
    oy = (src_h - pil_img.height) // 2
    canvas.paste(pil_img, (ox, oy))
    img_arr = np.array(canvas)
    ih, iw = img_arr.shape[:2]

    def make_frame(t: float):
        progress = t / duration if duration > 0 else 0.0
        zoom = zoom_from + (zoom_to - zoom_from) * progress
        # Crop a region of size iw/zoom × ih/zoom from center
        cw = max(1, int(iw / zoom))
        ch = max(1, int(ih / zoom))
        cx, cy = iw // 2, ih // 2
        x1 = max(0, cx - cw // 2)
        y1 = max(0, cy - ch // 2)
        x2 = min(iw, x1 + cw)
        y2 = min(ih, y1 + ch)
        crop = img_arr[y1:y2, x1:x2]
        out = np.array(Image.fromarray(crop).resize((TARGET_W, TARGET_H), Image.LANCZOS))
        return out

    video = VideoClip(make_frame, duration=duration).with_fps(fps)
    video = video.with_audio(audio)

    temp_audio = os.path.join(os.path.dirname(os.path.abspath(output_path)), "temp-audio-kb.m4a")
    video.write_videofile(
        output_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=temp_audio,
        remove_temp=True,
        audio_bitrate="192k",
        preset="medium",
        logger=None,
    )
    audio.close()
    video.close()
    return output_path
