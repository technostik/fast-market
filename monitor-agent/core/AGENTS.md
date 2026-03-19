# core/

## 🎯 Purpose
Provides the foundational infrastructure for rule-based content monitoring: data models, rule evaluation, action execution, and persistence.

## 🏗️ Essential Components
- `models.py` — Dataclasses: Source, Action, Rule, ItemMetadata, TriggerLog
- `rule_engine.py` — Recursive rule evaluator with AND/OR condition groups
- `executor.py` — Shell command execution with placeholder substitution
- `storage.py` — SQLite persistence layer (MonitorStorage class)
- `scheduler.py` — XDG-compliant path utilities

## 📋 Core Responsibilities
- Define data contracts between components
- Evaluate rules against item metadata
- Execute shell actions with proper placeholder handling
- Persist configuration and trigger history

## 🔗 Dependencies & Integration
- Imports from: `common.core.paths`, `common.cli.helpers`
- Used by: `commands/*`, `plugins/*`
- External deps: `sqlite3` (stdlib), `feedparser`, `click`

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
4. Add tests for all operations

### Add New Rule Operator
1. Update `_evaluate_single_condition()` in `rule_engine.py`
2. Handle the operator in the conditional chain
3. Raise `ValueError` for unknown operators
4. Add tests for edge cases

### Add New Placeholder
1. Add to `placeholders` dict in `executor.py`
2. Use uppercase with underscores (`EXTRA_FIELD_NAME`)
3. Handle None values gracefully
4. Add tests for the new placeholder

## 📚 Related Documentation
- See `AGENTS.md` (root) for system overview
- See `core/models.py` for data contracts
- See `core/rule_engine.py` for condition evaluation
