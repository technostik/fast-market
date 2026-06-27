from __future__ import annotations

import os
import random as _rnd

import numpy as np

# (zoom_start, zoom_end, ax_start, ay_start, ax_end, ay_end)
# ax/ay are normalised [0, 1] anchor positions within the canvas (0.5, 0.5 = centre)
_PROFILES: dict[str, tuple[float, float, float, float, float, float]] = {
    "zoom_in":    (1.0, 1.3, 0.5, 0.5, 0.5, 0.5),
    "zoom_out":   (1.3, 1.0, 0.5, 0.5, 0.5, 0.5),
    "zoom_in_tl": (1.0, 1.3, 0.5, 0.5, 0.3, 0.3),
    "zoom_in_tr": (1.0, 1.3, 0.5, 0.5, 0.7, 0.3),
    "zoom_in_bl": (1.0, 1.3, 0.5, 0.5, 0.3, 0.7),
    "zoom_in_br": (1.0, 1.3, 0.5, 0.5, 0.7, 0.7),
    "pan_right":  (1.2, 1.2, 0.25, 0.5, 0.75, 0.5),
    "pan_left":   (1.2, 1.2, 0.75, 0.5, 0.25, 0.5),
    "pan_up":     (1.2, 1.2, 0.5, 0.75, 0.5, 0.25),
    "pan_down":   (1.2, 1.2, 0.5, 0.25, 0.5, 0.75),
    "drift_tl":   (1.1, 1.3, 0.6, 0.6, 0.35, 0.35),
    "drift_tr":   (1.1, 1.3, 0.4, 0.6, 0.65, 0.35),
}

# Dynamic motions: focal point chosen randomly per clip, kept away from edges.
_RAND_MARGIN = 0.25
_DYNAMIC_MOTIONS = ("zoom_in_random", "zoom_out_random", "zoom_random")

MOTION_CHOICES = list(_PROFILES.keys()) + list(_DYNAMIC_MOTIONS)


def _make_profile(motion: str, zoom_from: float, zoom_to: float) -> tuple:
    if motion in _PROFILES:
        return _PROFILES[motion]
    rx = _rnd.uniform(_RAND_MARGIN, 1.0 - _RAND_MARGIN)
    ry = _rnd.uniform(_RAND_MARGIN, 1.0 - _RAND_MARGIN)
    if motion == "zoom_in_random":
        return (1.0, 1.3, 0.5, 0.5, rx, ry)
    if motion == "zoom_out_random":
        return (1.3, 1.0, rx, ry, 0.5, 0.5)
    if motion == "zoom_random":
        if _rnd.random() < 0.5:
            return (1.0, 1.3, 0.5, 0.5, rx, ry)
        return (1.3, 1.0, rx, ry, 0.5, 0.5)
    return (zoom_from, zoom_to, 0.5, 0.5, 0.5, 0.5)  # unknown fallback


def ken_burns_clip(
    image_path: str,
    audio_path: str,
    output_path: str,
    zoom_from: float = 1.0,
    zoom_to: float = 1.3,
    fps: int = 24,
    motion: str = "random",
) -> str:
    """Render a Ken Burns animated clip from a still image + audio.

    motion: "random" picks any profile at random (including dynamic ones);
    named profiles control direction; unknown values fall back to zoom_from/zoom_to.
    Output is always 1280×720 H.264/AAC MP4.
    """
    from moviepy import VideoClip, AudioFileClip
    from PIL import Image

    TARGET_W, TARGET_H = 1280, 720

    if motion == "random":
        profile = _make_profile(_rnd.choice(MOTION_CHOICES), zoom_from, zoom_to)
    else:
        profile = _make_profile(motion, zoom_from, zoom_to)

    z_start, z_end, ax_s, ay_s, ax_e, ay_e = profile
    max_zoom = max(z_start, z_end)

    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Canvas: 2× max-zoom size gives room for off-centre pans without clamping
    canvas_scale = max_zoom * 2.0
    src_w = int(TARGET_W * canvas_scale) + 8
    src_h = int(TARGET_H * canvas_scale) + 8

    pil_img = Image.open(image_path).convert("RGB")
    pil_img.thumbnail((src_w, src_h), Image.LANCZOS)
    canvas = Image.new("RGB", (src_w, src_h), (0, 0, 0))
    ox = (src_w - pil_img.width) // 2
    oy = (src_h - pil_img.height) // 2
    canvas.paste(pil_img, (ox, oy))
    img_arr = np.array(canvas)
    ih, iw = img_arr.shape[:2]

    def make_frame(t: float):
        progress = t / duration if duration > 0 else 0.0
        z  = z_start + (z_end  - z_start)  * progress
        ax = ax_s    + (ax_e   - ax_s)      * progress
        ay = ay_s    + (ay_e   - ay_s)      * progress

        cw = iw / z
        ch = ih / z
        # Clamp crop centre so it never exceeds canvas bounds
        cx = max(cw / 2, min(iw - cw / 2, ax * iw))
        cy = max(ch / 2, min(ih - ch / 2, ay * ih))

        x1 = max(0, int(cx - cw / 2))
        y1 = max(0, int(cy - ch / 2))
        x2 = min(iw, x1 + int(cw))
        y2 = min(ih, y1 + int(ch))

        crop = img_arr[y1:y2, x1:x2]
        return np.array(Image.fromarray(crop).resize((TARGET_W, TARGET_H), Image.LANCZOS))

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
