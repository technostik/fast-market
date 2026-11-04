"""Profile picker lock rules (`data-profile-lock` / `data-profile-lock-allow`).

The toolbar locks profile switching while anything runs. The short_publish
page picker has one deliberate exception: the pool queue is sequential, so the
next video can be queued for another YouTube channel while the current one
uploads. It must be locked again as soon as another plugin is busy (two
pipelines would race on the process-wide FASTMARKET_PROFILE).
"""

from __future__ import annotations

from pathlib import Path

import pytest

WEBUX = Path(__file__).resolve().parent.parent
SHORT_HTML = WEBUX / "webux" / "short_publish" / "frontend.html"
LONG_HTML = WEBUX / "webux" / "long_publish" / "frontend.html"

from core.server import _WEBUX_PROFILE_SCRIPT  # noqa: E402


def _tag(html: str, element_id: str) -> str:
    """Return the full opening tag of the element with that id."""
    marker = f'id="{element_id}"'
    idx = html.find(marker)
    assert idx != -1, f"no element with {marker}"
    start = html.rfind("<", 0, idx)
    end = html.find(">", idx)
    return html[start : end + 1]


def test_short_publish_picker_allows_only_its_own_plugin():
    tag = _tag(SHORT_HTML.read_text(encoding="utf-8"), "jobProfile")
    assert "data-profile-lock " in tag or 'data-profile-lock"' in tag
    assert 'data-profile-lock-allow="short_publish"' in tag


def test_long_publish_picker_has_no_allow_exception():
    tag = _tag(LONG_HTML.read_text(encoding="utf-8"), "jobProfile")
    assert "data-profile-lock" in tag
    assert "data-profile-lock-allow" not in tag


def test_toolbar_selector_has_no_allow_exception():
    # The toolbar select is matched by id, not by data-profile-lock, so an
    # allow attribute on it would be silently ignored — guard against that.
    source = (WEBUX / "core" / "server.py").read_text(encoding="utf-8")
    idx = source.find('id="webux-profile" class="profile-select"')
    assert idx != -1
    end = source.find(">", idx)
    tag = source[source.rfind("<", 0, idx) : end + 1]
    assert "data-profile-lock-allow" not in tag
    assert "data-profile-lock" not in tag


def test_apply_busy_reads_the_allow_attribute():
    assert "profileLockAllow" in _WEBUX_PROFILE_SCRIPT
    assert "blockers" in _WEBUX_PROFILE_SCRIPT


@pytest.mark.parametrize("path", [SHORT_HTML, LONG_HTML])
def test_page_profile_picker_still_drives_the_page(path: Path):
    html = path.read_text(encoding="utf-8")
    assert "function pageProfile()" in html
