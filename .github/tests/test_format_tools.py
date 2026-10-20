"""Standalone tests for formatting and lint entry points; Blender is not required."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".vscode" / "ruff_git_changed.py"
SPEC = importlib.util.spec_from_file_location("ruff_git_changed", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ruff_git_changed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ruff_git_changed)
DEV_SPEC = importlib.util.spec_from_file_location("dev", ROOT / "dev.py")
assert DEV_SPEC is not None and DEV_SPEC.loader is not None
dev = importlib.util.module_from_spec(DEV_SPEC)
DEV_SPEC.loader.exec_module(dev)


class TestFormatCode(unittest.TestCase):
    def setUp(self):
        self.runner = Mock()
        patcher = patch.object(dev, "subprocess", self.runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.format_code = dev.format_code

    def test_sorts_imports_before_formatting_from_repository_root(self):
        self.format_code()
        self.assertEqual(
            self.runner.run.call_args_list,
            [
                call(
                    [sys.executable, "-m", "ruff", "check", ".", "--fix"],
                    cwd=str(ROOT),
                    check=True,
                ),
                call(
                    [sys.executable, "-m", "ruff", "format", "."],
                    cwd=str(ROOT),
                    check=True,
                ),
            ],
        )

    def test_propagates_failure_from_either_command(self):
        for failed_command in (0, 1):
            with self.subTest(failed_command=failed_command):
                self.runner.reset_mock()
                self.runner.run.side_effect = [None] * failed_command + [
                    subprocess.CalledProcessError(1, "ruff")
                ]
                with self.assertRaises(subprocess.CalledProcessError):
                    self.format_code()
                self.assertEqual(self.runner.run.call_count, failed_command + 1)


class TestLintCode(unittest.TestCase):
    @patch.object(dev, "subprocess")
    def test_runs_all_read_only_checks_from_repository_root(self, runner):
        dev.lint_code()
        self.assertEqual(
            runner.run.call_args_list,
            [
                call(
                    [sys.executable, "-m", "ruff", "check", "."],
                    cwd=str(ROOT),
                    check=True,
                ),
                call(
                    [sys.executable, "-m", "ruff", "format", ".", "--check", "--diff"],
                    cwd=str(ROOT),
                    check=True,
                ),
                call(
                    [sys.executable, "-m", "pydoclint.main", "--quiet", "."],
                    cwd=str(ROOT),
                    check=True,
                ),
            ],
        )

    @patch.object(dev, "subprocess")
    def test_propagates_failure_from_each_check(self, runner):
        for failed_command in range(3):
            with self.subTest(failed_command=failed_command):
                runner.reset_mock()
                runner.run.side_effect = [None] * failed_command + [
                    subprocess.CalledProcessError(1, "lint")
                ]
                runner.CalledProcessError = subprocess.CalledProcessError
                with self.assertRaises(subprocess.CalledProcessError):
                    dev.lint_code()
                self.assertEqual(runner.run.call_count, failed_command + 1)


class TestBranchChecks(unittest.TestCase):
    def setUp(self):
        self.original_selection = ruff_git_changed.get_git_changed_files_branch
        self.chdir = patch.object(ruff_git_changed.os, "chdir").start()
        self.changed = patch.object(
            ruff_git_changed,
            "get_git_changed_files_branch",
            return_value=["some file.py"],
        ).start()
        self.run = patch.object(ruff_git_changed.subprocess, "run").start()
        self.run.return_value.returncode = 0
        self.addCleanup(patch.stopall)

    def test_runs_both_checks_with_selected_python_and_preserves_spaced_paths(self):
        self.assertEqual(ruff_git_changed.main(), 0)
        self.chdir.assert_called_once_with(ROOT)
        self.assertEqual(
            self.run.call_args_list,
            [
                call(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "check",
                        "some file.py",
                        "--config",
                        str(ROOT / "pyproject.toml"),
                    ],
                    check=False,
                ),
                call(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "format",
                        "--check",
                        "--diff",
                        "some file.py",
                        "--config",
                        str(ROOT / "pyproject.toml"),
                    ],
                    check=False,
                ),
            ],
        )

    def test_reports_failure_from_either_check_and_still_runs_both(self):
        for returncodes in ((1, 0), (0, 1)):
            with self.subTest(returncodes=returncodes):
                self.run.reset_mock()
                self.run.side_effect = [Mock(returncode=code) for code in returncodes]
                self.assertEqual(ruff_git_changed.main(), 1)
                self.assertEqual(self.run.call_count, 2)

    def test_no_changed_files_skips_ruff(self):
        self.changed.return_value = []
        self.assertEqual(ruff_git_changed.main(), 0)
        self.run.assert_not_called()

    def test_git_errors_are_not_reported_as_success(self):
        for error in (RuntimeError("invalid base"), FileNotFoundError("git")):
            with self.subTest(error=error):
                self.changed.side_effect = error
                self.assertEqual(ruff_git_changed.main(), 1)
                self.run.assert_not_called()

    def test_branch_selection_uses_null_delimited_existing_python_paths(self):
        with (
            patch.object(ruff_git_changed, "_pick_default_base", return_value="main"),
            patch.object(
                ruff_git_changed,
                "_run_git",
                side_effect=[
                    "abc123",
                    "some file.py\0stub.pyi\0missing.py\0README.md\0",
                ],
            ) as git,
            patch.object(
                ruff_git_changed.Path,
                "is_file",
                autospec=True,
                side_effect=lambda path: str(path) != "missing.py",
            ),
        ):
            files = self.original_selection()
        self.assertEqual(files, ["some file.py", "stub.pyi"])
        self.assertEqual(
            git.call_args_list,
            [
                call(["merge-base", "main", "HEAD"]),
                call(
                    ["diff", "--name-only", "--diff-filter=ACMRT", "-z", "abc123..HEAD"]
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
