import re
import unittest

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]


class TestAddOnVersions(unittest.TestCase):
    def test_manifest_version_matches_bl_info_version(self):
        """Check that the bl_info['version'] in __init__.py matches the version in blender_manifest.toml."""

        with open("blender_manifest.toml") as manifest_file:
            manifest_content = manifest_file.read()
        manifest_version_match = re.search(
            r'version\s+=\s+"(\d+)\.(\d+)\.(\d+)-(\d{6})"', manifest_content
        )
        self.assertIsNotNone(
            manifest_version_match,
            "Could not find version in blender_manifest.toml",
        )
        manifest_version = tuple(manifest_version_match.groups())

        with open("__init__.py") as f:
            init_content = f.read()
        bl_info_version_match = re.search(
            r'"version":\s+\((\d+),\s+(\d+),\s+(\d+),\s+(\d{6})\)', init_content
        )
        self.assertIsNotNone(
            bl_info_version_match,
            "Could not find 'version' in bl_info in __init__.py",
        )
        bl_info_version = tuple(bl_info_version_match.groups())

        self.assertEqual(
            manifest_version,
            bl_info_version,
            "Version in blender_manifest.toml does not match does not match bl_info['version'] in __init__.py",
        )

    def test_manifest_version_matches_init_VERSION(self):
        """Ensure the VERSION in __init__.py matches the version in blender_manifest.toml."""

        with open("blender_manifest.toml") as manifest_file:
            manifest_content = manifest_file.read()
        manifest_version_match = re.search(
            r'version\s+=\s+"(\d+)\.(\d+)\.(\d+)-(\d{6})"', manifest_content
        )
        self.assertIsNotNone(
            manifest_version_match,
            "Could not find version in blender_manifest.toml",
        )
        manifest_version = tuple(manifest_version_match.groups())

        with open("__init__.py") as f:
            init_content = f.read()
        init_version_match = re.search(
            r"VERSION\s+=\s+\((\d+),\s+(\d+),\s+(\d+),\s+(\d{6})\)", init_content
        )
        self.assertIsNotNone(
            init_version_match,
            "Could not find VERSION tuple in __init__.py",
        )
        init_version = tuple(init_version_match.groups())

        self.assertEqual(
            manifest_version,
            init_version,
            "Version in blender_manifest.toml does not match the VERSION tuple in __init__.py",
        )
