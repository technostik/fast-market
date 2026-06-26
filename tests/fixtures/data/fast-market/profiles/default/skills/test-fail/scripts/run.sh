#!/usr/bin/env bash
echo "FAIL: ${SKILL_REASON:-deliberate failure}" >&2
exit 1
