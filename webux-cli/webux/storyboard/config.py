from __future__ import annotations

from common.core.config import load_tool_config, save_tool_config

# Prompts now live in the prompt store (create them with
# `prompt setup webux import`). These are the default prompt *names*
# the pipeline applies. Per-project overrides can be set in the WebUX
# config panel (stored under `prompt_overrides`).
DEFAULT_PROMPT_NAMES = {
    "story_breakdown": "storyboard-breakdown",
    "scene_transcript": "storyboard-scene-transcript",
    "scene_image_prompt": "storyboard-scene-image",
}


def load_storyboard_config(migrate: bool = True) -> dict:
    base = load_tool_config("storyboard")
    base.setdefault("tts_engine", "kokoro")
    base.setdefault("language", "en")
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
    base.setdefault("draft_mode", False)   # small 512×288 images, draft_steps
    base.setdefault("draft_steps", 1)
    base.setdefault("chapter_transition", "none")
    base.setdefault("chapter_transition_duration", 1.0)
    base.setdefault("chapter_range", "2–5")
    base.setdefault("scene_range", "2–5")
    base.setdefault("scene_duration", "15–45 seconds")
    prompts = base.setdefault("prompts", {})
    overrides = base.setdefault("prompt_overrides", {})
    migrated = False
    for k, default_name in DEFAULT_PROMPT_NAMES.items():
        v = prompts.get(k, default_name)
        # Migration: older configs stored the full prompt text inline. Treat
        # such legacy text as an override of the default named prompt.
        if isinstance(v, str) and ("\n" in v or "You are" in v or len(v) > 200):
            if not overrides.get(k):
                overrides[k] = v
            v = default_name
            migrated = True
        prompts[k] = v
    if migrated and migrate:
        save_storyboard_config(base)
    return base


def save_storyboard_config(updates: dict) -> None:
    # Load without re-running migration: otherwise the migration's own save
    # would reload the still-legacy config from disk and recurse forever.
    current = load_storyboard_config(migrate=False)
    # Only persist storyboard-specific keys, not inherited common/llm config
    storyboard_keys = {
        "tts_engine", "language", "image_engine", "image_size", "image_style",
        "narrative_style", "animation_style", "ken_burns_zoom_from",
        "ken_burns_zoom_to", "ken_burns_motion", "fps",
        "image_seed", "image_steps", "draft_mode", "draft_steps",
        "chapter_transition", "chapter_transition_duration",
        "chapter_range", "scene_range", "scene_duration", "prompts",
        "prompt_overrides",
    }
    merged = {k: v for k, v in current.items() if k in storyboard_keys}
    for k, v in updates.items():
        if k in storyboard_keys:
            merged[k] = v
    save_tool_config("storyboard", merged)
