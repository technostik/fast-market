#!/usr/bin/env bash
# test-guess skill runner - executes the guess command with the provided input
set -euo pipefail

INPUT="${input:-}"
if [[ -z "$INPUT" ]]; then
    echo "Error: input parameter is required" >&2
    exit 1
fi

guess doit again "$INPUT"
