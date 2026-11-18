#!/usr/bin/env python
"""Run one chatterbox synthesis inside its side venv.

chatterbox-tts pins torch==2.6.0 / transformers==5.2.0 (py<=3.12) and is
normally missing from the host CLI environment. ``plugin.py`` launches this
script with ``<side-venv>/bin/python`` and a JSON payload on stdin.

stdin payload keys: text, language, clone, exaggeration, ref_text, speed,
output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # sound-cli root

import soundfile as sf  # noqa: E402

from plugins.chatterbox.plugin import ChatterboxTTSPlugin  # noqa: E402


def main() -> int:
    os.environ["_SOUND_CHATTERBOX_RUNNER"] = "1"  # never re-delegate from inside the venv
    payload = json.load(sys.stdin)
    output = Path(payload["output"])

    plug = ChatterboxTTSPlugin({"chatterbox": {}})
    audio, sr = plug.synthesize(
        text=payload.get("text", ""),
        voice="",
        speed=payload.get("speed", 1.0),
        language=payload.get("language"),
        clone=payload.get("clone"),
        ref_text=payload.get("ref_text"),
        exaggeration=payload.get("exaggeration"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), audio.numpy() if audio.dim() else audio, sr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
