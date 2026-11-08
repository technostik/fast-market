from __future__ import annotations

import pytest
import click

from commands.upload.register import DEFAULT_CATEGORY_ID, resolve_category_id


@pytest.mark.parametrize(
    "value, expected",
    [
        ("", "22"),
        (None, "22"),
        ("25", "25"),
        ("28", "28"),
        ("Actualités et politique", "25"),
        ("actualites et politique", "25"),
        ("News & Politics", "25"),
        ("Science et technologie", "28"),
        ("Science & Technology", "28"),
        ("  Science et Technologie  ", "28"),
        ("Personnes et blogs", "22"),
        ("Éducation", "27"),
        ("Education", "27"),
    ],
)
def test_resolve_category_id(value, expected):
    assert resolve_category_id(value) == expected


def test_resolve_unknown_category_raises():
    with pytest.raises(click.ClickException):
        resolve_category_id("not a real category")


def test_default_category_is_people_and_blogs():
    assert DEFAULT_CATEGORY_ID == "22"
