# common/llm

## 🎯 Purpose
Shared LLM provider abstraction for all fast-market agents. Enables centralized provider management with lazy initialization — API keys are validated on first use, not at import time.

## 🏗️ Architecture

```
common/llm/
├── base.py             # LLMProvider, LazyLLMProvider, LLMRequest, LLMResponse, ToolCall, PluginManifest
├── registry.py         # discover_providers(), get_default_provider_name()
├── recorder.py         # RecordingProvider — wraps any provider to record calls to a JSONL file
├── anthropic/          # Anthropic (Claude) provider
├── openai/             # OpenAI provider
├── openai_compatible/  # Generic OpenAI-compatible endpoint (DeepSeek, Cloudflare AI, etc.)
├── ollama/             # Local Ollama provider
├── groq/               # Groq cloud provider
└── xai/                # xAI (Grok) provider
```

Each provider subdirectory contains:
- `provider.py` — `LazyLLMProvider` subclass + inner `_RealProvider`
- `register.py` — `register(config) -> PluginManifest`

## 📋 Core Responsibilities
- Provide a uniform `LLMProvider.complete(LLMRequest) -> LLMResponse` interface
- Discover and instantiate all configured providers from config
- Fail gracefully when a provider's API key is missing (log warning, set `_provider = None`)
- Support tool calling via OpenAI-style function schemas

## 🔗 Dependencies & Integration
- Imports from: `common.core.config` (for config loading), `common.structlog`
- Used by: `common.agent.loop`, `prompt-cli`, any CLI that calls an LLM
- External deps: `anthropic`, `openai`, `requests` — only installed if the provider is used

## ✅ Do's
- Use `LazyLLMProvider` for new providers — it handles missing API keys without crashing at import
- Implement `list_models()` to return available models
- Use `_format_debug_request()` / `_format_debug_response()` from `base.py` for verbose output
- Use `RecordingProvider` to wrap any provider when recording sessions for testing

## ❌ Don'ts
- Don't validate API keys at module import time — use lazy initialization
- Don't write provider-specific logic in agent commands — keep it inside the provider class

## ⚠️ Pitfalls
- `discover_providers()` raises `ConfigError` if `config["providers"]` is empty. Always call `load_tool_config()` before `discover_providers()`.
- The config supports two formats: new top-level `providers:` key and old `llm.providers:` key. `registry.py` handles both, but mixing them in one file causes silent fallback.
- `xai` provider uses the OpenAI client pointed at `https://api.x.ai/v1` — it requires `openai` to be installed even though it's not an OpenAI account.

## Usage

### Discovering providers
```python
from common.core.config import load_tool_config
from common.llm.registry import discover_providers

config = load_tool_config("skill")
providers = discover_providers(config)   # {"anthropic": AnthropicProvider, ...}
```

### Making a request
```python
from common.llm.base import LLMRequest

request = LLMRequest(
    prompt="Your prompt here",
    model="claude-sonnet-4-20250514",
    temperature=0.3,
    max_tokens=4096,
)
response = providers["anthropic"].complete(request)
print(response.content)
```

### Recording calls (for tests)
```python
from common.llm.recorder import RecordingProvider
from pathlib import Path

wrapped = RecordingProvider(providers["anthropic"], Path("/tmp/session.jsonl"))
response = wrapped.complete(request)
# All calls written to /tmp/session.jsonl as JSONL
```

## Adding a New Provider

1. Create `common/llm/{name}/` with `provider.py` and `register.py`
2. `provider.py`: extend `LazyLLMProvider`, implement `_initialize()` and `_complete_raw()`
3. `register.py`: implement `register(config) -> PluginManifest`
4. Add `"{name}": "common.llm.{name}.register"` to `_PROVIDER_MODULES` in `registry.py`

## Configuration

New format (top-level, supports named instances with `type`):
```yaml
default_provider: deepseek
providers:
  deepseek:
    type: openai-compatible
    model: deepseek-chat
    base_url: http://localhost:5005/v1
    api_key_env: NONE
  local-llama:
    type: ollama
    model: llama3.2
    base_url: http://127.0.0.1:11434
  anthropic-main:
    type: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
  grok:
    type: xai
    model: grok-3-mini
    api_key_env: XAI_API_KEY
```

Old format (backward compatible):
```yaml
llm:
  default_provider: anthropic
  providers:
    anthropic:
      model: claude-sonnet-4-20250514
      api_key_env: ANTHROPIC_API_KEY
```

## 🧪 Tests
- Test files: `tests/` (project root)
- Run with: `pytest tests/`
- Key scenarios: provider initialization, graceful degradation on missing keys, tool call parsing

## 🔍 Observability
- Log level: set root logger to DEBUG
- Key log markers: `provider_registered`, `provider_registration_failed`, `xai_provider_initialized`

## 📚 Related Documentation
- See `README.md` for usage and CLI reference
- See `common/core/AGENTS.md` for config loading and path conventions
- See `_doc/adr/008-multiple-named-llm-providers.md` for the architecture decision
