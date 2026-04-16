# Skill Run Export/Import and Plan Management

## Overview

The `skill run` and `skill plan` commands support a full lifecycle for plan management:
1. **List** existing run plans
2. **Export** the planned skill execution as a user-readable YAML file
3. **Export** the actual execution log as a YAML file
4. **Import** a pre-defined skill execution plan instead of relying on the router's auto-planning
5. **Inject** custom instructions into each skill step
6. **Edit** plans interactively or with LLM assistance
7. **Parameterize** plans with placeholders for reuse

## Plan Commands

### `skill plan list`

List all `run.yaml` files in the workdir (from common config).

```bash
skill plan list                  # text format
skill plan list --format json    # machine-readable
skill plan list --show-params    # show placeholders
```

### `skill plan params <plan>`

Show all `{{placeholders}}` and their defaults for a specific plan.

```bash
skill plan params my-plan/run.yaml
```

Output:
```
Plan: /workdir/my-plan/run.yaml
Goal: Promote my video {{video_url}}

Parameters:
  video_url  [required]
  count      [optional] (default: 5)
  keywords   [optional] (default: marketing,tech)
```

### `skill plan edit <plan>`

Interactive wizard to edit a plan's steps:

- **[S]how** — detailed view of a step
- **[E]dit** — open step YAML in your editor
- **[D]elete** — remove a step
- **[M]ove** — reorder a step
- **[A]dd** — add a new step (run/task/ask)
- **[C]hange step (LLM)** — discuss with LLM to modify a single step
- **[P]lan change (LLM)** — discuss with LLM to modify the entire plan
- **[L]earn.md** — edit LEARN.md of the auto-skill for a named task
- **[K]ill** — edit SKILL.md of the auto-skill for a named task
- **[Q]uit** — save and exit

### Plan YAML Format

```yaml
goal: "Analyze and promote a video"
success_criteria: "At least 5 replies generated"
plan:
  - step: 1
    action: run
    skill: my-analyse
    params:
      url: "{{video_url}}"
    context_hint: "Analysis result for {{video_url}}"
  - step: 2
    action: task
    name: find-videos
    description: "Search for videos about the same topic"
    instructions: "Find at least 5 related videos"
    context_hint: "List of related video URLs"
  - step: 3
    action: ask
    question: "Which videos should we prioritize?"
```

**Step types:**
- `run` — executes a skill. Fields: `skill`, `params`, `inject`, `context_hint`
- `task` — free-form LLM task. Fields: `description`, `instructions`, `name` (for auto-skill), `context_hint`
- `ask` — prompt the user. Fields: `question`

## `skill run` Command

### Import/Export

### `--export` / `-e`
Export the execution plan and log to YAML files.

```bash
skill run "Create marketing content for my video" --export plan.yaml
```

**Export location:**
- With `--run-isolated` or `--skill-isolated`: Files are placed in the isolated run directory (e.g., `{workdir_prefix}abc123/plan.yaml` where prefix is from common config, defaults to `skill_run_`)
- Without isolation: Files are placed in the workdir
- With absolute path: Files are placed at the specified absolute location
- Use `--export -` to export to stdout instead of a file

This creates two files:
- `plan.yaml` - The planned skill execution sequence
- `plan.execution.yaml` - The actual execution log with results

### `--import`
Import a pre-defined skill execution plan from a YAML file.

```bash
skill run "Execute my plan" --import my-plan.yaml
```

The router will follow the imported plan step-by-step instead of auto-planning.

## YAML Plan Format

### Structure

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

### Step Types

#### 1. `run` - Execute a Skill
Runs a specific skill with parameters and optional injected instructions.

```yaml
- step: 1
  action: run
  skill: skill-name
  params:
    param1: value1
    param2: value2
  inject: |
    Additional instructions for this skill
  context_hint: "Hint about what context the next step will need"
```

**Fields:**
- `skill`: Name of the skill to execute
- `params`: Key-value parameters to pass to the skill
- `inject`: Additional instructions appended to the skill's prompt (only for prompt-mode skills)
- `context_hint`: Hint about what context this step will provide to the next step

#### 2. `task` - Free-form Task
Executes a free-form CLI task description.

```yaml
- step: 2
  action: task
  name: find-videos          # optional: used by plan convert-task-to-skill
  description: "Review the generated content and make improvements"
  instructions: |
    Focus on engagement metrics
    Ensure brand voice consistency
```

