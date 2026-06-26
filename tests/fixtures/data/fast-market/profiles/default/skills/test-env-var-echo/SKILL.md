---
name: test-env-var-echo
description: Prompt-mode skill that tests $SKILL_XXX env var injection into shell commands
parameters:
  - name: secret_token
    description: A token value that must be accessed via $SKILL_SECRET_TOKEN
    required: true
---
# test-env-var-echo

## Instructions
Echo the value of the `secret_token` parameter to stdout.

**Important**: You must access the parameter using the environment variable `$SKILL_SECRET_TOKEN` in your shell command, not by reading it from the task description. For example: `echo $SKILL_SECRET_TOKEN`

Then stop.
