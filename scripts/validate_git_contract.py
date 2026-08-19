"""Validate feature-branch and Conventional Commit PR identifiers."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Sequence

BRANCH_RE = re.compile(r"^pr-(?P<number>\d{2})/[a-z0-9][a-z0-9-]*$")
SUBJECT_RE = re.compile(
    r"^(?P<type>feat|fix|docs|test|refactor|perf|build|ci|chore)"
    r"\(pr-(?P<number>\d{2})\): (?P<description>[a-z0-9].+)$"
)


def branch_pr_id(branch: str) -> str:
    """Return the canonical ``pr-XX`` identifier encoded in a branch."""
    match = BRANCH_RE.fullmatch(branch)
    if match is None:
        raise ValueError(f"invalid implementation branch: {branch!r}")
    return f"pr-{match.group('number')}"


def validate_subject(subject: str, expected_pr_id: str) -> None:
    """Validate one Conventional Commit subject against a PR identifier."""
    match = SUBJECT_RE.fullmatch(subject)
    if match is None:
        raise ValueError(f"invalid Conventional Commit subject: {subject!r}")
    actual = f"pr-{match.group('number')}"
    if actual != expected_pr_id:
        raise ValueError(
            f"commit scope {actual!r} does not match branch PR {expected_pr_id!r}: {subject!r}"
        )


def validate_contract(branch: str, subjects: Sequence[str], *, event: str = "local") -> None:
    """Validate all implementation commit subjects for a feature branch."""
    if event == "merge_group" or branch == "main":
        return
    expected = branch_pr_id(branch)
    if not subjects:
        raise ValueError("no implementation commits found for validation")
    for subject in subjects:
        validate_subject(subject, expected)


def git_subjects(base: str) -> list[str]:
    """Read commit subjects reachable from HEAD but not from ``base``."""
    completed = subprocess.run(
        ["git", "log", "--format=%s", f"{base}..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--event", default="local")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = _parser().parse_args(argv)
    if args.event == "merge_group" or args.branch == "main":
        return 0
    validate_contract(args.branch, git_subjects(args.base), event=args.event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
