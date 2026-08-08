# operations/

## 🎯 Purpose
LLM-backed field-filling operations. Each operation computes a value for one
declared soft field (e.g. `summary`, `tags`) from a document dict and returns
it to the sync engine, which persists it via `set_document_field`.

## Architecture
- `base.py` — `Operation` ABC + `OperationManifest`
- `summarize/` — `summarize` operation → fills the `summary` field
- `tag/` — `tag` operation → fills the `tags` field (JSON array of strings)

## Adding an Operation
1. Create `operations/<name>/` with `__init__.py` and `register.py`.
2. `register(config) -> OperationManifest`:
   ```python
   OperationManifest(name="myname", operation_class=MyOp, field="myfield", applies_to="all")
   ```
3. `MyOp(Operation)` implements `run(doc) -> value`. Set `requires` to the
   document fields that must be present (absent → `MissingInputFieldError`).
4. Operations use `self.llm()` (default provider) or inject a provider for tests.

## Rules
- Operations are pure: they only compute a value, never write to the store.
- `requires` is enforced via `check_inputs()` (FAIL LOUDLY).
- Values are JSON-serializable (stored in `metadata_json`).
- `applies_to` must be `"all"` or a source plugin name.
- Field output must be declared via `corpus field create` before `sync --field`.

## Used by
- `commands/sync/register.py` — `corpus sync --field <name>` looks up the
  operation whose `field` matches, then calls `SyncEngine.sync_field()`.
