from __future__ import annotations

import re
import sys
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


def resolve_arguments(template: str, args: dict[str, str]) -> str:
    """Resolve placeholders in template."""
    resolved: dict[str, str] = {}

    for key, value in args.items():
        if value == "-":
            content = sys.stdin.read()
            logger.info("substitution_from_stdin", placeholder=key, chars=len(content))
            resolved[key] = content
        elif value.startswith("@"):
            path = Path(value[1:]).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            content = path.read_text(encoding="utf-8")
            logger.info(
                "substitution_from_file",
                placeholder=key,
                path=str(path),
                chars=len(content),
            )
            resolved[key] = content
        else:
            logger.info("substitution_literal", placeholder=key, chars=len(value))
            resolved[key] = value

    required = set(re.findall(r"\{(\w+)\}", template))
    missing = required - set(resolved)
    if missing:
        raise ValueError(f"Missing required arguments: {', '.join(sorted(missing))}")

    result = template.format(**resolved)
    logger.info("substitution_complete", placeholders=len(resolved), result_chars=len(result))
    return result


def extract_placeholders(template: str) -> list[str]:
    """Extract placeholder names from template."""
    return sorted(set(re.findall(r"\{(\w+)\}", template)))
