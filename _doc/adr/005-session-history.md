# ADR 005: Session History

## Status: Resolved

The `format_message_history()` text-based hack has been removed. The agentic loop now passes the native `messages` list directly to the LLM provider via `LLMRequest(messages=messages)`, preserving proper tool call and tool result structures.

### Before
- Entire conversation was flattened to a single text string
- Tool results were formatted as `[TOOL RESULT for {id}]\n{content}`
- LLM received everything as a single user prompt, not native messages

### After
- `messages` list is passed directly to providers
- Tool calls and results maintain their native OpenAI-style structure
- Anthropic provider converts messages to its native format (tool_result content blocks)
- All other providers (OpenAI, Ollama, OpenAI-compatible, Groq, XAI) accept the format natively


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
    
    
    
class TaskLoop:
    config: TaskConfig
            request = LLMRequest(
                prompt=format_message_history(messages),
                model=self.model,
                system=system_prompt,
                max_tokens=4096,


format_message_history kept as backward compatibility layer
