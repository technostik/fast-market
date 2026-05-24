#!/bin/bash

# Install all CLI tools in editable mode with all optional dependencies.
# Detects all *-cli directories automatically.
#
# Usage: install-all-cli.sh [--exclude <dir>] [--exclude-dep <pkg>] ...
# Examples:
#   install-all-cli.sh --exclude image-cli
#   install-all-cli.sh --exclude-dep torch --exclude-dep nvidia

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse flags (all repeatable)
exclude_list=()
exclude_dep_list=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exclude)
            shift; exclude_list+=("$1"); shift ;;
        --exclude-dep)
            shift; exclude_dep_list+=("$1"); shift ;;
        -h|--help)
            echo "Usage: $0 [--exclude <dir>] [--exclude-dep <pkg>] ..."
            exit 0 ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--exclude <dir>] [--exclude-dep <pkg>] ..."
            exit 1 ;;
    esac
done

# Returns 0 (true) if the dir's pyproject.toml lists a dep matching any --exclude-dep pattern.
# Matching is prefix-based and case/underscore-insensitive, e.g. "nvidia" matches "nvidia-cublas-cu13".
has_excluded_dep() {
    local dir="$1"
    local pyproject="$dir/pyproject.toml"
    [[ -f "$pyproject" ]] || return 1

    python3 - "$pyproject" "${exclude_dep_list[@]}" <<'EOF'
import sys, tomllib

pyproject_path = sys.argv[1]
excluded = [e.lower().replace("_", "-") for e in sys.argv[2:]]

with open(pyproject_path, "rb") as f:
    data = tomllib.load(f)

project = data.get("project", {})
deps = list(project.get("dependencies", []))
for extra_deps in project.get("optional-dependencies", {}).values():
    deps.extend(extra_deps)

for dep in deps:
    pkg = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("[")[0].strip().lower().replace("_", "-")
    for excl in excluded:
        if pkg == excl or pkg.startswith(excl):
            print(f"    skipped: depends on '{pkg}'", file=sys.stderr)
            sys.exit(0)
sys.exit(1)
EOF
}

echo "=== Finding CLI directories in $PROJECT_ROOT ==="

cli_dirs=()
skipped_dep=()
while IFS= read -r -d '' dir; do
    name=$(basename "$dir")

    # Skip by dir name
    skip=false
    for excl in "${exclude_list[@]}"; do
        [[ "$name" == "$excl" ]] && skip=true && break
    done
    [[ "$skip" == "true" ]] && continue

    # Skip by dependency
    if [[ ${#exclude_dep_list[@]} -gt 0 ]] && has_excluded_dep "$dir"; then
        skipped_dep+=("$name")
        continue
    fi

    cli_dirs+=("$dir")
done < <(find "$PROJECT_ROOT" -maxdepth 1 -type d -name '*-cli' -print0 | sort -z)

if [ ${#cli_dirs[@]} -eq 0 ]; then
    echo "No *-cli directories found (after exclusions)!"
    exit 1
fi

echo "Found ${#cli_dirs[@]} CLI directories:"
for dir in "${cli_dirs[@]}"; do
    echo "  - $(basename "$dir")"
done
[[ ${#exclude_list[@]} -gt 0 ]]    && echo "Excluded by name: ${exclude_list[*]}"
[[ ${#skipped_dep[@]} -gt 0 ]]     && echo "Excluded by dep (${exclude_dep_list[*]}): ${skipped_dep[*]}"
echo ""

# Pass 1: register all local packages without deps so cross-references resolve locally
echo "=== Pass 1: registering all packages (no deps) ==="
for dir in "${cli_dirs[@]}"; do
    pip install -e "$dir" --no-deps -q
done
echo ""

# Pass 2: install all packages in one shot so pip resolves deps together cleanly
echo "=== Pass 2: installing all packages with dependencies ==="
pip_args=()
for dir in "${cli_dirs[@]}"; do
    pip_args+=("-e" "$dir[all]")
done
pip install "${pip_args[@]}"

echo ""
echo "=== All CLI tools installed! ==="
