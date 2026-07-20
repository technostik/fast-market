from __future__ import annotations

import shutil
from pathlib import Path

from common.core.config import load_tool_config, save_tool_config, get_tool_config_path

# Prompts now live in the prompt store (create them with
# `prompt setup webux import`). These are the default prompt *names*
# the pipeline applies. Per-project overrides can be set in the WebUX
# config panel (stored under `prompt_overrides`).
DEFAULT_PROMPT_NAMES = {
    "narrate": "storyboard-narrate",
    "story_breakdown": "storyboard-breakdown",
    "scene_transcript": "storyboard-scene-transcript",
    "scene_image_prompt": "storyboard-scene-image",
    "scene_image_prompt_with_character": "storyboard-scene-image-character",
    "character": "storyboard-character",
}

# All character-related settings live under a single `character:` YAML section.
# The flat `character_*` keys below are the legacy on-disk format and are
# migrated into the nested section on load (and no longer persisted).
DEFAULT_CHARACTER = {
    "enabled": False,
    "use_reference": False,        # reuse stored reference from config
    "style": "realist",            # cartoon | realist | (free text below)
    "style_free": "",
    "reference_image": None,       # stable path for cross-story reuse
    "reference_description": "",   # stored description for reuse
    "strength": 0.35,             # reference weight (local flux2 img2img)
}

# Legacy flat keys (on disk) → nested character sub-key.
_LEGACY_CHARACTER_MAP = {
    "character_enabled": "enabled",
    "character_use_reference": "use_reference",
    "character_style": "style",
    "character_style_free": "style_free",
    "character_reference_image": "reference_image",
    "character_reference_description": "reference_description",
    "character_strength": "strength",
}


def load_storyboard_config(migrate: bool = True) -> dict:
    base = load_tool_config("storyboard")
    base.setdefault("tts_engine", "kokoro")
    base.setdefault("language", "en")
    base.setdefault("image_engine", "flux2cloud")
    base.setdefault("image_size", "landscape")
    base.setdefault("image_style", "cinematic, dramatic lighting, photorealistic, hyperrealistic")
    base.setdefault("narrative_style", "documentary, dramatic third-person narration")
    base.setdefault("narrative_guidance", "")   # broader story context injected into scene prompts
    # content_mode drives whether the "narrate" step runs at all:
    #   raw_article  → pasted text is written material (e.g. a Substack essay); the
    #                  narrate step rewrites it into a continuous oral narration.
    #   oral_script  → pasted text is ALREADY a finished oral script (e.g. produced by
    #                  a separate scriptwriting prompt/pipeline, already paced and
    #                  narratively crafted); narrate is skipped entirely and the text
    #                  is used verbatim as the narration to segment.
    base.setdefault("content_mode", "raw_article")
    # target_duration_seconds: optional. When set (raw_article mode only), the narrate
    # step is allowed/instructed to condense the article to roughly fit this spoken
    # duration — useful for quick test renders. When null, narrate must be fully
    # faithful (no summarizing), it only adapts register from written to spoken.
    base.setdefault("target_duration_seconds", None)
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

    # ── Central character (nested `character:` section) ──────────────────────
    character = dict(DEFAULT_CHARACTER)
    # Load any previously-saved nested section.
    saved = base.get("character")
    if isinstance(saved, dict):
        character.update({k: v for k, v in saved.items() if k in DEFAULT_CHARACTER})
    # Migrate legacy flat `character_*` keys (if present on disk).
    migrated = False
    for flat_key, nested_key in _LEGACY_CHARACTER_MAP.items():
        if flat_key in base:
            character[nested_key] = base[flat_key]
            del base[flat_key]
            migrated = True
    base["character"] = character
    # Expose flat aliases for backward-compatible reads in the pipeline.
    for flat_key, nested_key in _LEGACY_CHARACTER_MAP.items():
        base[flat_key] = character[nested_key]

    prompts = base.setdefault("prompts", {})
    overrides = base.setdefault("prompt_overrides", {})
    prompt_migrated = False
    for k, default_name in DEFAULT_PROMPT_NAMES.items():
        v = prompts.get(k, default_name)
        # Migration: older configs stored the full prompt text inline. Treat
        # such legacy text as an override of the default named prompt.
        if isinstance(v, str) and ("\n" in v or "You are" in v or len(v) > 200):
            if not overrides.get(k):
                overrides[k] = v
            v = default_name
            prompt_migrated = True
        prompts[k] = v
    if (migrated or prompt_migrated) and migrate:
        save_storyboard_config(base)
    return base


def save_storyboard_config(updates: dict) -> None:
    # Load without re-running migration: otherwise the migration's own save
    # would reload the still-legacy config from disk and recurse forever.
    current = load_storyboard_config(migrate=False)
    # Only persist storyboard-specific keys, not inherited common/llm config.
    storyboard_keys = {
        "tts_engine", "language", "image_engine", "image_size", "image_style",
        "narrative_style", "narrative_guidance", "animation_style", "ken_burns_zoom_from",
        "ken_burns_zoom_to", "ken_burns_motion", "fps",
        "image_seed", "image_steps", "draft_mode", "draft_steps",
        "chapter_transition", "chapter_transition_duration",
        "chapter_range", "scene_range", "scene_duration", "prompts",
        "prompt_overrides", "character", "content_mode", "target_duration_seconds",
    }
    merged = {k: v for k, v in current.items() if k in storyboard_keys}
    # Start from the persisted nested character section.
    character = dict(merged.get("character") or DEFAULT_CHARACTER)
    for k, v in updates.items():
        if k == "character":
            # Full nested section replacement (merge to preserve unspecified keys).
            if isinstance(v, dict):
                character.update({kk: vv for kk, vv in v.items() if kk in DEFAULT_CHARACTER})
        elif k in _LEGACY_CHARACTER_MAP:
            # Legacy flat update → fold into the nested section.
            character[_LEGACY_CHARACTER_MAP[k]] = v
        elif k in storyboard_keys:
            merged[k] = v
    merged["character"] = character
    save_tool_config("storyboard", merged)


def stable_reference_dir() -> Path:
    """Directory (inside the profile config dir) where the reusable reference
    character image is stored, so it survives workdir wipes across restarts."""
    d = get_tool_config_path("storyboard").parent / "reference"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_reference_character(image_path: str, description: str) -> str:
    """Copy the given reference image into the stable profile dir and persist it
    in the storyboard config. Returns the stable image path.

    The reference image originally lives in the project workdir, which is
    recreated with a fresh random name on every /init. Storing it there means a
    workdir wipe (or restart after re-init) silently loses the reference. Keeping
    a copy in the profile config dir makes the reference durable."""
    src = Path(image_path).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"Reference image not found: {image_path}")
    dest = stable_reference_dir() / "character_reference.png"
    shutil.copy2(src, dest)
    save_storyboard_config({
        "character": {
            "reference_image": str(dest),
            "reference_description": description,
        }
    })
    return str(dest)
