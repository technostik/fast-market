from __future__ import annotations

import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Default prompt for shellify — declared here, overridable via prompt service
# ---------------------------------------------------------------------------
SHELLIFY_PROMPT_DEFAULT = """You are an agentic shell-script engineer. Your job is to create or replace `scripts/run.sh` for a skill.

You have access to a working directory where you can:
- **Read files** (cat, head, ls, find) to explore SKILL.md, LEARN.md, and any existing `scripts/run.sh`
- **Execute commands** to discover tool behavior with `--help` or dry runs
- **Write files** to create and iterate on `scripts/run.sh`
- **Think** before acting — plan your approach step by step

# Skill Description
{skill_description}

# Skill Parameters
{skill_parameters}

# Skill Body (from SKILL.md) — THIS IS WHAT YOU ARE TRANSFORMING INTO A SHELL SCRIPT
{skill_body}

{learn_section}

{existing_script_section}

{instructions_section}

{tools_section}

# Your Task

Create a robust, reproducible `scripts/run.sh` bash script that implements this skill's goal.

## Rules for the Script

1. **Start with `#!/usr/bin/env bash`** and use `set -euo pipefail`
2. **Use environment variables for parameters** — each skill parameter is available as `$SKILL_{{PARAM_NAME_UPPER}}` (e.g., `video_url` → `$SKILL_VIDEO_URL`)
3. **Validate required parameters** — exit with a helpful error if missing
4. **Use CLI tools** — refer to the Available Tools section above for what you can use. Discover their options with `--help`.
5. **Be incremental and robust** — use intermediate files, handle errors gracefully
6. **Be self-contained** — all commands in one script
7. **Output to current directory** — no hardcoded absolute paths
8. **Provide progress output** — echo status messages so the user can follow along

## Parameter Handling

- For a parameter named `foo`, the env var is `$SKILL_FOO`
- For optional params with defaults: `${{SKILL_FOO:-default_value}}`
- Validate required params early:
  ```bash
  if [ -z "${{SKILL_REQUIRED_PARAM:-}}" ]; then
    echo "Error: SKILL_REQUIRED_PARAM is required" >&2
    exit 1
  fi
  ```

## Workflow

1. **Explore** — Read SKILL.md, LEARN.md, and any existing `scripts/run.sh` to understand context
2. **Research** — Use `--help` on tools from the Available Tools list to discover flags and options
3. **Write** — Create `scripts/run.sh` in the current directory
4. **Verify** — Test the script works (or dry-run if it has side effects)
5. **Iterate** — Fix issues until the script is robust

When {reset_mode}, write a completely new script. When iterating on an existing one, use it as context but feel free to completely rewrite.

## Finishing

When the script is ready and you've written it to `scripts/run.sh`, indicate the task is complete.
"""

# Simple one-shot prompt for --no-agent mode — only asks for the script, nothing else.
SHELLIFY_NOAGENT_PROMPT = """You are converting an agentic skill into a deterministic shell script (`run.sh`).


# Goal
Transform the skill description and instructions into a robust, reproducible `run.sh` bash script that accomplishes the same task using shell commands and CLI tools.

# Skill Description
{skill_description}

# Skill Parameters
{skill_parameters}

# Skill Body (from SKILL.md) — THIS IS WHAT YOU ARE TRANSFORMING INTO A SHELL SCRIPT
{skill_body}

{learn_section}

{tools_section}

# Output Requirements

Produce ONLY a valid bash script. The script must:

1. **Start with `#!/usr/bin/env bash`** and use `set -euo pipefail`
2. **Use environment variables for parameters** — each skill parameter is available as `$SKILL_{{PARAM_NAME_UPPER}}` (e.g., parameter `video_url` becomes `$SKILL_VIDEO_URL`)
3. **Validate required parameters** — check that required parameters are set and exit with a helpful error message if not
4. **Use CLI tools** — refer to the Available Tools section above for what you can use. Use `--help` to discover their options.
5. **Be incremental and robust** — use intermediate files, handle errors gracefully, provide progress output
6. **Be self-contained** — include all necessary commands in one script
7. **Output results to the current working directory** — do not use hardcoded absolute paths

# Parameter Handling

- For a parameter named `foo`, the environment variable is `$SKILL_FOO`
- For optional parameters with defaults, use `${{SKILL_FOO:-default_value}}`
- Validate required parameters early:
  ```bash
  if [ -z "${{SKILL_REQUIRED_PARAM:-}}" ]; then
    echo "Error: SKILL_REQUIRED_PARAM is required" >&2
    exit 1
  fi
  ```

# Shell Script

```bash
#!/usr/bin/env bash
set -euo pipefail

# Your script here
```

Output ONLY the script content, with no extra explanation.
"""


