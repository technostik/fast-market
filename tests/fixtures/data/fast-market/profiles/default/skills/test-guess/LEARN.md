# Lessons Learned for test-guess

## What Works
- `guess doit again <input_value>` — Successfully processes the value of an input variable by chaining the `doit` command with the `again` flag.

## What to Avoid
- Using commands directly as arguments (e.g., `guess baseline1`) — causes `unknown command` errors.
- Attempting to use `baseline1` directly as a command — causes `unknown command` errors.
- Incorrectly mixing arguments (e.g., `guess doit baseline1`) — causes `expected keyword` errors.

## Useful Commands for This Skill
- `guess --help` — Shows the available commands for the `guess` tool.
- `guess doit` — Executes the `doit` operation.
- `guess doit again <string>` — Processes the input value using the `doit` operation.

## Common Errors and Fixes
- Error: `unknown command 'baseline1'` → Fix: Check `guess --help` to understand the valid commands.
- Error: `expected keyword 'again', got 'baseline1'` → Fix: Use the correct syntax for chaining commands, specifically `guess doit again <value>`.
