#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <pr-number>" >&2
  exit 2
fi

gh pr merge "$1" --auto --squash
