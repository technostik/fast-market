---
name: test-echo
description: Echoes back its parameters. Used for testing skill execution.
parameters:
  - name: message
    description: The message to echo
    required: true
  - name: prefix
    description: Optional prefix
    required: false
    default: "ECHO"
---
# test-echo

## Instructions
Echo the message parameter back to stdout with the prefix.
