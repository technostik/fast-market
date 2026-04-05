"""LLM agent integration and unit tests.

Run this module with ``-x`` to stop on first failure and avoid wasting LLM calls.
Use ``--provider`` to isolate one provider (xai, openai-compatible, or ollama).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from common.agent.executor import CommandResult, execute_command
from common.agent.loop import TaskConfig, TaskLoop
from common.agent.prompts import (
    build_command_documentation,
    build_system_prompt,
    render_command_documentation,
)
from common.agent.session import Session, ToolCallEvent, Turn
from common.core.config import load_tool_config
from common.llm.base import LLMRequest, LazyLLMProvider
from common.llm.registry import discover_providers

pytestmark = pytest.mark.order  # keep declaration order

SUPPORTED_PROVIDERS = ["xai", "openai-compatible", "ollama"]


@pytest.fixture(scope="session", params=SUPPORTED_PROVIDERS)
def provider_name(request) -> str:
    return request.param


@pytest.fixture(scope="session")
def selected_providers(request) -> list[str]:
    raw = request.config.getoption("--provider")
    if not raw:
        return list(SUPPORTED_PROVIDERS)
    if raw not in SUPPORTED_PROVIDERS:
        raise pytest.UsageError(
            f"Unsupported provider '{raw}'. Use one of: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return [raw]


@pytest.fixture(scope="session")
def llm_config() -> dict:
    return load_tool_config("task")


@pytest.fixture(scope="session")
def provider_fixture(provider_name: str, llm_config: dict, selected_providers: list[str]):
    if provider_name not in selected_providers:
        pytest.skip(f"Provider '{provider_name}' not selected")

    providers = discover_providers(llm_config)
    if provider_name not in providers:
        pytest.skip(f"{provider_name} not configured")

    provider = providers[provider_name]
    provider._ensure_initialized()
    if provider._provider is None:
        pytest.skip(f"{provider_name} not available")
    return provider


@pytest.fixture
def echo_execute_fn(tmp_path: Path):
    allowed = {"echo", "ls", "cat", "touch"}

    def _fn(cmd: str) -> CommandResult:
        return execute_command(cmd, workdir=tmp_path, allowed=allowed, timeout=10)

    return _fn


@pytest.fixture
def make_task_loop(tmp_path: Path, llm_config: dict):
    def _factory(provider_name: str, max_iterations: int = 10) -> TaskLoop:
        config = TaskConfig(
            fastmarket_tools={},
            system_commands=["echo", "ls", "cat", "touch"],
            max_iterations=max_iterations,
        )
        return TaskLoop(
            config=config,
            workdir=tmp_path,
            provider=provider_name,
            model=None,
            silent=True,
            verbose=False,
        )

    return _factory


def _weather_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name",
                        }
                    },
                    "required": ["city"],
                },
            },
        }
    ]


def _maybe_skip_provider(provider_name: str, selected_providers: list[str]) -> None:
    if provider_name not in selected_providers:
        pytest.skip(f"Provider '{provider_name}' not selected")


# Group 1 — Config & Provider Bootstrap

def test_01_llm_config_has_providers(llm_config: dict):
    assert isinstance(llm_config, dict)

    if "providers" in llm_config:
        providers = llm_config["providers"]
    else:
        providers = llm_config.get("llm", {}).get("providers", {})

    assert isinstance(providers, dict)
    assert providers
    assert any(name in providers for name in SUPPORTED_PROVIDERS)


def test_02_discover_providers_returns_instances(llm_config: dict):

    providers = discover_providers(llm_config)
    assert isinstance(providers, dict)
    assert providers
    assert all(hasattr(provider, "complete") for provider in providers.values())


def test_03_provider_is_lazy_llm_provider(llm_config: dict):

    providers = discover_providers(llm_config)
    assert providers
    for provider in providers.values():
        assert isinstance(provider, LazyLLMProvider)


def test_04_missing_provider_key_leaves_others_intact(llm_config: dict):
    providers = discover_providers(llm_config)
    discovered_names = set(providers.keys())
    assert discovered_names

    removed = next(iter(discovered_names))
    config_copy = copy.deepcopy(llm_config)

    if "providers" in config_copy:
        config_copy["providers"].pop(removed, None)
    else:
        config_copy.setdefault("llm", {}).setdefault("providers", {}).pop(removed, None)

    updated = discover_providers(config_copy)
    remaining = discovered_names - {removed}
    assert remaining.issubset(set(updated.keys()))


# Group 2 — Raw LLM Round-Trip

@pytest.mark.slow
def test_05_simple_completion(provider_name, selected_providers, provider_fixture):
    _maybe_skip_provider(provider_name, selected_providers)

    request = LLMRequest(
        system="You are a test assistant.",
        prompt="Say the single word PONG and nothing else.",
        max_tokens=4096,
        temperature=0,
    )
    response = provider_fixture.complete(request)
    assert isinstance(response.content, str)
    assert response.content.strip()
    assert "PONG" in response.content.upper()


@pytest.mark.slow
def test_06_tool_call_returned(provider_name, selected_providers, provider_fixture):
    _maybe_skip_provider(provider_name, selected_providers)

    request = LLMRequest(
        system="You are a helpful assistant.",
        prompt="What is the weather in Paris? Use the get_weather tool.",
        tools=_weather_tools(),
        max_tokens=4096,
        temperature=0,
    )
    response = provider_fixture.complete(request)

    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    tool_call = response.tool_calls[0]
    assert tool_call.name == "get_weather"
    assert isinstance(tool_call.arguments, dict)
    lower_keys = {k.lower() for k in tool_call.arguments.keys()}
    assert "city" in lower_keys


@pytest.mark.slow
def test_07_tool_result_closes_loop(provider_name, selected_providers, provider_fixture):
    _maybe_skip_provider(provider_name, selected_providers)

    user_prompt = "What is the weather in Paris? Use the get_weather tool."
    initial = provider_fixture.complete(
        LLMRequest(
            system="You are a helpful assistant.",
            prompt=user_prompt,
            tools=_weather_tools(),
            max_tokens=4096,
            temperature=0,
        )
    )
    assert initial.tool_calls, "expected initial tool call"

    first_call = initial.tool_calls[0]
    assistant_message = {
        "role": "assistant",
        "content": initial.content,
        "tool_calls": [
            {
                "id": first_call.id,
                "function": {
                    "name": first_call.name,
                    "arguments": json.dumps(first_call.arguments),
                },
            }
        ],
    }

    messages = [
        {"role": "user", "content": user_prompt},
        assistant_message,
        {
            "role": "tool",
            "tool_call_id": first_call.id,
            "content": "Sunny, 22°C",
        },
    ]

    follow_up = provider_fixture.complete(
        LLMRequest(
            system="You are a helpful assistant.",
            messages=messages,
            tools=_weather_tools(),
            max_tokens=4096,
            temperature=0,
        )
    )

    assert follow_up.tool_calls in (None, [])
    assert isinstance(follow_up.content, str)
    assert follow_up.content.strip()


@pytest.mark.slow
def test_08_no_tool_call_when_not_needed(provider_name, selected_providers, provider_fixture):
    _maybe_skip_provider(provider_name, selected_providers)

    response = provider_fixture.complete(
        LLMRequest(
            system="You are a helpful assistant.",
            prompt="What is 2 + 2? Answer with just the number.",
            tools=_weather_tools(),
            max_tokens=4096,
            temperature=0,
        )
    )

    assert response.tool_calls in (None, [])


# Group 3 — Message History Fidelity

def test_09_tool_call_id_round_trip():
    tool_call = ToolCallEvent(tool_call_id="tc_123", tool_name="execute_command", arguments={"command": "echo hi"})
    turn = Turn(role="assistant", content="Calling tool", tool_calls=[tool_call])

    as_dict = turn.to_dict()
    assert as_dict["tool_calls"][0]["tool_call_id"] == "tc_123"

    session = Session(
        task_description="task",
        workdir="/tmp",
        provider="ollama",
        model="",
        max_iterations=3,
        turns=[turn],
    )
    round_trip = Session.from_dict(yaml.safe_load(session.to_yaml()))
    assert round_trip.turns[0].tool_calls[0].tool_call_id == "tc_123"


def test_10_session_yaml_round_trip():
    original_exit_code = 9
    session = Session(
        task_description="task",
        workdir="/tmp",
        provider="ollama",
        model="",
        max_iterations=5,
        end_reason="success",
        turns=[
            Turn(role="user", content="hello"),
            Turn(
                role="assistant",
                content="running",
                tool_calls=[
                    ToolCallEvent(
                        tool_call_id="tc_456",
                        tool_name="execute_command",
                        arguments={"command": "echo hello"},
                        stdout="hello\n",
                        stderr="warn",
                        exit_code=original_exit_code,
                    )
                ],
            ),
        ],
    )

    parsed = yaml.safe_load(session.to_yaml())
    session2 = Session.from_dict(parsed)

    assert session2.total_tool_calls == session.total_tool_calls
    assert session2.turns[1].tool_calls[0].exit_code == original_exit_code
    assert session2.end_reason == session.end_reason


def test_11_session_metrics_accuracy():
    session = Session(
        task_description="task",
        workdir="/tmp",
        provider="ollama",
        model="",
        max_iterations=5,
        turns=[
            Turn(
                role="assistant",
                tool_calls=[
                    ToolCallEvent("1", "execute_command", {"command": "echo a"}, exit_code=0),
                    ToolCallEvent("2", "execute_command", {"command": "bad"}, exit_code=1),
                    ToolCallEvent("3", "execute_command", {"command": "echo b"}, exit_code=0),
                ],
            )
        ],
    )

    assert session.error_count == 1
    assert session.guess_count == 1
    assert session.total_tool_calls == 3
    assert session.success_rate == pytest.approx(2 / 3, abs=0.01)


# Group 4 — Tool Documentation Construction

def test_12_build_command_documentation_keys():
    docs = build_command_documentation(
        fastmarket_tools_config={"corpus": {"description": "test", "commands": ["search"]}},
        system_commands=["echo", "ls"],
    )
    required = {
        "aliases",
        "fastmarket_tools",
        "fastmarket_tools_minimal",
        "fastmarket_tools_brief",
        "fastmarket_tools_commands",
        "system_commands",
        "system_commands_minimal",
    }
    assert required.issubset(docs.keys())


def test_13_fastmarket_tools_appear_in_docs():
    docs = build_command_documentation(
        fastmarket_tools_config={"mytool": {"description": "A cool tool", "commands": ["run", "list"]}},
        system_commands=[],
    )
    assert "mytool" in docs["fastmarket_tools"]
    assert "mytool" in docs["fastmarket_tools_minimal"]


def test_14_system_commands_appear_in_docs():
    docs = build_command_documentation(
        fastmarket_tools_config={},
        system_commands=["echo", "ls"],
    )
    assert "echo" in docs["system_commands"]
    assert "ls" in docs["system_commands"]
    assert "echo" in docs["system_commands_minimal"]
    assert "ls" in docs["system_commands_minimal"]


def test_15_render_command_documentation_no_unknown_placeholders():
    rendered = render_command_documentation(
        fastmarket_tools_config={},
        system_commands=["echo"],
    )
    assert isinstance(rendered, str)
    assert rendered.strip()
    assert "{" not in rendered


def test_16_build_system_prompt_completeness():
    prompt = build_system_prompt(
        task_description="Do X",
        fastmarket_tools_config={},
        system_commands=["echo"],
        workdir=Path("/tmp"),
    )
    assert "Do X" in prompt
    assert "echo" in prompt
    assert "/tmp" in prompt


def test_17_system_prompt_includes_task_params():
    prompt = build_system_prompt(
        task_description="Do X",
        fastmarket_tools_config={},
        system_commands=["echo"],
        workdir=Path("/tmp"),
        task_params={"my_key": "my_value"},
    )
    assert "my_key" in prompt
    assert "SKILL_MY_KEY" in prompt


# Group 5 — Executor Safety

def test_18_allowed_command_executes(tmp_path: Path):
    result = execute_command("echo hello", workdir=tmp_path, allowed={"echo"})
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_19_disallowed_command_blocked(tmp_path: Path):
    result = execute_command(
        "python3 -c 'pass'",
        workdir=tmp_path,
        allowed={"echo"},
    )
    assert result.exit_code == 126


def test_20_absolute_path_rejected(tmp_path: Path):
    result = execute_command("cat /etc/passwd", workdir=tmp_path, allowed={"cat"})
    assert result.exit_code == 126
    assert "absolute" in (result.stderr or "").lower()


def test_21_command_timeout(tmp_path: Path):
    result = execute_command("sleep 10", workdir=tmp_path, allowed={"sleep"}, timeout=1)
    assert result.timed_out is True
    assert result.exit_code == 124


def test_22_empty_command_blocked(tmp_path: Path):
    result = execute_command("", workdir=tmp_path, allowed={"echo"})
    assert result.exit_code == 126


# Group 6 — Agentic Loop Integration

@pytest.mark.slow
def test_23_loop_completes_echo_task(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    loop.run("Run the command 'echo hello_world' and tell me what you see.", execute_fn=echo_execute_fn)
    session = loop.session

    assert session is not None
    assert "success" in session.end_reason.lower()
    assert session.total_tool_calls >= 1

    tool_outputs = [tc.stdout for turn in session.turns for tc in turn.tool_calls]
    assert any("hello_world" in (out or "") for out in tool_outputs)


@pytest.mark.slow
def test_24_loop_requires_two_tool_calls(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    loop.run(
        "First run 'echo step_one', then run 'echo step_two'. Report both outputs.",
        execute_fn=echo_execute_fn,
    )
    assert loop.session is not None
    assert loop.session.total_tool_calls >= 2


@pytest.mark.slow
def test_25_loop_tool_result_fed_back(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    loop.run(
        "First run 'echo step_one', then run 'echo step_two'. Report both outputs.",
        execute_fn=echo_execute_fn,
    )
    session = loop.session
    assert session is not None

    assistant_idx = None
    for idx, turn in enumerate(session.turns):
        if turn.role == "assistant" and turn.tool_calls:
            assistant_idx = idx
            break
    assert assistant_idx is not None

    tool_call = session.turns[assistant_idx].tool_calls[0]
    assert tool_call.stdout.strip()


@pytest.mark.slow
def test_26_loop_respects_max_iterations(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name, max_iterations=2)
    loop.run("Keep running 'echo ping' in an infinite loop.", execute_fn=echo_execute_fn)

    assert loop.session is not None
    assert "round limit" in loop.session.end_reason.lower()


@pytest.mark.slow
def test_27_loop_failed_command_continues(provider_name, selected_providers, make_task_loop, tmp_path: Path):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    state = {"count": 0}

    def flaky_execute(cmd: str) -> CommandResult:
        state["count"] += 1
        if state["count"] == 1:
            return CommandResult(
                command="bad",
                stdout="",
                stderr="permission denied",
                exit_code=1,
            )
        return execute_command(
            cmd,
            workdir=tmp_path,
            allowed={"echo", "ls", "cat", "touch"},
            timeout=10,
        )

    loop.run("Run 'echo ok' and report.", execute_fn=flaky_execute)
    assert loop.session is not None
    assert loop.session.error_count >= 1
    assert loop.session.end_reason


@pytest.mark.slow
def test_28_loop_termination_signal_detected(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    loop.run("Run 'echo done', then say 'task complete'.", execute_fn=echo_execute_fn)

    assert loop.session is not None
    assert "success" in loop.session.end_reason.lower()
    assert "round limit" not in loop.session.end_reason.lower()


@pytest.mark.slow
def test_29_loop_session_structure_complete(provider_name, selected_providers, make_task_loop, echo_execute_fn):
    _maybe_skip_provider(provider_name, selected_providers)

    loop = make_task_loop(provider_name)
    loop.run("Run 'echo done', then finish.", execute_fn=echo_execute_fn)
    session = loop.session

    assert session is not None
    assert session.start_time is not None
    assert session.end_time is not None
    assert session.end_time >= session.start_time
    assert isinstance(session.end_reason, str)
    assert session.end_reason.strip()
    assert session.turns

    metrics = session.metrics_dict()
    for key in [
        "total_tool_calls",
        "error_count",
        "guess_count",
        "success_rate",
        "iterations_used",
    ]:
        assert key in metrics
        assert isinstance(metrics[key], (int, float))
        assert metrics[key] >= 0
