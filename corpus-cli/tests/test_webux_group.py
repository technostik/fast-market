"""Toolbar placement: the Corpus tabs belong to the Observe group.

They used to fall into the hub's "More" bucket, which hid two everyday
browse/search tabs behind the catch-all menu.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webux.corpus import register as corpus_register  # noqa: E402
from webux.corpus_browser import register as corpus_browser_register  # noqa: E402


def test_corpus_tabs_are_in_observe():
    corpus = corpus_register.register({})
    browser = corpus_browser_register.register({})

    assert corpus.group == "Observe"
    assert browser.group == "Observe"
    # Both stay left of the publish/create tabs inside their group.
    assert corpus.order < browser.order
