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
