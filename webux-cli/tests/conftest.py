from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Refresh webux theme screenshot goldens",
    )
