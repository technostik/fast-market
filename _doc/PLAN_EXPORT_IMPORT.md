# Skill Run Export/Import Feature

## Overview

The `skill run` command now supports exporting and importing execution plans in YAML format, allowing you to:
1. **Export** the planned skill execution as a user-readable YAML file
2. **Export** the actual execution log as a YAML file
3. **Import** a pre-defined skill execution plan instead of relying on the router's auto-planning
4. **Inject** custom instructions into each skill step

## CLI Options

### `--export` / `-e`
Export the execution plan and log to YAML files.

```bash
skill run "Create marketing content for my video" --export plan.yaml
```

This creates two files:
- `plan.yaml` - The planned skill execution sequence
- `plan.execution.yaml` - The actual execution log with results

Use `--export -` to export to stdout instead of a file.

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
  description: "Review the generated content and make improvements"
  instructions: |
    Focus on engagement metrics
    Ensure brand voice consistency
```

**Fields:**
- `description`: Task description for the agent
- `instructions`: Additional instructions for the task

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

## Usage Examples

### Example 1: Export a Plan for Review

Run the router and export the plan to review before executing:

```bash
skill run "Create a blog post from my video" \
  --export blog-plan.yaml \
  --verbose
```

Review the plan, then you can modify it and re-import:

```bash
# Edit the plan
nano blog-plan.yaml

# Execute the modified plan
skill run "Execute modified plan" \
  --import blog-plan.yaml \
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

## Troubleshooting

### Plan Import Fails
- Ensure the YAML file has a valid `goal` field
- Check that all steps have valid `action` values (run, task, or ask)
- Verify the file path exists and is readable

### Inject Not Working
- Confirm the skill is a prompt-mode skill (has body in SKILL.md)
- Check inject syntax in the YAML (use `|` for multi-line strings)
- Verify the skill supports the `--inject` parameter

### Execution Log Empty
- The router may not have executed any steps yet
- Check if the router completed successfully
- Verify `--export` option is specified correctly

## Files Modified

- `skill-cli/commands/run/register.py` - Added CLI options
- `skill-cli/core/router.py` - Added export/import logic and data structures
- `tests/test_12_plan_export_import.py` - Unit tests for export/import
- `tests/test_08_skill_router.py` - Integration tests for export/import
