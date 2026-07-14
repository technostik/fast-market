"""Tests for the YouTube Shorts 3-minute length check that must account for the
appended signature video length."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish.utils import _effective_limit_seconds, SHORTS_MAX_SECONDS


def test_effective_limit_equals_max_when_no_signature():
    assert _effective_limit_seconds(0.0) == SHORTS_MAX_SECONDS
    assert _effective_limit_seconds() == SHORTS_MAX_SECONDS


def test_effective_limit_subtracts_signature():
    sig = 4.0
    assert _effective_limit_seconds(sig) == SHORTS_MAX_SECONDS - sig


def test_effective_limit_ignores_negative_signature():
    assert _effective_limit_seconds(-5.0) == SHORTS_MAX_SECONDS


def test_overshoot_detected_when_signature_pushes_over_limit():
    # 2:59 source + 4s signature => 3:03 final, must be rejected.
    source_duration = 179.0
    sig_duration = 4.0
    assert source_duration > _effective_limit_seconds(sig_duration)


def test_safe_video_accepted_when_signature_fits():
    # 2:55 source + 4s signature => 2:59 final, must be accepted.
    source_duration = 175.0
    sig_duration = 4.0
    assert source_duration <= _effective_limit_seconds(sig_duration)


def test_boundary_at_exactly_limit():
    sig_duration = 4.0
    source_duration = SHORTS_MAX_SECONDS - sig_duration  # 176s -> final 180s
    # Strictly over the limit fails; exactly at the limit is allowed.
    assert source_duration <= _effective_limit_seconds(sig_duration)
    assert (source_duration + 0.1) > _effective_limit_seconds(sig_duration)
