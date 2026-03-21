from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tmp_db(tmp_path):
    from core.storage import MonitorStorage

    db_path = tmp_path / "test.db"
    return MonitorStorage(db_path)


@pytest.fixture
def sample_source():
    from core.models import Source
    from datetime import datetime

    return Source(
        id="test-source-1",
        plugin="youtube",
        origin="UC123456789",
        description="Test Channel",
        metadata={"theme": "tech", "priority": "high"},
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_action():
    from core.models import Action
    from datetime import datetime

    return Action(
        id="test-action-1",
        command="echo $ITEM_TITLE",
        description="Test description",
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_rule():
    from core.models import Rule
    from datetime import datetime

    return Rule(
        id="test-rule-1",
        conditions={
            "all": [
                {"field": "source_plugin", "operator": "==", "value": "youtube"},
                {"field": "content_type", "operator": "==", "value": "video"},
            ]
        },
        action_ids=["test-action-1"],
        description="Test Rule",
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_item():
    from core.models import ItemMetadata
    from datetime import datetime, timezone

    return ItemMetadata(
        id="vid123",
        title="Test Video",
        url="https://youtube.com/watch?v=vid123",
        published_at=datetime.now(timezone.utc),
        content_type="video",
        source_plugin="youtube",
        source_id="test-source-1",
        extra={"is_short": False, "duration_seconds": 600, "channel_name": "Test Channel"},
    )
