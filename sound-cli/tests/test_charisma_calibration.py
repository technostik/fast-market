from __future__ import annotations

import os
from pathlib import Path

import pytest

from commands.charisma.analysis import score_charisma
from commands.prosody.analysis import load_audio

# Validation fixtures: the user's own "flat" vs "enhanced/charismatic" reference
# recordings. These are PERSONAL validation files (never committed, never used to
# calibrate the bands) — they confirm the scoring shape is right, not train it.
# Provide them via env vars; the test is skipped when they are absent.
FLAT_PATH = os.environ.get("CHARISMA_FIXTURE_FLAT")
ENH_PATH = os.environ.get("CHARISMA_FIXTURE_ENH")

pytestmark = pytest.mark.skipif(
    not (FLAT_PATH and ENH_PATH),
    reason="CHARISMA_FIXTURE_FLAT / CHARISMA_FIXTURE_ENH env vars not set",
)


def _scores(path: str) -> dict:
    y, sr = load_audio(Path(path))
    return score_charisma(y, sr)


def test_enhanced_outscores_flat():
    flat = _scores(FLAT_PATH)
    enh = _scores(ENH_PATH)
    assert enh["charisma_score"] > flat["charisma_score"]


def test_dims_not_dead_for_both():
    """Regression guard: the intonation and HNR subscores must be computable
    (not permanently 0 for both files) after the noise-robust fixes."""
    flat = _scores(FLAT_PATH)
    enh = _scores(ENH_PATH)
    for key in ("intonation_score", "hnr_score"):
        assert (flat[key] + enh[key]) > 0
