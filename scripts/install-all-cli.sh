#!/bin/bash

# Install all CLI tools in editable mode with all optional dependencies
# Detects all *-cli directories automatically

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Finding CLI directories in $PROJECT_ROOT ==="

# Find all *-cli directories
cli_dirs=()
while IFS= read -r -d '' dir; do
    cli_dirs+=("$dir")
done < <(find "$PROJECT_ROOT" -maxdepth 1 -type d -name '*-cli' -print0)

if [ ${#cli_dirs[@]} -eq 0 ]; then
    echo "No *-cli directories found!"
    exit 1
fi

echo "Found ${#cli_dirs[@]} CLI directories:"
for dir in "${cli_dirs[@]}"; do
    echo "  - $(basename "$dir")"
done
echo ""

# Install each CLI tool
for dir in "${cli_dirs[@]}"; do
    name=$(basename "$dir")
    echo "=== Installing $name ==="
    pip install -e "$dir[all]"
    echo ""
done

echo "=== All CLI tools installed! ==="