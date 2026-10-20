#!/usr/bin/env python3
"""Check imports and formatting of Python files committed on the current branch.

Detect the base from origin/HEAD, falling back to origin/main, origin/master,
main, or master. Uncommitted changes are not part of the branch file selection.
Ruff's configured exclusions apply even when files are passed explicitly.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _run_git(args: List[str], check: bool = True) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _detect_origin_head() -> Optional[str]:
    try:
        ref = _run_git(
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
        )
        return ref or None
    except RuntimeError:
        return None


def _pick_default_base() -> str:
    ref = _detect_origin_head()
    if ref:
        return ref
    for candidate in ("origin/main", "origin/master", "main", "master"):
        try:
            _run_git(["rev-parse", "--verify", candidate])
            return candidate
        except RuntimeError:
            continue
    return "origin/main"


def get_git_changed_files_branch() -> List[str]:
    """Get existing Python files changed in branch commits relative to the base."""
    base = _pick_default_base()
    merge_base = _run_git(["merge-base", base, "HEAD"])
    output = _run_git(
        ["diff", "--name-only", "--diff-filter=ACMRT", "-z", f"{merge_base}..HEAD"]
    )
    return [
        name
        for name in output.split("\0")
        if name.endswith((".py", ".pyi")) and Path(name).is_file()
    ]


def main():
    """Run both Ruff checks, returning failure if either check fails."""
    workspace_root = Path(__file__).resolve().parent.parent
    os.chdir(workspace_root)
    print(f"Workspace root: {workspace_root}")

    try:
        changed_files = get_git_changed_files_branch()
    except (RuntimeError, FileNotFoundError) as error:
        print(f"Error getting branch-changed files: {error}")
        return 1

    if not changed_files:
        print("No changed Python files found.")
        return 0

    status = 0
    for arguments in (
        ["check", *changed_files],
        ["format", "--check", "--diff", *changed_files],
    ):
        command = [
            sys.executable,
            "-m",
            "ruff",
            *arguments,
            "--config",
            str(workspace_root / "pyproject.toml"),
        ]
        print(f"Running: {subprocess.list2cmdline(command)}")
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            status = result.returncode
    return status


if __name__ == "__main__":
    sys.exit(main())