**Fields:**
- `name`: (optional) Task name — used by `plan convert-task-to-skill` to create skill `auto-{name}`
- `description`: Task description for the agent
- `instructions`: Additional instructions for the task
- `context_hint`: Hint for context extraction

#### 3. `ask` - User Interaction
Asks the user a question during execution.

```yaml
- step: 3
  action: ask
  question: "Which option do you prefer: A or B?"
```

**Fields:**
- `question`: Question to ask the user

## Execution Log Format

The execution log (`.execution.yaml`) records what actually happened:

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
    
  - step: 2
    action: run
    skill: content-generator
    params:
      topic: "marketing"
    success: true
    exit_code: 0
    summary: "Generated marketing content"
    output_preview: "Generated content..."
```

## Plan Parameterization

Plans can be made reusable with `{{placeholders}}` that are substituted at import time.

### Syntax

- `{{key}}` — **mandatory** parameter, fails if not provided
- `{{key:default}}` — **optional** parameter with default value

```yaml
goal: "Promote {{video_url}}"
plan:
  - step: 1
    action: run
    skill: my-analyse
    params:
      url: "{{video_url}}"
  - step: 2
    action: run
    skill: find_videos
    params:
      keywords: "{{keywords:marketing,tech}}"
      count: "{{count:5}}"
```

### Usage

```bash
# Provide mandatory params, use defaults for the rest
skill run "promote" --import plan.yaml -p video_url=https://youtube.com/abc

# Override defaults
skill run "promote" --import plan.yaml \
  -p video_url=https://youtube.com/abc \
  -p keywords=AI,ML \
  -p count=10

# Fails if mandatory param not provided
# Error: Unresolved mandatory placeholders in plan: video_url
```

### Inspect Plan Parameters

```bash
skill plan params plan.yaml           # show params for a specific plan
skill plan list --show-params         # show params when listing
```

## Interactive Mode (`--interactive` / `-I`)

Pause before each step for user approval:

```bash
skill run "promote my video" --interactive
```

At each step you can:
- **[A]ccept** — execute as planned
- **[S]kip** — mark as success without executing
- **[E]dit** — modify the step in your editor before running
- **[R]eplan** — ask the LLM for an alternative approach
- **[Q]uit** — stop and export what succeeded

Export successful steps:
```bash
skill run "promote" --interactive --export-successful good-plan.yaml
```

## Auto-Skills (`plan convert-task-to-skill`)

Named tasks (with `name` field) can be converted to persistent auto-skills using:

```bash
skill plan convert-task-to-skill run.yaml             # Create skills, print new plan
skill plan convert-task-to-skill run.yaml > new.yaml  # Save new plan to file
skill plan convert-task-to-skill run.yaml --reset     # Force recreate skills
```

Given a plan with named tasks:
```yaml
plan:
  - step: 2
    action: task
    name: find-related-videos
    description: "Search YouTube for {{query}} related to {{topic}}..."
```

The subcommand:
1. Creates skill `auto-find-related-videos` with parameters `query` and `topic` extracted from `{{placeholders}}`
2. Generates a one-sentence description via LLM
3. Converts `{{key:default}}` to `{key}` in the skill body for runtime substitution
4. Outputs a new plan with `run` steps referencing the auto-skills:

```yaml
plan:
  - step: 1
    action: run
    skill: some-existing-skill
    params:
      url: "{{video_url}}"
  - step: 2
    action: run
    skill: auto-find-related-videos
    params:
      query: "{{query}}"
      topic: "{{topic}}"
```

Run the new plan with:
```bash
skill run "promote" --import new.yaml -p query=cats -p topic=animals
```

### Edit Auto-Skills

In `skill plan edit`, for named task steps:
- **[L]earn.md** — opens `LEARN.md` of the auto-skill in your editor
- **[K]ill** — opens `SKILL.md` of the auto-skill in your editor

Auto-skill names are shown in the step list:
```
  [2] TASK
      Auto-skill: auto-find-related-videos
      Search YouTube for related videos...
```

## Usage Examples

### Example 1: Export a Plan for Review

Run the router and export the plan to review before executing:

```bash
skill run "Create a blog post from my video" \
  --export blog-plan.yaml \
  --verbose