# ---------------------------------------------------------------------------
# Shellify helper functions
# ---------------------------------------------------------------------------

def _backup_run_sh(run_sh_path: Path) -> Path | None:
    """Backup existing run.sh before overwriting. Returns backup path or None."""
    if not run_sh_path.exists():
        return None

    import time
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = run_sh_path.with_name(f"run.sh.bak.{ts}")
    try:
        run_sh_path.rename(backup)
        return backup
    except Exception:
        return None


def _extract_bash_script(content: str) -> str:
    """Extract bash script from LLM response — strips markdown fences, commentary."""
    content = content.strip()

    # If wrapped in code fences, extract content
    if content.startswith("```bash"):
        content = content[len("```bash"):]
    if content.startswith("```\n"):
        content = content[len("```\n"):]
    if content.startswith("```"):
        content = content[len("```"):]
    if content.endswith("```"):
        content = content[:-len("```")]

    content = content.strip()

    # If it doesn't start with shebang, try to find the script within
    if not content.startswith("#!/"):
        # Look for last occurrence of ```bash or ```
        lines = content.split("\n")
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("#!"):
                start_idx = i
                break
        if start_idx > 0:
            content = "\n".join(lines[start_idx:])

    return content


def _shellify_no_agent(
    skill,
    provider: str,
    model: str | None,
    skill_description: str,
    skill_parameters: str,
    skill_body: str,
    learn_section: str,
    tools_section: str,
    verbose: bool,
    debug: bool,
) -> bool:
    """Simple one-shot LLM call to generate run.sh (no agentic loop)."""
    from common.core.config import load_tool_config
    from common.llm.registry import discover_providers
    from common.llm.base import LLMRequest

    # CRITICAL system instruction for no-agent mode
    system_msg = (
        "You are a bash script generator. Your ONLY job is to output a bash script.\n"
        "RULES:\n"
        "1. Output ONLY the script content, with NO explanation, NO commentary, NO markdown.\n"
        "2. If you must use markdown fences, the script must be the ONLY code block.\n"
        "3. Start with #!/usr/bin/env bash and use set -euo pipefail.\n"
        "4. Do NOT include any text before or after the script.\n"
        "5. Any extra text will be discarded. Just output the raw script."
    )

    # Use the dedicated no-agent prompt template
    formatted_prompt = SHELLIFY_NOAGENT_PROMPT.format(
        skill_description=skill_description,
        skill_parameters=skill_parameters,
        skill_body=skill_body,
        learn_section=learn_section,
        tools_section=tools_section,
    )

    # Add a final emphatic reminder to the prompt
    formatted_prompt += (
        "\n\n---\n"
        "FINAL INSTRUCTION: Output ONLY the bash script. No explanation. No preamble. "
        "No summary. Just the script."
    )

    click.echo(f"Shellifying skill '{skill.name}' (one-shot)...", err=True)

    # Debug: print prompt and exit
    if debug:
        click.echo(f"=== Shellify prompt for skill '{skill.name}' (no-agent) ===")
        click.echo(formatted_prompt)
        click.echo("=== End of prompt ===")
        return True

    config = load_tool_config("skill")
    providers = discover_providers(config)
    llm = providers.get(provider)
    if not llm:
        click.echo(f"Error: provider '{provider}' not available.", err=True)
        return False

    req = LLMRequest(
        system=system_msg,
        messages=[{"role": "user", "content": formatted_prompt}],
        model=model,
        temperature=0.1,
    )
    resp = llm.complete(req)
    script_content = _extract_bash_script(resp.content)

    if not script_content or not script_content.startswith("#!/"):
        click.echo(
            f"Warning: LLM response does not appear to be a valid bash script. "
            f"Writing raw output anyway.",
            err=True,
        )

    # Backup existing run.sh before writing
    run_sh_path = skill.path / "scripts" / "run.sh"
    backup = _backup_run_sh(run_sh_path)
    if backup and verbose:
        click.echo(f"Backed up: {backup}", err=True)

    run_sh_path.write_text(script_content + "\n", encoding="utf-8")

    try:
        run_sh_path.chmod(0o755)
    except Exception:
        pass

    click.echo(f"Generated {run_sh_path}", err=True)
    return True


