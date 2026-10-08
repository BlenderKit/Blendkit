#!/usr/bin/env python3
"""
Run Black on Python files changed by the current branch (commits) relative to its base.

Behavior:
- Detect base as origin/HEAD when available (typically origin/main), otherwise fallback
  to origin/main, origin/master, main, master.
- List files changed in commits on this branch: git diff --name-only <merge-base>..HEAD
- Filter to .py files and run: black --check --diff <files>

No script arguments by design (keep it simple like the original black_git_changed).
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _run_git(args: List[str], check: bool = True) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def _detect_origin_head() -> Optional[str]:
    try:
        # e.g., 'origin/main'
        ref = _run_git(
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
        )
        return ref or None
    except Exception:
        return None


def _pick_default_base() -> str:
    ref = _detect_origin_head()
    if ref:
        return ref
    for cand in ("origin/main", "origin/master", "main", "master"):
        try:
            _run_git(["rev-parse", "--verify", cand])
            return cand
        except Exception:
            continue
    # Last resort
    return "origin/main"


def _merge_base(a: str, b: str) -> str:
    return _run_git(["merge-base", a, b])


def get_git_changed_files_branch() -> List[str]:
    """Get list of Python files changed by the branch relative to base (committed work).

    Uses: git diff --name-only --diff-filter=ACMRT <merge-base(base, HEAD)>..HEAD
    """
    try:
        base = _pick_default_base()
        mb = _merge_base(base, "HEAD")
        diff_range = f"{mb}..HEAD"
        out = _run_git(
            ["diff", "--name-only", "--diff-filter=ACMRT", diff_range], check=True
        )
        files = [f for f in (out.splitlines() if out else []) if f.endswith(".py")]
        return files
    except RuntimeError as e:
        print(f"Error getting branch-changed files: {e}")
        return []
    except FileNotFoundError:
        print("Git not found in PATH")
        return []


def main():
    """Run Black on git-changed Python files."""
    # Get workspace root (parent of .vscode)
    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent

    print(f"Workspace root: {workspace_root}")

    # Change to workspace directory
    import os

    os.chdir(workspace_root)

    # Get changed Python files for this branch (committed relative to base)
    changed_files = get_git_changed_files_branch()

    if not changed_files:
        print("No changed Python files found.")
        return 0

    print(f"Found {len(changed_files)} changed Python files:")
    for file in changed_files:
        print(f"  - {file}")

    # Run Black on changed files (no script args, fixed flags like original)
    black_args = ["black", "--check", "--diff", *changed_files]

    print(f"\nRunning: {' '.join(black_args)}")

    try:
        result = subprocess.run(black_args, check=False)
        return result.returncode
    except FileNotFoundError:
        print("Black not found. Make sure it's installed and in PATH.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
