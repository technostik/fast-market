from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TaskConfig:
    allowed_commands: set[str]
    max_iterations: int = 20
    default_timeout: int = 60


_TERMINATION_PATTERNS = (
    "task complete",
    "task completed",
    "all done",
    "done!",
    "finished!",
    "completed successfully",
    "no more commands needed",
)


def is_termination_message(content: str) -> bool:
    """Check if the message indicates task completion."""
    content_lower = content.lower()
    return any(p in content_lower for p in _TERMINATION_PATTERNS)


@dataclass
class TaskLoop:
    config: TaskConfig
    workdir: Path
    provider: str
    model: str | None
    verbose: bool = False

    def run(
        self,
        task_description: str,
        execute_fn,
        task_params: dict[str, str] | None = None,
    ) -> None:
        """Run the agentic loop until completion or max iterations."""
        from common.core.config import load_tool_config
        from commands.helpers import build_engine
        from commands.task.prompts import build_system_prompt

        config = load_tool_config("prompt")
        providers = build_engine(self.verbose)

        if self.provider not in providers:
            raise ValueError(
                f"Provider '{self.provider}' not found. "
                f"Available: {list(providers.keys())}"
            )

        llm_provider = providers[self.provider]
        system_prompt = build_system_prompt(
            task_description=task_description,
            allowed_commands=list(self.config.allowed_commands),
            workdir=self.workdir,
            task_params=task_params,
        )

        messages = [
            {
                "role": "user",
                "content": f"## Task\n{task_description}\n\nBegin executing commands to complete this task.",
            }
        ]

        iteration = 0
        max_iter = self.config.max_iterations

        self._log(f"Starting task with {max_iter} max iterations...")
        if task_params:
            self._log(f"Task parameters: {list(task_params.keys())}")

        while iteration < max_iter:
            iteration += 1
            self._log(f"\n--- Iteration {iteration}/{max_iter} ---")

            request = self._build_request(system_prompt, messages)
            response = llm_provider.complete(request)

            response_text = response.content
            self._log(f"LLM response: {response_text[:200]}...")

            if self._has_tool_use(response_text):
                should_continue = self._handle_tool_use(
                    response_text,
                    execute_fn,
                    messages,
                )
                if not should_continue:
                    break
            elif is_termination_message(response_text):
                self._log("\n=== TASK COMPLETE ===")
                print(response_text)
                break
            else:
                messages.append({"role": "assistant", "content": response_text})
                print(response_text)
                break
        else:
            print(f"\nMax iterations ({max_iter}) reached. Task may not be complete.")

    def _build_request(self, system_prompt: str, messages: list[dict]):
        from plugins.base import LLMRequest

        return LLMRequest(
            prompt=self._format_messages(messages),
            model=self.model,
            system=system_prompt,
            max_tokens=4096,
        )

    def _format_messages(self, messages: list[dict]) -> str:
        """Format messages for non-tool-use providers."""
        formatted = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if msg.get("tool_results"):
                for tr in msg["tool_results"]:
                    formatted.append(
                        f"[TOOL RESULT: {tr['command']}]\n"
                        f"Exit code: {tr['exit_code']}\n"
                        f"Stdout:\n{tr['stdout']}\n"
                        f"Stderr:\n{tr['stderr']}"
                    )
            else:
                formatted.append(f"[{role.upper()}]\n{content}")
        return "\n\n".join(formatted)

    def _has_tool_use(self, text: str) -> bool:
        """Check if response contains tool use."""
        import re

        return bool(re.search(r"<tool_call>", text, re.IGNORECASE))

    def _handle_tool_use(
        self,
        response_text: str,
        execute_fn,
        messages: list[dict],
    ) -> bool:
        """Handle tool use response. Returns False if task should terminate."""
        import re

        tool_calls = re.findall(
            r"<tool_call>\s*<name>(\w+)</name>\s*<input>\s*<command>([^<]+)</command>\s*<explanation>([^<]*)</explanation>\s*</input>\s*</tool_call>",
            response_text,
            re.DOTALL,
        )

        if not tool_calls:
            if is_termination_message(response_text):
                return False
            messages.append({"role": "assistant", "content": response_text})
            return True

        messages.append({"role": "assistant", "content": response_text})

        for tool_name, command, explanation in tool_calls:
            self._log(f"Executing: {command}")
            if explanation:
                self._log(f"  Reason: {explanation}")

            command = command.strip()
            result = execute_fn(command)
            self._log(f"  Exit code: {result.exit_code}")

            messages.append(
                {
                    "role": "user",
                    "content": self._format_tool_result(command, explanation, result),
                }
            )

        return True

    def _format_tool_result(
        self,
        command: str,
        explanation: str,
        result,
    ) -> str:
        return f"""[TOOL RESULT]
Command: {command}
Exit code: {result.exit_code}
Stdout:
{result.stdout[:5000] if result.stdout else "(empty)"}
Stderr:
{result.stderr[:2000] if result.stderr else "(empty)"}
Timed out: {result.timed_out}"""

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[VERBOSE] {msg}", file=sys.stderr)


def run_dry_run(
    task_description: str,
    config: TaskConfig,
    workdir: Path,
    task_params: dict[str, str] | None = None,
) -> None:
    """Show what commands would be executed without running them."""
    print(f"[DRY RUN] Task: {task_description}")
    print(f"[DRY RUN] Workdir: {workdir}")
    print(f"[DRY RUN] Max iterations: {config.max_iterations}")
    print(f"[DRY RUN] Allowed commands: {', '.join(sorted(config.allowed_commands))}")
    if task_params:
        print(f"[DRY RUN] Parameters:")
        for key, value in task_params.items():
            display = value[:50] + "..." if len(value) > 50 else value
            print(f"  - {key}: {display}")
    print("\n[DRY RUN] Note: Commands not actually executed in dry-run mode.")
