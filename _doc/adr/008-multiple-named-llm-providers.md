# ADR 008: Support Multiple Named LLM Providers

## Status
Accepted

## Context
The LLM configuration system only supported one instance per provider type (e.g., only one "openai-compatible" provider). Users wanted to configure multiple instances of the same provider type with different settings and arbitrary names, enabling better organization and flexibility in LLM usage.

## Decision
We will modify the LLM configuration format to allow named providers with a "type" field, supporting multiple instances of the same provider type.

### New Configuration Format
```yaml
default_provider: deepseek
providers:
  deepseek:
    type: openai-compatible
    model: deepseek-chat
    base_url: http://localhost:5005/v1
    api_key_env: NONE
  local-gpt:
    type: openai-compatible
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
```

### Key Changes
1. **Config Format**: Add "type" field to specify provider implementation, allow arbitrary provider names
2. **Registry Logic**: Detect "type" field and instantiate appropriate provider class
3. **Provider Instantiation**: Pass provider name to enable dynamic config lookup
4. **Backward Compatibility**: Maintain support for old format without "type" field
5. **Field Rename**: Change "default_model" to "model" for consistency

## Consequences

### Positive
- Users can configure multiple providers of the same type
- Arbitrary naming enables better organization
- Backward compatible with existing configs
- Cleaner config structure

### Negative
- Slight increase in config verbosity due to "type" field
- Migration required for existing configs (though backward compatible)

### Implementation Details
- Modified `LazyLLMProvider.__init__` to accept `provider_name`
- Updated all provider classes to use dynamic config lookup
- Changed `discover_providers()` to handle new format
- Updated documentation and examples

## Alternatives Considered
- Keep type as key but allow multiple configs per type (more complex)
- Use nested structure (less intuitive)

## References
- Implementation in `common/llm/`
- Updated config in `common/llm/config.yaml`
- Documentation in `common/llm/AGENTS.md`