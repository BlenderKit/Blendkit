"""Standalone tests for release automation; Blender is not required."""

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bump-version.py"
SPEC = importlib.util.spec_from_file_location("bump_version", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bump_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump_version)

INIT = """bl_info = {
    "version": (3, 21, 3, 261002),  # X.Y.Z.yymmdd
    "blender": (3, 0, 0),
}
VERSION = (3, 21, 3, 261002)
import bpy
"""
MANIFEST = """schema_version = "1.0.0"
version = "3.21.3-261002" # X.Y.Z-YYMMDD
blender_version_min = "3.0.0"
"""


class TestBumpVersion(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write_sources(INIT, MANIFEST)

    def write_sources(self, init, manifest):
        (self.root / "__init__.py").write_bytes(init.encode("utf-8"))
        (self.root / "blender_manifest.toml").write_bytes(manifest.encode("utf-8"))

    def assert_rejected_without_changes(self, init, manifest):
        self.write_sources(init, manifest)
        with self.assertRaises(ValueError):
            bump_version.bump_version(self.root, date(2026, 10, 7))
        self.assertEqual((self.root / "__init__.py").read_bytes(), init.encode("utf-8"))
        self.assertEqual(
            (self.root / "blender_manifest.toml").read_bytes(), manifest.encode("utf-8")
        )

    def test_updates_all_declarations_and_preserves_other_content(self):
        result = bump_version.bump_version(self.root, date(2026, 10, 7))
        self.assertEqual(result, "3.21.4.261007")
        self.assertEqual(
            (self.root / "__init__.py").read_text(encoding="utf-8"),
            INIT.replace("3, 21, 3, 261002", "3, 21, 4, 261007"),
        )
        self.assertEqual(
            (self.root / "blender_manifest.toml").read_text(encoding="utf-8"),
            MANIFEST.replace("3.21.3-261002", "3.21.4-261007"),
        )

    def test_preserves_crlf(self):
        self.write_sources(INIT.replace("\n", "\r\n"), MANIFEST.replace("\n", "\r\n"))
        bump_version.bump_version(self.root, date(2026, 10, 7))
        self.assertEqual(
            (self.root / "__init__.py").read_bytes(),
            INIT.replace("3, 21, 3, 261002", "3, 21, 4, 261007")
            .replace("\n", "\r\n")
            .encode("utf-8"),
        )
        self.assertEqual(
            (self.root / "blender_manifest.toml").read_bytes(),
            MANIFEST.replace("3.21.3-261002", "3.21.4-261007")
            .replace("\n", "\r\n")
            .encode("utf-8"),
        )

    def test_patch_rollover_and_leap_day(self):
        self.write_sources(
            INIT.replace("3, 21, 3", "3, 21, 99"),
            MANIFEST.replace("3.21.3", "3.21.99"),
        )
        self.assertEqual(
            bump_version.bump_version(self.root, date(2028, 2, 29)),
            "3.21.100.280229",
        )

    def test_date_with_leading_zero_remains_readable_on_next_bump(self):
        self.assertEqual(
            bump_version.bump_version(self.root, date(2009, 1, 2)),
            "3.21.4.090102",
        )
        self.assertEqual(
            bump_version.bump_version(self.root, date(2009, 1, 3)),
            "3.21.5.090103",
        )
        compile(
            (self.root / "__init__.py").read_text(encoding="utf-8"),
            "__init__.py",
            "exec",
        )

    def test_mismatched_versions(self):
        for init, manifest in (
            (INIT.replace("VERSION = (3, 21, 3", "VERSION = (3, 21, 4"), MANIFEST),
            (INIT, MANIFEST.replace("3.21.3", "3.21.4")),
        ):
            with self.subTest(init=init, manifest=manifest):
                self.assert_rejected_without_changes(init, manifest)

    def test_missing_and_duplicate_declarations(self):
        for init, manifest in (
            (INIT.replace('    "version":', '    "other":'), MANIFEST),
            (INIT.replace("VERSION =", "OTHER ="), MANIFEST),
            (INIT, MANIFEST.replace("version =", "other =")),
            (INIT + "VERSION = (3, 21, 3, 261002)\n", MANIFEST),
            (INIT, MANIFEST + 'version = "3.21.3-261002"\n'),
        ):
            with self.subTest(init=init, manifest=manifest):
                self.assert_rejected_without_changes(init, manifest)

    def test_invalid_existing_date(self):
        self.assert_rejected_without_changes(
            INIT.replace("261002", "260231"), MANIFEST.replace("261002", "260231")
        )

    def test_rejects_dates_outside_supported_century(self):
        for year in (1999, 2100):
            with self.subTest(year=year):
                with self.assertRaises(ValueError):
                    bump_version.bump_version(self.root, date(year, 1, 1))
                self.assertEqual(
                    (self.root / "__init__.py").read_bytes(), INIT.encode("utf-8")
                )


if __name__ == "__main__":
    unittest.main()
