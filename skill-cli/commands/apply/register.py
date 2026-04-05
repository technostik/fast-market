from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import apply_skill_impl
from commands.params import SkillRefType, SkillParamType


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("apply")
    @click.argument("skill_ref", type=SkillRefType())
    @click.argument("params", nargs=-1, type=SkillParamType())
    @click.option(
        "--workdir",
        "-w",
        default=None,
        type=click.Path(),
        help="Working directory (default: common config workdir or current dir)",
    )
    @click.option(
        "--timeout",
        "-t",
        type=int,
        default=None,
        help="Overall execution timeout in seconds (default: skill frontmatter or 60/300)",
    )
    @click.option(
        "--max-iterations",
        "-i",
        type=int,
        default=None,
        help="Max LLM iterations (overrides skill frontmatter)",
    )
    @click.option(
        "--llm-timeout",
        type=int,
        default=None,
        help="LLM call timeout in seconds (0=no limit, overrides skill frontmatter)",
    )
    @click.option(
        "--dry-run",
        "-n",
        is_flag=True,
        help="Show what would be executed without running",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    @click.option(
        "--provider",
        "-P",
        default=None,
        help="LLM provider (for prompt mode skills)",
    )
    @click.option(
        "--model",
        "-m",
        default=None,
        help="LLM model (for prompt mode skills)",
    )
    @click.option(
        "--save-session",
        default=None,
        type=click.Path(),
        help="Save task session to this file (forwarded to task apply)",
    )
    @click.option(
        "--auto-learn",
        "-L",
        is_flag=True,
        help="After execution, update LEARN.md for this skill",
    )
    @click.option(
        "--compact",
        "-C",
        is_flag=True,
        help="Use compacting prompt to consolidate multiple learnings",
    )
    @click.option(
        "--verbose",
        "-v",
        is_flag=True,
        help="Show tool calls and their results during execution",
    )
    def apply_cmd(
        skill_ref,
        params,
        workdir,
        timeout,
        max_iterations,
        llm_timeout,
        dry_run,
        fmt,
        provider,
        model,
        save_session,
        auto_learn,
        compact,
        verbose,
    ):
        """Apply (execute) a skill by name.

        SKILL_REF is the skill name or 'skillname/scriptname'.
        PARAMS are KEY=VALUE pairs passed as SKILL_KEY environment variables.
        """
        apply_skill_impl(
            skill_ref=skill_ref,
            params=params,
            workdir=workdir,
            timeout=timeout,
            max_iterations=max_iterations,
            llm_timeout=llm_timeout,
            dry_run=dry_run,
            fmt=fmt,
            provider=provider,
            model=model,
            auto_learn=auto_learn,
            save_session=save_session,
            compact=compact,
            verbose=verbose,
        )

    return CommandManifest(name="apply", click_command=apply_cmd)
