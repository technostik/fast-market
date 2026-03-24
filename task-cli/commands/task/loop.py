from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from common import structlog
from core.session import Session, Turn, ToolCallEvent
from common.llm.base import (
    LLMRequest,
    _format_debug_request,
    _format_debug_response,
)

logger = structlog.get_logger(__name__)


@dataclass
class TaskConfig:
    fastmarket_tools: dict
    system_commands: list[str]
    max_iterations: int = 20
    default_timeout: int = 60
    allowed_commands: list[str] = field(default_factory=list)


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


def build_execute_command_tool(allowed_commands: list[str]) -> dict:
    """Build the OpenAI-style tool definition for execute_command."""
    return {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a whitelisted CLI command in the working directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of why you're running this command",
                    },
                },
                "required": ["command"],
            },
        },
    }


def format_message_history(messages: list[dict]) -> str:
    """Format message history for the prompt."""
    formatted = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "tool":
            tc_id = msg.get("tool_call_id", "")
            formatted.append(f"[TOOL RESULT for {tc_id}]\n{content}")
        elif msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                tc_list.append(
                    f"- {tc['function']['name']}: {tc['function']['arguments']}"
                )
            formatted.append(
                f"[ASSISTANT]\n{content}\n[TOOL CALLS]\n" + "\n".join(tc_list)
            )
        else:
            formatted.append(f"[{role.upper()}]\n{content}")
    return "\n\n".join(formatted)