```

**With isolation modes:**
```bash
# Files go into isolated run directory
skill run "Create a blog post" \
  --run-isolated \
  --export blog-plan.yaml

# You'll find files at:
# workdir/skill_run_abc123/blog-plan.yaml
# workdir/skill_run_abc123/blog-plan.execution.yaml
```

Review the plan, then you can modify it and re-import:

```bash
# Edit the plan
nano workdir/skill_run_abc123/blog-plan.yaml

# Execute the modified plan
skill run "Execute modified plan" \
  --import workdir/skill_run_abc123/blog-plan.yaml \
  --export final-plan.yaml
```

### Example 2: Create a Reusable Plan

Create a plan file manually:

```yaml
# my-workflow.yaml
goal: "Process video content"
plan:
  - step: 1
    action: run
    skill: youtube-extract
    params:
      url: "https://youtube.com/watch?v=VIDEO_ID"
    inject: |
      Extract transcript and key topics
      
  - step: 2
    action: run
    skill: content-generator
    params:
      topic: "extracted topics"
    inject: |
      Generate a blog post outline
      
  - step: 3
    action: task
    description: "Format the blog post with proper markdown"
```

Execute it:

```bash
skill run "Process video" --import my-workflow.yaml
```

### Example 3: Export to Stdout for Piping

```bash
skill run "Quick task" --export - | grep "skill:"
```

## Implementation Details

### How Inject Works

The `inject` field appends custom instructions to the skill's prompt during execution. This is particularly useful for:

- Modifying skill behavior without editing the skill file
- Adding context-specific instructions
- Providing examples or constraints

**Note:** Inject only works for prompt-mode skills (skills with a body in SKILL.md). Script and run-mode skills do not use this mechanism.

### Plan Execution Flow

1. Router loads the imported plan
2. For each step in the plan:
   - Execute the skill/task with specified parameters
   - Pass inject instructions to prompt skills
   - Record the execution results
3. Export the execution log with actual results

### Plan Creation Flow

1. Router performs preparation phase
2. Router enters planning loop
3. For each iteration:
   - Planner decides next action (or uses imported plan)
   - Step is recorded in the plan
   - Skill/task is executed
   - Results are logged
4. Export both plan and execution log

## Best Practices

1. **Review exported plans** before importing them to ensure they're correct
2. **Use inject** to customize skill behavior without modifying skill files
3. **Keep plans modular** - create separate plan files for different workflows
4. **Test with small plans** before creating complex multi-step workflows
5. **Use context hints** to help the planner understand data flow between steps
6. **Parameterize reusable plans** with `{{placeholders}}` and defaults
7. **Use `plan convert-task-to-skill`** to create auto-skills for named tasks
8. **Use `--interactive`** for critical workflows where you want to approve each step

## Troubleshooting

### Plan Import Fails
- Ensure the YAML file has a valid `goal` field
- Check that all steps have valid `action` values (run, task, or ask)
- Verify the file path exists and is readable

### Unresolved Placeholders
- Provide all mandatory parameters with `-p key=value`
- Check for typos in placeholder names (`{{key}}` vs `{{keys}}`)
- Use `skill plan params <plan>` to see what's required

### Inject Not Working
- Confirm the skill is a prompt-mode skill (has body in SKILL.md)
- Check inject syntax in the YAML (use `|` for multi-line strings)
- Verify the skill supports the `--inject` parameter

### Execution Log Empty
- The router may not have executed any steps yet
- Check if the router completed successfully
- Verify `--export` option is specified correctly

### Auto-Skill Not Created
- Ensure the task has a `name` field
- Run `skill plan convert-task-to-skill <plan>` to create auto-skills
- Check LLM provider is configured for skill extraction

## Files Modified

- `skill-cli/commands/run/register.py` - CLI options (`--interactive`, `--param`, `--export-successful`)
- `skill-cli/commands/run-plan/register.py` - Plan management commands (`list`, `edit`, `params`, `convert-task-to-skill`)
- `skill-cli/commands/params.py` - `RunPlanFileType` for TAB completion
- `skill-cli/core/router.py` - Export/import logic, placeholder substitution, interactive approval
- `skill-cli/core/repl.py` - Interactive prompt utilities
- `common/cli/helpers.py` - Editor integration
