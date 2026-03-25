#!/usr/bin/env bash
# Validates that a number equals the unique word count of a given file
# Usage: validate.sh <file> <claimed_count>
set -euo pipefail
actual=$(tr '[:upper:]' '[:lower:]' < "$1" | tr -cs '[:alpha:]' '\n' | sort -u | wc -l | tr -d ' ')
claimed=$(echo "$2" | tr -d ' ')
if [ "$actual" = "$claimed" ]; then
    echo "CORRECT"
    exit 0
else
    echo "WRONG: actual=$actual claimed=$claimed"
    exit 1
fi
