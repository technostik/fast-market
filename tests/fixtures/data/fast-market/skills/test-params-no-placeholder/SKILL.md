---
name: test-params-no-placeholder
description: Prompt-mode skill with parameters but no placeholders in body. Used to test parameter injection.
parameters:
  - name: expected_value
    description: A value the LLM must echo back
    required: true
---
# test-params-no-placeholder

## Instructions
Echo back the value of expected_value parameter to stdout using the echo command.
Then stop.
