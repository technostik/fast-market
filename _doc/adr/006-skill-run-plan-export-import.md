# ADR 006: Skill Run Plan Export/Import Architecture

## Status: Implemented

The `skill run` command now supports exporting planned skill sequences, importing pre-defined plans, and injecting custom instructions into each skill step via YAML files.

### Problem

The original `skill run` router was a black-box orchestrator:
- Router dynamically planned each step using LLM calls
- No visibility into what the router intended to do
- No way to pre-define a skill execution sequence
- No mechanism to customize skill behavior per step without editing skill files
- Users couldn't review, edit, or reuse execution plans

This made the router inflexible for:
- Reproducible workflows
- Plan review before execution
- Sharing skill sequences between team members
- Fine-tuning skill behavior with custom instructions

### Solution

Added three new capabilities to the `skill run` command:

#### 1. Export (`--export` / `-e`)
Export both the planned skill sequence and actual execution log to YAML files:

```bash
skill run "Create marketing content" --export plan.yaml
```

Produces:
- `plan.yaml` - The planned skill execution sequence
- `plan.execution.yaml` - The actual execution results

#### 2. Import (`--import`)
Import a pre-defined YAML plan instead of relying on auto-planning:

```bash
skill run "Execute workflow" --import my-plan.yaml
```

The router follows the imported plan step-by-step.

#### 3. Inject Instructions
Each step in a plan can include custom instructions that are appended to the skill's prompt:

```yaml
- step: 1
  action: run
  skill: content-generator
  params:
    topic: "marketing"
  inject: |
    Use an enthusiastic tone
    Include call-to-action
```

### Architecture Changes

#### Data Structures Added

**`SkillPlanStep`**: Represents a single step in an execution plan
```python
@dataclass
class SkillPlanStep:
    step: int
    action: str  # "run", "task", "ask"
    skill_name: str = ""
    params: dict[str, str] = None
    inject: str = ""  # Injected instructions
    description: str = ""  # For task action
    instructions: str = ""  # For task action
    question: str = ""  # For ask action
    context_hint: str = ""
```

**`SkillPlan`**: Complete execution plan
```python
@dataclass
class SkillPlan:
    goal: str
    steps: list[SkillPlanStep] = None
    success_criteria: str = ""
    preparation_plan: str = ""
```

**`SkillExecutionLog`**: Execution results
```python
@dataclass
class SkillExecutionLog:
    goal: str
    attempts: list[dict] = None
    start_time: str = ""
    end_time: str = ""
    status: str = ""
    final_result: str = ""
    failure_reason: str = ""
```

#### RouterState Extensions

Added fields to track import/export state:
```python
@dataclass
class RouterState:
    # ... existing fields ...
    imported_plan: SkillPlan | None = None
    exported_plan_path: Path | None = None
    export_execution_path: Path | None = None
```

#### New Functions

**YAML Conversion:**
- `_plan_to_yaml(plan: SkillPlan) -> str` - Convert plan to YAML
- `_execution_log_to_yaml(state: RouterState) -> str` - Convert execution log to YAML

**Export Functions:**
- `_export_plan_to_file(plan: SkillPlan, filepath: str) -> None` - Export plan
- `_export_execution_log(state: RouterState, filepath: str) -> None` - Export log

**Import Function:**
- `_import_plan_from_yaml(filepath: str, workdir: str) -> SkillPlan` - Load plan from YAML

#### Modified Functions

**`_run_skill()`**: Added `inject` parameter
```python
def _run_skill(
    # ... existing params ...
    inject: str | None = None,
) -> tuple[int, str, Path | None]:
```

Passes inject to `execute_skill_prompt()` for prompt-mode skills.

**`run_router()`**: Added export/import parameters
```python
def run_router(
    # ... existing params ...
    export_plan_path: str | None = None,
    import_plan_path: str | None = None,
) -> RouterState:
```

#### Router Loop Modifications

**Import Mode:**
When `import_plan_path` is provided:
1. Load plan from YAML file
2. Store in `state.imported_plan`
3. During planning loop, use imported steps instead of calling `_call_plan()`
4. Execute each step with specified parameters and inject instructions

**Export Mode:**
During execution:
1. Track each planned step in `planned_steps` list
2. After execution completes, build `SkillPlan` object
3. Export plan to YAML file
4. Export execution log to `.execution.yaml` file

### YAML Format

#### Plan File Structure

