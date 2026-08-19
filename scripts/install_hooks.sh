#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
source_hook="$repo_root/.githooks/pre-push"
target_dir="$repo_root/.git/hooks"
target_hook="$target_dir/pre-push"

mkdir -p "$target_dir"
install -m 0755 "$source_hook" "$target_hook"
printf 'installed %s\n' "$target_hook"
