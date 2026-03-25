from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from common import structlog
from common.core.paths import get_skills_dir
from common.skill.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)


ROUTER_PROMPT = """You are a skill router. Given a task description and a list of available skills, select the best matching skill and extract any parameters needed.

## Available Skills

{skills_list}

## Task

{task}

## Instructions

1. Find the skill whose description and instructions best match the task.
2. Extract parameter values from the task description if the skill declares parameters.
3. If no skill is a good match (confidence < 0.5), set skill_name to null.

Respond with ONLY a JSON object, no preamble, no code fences:
{{
  "skill_name": "the-skill-name or null",
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation",
  "params": {{"param_name": "extracted_value"}}
}}
"""


@dataclass
class RouterMatch:
    skill: Skill | None
    confidence: float
    reason: str
    params: dict[str, str]


def build_skills_list(skills: list[Skill]) -> str:
    """Format skills for the router prompt."""
    parts = []
    for skill in skills:
        lines = [f"### {skill.name}", f"Description: {skill.description}"]
        if skill.parameters:
            param_names = ", ".join(
                p["name"] + (" (required)" if p.get("required") else "")
                for p in skill.parameters
            )
            lines.append(f"Parameters: {param_names}")
        body = skill.get_body()
        if body:
            preview = body[:300] + ("..." if len(body) > 300 else "")
            lines.append(f"Instructions preview: {preview}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def route(
    task: str,
    provider,
    model: str | None = None,
    skills_dir: Path | None = None,
    confidence_threshold: float = 0.5,
) -> RouterMatch:
    """Find the best skill for a task description."""
    from common.llm.base import LLMRequest

    skills = discover_skills(skills_dir or get_skills_dir())
    if not skills:
        return RouterMatch(
            skill=None,
            confidence=0.0,
            reason="No skills available",
            params={},
        )

    skills_list = build_skills_list(skills)
    prompt = ROUTER_PROMPT.format(skills_list=skills_list, task=task)

    request = LLMRequest(
        prompt=prompt,
        model=model,
        temperature=0.0,
        max_tokens=256,
    )

    try:
        response = provider.complete(request)
        data = json.loads(response.content.strip())
    except Exception as exc:
        logger.warning("router_llm_failed", error=str(exc))
        return RouterMatch(
            skill=None,
            confidence=0.0,
            reason=f"Router error: {exc}",
            params={},
        )

    skill_name = data.get("skill_name")
    confidence = float(data.get("confidence", 0.0))
    reason = data.get("reason", "")
    params = data.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if not skill_name or confidence < confidence_threshold:
        return RouterMatch(skill=None, confidence=confidence, reason=reason, params={})

    matched = next((s for s in skills if s.name == skill_name), None)
    if not matched:
        logger.warning("router_unknown_skill", skill_name=skill_name)
        return RouterMatch(
            skill=None,
            confidence=0.0,
            reason=f"Router returned unknown skill: {skill_name}",
            params={},
        )

    return RouterMatch(
        skill=matched,
        confidence=confidence,
        reason=reason,
        params={str(k): str(v) for k, v in params.items()},
    )