def _shellify_skill(
    skill,
    provider: str,
    model: str | None = None,
    prompt_template: str | None = None,
    instruction: str | None = None,
    reset: bool = False,
    verbose: bool = False,
    max_iterations: int = 25,
    no_agent: bool = False,
    debug: bool = False,
) -> bool:
    """Convert a skill into scripts/run.sh using an agentic loop.

    Args:
        skill: Skill object with parameters, description, and path.
        provider: LLM provider name.
        model: Optional model name override.
        prompt_template: Optional shellify prompt template.
        instruction: Additional user instructions appended to prompt.
        reset: If True, ignore existing scripts/run.sh (fresh start).
        verbose: Show agent progress to stderr.
        max_iterations: Maximum agent iterations.
        no_agent: If True, use a simple one-shot LLM call instead.
        debug: If True, print the full prompt to stdout and exit.

    Returns True on success, False on failure.
    """
    from common.agent.call import agent_call
    from common.core.paths import get_skills_dir
    from common.core.config import load_tool_config
    from commands.setup import init_skill_agent_config

    # Read skill content
    skill_body = skill.get_body()
    skill_description = skill.description or skill.name

    # Build parameters section
    params_list = skill.parameters
    if params_list:
        params_lines = []
        for p in params_list:
            pname = p.get("name", "?")
            req = " (required)" if p.get("required", True) else f" (optional, default: {p.get('default', 'none')})"
            desc = p.get("description", "")
            params_lines.append(f"- {pname}{req}: {desc}")
        skill_parameters = "\n".join(params_lines)
    else:
        skill_parameters = "No parameters — this skill has no configurable inputs."

    # Read LEARN.md if it exists
    learn_path = skill.path / "LEARN.md"
    if learn_path.exists():
        learn_content = learn_path.read_text(encoding="utf-8")
        learn_section = f"# Lessons from Previous Runs\n\n{learn_content}"
    else:
        learn_section = "# Lessons from Previous Runs\n\nNone — this is a fresh skill with no previous runs."

    # Read existing scripts/run.sh if present (and not resetting)
    run_sh_path = skill.path / "scripts" / "run.sh"
    if not reset and run_sh_path.exists():
        existing_content = run_sh_path.read_text(encoding="utf-8")
        existing_script_section = (
            f"# Existing scripts/run.sh (current version for reference)\n\n"
            f"```bash\n{existing_content}\n```"
        )
        reset_mode_str = "resetting (--reset flag)"
    elif reset:
        existing_script_section = "# No existing script — starting fresh (--reset flag)."
        reset_mode_str = "resetting (--reset flag)"
    else:
        existing_script_section = "# No existing scripts/run.sh — starting from scratch."
        reset_mode_str = "iterating on the existing script"

    # Additional instructions
    if instruction:
        instructions_section = f"# Additional Instructions\n\n{instruction}"
    else:
        instructions_section = "# Additional Instructions\n\nNone."

    # Available tools for the script (level 1 = tool name + description only)
    system_commands = [
        "ls", "cat", "head", "tail", "grep", "find", "wc",
        "mkdir", "touch", "cp", "mv", "rm", "chmod", "date",
        "printf", "sed", "awk", "cut", "tr", "sort", "uniq",
        "curl", "wget", "jq", "tee", "tar", "gzip", "zip", "unzip",
    ]
    
    from common.agent.doc import build_tool_documentation
    tools_section = build_tool_documentation(
        depth=1,
        system_commands=system_commands,
    )

    # Build the prompt
    if prompt_template is None:
        prompt_template = SHELLIFY_PROMPT_DEFAULT

    formatted_prompt = prompt_template.format(
        skill_description=skill_description,
        skill_parameters=skill_parameters,
        skill_body=skill_body,
        learn_section=learn_section,
        existing_script_section=existing_script_section,
        instructions_section=instructions_section,
        tools_section=tools_section,
        reset_mode=reset_mode_str,
    )

    # Ensure scripts/ directory exists
    scripts_dir = skill.path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # No-agent mode: simple one-shot LLM call
    # ------------------------------------------------------------------
    if no_agent:
        return _shellify_no_agent(
            skill=skill,
            provider=provider,
            model=model,
            skill_description=skill_description,
            skill_parameters=skill_parameters,
            skill_body=skill_body,
            learn_section=learn_section,
            tools_section=tools_section,
            verbose=verbose,
            debug=debug,
        )

    # ------------------------------------------------------------------
    # Agentic mode
    # ------------------------------------------------------------------
    click.echo(f"Shellifying skill '{skill.name}' (agentic)...", err=True)
    if verbose:
        click.echo(f"  Workdir: {skill.path}", err=True)
        click.echo(f"  Provider: {provider}, Model: {model or 'default'}", err=True)
        click.echo(f"  Max iterations: {max_iterations}", err=True)
        if reset:
            click.echo("  Mode: reset — ignoring existing run.sh", err=True)
        if instruction:
            click.echo(f"  Instructions: {instruction[:80]}...", err=True)

    # System commands the agent can use for exploration and file operations
    # (must match the tools_section list above)
    agent_system_commands = [
        "ls", "cat", "head", "tail", "grep", "find", "wc",
        "mkdir", "touch", "cp", "mv", "rm", "chmod", "date",
        "printf", "sed", "awk", "cut", "tr", "sort", "uniq",
        "curl", "wget", "jq", "tee", "tar", "gzip", "zip", "unzip",
    ]

    # Load fastmarket_tools from config to include prompt, corpus, image, etc.
    agent_config = init_skill_agent_config()
    fastmarket_tools = agent_config.get("fastmarket_tools", {})

    task_description = formatted_prompt

    # Backup existing run.sh before the agent runs (agent will overwrite it)
    backup = _backup_run_sh(run_sh_path)
    if backup and verbose:
        click.echo(f"Backed up: {backup}", err=True)

    # Debug: print prompt and exit
    if debug:
        click.echo(f"=== Shellify prompt for skill '{skill.name}' (agentic) ===")
        click.echo(formatted_prompt)
        click.echo("=== End of prompt ===")
        return True

    try:
        session = agent_call(
            task_description=task_description,
            workdir=skill.path,
            system_commands=agent_system_commands,
            fastmarket_tools=fastmarket_tools,
            provider=provider,
            model=model,
            verbose=verbose,
        )

        # Check if the agent wrote scripts/run.sh
        if run_sh_path.exists():
            # Make executable
            try:
                run_sh_path.chmod(0o755)
            except Exception:
                pass

            click.echo(f"Generated {run_sh_path}", err=True)
            if verbose:
                turns = len(session.turns) if session.turns else 0
                tool_calls = sum(
                    1 for t in (session.turns or [])
                    if hasattr(t, "tool_calls") and t.tool_calls
                )
                click.echo(
                    f"  Agent: {turns} turns, {tool_calls} with tool calls, "
                    f"end reason: {getattr(session, 'end_reason', 'unknown')}",
                    err=True,
                )
            return True
        else:
            click.echo(
                f"Warning: agent did not create {run_sh_path}",
                err=True,
            )
            if verbose:
                click.echo(f"  End reason: {getattr(session, 'end_reason', 'unknown')}", err=True)
            return False

    except Exception as exc:
        click.echo(f"Error during shellification: {exc}", err=True)
        return False


