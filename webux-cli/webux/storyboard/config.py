from __future__ import annotations

from pathlib import Path

from common.core.config import load_tool_config, save_tool_config

_STORY_BREAKDOWN_PROMPT = """\
You are a creative director. Given the following script, break it into chapters and scenes \
for a narrated video. Return ONLY valid JSON, no other text.

Schema:
{
  "chapters": [
    {
      "title": "Short chapter title",
      "scenes": [
        {
          "title": "Short scene title",
          "description": "2-3 sentences describing what happens in this scene, \
what visuals would accompany it, and what the narrator covers."
        }
      ]
    }
  ]
}

Rules:
- Aim for 2–6 chapters, 2–5 scenes per chapter.
- Each scene should be 15–45 seconds of narration.
- Scene descriptions should be vivid enough to generate an image prompt.

SCRIPT:
"""

_SCENE_TRANSCRIPT_PROMPT = """\
You are a narrator scriptwriter. Given the scene description below, write the narrator's \
spoken text for this scene. The text should be clear, engaging, and suitable for text-to-speech. \
Return ONLY the narration text — no stage directions, no JSON, no headers.

Narrative style: {narrative_style}

SCENE DESCRIPTION:
"""

_SCENE_IMAGE_PROMPT = """\
You are an art director. Given the scene description below, write a detailed image \
generation prompt suitable for FLUX image generation. The prompt should describe the \
visual elements, mood, lighting, and composition. Return ONLY the image prompt text, \
no explanations.

Visual style: {image_style}

SCENE DESCRIPTION:
"""

DEFAULT_PROMPTS = {
    "story_breakdown": _STORY_BREAKDOWN_PROMPT,
    "scene_transcript": _SCENE_TRANSCRIPT_PROMPT,
    "scene_image_prompt": _SCENE_IMAGE_PROMPT,
}


def load_storyboard_config() -> dict:
    base = load_tool_config("storyboard")
    base.setdefault("tts_engine", "kokoro")
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
    prompts = base.setdefault("prompts", {})
    for k, v in DEFAULT_PROMPTS.items():
        prompts.setdefault(k, v)
    return base


def save_storyboard_config(updates: dict) -> None:
    current = load_storyboard_config()
    # Only persist storyboard-specific keys, not inherited common/llm config
    storyboard_keys = {
        "tts_engine", "image_engine", "image_size", "image_style",
        "narrative_style", "animation_style", "ken_burns_zoom_from",
        "ken_burns_zoom_to", "ken_burns_motion", "fps",
        "image_seed", "image_steps", "draft_mode", "draft_steps", "prompts",
    }
    merged = {k: v for k, v in current.items() if k in storyboard_keys}
    for k, v in updates.items():
        if k in storyboard_keys:
            merged[k] = v
    save_tool_config("storyboard", merged)