```yaml
goal: "Create marketing content for my video"
success_criteria: "Marketing content created and optimized"
preparation_plan: "Router's preparation plan..."
plan:
  - step: 1
    action: run
    skill: youtube-extract
    params:
      url: "https://youtube.com/watch?v=example"
    inject: |
      Focus on extracting trending keywords and topics
    context_hint: "Extracted keywords for content generation"
    
  - step: 2
    action: run
    skill: content-generator
    params:
      topic: "keywords from step 1"
    inject: |
      Use an enthusiastic tone
      Include call-to-action
    context_hint: "Generated content for review"
    
  - step: 3
    action: task
    description: "Review and polish the content"
    instructions: |
      Check for grammar, flow, and engagement
      Ensure brand voice consistency
    
  - step: 4
    action: ask
    question: "Does this content meet your expectations?"
```

#### Execution Log Structure

```yaml
goal: "Create marketing content for my video"
status: completed  # or "failed" or "max_iterations"
final_result: "Content successfully created"
preparation: "Router's preparation plan..."
success_criteria: "Marketing content created"
total_steps: 3
execution:
  - step: 1
    action: run
    skill: youtube-extract
    params:
      url: "https://youtube.com/watch?v=example"
    success: true
    exit_code: 0
    summary: "Successfully extracted keywords from video"
    output_preview: "Keywords: marketing, content, video..."
```

### Decision Rationale

#### Why YAML?
- **Human-readable**: Users can easily review and edit plans
- **Machine-parseable**: Easy to load and validate programmatically
- **Standard format**: Widely supported, well-documented
- **Flexible**: Supports complex nested structures (params, inject, instructions)
- **Version-controllable**: Plans can be committed to git

#### Why Two Files (plan + execution log)?
- **Separation of concerns**: Plan is intent, execution log is reality
- **Reusability**: Same plan can be executed multiple times with different results
- **Debugging**: Compare planned vs actual to identify issues
- **Audit trail**: Keep execution history while preserving original plan

#### Why Inject Only for Prompt-Mode Skills?
- Script and run-mode skills don't have a prompt body to append to
- Inject appends `## Additional Instructions` section to skill body
- This is consistent with `skill apply --inject` behavior
- Future enhancement could support script injection via environment variables

#### Why Track Steps During Execution?
- Router plans dynamically, so the full plan isn't known upfront
- By tracking each step as it's planned, we capture the actual sequence
- This allows exporting what was actually planned, not just what was imported
- Supports both imported plans and dynamically generated plans

### Impact

#### Benefits
1. **Visibility**: Users can see what the router plans to do
2. **Reproducibility**: Plans can be saved, shared, and re-executed
3. **Customization**: Inject instructions allow per-step customization
4. **Flexibility**: Import mode enables pre-defined workflows
5. **Review**: Plans can be reviewed and edited before execution
6. **Debugging**: Execution logs help understand what happened

#### Backward Compatibility
- All changes are additive
- Existing `skill run` usage works unchanged
- Export/import are optional features
- No breaking changes to router API

#### Performance
- Minimal overhead: YAML serialization is fast
- Export happens only when requested
- Import replaces LLM planning (faster)

### Limitations

1. **Inject only works for prompt-mode skills**: Script and run-mode skills don't support injection
2. **Import mode requires valid plan format**: Invalid YAML or missing fields cause errors
3. **No plan validation before execution**: Router validates steps during execution, not upfront
4. **Execution log truncates output**: Raw output limited to 500 chars for readability

### Testing

Added comprehensive test coverage:
- **Unit tests** (`tests/test_12_plan_export_import.py`): 7 tests covering import/export functions
- **Integration tests** (`tests/test_08_skill_router.py`): 3 tests covering router behavior
- All tests passing (9/9)

### Files Modified

- `skill-cli/commands/run/register.py` - CLI options
- `skill-cli/core/router.py` - Data structures, functions, router logic
- `tests/test_12_plan_export_import.py` - Unit tests (new file)
- `tests/test_08_skill_router.py` - Integration tests (extended)
- `_doc/PLAN_EXPORT_IMPORT.md` - User documentation (new file)
- `_doc/adr/006-skill-run-plan-export-import.md` - This ADR (new file)

### Future Enhancements

1. **Plan validation**: Validate imported plans before execution
2. **Plan templates**: Provide template library for common workflows
3. **Conditional steps**: Support if/else logic in plans
4. **Loop/retry**: Add retry logic to plan steps
5. **Script injection**: Support inject for script-mode skills via environment variables
6. **Plan diff**: Compare two plans to see differences
7. **Plan visualization**: Generate visual workflow diagrams from YAML

### Migration Guide

**No migration needed** - all changes are backward compatible.

To use new features:

```bash
# Export plans from existing workflows
skill run "Your task" --export workflow.yaml

# Create custom plans manually
# See _doc/PLAN_EXPORT_IMPORT.md for format

# Import and execute plans
skill run "Execute plan" --import workflow.yaml
```
