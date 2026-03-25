---
name: test-chain-b
description: Second skill in a chain. Consumes output from test-chain-a.
parameters:
  - name: chain_input
    description: Output from test-chain-a
    required: true
---
# test-chain-b

## Instructions
Consume the chain_input and produce a final result.
