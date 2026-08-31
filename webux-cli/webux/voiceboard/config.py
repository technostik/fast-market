from __future__ import annotations

from common.core.config import load_tool_config, save_tool_config

from ..storyboard.config import DEFAULT_PROMPT_NAMES


def load_voiceboard_config() -> dict:
    base = load_tool_config("voiceboard")
    # Image / animation defaults mirror storyboard.
    base.setdefault("image_engine", "flux2cloud")
    base.setdefault("image_size", "landscape")
    base.setdefault("image_style", "cinematic, dramatic lighting, photorealistic, hyperrealistic")
    base.setdefault("narrative_style", "documentary, dramatic third-person narration")
    base.setdefault("animation_style", "ken_burns")
    base.setdefault("ken_burns_zoom_from", 1.0)
    base.setdefault("ken_burns_zoom_to", 1.3)
    base.setdefault("ken_burns_motion", "random")
    base.setdefault("fps", 24)
    base.setdefault("image_seed", None)    # null = random each time
    base.setdefault("image_steps", None)   # null = engine default
    base.setdefault("draft_mode", False)
    base.setdefault("draft_steps", 1)
    base.setdefault("chapter_transition", "none")
    base.setdefault("chapter_transition_duration", 1.0)
    # Voice ingestion defaults.
    base.setdefault("language", "en")
    base.setdefault("transcript_engine", "whisperx")  # whisperx (local) | groq
    base.setdefault("transcript_model", "medium")
    base.setdefault("segment_min", 10.0)     # target min scene duration (s)
    base.setdefault("segment_max", 30.0)     # hard max scene duration (s)
    base.setdefault("segment_silence", 0.6)  # pause threshold that prefers a cut
    prompts = base.setdefault("prompts", {})
    prompts.setdefault("scene_image_prompt", DEFAULT_PROMPT_NAMES["scene_image_prompt"])
    return base


def save_voiceboard_config(updates: dict) -> None:
    current = load_voiceboard_config()
    voiceboard_keys = {
        "image_engine", "image_size", "image_style", "narrative_style",
        "animation_style", "ken_burns_zoom_from", "ken_burns_zoom_to",
        "ken_burns_motion", "fps", "image_seed", "image_steps",
        "draft_mode", "draft_steps", "chapter_transition",
        "chapter_transition_duration", "language", "transcript_engine",
        "transcript_model", "segment_min", "segment_max", "segment_silence",
        "prompts",
    }
    merged = {k: v for k, v in current.items() if k in voiceboard_keys}
    for k, v in updates.items():
        if k in voiceboard_keys:
            merged[k] = v
    save_tool_config("voiceboard", merged)
