"""Browser-specific agentic loop.

This loop is like ``common.agent.loop.TaskLoop`` but uses **only** the
``browse`` tool — there is no ``execute_command`` or ``shared_context`` tool.
The system prompt includes the full ``agent-browser`` documentation so the
LLM knows every available sub-command.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from common import structlog
from common.agent.session import Session, Turn, ToolCallEvent
from common.llm.base import (
    LLMRequest,
    _format_debug_request,
    _format_debug_response,
)
from commands.run.browser_tool import (
    build_browse_tool,
    execute_browse_action,
    format_browse_result,
)

logger = structlog.get_logger(__name__)

# Patterns that signal the LLM considers the task done.
_TERMINATION_PATTERNS = (
    "task complete",
    "task completed",
    "all done",
    "done!",
    "finished!",
    "completed successfully",
    "no more",
    "browsing complete",
    "browser task complete",
)


# ---------------------------------------------------------------------------
# Default prompt templates
# ---------------------------------------------------------------------------

BROWSER_DEFAULT_PROMPTS = {
    "browser": (
        "You are an autonomous web browser agent. "
        "Your job is to accomplish the task described below by interacting with "
        "a real web browser through the ``browse`` tool. "
        "You have **only one tool**: ``browse``.  You **cannot** execute shell "
        "commands, fetch URLs, or use curl/wget.  This is NOT a web scraping tool — "
        "it controls an actual Chromium browser instance via CLI commands.\n\n"
        "**Understanding page content:** To discover what's on a page, you MUST use "
        "the ``snapshot`` action first. This returns an accessibility tree showing all "
        "visible elements with their refs (like ``@e2``, ``@e5``). The snapshot is your "
        "map of the page — use it to identify buttons, links, form fields, and text.\n\n"
        "**Interacting with elements:** Once you have a snapshot, use the element refs "
        "to interact with specific elements: ``click @e2``, ``fill @e5 text``, etc. "
        "Always work from the snapshot refs rather than guessing CSS selectors.\n\n"
        "Every browser operation — navigation, clicking, filling "
        "forms, taking screenshots, extracting data — must be done through "
        "the ``browse`` tool."
    ),
    "browser-params-header": (
        "The following parameters are available as ``{key}`` placeholders "
        "in the ``args`` of the ``browse`` tool.  They will be substituted "
        "before the command is executed:"
    ),
    "browser-doc-header": (
        "Below is the complete reference for the ``browse`` tool. "
        "The ``action`` parameter maps to the first word of each command, "
        "and ``args`` maps to the remaining arguments."
    ),
    "browser-rules": (
        "1. **Always start with ``snapshot``** — this gives you the accessibility tree "
        "with element refs (``@e2``, ``@e5``, etc.). This is your PRIMARY way to understand "
        "what's on the page. Without a snapshot, you're flying blind.\n"
        "2. Use element refs from snapshot directly: ``click @e2``, ``fill @e5 hello``. "
        "These are far more reliable than CSS selectors.\n"
        "3. After navigating or interacting with the page, take a new ``snapshot`` to see "
        "the updated state before taking the next action.\n"
        "4. Use ``screenshot`` to capture visual state when you need to see the actual rendering.\n"
        "5. When a file upload is needed and a ``{key}`` parameter contains "
        "the file path, pass it directly in the args.\n"
        "6. When the task is complete, provide a clear summary of what you "
        "accomplished and include relevant extracted data or results.\n"
        "7. If you encounter an error, try to recover and continue.  If "
        "recovery is impossible, report the error clearly.\n"
    ),
}


def is_termination_message(content: str) -> bool:
    """Check if the LLM message indicates the browser task is done."""
    content_lower = content.lower()
    return any(p in content_lower for p in _TERMINATION_PATTERNS)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_browser_system_prompt(
    task_description: str,
    browser_doc: str,
    task_params: dict[str, str] | None = None,
    workdir: Path | None = None,
    imported_session: Optional[Session] = None,
) -> str:
    """Build the full system prompt for the browser agent loop.

    Includes:
    - Role description (from prompt service or default)
    - The **full** browser documentation (as ``browser doc`` outputs it)
    - Parameter documentation
    - Usage rules
    - Previous session reference (if imported)
    """
    from common.prompt import get_cached_manager

    # Get the browser role prompt from the prompt service
    manager = get_cached_manager("browser")
    role_prompt = manager.get("browser") if manager else None
    if role_prompt is None:
        role_prompt = BROWSER_DEFAULT_PROMPTS["browser"]

    parts: list[str] = []

    # Role
    parts.append(role_prompt)

    # Parameters
    if task_params:
        params_header = manager.get("browser-params-header") if manager else None
        if params_header is None:
            params_header = BROWSER_DEFAULT_PROMPTS["browser-params-header"]

        parts.append("## Task Parameters\n")
        parts.append(params_header)
        for k, v in task_params.items():
            display = v[:80] + "..." if len(v) > 80 else v
            parts.append(f"- ``{{{k}}}`` → ``{display}``")

    # Working directory
    if workdir:
        parts.append(f"\n## Working Directory\n``{workdir}``")

    # Full browser documentation
    doc_header = manager.get("browser-doc-header") if manager else None
    if doc_header is None:
        doc_header = BROWSER_DEFAULT_PROMPTS["browser-doc-header"]

    parts.append("\n## Browser Command Reference\n" + doc_header + "\n")
    parts.append(browser_doc)

    # Rules
    rules_prompt = manager.get("browser-rules") if manager else None
    if rules_prompt is None:
        rules_prompt = BROWSER_DEFAULT_PROMPTS["browser-rules"]

    parts.append("\n## Rules\n" + rules_prompt)

    # Imported session reference
    if imported_session is not None:
        imported_text = imported_session.format_for_import(task_description)
        parts.append(f"\n## Previous Session Reference\n\n{imported_text}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Browser task loop
# ---------------------------------------------------------------------------

@dataclass
class BrowserTaskLoop:
    """Agentic loop that uses only the ``browse`` tool."""

    workdir: Path
    provider: str
    model: str | None
    max_iterations: int = 20
    llm_timeout: int = 0               # 0 = no limit
    temperature: float = 0.3
    cdp_port: int = 9222
    verbose: bool = False
    debug: str = ""                    # "" | "normal" | "full"
    silent: bool = False
    imported_session: Optional[Session] = None
    session: Optional[Session] = None

    @property
    def _debug_enabled(self) -> bool:
        return bool(self.debug)

    @property
    def _debug_full(self) -> bool:
        return self.debug == "full"

    # -- public API ----------------------------------------------------------

    def run(
        self,
        task_description: str,
        browser_doc: str,
        task_params: dict[str, str] | None = None,
    ) -> None:
        """Run the browser agentic loop until completion or max iterations."""
        from common.core.config import load_tool_config
        from common.llm.registry import discover_providers

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
            max_iterations=self.max_iterations,
            task_params=task_params or {},
        )

        self.session.add_turn(
            Turn(
                role="user",
                content=f"## Task\n{task_description}\n\nBegin executing browser actions to complete this task.",
                timestamp=datetime.utcnow(),
            )
        )

        if not self.silent:
            self._print_session_header()

        system_prompt = build_browser_system_prompt(
            task_description=task_description,
            browser_doc=browser_doc,
            task_params=task_params,
            workdir=self.workdir,
            imported_session=self.imported_session,
        )

        messages = [
            {
                "role": "user",
                "content": (
                    f"## Task\n{task_description}\n\n"
                    "Begin executing browser actions with tool_calls "
                    "to complete this task."
                ),
            }
        ]

        tools = [build_browse_tool()]

        self._log(f"Starting browser task with {self.max_iterations} max iterations...")
        if task_params:
            self._log(f"Task parameters: {list(task_params.keys())}")

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            self._debug(f"{'=' * 50}")
            self._debug(f"ITERATION {iteration}/{self.max_iterations}")
            self._debug(f"{'=' * 50}")

            if self._debug_full:
                self._debug(f">>> LLM REQUEST")
                self._debug(f"System prompt: {len(system_prompt)} chars")
                self._debug(f"Messages: {len(messages)} in history")
                self._debug(f"Tools: {len(tools)} defined")

            request = LLMRequest(
                messages=messages,
                model=self.model,
                system=system_prompt,
                max_tokens=4096,
                tools=tools,
                timeout=self.llm_timeout,
                temperature=self.temperature,
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
                    messages,
                    tools,
                    task_params,
                )
                if not should_continue:
                    break
            elif is_termination_message(response.content):
                messages.append({"role": "assistant", "content": response.content})
                if self.session:
                    self.session.add_turn(
                        Turn(
                            role="assistant",
                            content=response.content,
                            timestamp=datetime.utcnow(),
                        )
                    )
                    self.session.end_time = datetime.utcnow()
                self.session.end_reason = "success: model signaled task completion"
                self._log("\n=== BROWSER TASK COMPLETE ===")
                if not self.silent:
                    print(response.content)
                break
            else:
                self._debug(f">>> No tool_calls, final response")
                messages.append({"role": "assistant", "content": response.content})
                if self.session:
                    self.session.add_turn(
                        Turn(
                            role="assistant",
                            content=response.content,
                            timestamp=datetime.utcnow(),
                        )
                    )
                    self.session.end_time = datetime.utcnow()
                self.session.end_reason = "success: assistant returned final response"
                if not self.silent:
                    print(response.content)
                break
        else:
            self.session.end_time = datetime.utcnow()
            self.session.end_reason = "round limit reached"
            if not self.silent:
                print(
                    f"\nMax iterations ({self.max_iterations}) reached. "
                    f"Task may not be complete."
                )

        if self.session and not self.session.end_time:
            self.session.end_time = datetime.utcnow()
        if self.session and not self.session.end_reason:
            self.session.end_reason = "stopped: loop exited"

    # -- tool call handling --------------------------------------------------

    def _handle_tool_calls(
        self,
        response,
        messages: list[dict],
        tools: list[dict],
        task_params: dict[str, str] | None,
    ) -> bool:
        """Handle ``browse`` tool calls from the LLM response."""
        if not response.tool_calls:
            return True

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
            action = tool_call.arguments.get("action", "")
            args = tool_call.arguments.get("args", [])
            explanation = tool_call.arguments.get("explanation", "")

            self._debug(f">>> BROWSE TOOL: {action} {args}")
            if explanation:
                self._debug(f"    Reason: {explanation}")

            # Execute the browse action
            result = execute_browse_action(
                action=action,
                args=args if isinstance(args, list) else [str(args)],
                cdp_port=self.cdp_port,
                params=task_params,
            )

            tool_event.stdout = result.stdout or ""
            tool_event.stderr = result.stderr or ""
            tool_event.exit_code = result.exit_code
            tool_event.result = {"timed_out": result.timed_out}

            if not self.silent:
                self._print_tool_result(tool_event)

            tool_result_text = format_browse_result(result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_text,
                }
            )

        return True

    # -- helpers -------------------------------------------------------------

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
        print(f"BROWSER TASK: {self.session.task_description}")
        print(
            f"Provider: {self.session.provider}, Model: {self.session.model or 'default'}"
        )
        print(f"Workdir: {self.session.workdir}")
        print(f"CDP Port: {self.cdp_port}")
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
                action = tc.arguments.get("action", "")
                args = tc.arguments.get("args", [])
                args_str = " ".join(str(a) for a in args) if isinstance(args, list) else str(args)
                print(f"  - browse {action} {args_str}")
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
