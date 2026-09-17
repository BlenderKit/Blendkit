# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
# #
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# #
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
# #
# ##### END GPL LICENSE BLOCK #####

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative imports.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

# ``override_extension_draw`` imports ``bl_pkg``, which only exists in the
# extensions system introduced in Blender 4.2. Skip the whole module on older
# versions, and avoid importing it so the missing ``bl_pkg`` does not error.
if bpy.app.version >= (4, 2, 0):
    from . import override_extension_draw as oed
else:
    oed = None


class _FakeRepo:
    """Minimal stand-in for a Blender extensions repository."""

    def __init__(self, name, module, remote_url, use_custom_directory=False):
        self.name = name
        self.module = module
        self.remote_url = remote_url
        self.use_custom_directory = use_custom_directory


class _FakeRepos(list):
    """List that mimics ``preferences.extensions.repos`` (supports remove)."""


def _patched_bpy(repos):
    return SimpleNamespace(
        context=SimpleNamespace(
            preferences=SimpleNamespace(
                extensions=SimpleNamespace(repos=repos),
            ),
        ),
    )


@unittest.skipUnless(
    bpy.app.version >= (4, 2, 0), "override_extension_draw requires Blender 4.2+"
)
class TestMigrateRepository(unittest.TestCase):
    def _run(self, repos):
        with patch.object(oed, "bpy", _patched_bpy(repos)):
            oed.migrate_repository()

    def test_updates_legacy_url_repo(self):
        """A single legacy repo is migrated to the new URL and normalized."""
        repo = _FakeRepo(
            "www.blenderkit.com",
            "www_blenderkit_com",
            oed.LEGACY_EXTENSIONS_API_URL,
        )
        repos = _FakeRepos([repo])
        self._run(repos)

        self.assertEqual(len(repos), 1)
        self.assertEqual(repo.remote_url, oed.EXTENSIONS_API_URL)
        self.assertEqual(repo.name, "www.blenderkit.com")
        self.assertEqual(repo.module, oed.EXTENSIONS_REPO_MODULE)

    def test_removes_duplicate_keeps_canonical_module(self):
        """Legacy + fresh duplicate collapse to the canonical-module repo."""
        legacy = _FakeRepo(
            "www.blenderkit.com",
            "www_blenderkit_com",
            oed.LEGACY_EXTENSIONS_API_URL,
        )
        duplicate = _FakeRepo(
            "www.blenderkit.com.001",
            "www_blenderkit_com_001",
            oed.EXTENSIONS_API_URL,
        )
        repos = _FakeRepos([legacy, duplicate])
        self._run(repos)

        self.assertEqual(len(repos), 1)
        self.assertIs(repos[0], legacy)
        self.assertEqual(legacy.remote_url, oed.EXTENSIONS_API_URL)
        self.assertEqual(legacy.module, oed.EXTENSIONS_REPO_MODULE)
        self.assertEqual(legacy.name, "www.blenderkit.com")

    def test_restores_module_on_leftover_001_repo(self):
        """A leftover ``_001`` repo gets its module and name restored so
        installed ``bl_ext.www_blenderkit_com.*`` add-ons resolve again."""
        repo = _FakeRepo(
            "www.blenderkit.com.001",
            "www_blenderkit_com_001",
            oed.EXTENSIONS_API_URL,
            use_custom_directory=True,
        )
        repos = _FakeRepos([repo])
        self._run(repos)

        self.assertEqual(len(repos), 1)
        self.assertEqual(repo.module, oed.EXTENSIONS_REPO_MODULE)
        self.assertEqual(repo.name, "www.blenderkit.com")
        self.assertFalse(repo.use_custom_directory)

    def test_no_matching_repo_is_noop(self):
        """Unrelated repos are left untouched."""
        other = _FakeRepo(
            "extensions.blender.org",
            "blender_org",
            "https://extensions.blender.org/api/v1/extensions/",
        )
        repos = _FakeRepos([other])
        self._run(repos)

        self.assertEqual(len(repos), 1)
        self.assertIs(repos[0], other)
        self.assertEqual(other.module, "blender_org")


if __name__ == "__main__":
    unittest.main()
