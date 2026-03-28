"""
Backward compatibility module - imports from common/learn.

This module is kept for backward compatibility.
All functionality has been moved to common/learn.
"""

from __future__ import annotations

from common.learn import (
    analyze_session as analyze_session,
    update_learn_file as update_learn_file,
)

__all__ = ["analyze_session", "update_learn_file"]
