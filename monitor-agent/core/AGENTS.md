# core/

## 🎯 Purpose
Provides the foundational infrastructure for rule-based content monitoring: data models, rule evaluation, action execution, persistence, DSL parsing, and scheduling.

## 🏗️ Essential Components
- `models.py` — Dataclasses: Source, Action, Rule, ItemMetadata, TriggerLog
- `rule_engine.py` — Recursive rule evaluator with AND/OR condition groups
- `rule_parser.py` — DSL condition string parser (RuleParser class)
- `rule_formatter.py` — DSL formatter (RuleFormatter class)
- `executor.py` — Shell command execution with placeholder substitution
- `storage.py` — SQLite persistence layer (MonitorStorage class)
- `scheduler.py` — XDG path utilities
- `time_scheduler.py` — Cron/interval schedule logic

## 📋 Core Responsibilities
- Define data contracts between components
- Evaluate rules against item metadata
- Parse and format DSL condition strings
- Execute shell actions with proper placeholder handling
- Persist configuration and trigger history
- Manage time-based rule scheduling

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths`, `common.cli.helpers`
- Used by: `commands/*`, `plugins/*`
- External deps: `sqlite3` (stdlib), `croniter`, `pytz`, `click`

## ✅ Do's
- Use `dataclasses` with `slots=True` for memory efficiency
- Validate all inputs before processing (FAIL LOUDLY)
- Log errors with context before re-raising
- Use `datetime` with timezone (`datetime.now(timezone.utc)`)
- Return structured data for observability

## ❌ Don'ts
- Don't add business logic to models (keep them as data)
- Don't swallow exceptions — let them propagate
- Don't use naive datetime — always use timezone-aware
- Don't hardcode paths — use `scheduler.py` utilities

## 🛠️ Extension Points

### Add New Model
1. Add dataclass to `models.py` with `slots=True`
2. Add corresponding table in `storage.py`
3. Add CRUD methods to `MonitorStorage`
4. Add migration-safe ALTER TABLE
5. Add tests for all operations

### Add New Rule Operator
1. Update `_evaluate_single_condition()` in `rule_engine.py`
2. Handle the operator in the conditional chain
3. Raise `ValueError` for unknown operators
4. Update `rule_parser.py` tokenizer to recognize new operator
5. Add tests for edge cases

### Add DSL Parser Feature
1. Update `rule_parser.py` tokenizer for new syntax
2. Update `_parse_*` methods to handle new grammar
3. Update `rule_formatter.py` to format new syntax
4. Add round-trip tests (parse → format → parse)

### Add Schedule Type
1. Update `time_scheduler.py` with new trigger logic
2. Add `validate_*` function for new format
3. Update `should_run_rule()` to handle new type
4. Add tests for scheduling edge cases

### Add New Placeholder
1. Add to `placeholders` dict in `executor.py`
2. Use uppercase with underscores (`EXTRA_FIELD_NAME`)
3. Handle None values gracefully
4. Add tests for the new placeholder

### Add Source URL Helper
1. Update `_get_source_url()` in `executor.py`
2. Handle plugin-specific URL construction
3. Return proper URLs for each plugin type (e.g., YouTube channel URLs)

## DSL Condition Format

### Supported Operators
- `==`, `!=`, `>`, `<`, `>=`, `<=` — Comparison
- `contains` — List/string membership
- `matches` — Regex matching

### Logical Operators
- `and` — All conditions must match (implicit grouping)
- `or` — Any condition can match
- `()` — Explicit grouping for precedence

### Example Usage
```python
from core.rule_parser import RuleParser, RuleParseError
from core.rule_formatter import RuleFormatter

# Parse DSL string
parser = RuleParser()
conditions = parser.parse("content_type == 'video' and duration > 600")

# Format back to DSL
formatter = RuleFormatter()
dsl_string = formatter.format(conditions)
```

## Time-Based Scheduling

### Schedule Types
- **Cron**: `{"cron": "0 * * * *"}` — At specific times
- **Interval**: `{"interval": "1h"}` — After elapsed time

### Usage
```python
from core.time_scheduler import should_run_rule, get_next_run_time

# Check if rule should run
if should_run_rule(rule):
    # Rule schedule allows execution

# Get next scheduled run
next_run = get_next_run_time(rule)
```

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `core/models.py` for data contracts
- See `core/rule_engine.py` for condition evaluation
- See `core/rule_parser.py` for DSL parsing
- See `core/time_scheduler.py` for scheduling logic
