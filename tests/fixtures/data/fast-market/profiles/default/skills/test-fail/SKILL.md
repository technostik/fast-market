---
name: test-fail
description: Always fails with exit code 1. Used for testing error handling and retry logic.
parameters:
  - name: reason
    description: The failure reason to print
    required: false
    default: "deliberate failure"
---
# test-fail

## Instructions
This skill always fails. Used to test retry and error handling.
