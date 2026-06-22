from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PUBLISH_FIXTURES = FIXTURES_DIR / "publish"
GOLDEN_DIR = PUBLISH_FIXTURES / "golden"
TEST_VIDEO = PUBLISH_FIXTURES / "test_clip.mkv"

import sys
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--generate-golden",
        action="store_true",
        default=False,
        help="Regenerate all golden fixtures from the test video (overwrites existing)",
    )


@pytest.fixture(scope="session")
def test_video() -> Path:
    if not TEST_VIDEO.exists():
        pytest.skip(f"Test video not found: {TEST_VIDEO}")
    return TEST_VIDEO


def _probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        text=True,
    )
    return float(json.loads(out)["format"]["duration"])


@pytest.fixture(scope="session", autouse=True)
def maybe_regenerate_golden(request, test_video: Path, tmp_path_factory):
    if not request.config.getoption("--generate-golden"):
        return

    from commands.extract_transcript.register import generate_karaoke_ass
    from commands.remove_silence.register import remove_silence_simple
    from commands.burn_subtitles.register import burn_ass_subtitles

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_factory.mktemp("golden_gen")

    # Golden ASS transcript
    golden_ass = GOLDEN_DIR / f"{test_video.stem}.ass"
    generate_karaoke_ass(str(test_video), str(golden_ass), language="fr", model_size="medium")
    print(f"\n[generate-golden] {golden_ass}")

    # Silence removal reference durations
    no_silence = tmp / "nosilence.mp4"
    _, orig_dur, final_dur = remove_silence_simple(str(test_video), str(no_silence), threshold=-65.0)
    silence_probed = _probe_duration(no_silence)

    # Subtitle burn reference duration
    subtitled = tmp / "subtitled.mp4"
    burn_ass_subtitles(str(test_video), str(golden_ass), str(subtitled))
    burn_probed = _probe_duration(subtitled)

    src_probed = _probe_duration(test_video)

    durations = {
        "source": {"duration": round(src_probed, 6)},
        "silence_removal": {
            "reported_duration": final_dur,
            "probed_duration": round(silence_probed, 6),
        },
        "subtitle_burn": {
            "probed_duration": round(burn_probed, 6),
        },
    }
    golden_dur = GOLDEN_DIR / "durations.json"
    golden_dur.write_text(json.dumps(durations, indent=2) + "\n")
    print(f"[generate-golden] {golden_dur}")
