# commands/apply

## Purpose
Execute prompts with placeholder substitution. Supports both saved prompts and direct prompt strings.

## Three Input Modes

### 1. Saved Prompt (database lookup)
```bash
prompt apply summarize text=@article.txt
```
- Looks up "summarize" in PromptStore
- Uses saved model/provider settings
- Falls through to direct mode if not found

### 2. Direct Prompt (inline string)
```bash
prompt apply "Explain {topic}" topic="quantum physics"
```
- Uses the literal string as prompt content
- Uses default provider and model settings
- No database lookup

### 3. Stdin Mode (piping/chaining)
```bash
echo "What is AI?" | prompt apply -
cat template.txt | prompt apply --stdin var=value
```
- Reads prompt from stdin
- Enables command chaining
- Uses default provider and model settings

## Decision Flow
1. If `--stdin` flag OR argument is `-`: read from stdin → direct mode
2. Else: try PromptStore lookup
3. If found: use saved prompt
4. If not found: treat as direct prompt

## Placeholder Resolution
Same for all modes:
- `key=value`: literal substitution
- `key=-`: read from stdin
- `key=@file.txt`: read from file

## Provider/Model Selection
Saved prompts:
- Provider: CLI option > saved > default
- Model: CLI option > saved > None
- Temperature: CLI option > saved > None
- Max tokens: CLI option > saved > None

Direct prompts:
- Provider: CLI option > default
- Model: CLI option > None
- Temperature: CLI option > None
- Max tokens: CLI option > None

## Execution Recording
All executions recorded with:
- Saved: actual prompt name
- Direct: `<direct>`
- Stdin: `<stdin>`

## Error Conditions (FAIL LOUDLY)
- Missing placeholder: ValueError with list of missing args
- Missing file: FileNotFoundError with path
- Missing provider: Exit with setup instructions
- No stdin when expected: Exit with clear message
- Invalid argument format: Exit with format example

## Dependencies
- `PromptStore`: for saved prompt lookup and execution recording
- `resolve_arguments`: for placeholder substitution
- `build_engine`: for provider initialization
- `get_default_provider`: for fallback provider

## Testing
See CHANGELOG.md for comprehensive test scenarios.
