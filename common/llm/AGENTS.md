# LLM Provider Module

## Purpose
Provides a shared LLM provider abstraction for all fast-market agents. Enables centralized provider management with lazy initialization (API key validated on first use, not at import).

## Architecture

```
common/llm/
├── __init__.py         # empty
├── base.py             # Base classes: LLMProvider, LazyLLMProvider, LLMRequest, LLMResponse, ToolCall, PluginManifest
├── registry.py         # Provider discovery and instantiation
├── anthropic/          # Anthropic provider
│   ├── __init__.py
│   ├── provider.py    # AnthropicProvider class
│   └── register.py    # register(config) -> PluginManifest
├── openai/             # OpenAI provider
│   ├── __init__.py
│   ├── provider.py
│   └── register.py
├── openai_compatible/  # OpenAI-compatible provider (generic endpoints)
│   ├── __init__.py
│   ├── provider.py
│   └── register.py
└── ollama/             # Ollama local provider
    ├── __init__.py
    ├── provider.py
    └── register.py
```

## Usage

### Discovering Providers

```python
from common.core.config import load_tool_config
from common.llm.registry import discover_providers

config = load_tool_config("prompt")
providers = discover_providers(config)
# Returns {"provider_name": provider_instance}
```

### Getting Default Provider

```python
from common.llm.registry import get_default_provider_name

provider_name = get_default_provider_name(config)
```

### Using a Provider

```python
from common.llm.base import LLMRequest

request = LLMRequest(
    prompt="Your prompt here",
    model="claude-sonnet-4-20250514",
    temperature=0.3,
    max_tokens=4096,
)

response = provider.complete(request)
print(response.content)
```

## Adding a New Provider

1. Create a new directory under `common/llm/` (e.g., `common/llm/mistral/`)
2. Create `provider.py` with a class extending `LazyLLMProvider`
3. Create `register.py` with a `register(config) -> PluginManifest` function
4. Add the provider to `_PROVIDER_MODULES` in `registry.py`

Example provider structure:

```python
# common/llm/mistral/provider.py
from common.llm.base import LazyLLMProvider, LLMProvider, LLMRequest, LLMResponse

class MistralProvider(LazyLLMProvider):
    name = "mistral"
    
    def _initialize(self):
        # Initialize client, validate API key, etc.
        pass

class _RealMistralProvider(LLMProvider):
    # Implement complete() and list_models()
    pass
```

```python
# common/llm/mistral/register.py
from common.llm.base import PluginManifest
from common.llm.mistral.provider import MistralProvider

def register(config: dict) -> PluginManifest:
    return PluginManifest(name="mistral", provider_class=MistralProvider)
```

## Lazy Initialization

Providers use `LazyLLMProvider` base class which:
- Does not validate API keys at import time
- Initializes on first `complete()` or `list_models()` call
- Logs warnings if initialization fails (e.g., missing API key)
- Allows graceful degradation when some providers are unavailable

## Configuration

Providers are configured in `~/.config/fast-market/config.yaml`. You can have multiple instances of the same provider type with arbitrary names.

```yaml
default_provider: deepseek
providers:
  deepseek:
    type: openai-compatible
    model: deepseek-chat
    base_url: http://localhost:5005/v1
    api_key_env: NONE
    flatten_messages: yes
  local-llama:
    type: ollama
    model: llama3.2
    base_url: http://127.0.0.1:11434
  anthropic-main:
    type: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
```

For backward compatibility, the old format without "type" is still supported:

```yaml
llm:
  default_provider: anthropic
  providers:
    anthropic:
      model: claude-sonnet-4-20250514
      api_key_env: ANTHROPIC_API_KEY
```

## Do's
- Use `LazyLLMProvider` for new providers (handles missing API keys gracefully)
- Implement `list_models()` to return available models
- Use debug methods `_format_debug_request()` and `_format_debug_response()` for verbose output

## Don'ts
- Don't validate API keys at module import time (use lazy initialization)
- Don't write provider-specific logic in commands (keep in provider)