@dataclass
class TaskLoop:
    config: TaskConfig
    workdir: Path
    provider: str
    model: str | None
    verbose: bool = False
    debug: str = ""  # "" = off, "normal" = inner dialog, "full" = everything
    silent: bool = False
    session: Optional[Session] = None

    @property
    def _debug_enabled(self) -> bool:
        return bool(self.debug)

    @property
    def _debug_full(self) -> bool:
        return self.debug == "full"

    def run(
        self,
        task_description: str,
        execute_fn,
        task_params: dict[str, str] | None = None,
    ) -> None:
        """Run the agentic loop until completion or max iterations."""
        from common.core.config import load_tool_config
        from common.llm.registry import discover_providers
        from commands.task.prompts import build_system_prompt

        config = load_tool_config("apply")
        providers = discover_providers(config)

        if self.provider not in providers:
            raise ValueError(
                f"Provider '{self.provider}' not found. "
                f"Available: {list(providers.keys())}"
            )

        llm_provider = providers[self.provider]
        if hasattr(llm_provider, "set_debug"):
            llm_provider.set_debug(self._debug_enabled)

        self.session = Session(
            task_description=task_description,
            workdir=str(self.workdir),
            provider=self.provider,
            model=self.model or "",
            max_iterations=self.config.max_iterations,
            task_params=task_params or {},
        )

        self.session.add_turn(
            Turn(
                role="user",
                content=f"## Task\n{task_description}\n\nBegin executing commands to complete this task.",
                timestamp=datetime.utcnow(),
            )
        )

        if not self.silent:
            self._print_session_header()

        system_prompt = build_system_prompt(
            task_description=task_description,
            fastmarket_tools_config=self.config.fastmarket_tools,
            system_commands=self.config.system_commands,
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
        allowed_commands = (
            list(self.config.fastmarket_tools.keys()) + self.config.system_commands
        )
        tools = [build_execute_command_tool(allowed_commands)]

        self._log(f"Starting task with {max_iter} max iterations...")
        if task_params:
            self._log(f"Task parameters: {list(task_params.keys())}")

        while iteration < max_iter:
            iteration += 1
            self._debug(f"{'=' * 50}")
            self._debug(f"ITERATION {iteration}/{max_iter}")
            self._debug(f"{'=' * 50}")

            if self._debug_full:
                self._debug(f">>> LLM REQUEST")
                self._debug(f"System prompt: {len(system_prompt)} chars")
                self._debug(
                    f"User message: {len(format_message_history(messages))} chars"
                )
                self._debug(f"Tools: {len(tools)} defined")

            from common.llm.base import LLMRequest

            request = LLMRequest(
                prompt=format_message_history(messages),
                model=self.model,
                system=system_prompt,
                max_tokens=4096,
                tools=tools,
            )

            if self._debug_full:
                self._debug("\n" + _format_debug_request(request))

            response = llm_provider.complete(request)

            if self._debug_full:
                self._debug("\n" + _format_debug_response(response))
            else:
                self._debug(f">>> LLM RESPONSE ({len(response.content)} chars)")
                self._debug(
                    response.content[:300]
                    + ("..." if len(response.content) > 300 else "")
                )

            if response.tool_calls:
                self._debug(f">>> {len(response.tool_calls)} tool_call(s) detected")
                should_continue = self._handle_tool_calls(
                    response,
                    execute_fn,
                    messages,
                    tools,
                )
                if not should_continue:
                    break
            elif is_termination_message(response.content):
                self.session.end_time = datetime.utcnow()
                self._log("\n=== TASK COMPLETE ===")
                if not self.silent:
                    print(response.content)
                break
            else:
                self._debug(f">>> No tool_calls, final response")
                messages.append({"role": "assistant", "content": response.content})
                if not self.silent:
                    print(response.content)
                break
        else:
            self.session.end_time = datetime.utcnow()
            if not self.silent:
                print(
                    f"\nMax iterations ({max_iter}) reached. Task may not be complete."
                )

        if self.session and not self.session.end_time:
            self.session.end_time = datetime.utcnow()

    def _handle_tool_calls(
        self,
        response,
        execute_fn,
        messages: list[dict],
        tools: list[dict],
    ) -> bool:
        """Handle tool calls from the response."""
        if not response.tool_calls:
            return True

        from common.core.aliases import get_all_aliases

        aliases = get_all_aliases()

        assistant_turn = Turn(
            role="assistant",
            content=response.content or "",
            timestamp=datetime.utcnow(),
        )

        for tc in response.tool_calls:
            tool_event = ToolCallEvent(
                tool_call_id=tc.id,
                tool_name=tc.name,
                arguments=tc.arguments if isinstance(tc.arguments, dict) else {},
                explanation=tc.arguments.get("explanation", "")
                if isinstance(tc.arguments, dict)
                else "",
            )
            assistant_turn.tool_calls.append(tool_event)

        if self.session:
            self.session.add_turn(assistant_turn)

        if not self.silent:
            self._print_assistant_turn(assistant_turn)

        messages.append(
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                            if isinstance(tc.arguments, dict)
                            else str(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
        )

        for tool_call, tool_event in zip(
            response.tool_calls, assistant_turn.tool_calls
        ):
            command = tool_call.arguments.get("command", "")
            explanation = tool_call.arguments.get("explanation", "")
            self._debug(f">>> TOOL: {tool_call.name}")

            if command in aliases:
                resolved = aliases[command]
                self._debug(f"    Command: {command}")
                self._debug(f"    Alias resolves to: {resolved}")
            else:
                self._debug(f"    Command: {command}")

            if explanation:
                self._debug(f"    Reason: {explanation}")
            if self._debug_full:
                self._debug(f"    Full args: {tool_call.arguments}")

            result = execute_fn(command.strip())

            tool_event.result = {"timed_out": result.timed_out}
            tool_event.exit_code = result.exit_code
            tool_event.stdout = result.stdout or ""
            tool_event.stderr = result.stderr or ""

            if self._debug_full:
                self._debug(f"    Exit: {result.exit_code}")
                if result.stdout:
                    self._debug(f"    Stdout: {result.stdout[:100]}...")
                if result.stderr:
                    self._debug(f"    Stderr: {result.stderr[:100]}...")
            else:
                output_preview = (result.stdout or result.stderr or "").strip()[:100]
                self._debug(
                    f"    -> Exit {result.exit_code}, Output: {output_preview[:80]}..."
                )

            if not self.silent:
                self._print_tool_result(tool_event)

            tool_result = self._format_tool_result(command, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

        return True

    def _format_tool_result(self, command: str, result) -> str:
        return f"""Command: {command}
Exit code: {result.exit_code}
Stdout:
{result.stdout[:5000] if result.stdout else "(empty)"}
Stderr:
{result.stderr[:2000] if result.stderr else "(empty)"}
Timed out: {result.timed_out}"""

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[VERBOSE] {msg}", file=sys.stderr)

    def _debug(self, msg: str) -> None:
        if self._debug_enabled:
            print(f"[DEBUG] {msg}", file=sys.stderr)

    def _print_session_header(self) -> None:
        if not self.session:
            return
        print("\n" + "=" * 60)
        print(f"TASK SESSION: {self.session.task_description}")
        print(
            f"Provider: {self.session.provider}, Model: {self.session.model or 'default'}"
        )
        print(f"Workdir: {self.session.workdir}")
        if self.session.task_params:
            print("Parameters:")
            for k, v in self.session.task_params.items():
                print(f"  {k}: {v[:50]}...")
        print("=" * 60 + "\n")

    def _print_assistant_turn(self, turn: Turn) -> None:
        print("\n---")
        print(f"ASSISTANT ({turn.timestamp.strftime('%H:%M:%S')})")
        if turn.content:
            print(turn.content)
        if turn.tool_calls:
            print("\nTOOL CALLS:")
            for tc in turn.tool_calls:
                print(f"  - {tc.tool_name}: {tc.arguments.get('command', '')}")
                if tc.explanation:
                    print(f"    Reason: {tc.explanation}")

    def _print_tool_result(self, tool_event: ToolCallEvent) -> None:
        print(f"\n-> TOOL RESULT (exit: {tool_event.exit_code})")
        if tool_event.stdout:
            preview = tool_event.stdout[:200] + (
                "..." if len(tool_event.stdout) > 200 else ""
            )
            print(preview)
        if tool_event.stderr and tool_event.exit_code != 0:
            print(f"Error: {tool_event.stderr[:200]}")


def run_dry_run(
    task_description: str,
    config: TaskConfig,
    workdir: Path,
    task_params: dict[str, str] | None = None,
) -> None:
    """Show what commands would be executed without running them."""
    from common.core.aliases import get_all_aliases

    print(f"[DRY RUN] Task: {task_description}")
    print(f"[DRY RUN] Workdir: {workdir}")
    print(f"[DRY RUN] Max iterations: {config.max_iterations}")
    print(f"[DRY RUN] Allowed commands: {', '.join(sorted(config.allowed_commands))}")

    aliases = get_all_aliases()
    if aliases:
        print(f"[DRY RUN] Available aliases:")
        for alias_name, actual_cmd in sorted(aliases.items()):
            print(f"  - {alias_name} → {actual_cmd}")

    if task_params:
        print(f"[DRY RUN] Parameters:")
        for key, value in task_params.items():
            display = value[:50] + "..." if len(value) > 50 else value
            print(f"  - {key}: {display}")
    print("\n[DRY RUN] Note: Commands not actually executed in dry-run mode.")
