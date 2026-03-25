#!/usr/bin/env bash
set -euo pipefail
if [ -z "${SKILL_FILEPATH:-}" ]; then
  echo "Missing required parameter: filepath" >&2
  exit 2
fi
tr '[:upper:]' '[:lower:]' < "${SKILL_FILEPATH}" | tr -cs '[:alpha:]' '\n' | sort -u | wc -l | tr -d ' '
