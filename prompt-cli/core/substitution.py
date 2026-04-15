from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)

INLINE_FILE_PATTERN = re.compile(r"@([\w.\-/\\]+)")


def resolve_inline_file_references(
    template: str, workdir: Path | None = None
) -> tuple[str, list[dict]]:
    """Replace @filename patterns in template with file contents.

    Security constraints:
    - No absolute paths (paths starting with /)
    - No home directory expansion (no ~)
    - Files not found are left as-is (not substituted)

    Args:
        template: The prompt template with @filename patterns
        workdir: Working directory for relative path resolution (default: cwd)

    Returns:
        Tuple of (resolved_template, list of {path, chars} dicts for logging)
    """
    if workdir is None:
        workdir = Path.cwd()

    resolved_files: list[dict] = []

    def replace_match(match: re.Match) -> str:
        filename = match.group(1)

        if filename.startswith("/") or filename.startswith("~"):
            return match.group(0)

        path = (workdir / filename).resolve()
        if not path.exists():
            return match.group(0)

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return match.group(0)

        resolved_files.append({"path": str(path), "chars": len(content)})
        return content

    resolved = INLINE_FILE_PATTERN.sub(replace_match, template)
    resolved = resolved.replace("\\@", "@")

    for info in resolved_files:
        logger.info("inline_file_resolved", path=info["path"], chars=info["chars"])

    return resolved, resolved_files


def resolve_arguments(
    template: str, args: dict[str, str], workdir: Path | None = None
) -> str:
    """Resolve inline @filename references and {parameter} placeholders in template.

    Args:
        template: The prompt template
        args: Dictionary of parameter values (key=value from CLI)
        workdir: Working directory for @filename resolution (default: cwd)

    Returns:
        Resolved template with all references replaced
    """
    resolved: dict[str, str] = {}

    for key, value in args.items():
        if value == "-":
            content = sys.stdin.read()
            logger.info("substitution_from_stdin", parameter=key, chars=len(content))
            resolved[key] = content
        elif value.startswith("@"):
            path = Path(value[1:]).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            content = path.read_text(encoding="utf-8")
            logger.info(
                "substitution_from_file",
                parameter=key,
                path=str(path),
                chars=len(content),
            )
            resolved[key] = content
        else:
            logger.info("substitution_literal", parameter=key, chars=len(value))
            resolved[key] = value

    template, inline_files = resolve_inline_file_references(template, workdir)

    required = set(re.findall(r"\{(\w+)\}|\{['\"](\w+)['\"]\}", template))
    required = {k1 or k2 for k1, k2 in required}
    missing = required - set(resolved)
    for key in list(missing):
        env_value = os.environ.get(key)
        if env_value is not None:
            resolved[key] = env_value
            missing.remove(key)
    if missing:
        raise ValueError(f"Missing required arguments: {', '.join(sorted(missing))}")

    try:
        result = template.format(**resolved)
    except KeyError as exc:
        raise ValueError(f"Unresolved placeholder: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Template formatting failed: {exc}") from exc
    logger.info(
        "substitution_complete",
        parameters=len(resolved),
        inline_files=len(inline_files),
        result_chars=len(result),
    )
    return result


def extract_placeholders(template: str) -> list[str]:
    """Extract placeholder names from template."""
    matches = re.findall(r"\{(\w+)\}|\{['\"](\w+)['\"]\}", template)
    return sorted(set(k1 or k2 for k1, k2 in matches))
