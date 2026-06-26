---
name: test-guess
description: Use the 'guess' CLI tool to process a string. The exact invocation is non-obvious and requires reading the help.
parameters:
  - name: input
    description: The string to process
    required: true
stop_condition: |
  - You executed the correct command and got a result
  - NOT just read the help, figured out the answer in your head, and returned it as text
  - The task is only complete when you execute the command and see its output
---
# test-guess

## Instructions

Use the `guess {input}` command to process the value of {input}.

**IMPORTANT**: If you get an error, IMMEDIATELY run `guess --help` to understand the correct syntax. Do NOT repeat the same failed command. Read the help output carefully and follow it exactly.
