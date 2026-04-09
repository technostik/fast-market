"""Generic agentic call — reusable entry point for running a TaskLoop.

Usage::

    from common.agent.call import agent_call
    from pathlib import Path

    session = agent_call(
        task_description="Create a bash script that ...",
        workdir=Path("/some/dir"),
        system_commands=["ls", "cat", "grep", "jq"],
        fastmarket_tools={"skill": {...}},   # optional
        max_iterations=30,
        provider="openai",    # or None for default
        model="gpt-4o",       # or None for default
        verbose=False,
    )

    # Inspect results
    print(session.success_rate)
    print(session.metrics_dict())
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Optional

from common.agent.executor import resolve_and_execute_command
from common.agent.loop import TaskConfig, TaskLoop
from common.agent.session import Session


def agent_call(
    task_description: str,
    workdir: Path,
    *,
    system_commands: list[str] | None = None,
    fastmarket_tools: dict[str, Any] | None = None,
    max_iterations: int = 20,
    default_timeout: int = 60,
    llm_timeout: int = 0,
    temperature: float = 0.3,
    provider: str | None = None,
    model: str | None = None,
    task_params: dict[str, str] | None = None,
    verbose: bool = False,
    debug: str = "",
    shared_context: Any | None = None,
) -> Session:
    """Run an agentic loop with tool access in a working directory.

    Args:
        task_description: What the agent should accomplish.
        workdir: Directory where commands execute and files are resolved.
        system_commands: Whitelisted system commands the agent may call.
        fastmarket_tools: Fast-Market tool configs (e.g. ``{"skill": {...}}``).
        max_iterations: Maximum LLM turn iterations.
        default_timeout: Seconds allowed per command execution.
        llm_timeout: Seconds allowed per LLM call (0 = no limit).
        temperature: LLM temperature.
        provider: LLM provider name (uses default if None).
        model: LLM model name (uses provider default if None).
        task_params: Parameters exposed as ``$SKILL_KEY`` env vars.
        verbose: Print progress to stderr.
        debug: Debug level (``""``, ``"normal"``, ``"full"``).
        shared_context: Optional shared context object.

    Returns:
        The completed Session with all turns and metrics.
    """
    system_commands = system_commands or []
    fastmarket_tools = fastmarket_tools or {}
    allowed_commands = list(fastmarket_tools.keys()) + system_commands

    task_config = TaskConfig(
        fastmarket_tools=fastmarket_tools,
        system_commands=system_commands,
        allowed_commands=allowed_commands,
        max_iterations=max_iterations,
        default_timeout=default_timeout,
        llm_timeout=llm_timeout,
        temperature=temperature,
    )

    # Resolve provider from default if not specified
    if provider is None:
        from common.core.config import load_tool_config
        from common.llm.registry import get_default_provider_name
        try:
            config = load_tool_config("skill")
            provider = get_default_provider_name(config)
        except Exception:
            config = load_tool_config("task")
            provider = get_default_provider_name(config)

    loop = TaskLoop(
        config=task_config,
        workdir=workdir,
        provider=provider,
        model=model,
        verbose=verbose,
        debug=debug,
        shared_context=shared_context,
    )

    execute_fn = partial(
        resolve_and_execute_command,
        workdir=workdir,
        allowed=set(allowed_commands),
        timeout=default_timeout,
        env_params=task_params or {},
    )

    loop.run(task_description, execute_fn, task_params=task_params)

    assert loop.session is not None
    return loop.session
