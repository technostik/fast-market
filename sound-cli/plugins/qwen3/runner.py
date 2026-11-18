#!/usr/bin/env python
"""Run one qwen3 synthesis inside the transformers-4.x side venv.

qwen-tts 0.1.1 pins transformers==4.57.3 and cannot generate in-process
under transformers >= 5. ``plugin.py`` launches this script with
``<side-venv>/bin/python`` and a JSON payload on stdin.

stdin payload keys:
    text, voice, speed, language, clone, ref_text, exaggeration, output,
    config (dict with voice_design_model / base_model)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # sound-cli root

from plugins.qwen3.plugin import Qwen3TTSPlugin  # noqa: E402


def main() -> int:
    payload = json.load(sys.stdin)
    output = Path(payload["output"])

    plug = Qwen3TTSPlugin(payload.get("config", {}))
    audio, sr = plug.synthesize(
        text=payload.get("text", ""),
        voice=payload.get("voice") or "",
        speed=payload.get("speed", 1.0),
        language=payload.get("language") or "en",
        clone=payload.get("clone"),
        ref_text=payload.get("ref_text"),
        exaggeration=payload.get("exaggeration"),
    )
    plug._save_wav(output, audio, sr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