def register_shellify_subcommand(plan):
    """Register the shellify subcommand on the plan command group."""
    from commands.params import SkillNameType as _SkillNameType

    @plan.command("shellify")
    @click.argument("skill", type=_SkillNameType())
    @click.option(
        "--model",
        "-m",
        default=None,
        help="LLM model to use for generation.",
    )
    @click.option(
        "--instruction",
        "-i",
        "instructions",
        default=(),
        multiple=True,
        help="Additional instructions (can be used multiple times). Use '-' to read from stdin.",
    )
    @click.option(
        "--reset",
        is_flag=True,
        default=False,
        help="Force recreation: ignore existing scripts/run.sh and start fresh.",
    )
    @click.option(
        "--verbose",
        "-v",
        is_flag=True,
        default=False,
        help="Show agent progress.",
    )
    @click.option(
        "--max-iterations",
        "-n",
        type=int,
        default=25,
        help="Maximum agent iterations (default: 25).",
    )
    @click.option(
        "--no-agent",
        is_flag=True,
        default=False,
        help="Use a simple one-shot LLM call instead of the agentic loop.",
    )
    @click.option(
        "--debug",
        "-d",
        is_flag=True,
        default=False,
        help="Print the full prompt that would be sent to the LLM and exit.",
    )
    def shellify_cmd(skill, model, instructions, reset, verbose, max_iterations, no_agent, debug):
        """Convert a skill into scripts/run.sh using an agentic LLM loop.

        Reads SKILL.md and LEARN.md (if present) from the skill directory,
        then uses an agentic loop with tool access to create scripts/run.sh.
        The agent can explore files, test commands with --help, and iterate.

        Use --no-agent for a simple one-shot LLM call (faster, less robust).
        """
        from common.core.config import requires_common_config, load_tool_config
        from common.llm.registry import get_default_provider_name
        from core.skill import Skill, discover_skills
        from common.core.paths import get_skills_dir

        requires_common_config("skill", ["llm"])
        try:
            config = load_tool_config("skill")
            provider_name = get_default_provider_name(config)
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1)

        # Merge instructions: handle "-" as stdin, join all with newlines
        merged_parts = []
        for instr in instructions:
            if instr == "-":
                if sys.stdin.isatty():
                    raise click.ClickException(
                        "Instruction '-' requires stdin (pipe content into this command)"
                    )
                stdin_content = sys.stdin.read().strip()
                if not stdin_content:
                    raise click.ClickException("No input from stdin for instruction '-'")
                merged_parts.append(stdin_content)
            else:
                merged_parts.append(instr)

        instruction = "\n\n".join(merged_parts) if merged_parts else None

        # Resolve the skill
        skills_dir = get_skills_dir()
        all_skills = discover_skills(skills_dir)
        skill_obj = None
        for s in all_skills:
            if s.name == skill:
                skill_obj = s
                break

        if skill_obj is None:
            click.echo(f"Error: skill '{skill}' not found.", err=True)
            raise SystemExit(1)

        # Get the prompt
        from cli.main import get_skill_prompt_manager
        prompt_manager = get_skill_prompt_manager()
        prompt_template = prompt_manager.get("shellify") if prompt_manager else SHELLIFY_PROMPT_DEFAULT

        # Run the shellify logic
        success = _shellify_skill(
            skill=skill_obj,
            provider=provider_name,
            model=model,
            prompt_template=prompt_template,
            instruction=instruction,
            reset=reset,
            verbose=verbose,
            max_iterations=max_iterations,
            no_agent=no_agent,
            debug=debug,
        )

        if not success:
            raise SystemExit(1)
