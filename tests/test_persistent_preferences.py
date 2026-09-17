# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import persistent_preferences as pp


class TestGetPreferencesPath(unittest.TestCase):
    def test_joins_config_dir_with_filename(self):
        with mock.patch.object(
            pp.paths, "get_config_dir_path", return_value=os.sep + "cfg"
        ):
            result = pp.get_preferences_path()
        self.assertEqual(
            result, os.path.abspath(os.path.join(os.sep + "cfg", "preferences.json"))
        )
        self.assertTrue(result.endswith("preferences.json"))


class TestWritePreferencesToJSON(unittest.TestCase):
    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "preferences.json")
            with (
                mock.patch.object(pp.paths, "ensure_config_dir_exists"),
                mock.patch.object(pp, "get_preferences_path", return_value=target),
            ):
                pp.write_preferences_to_JSON({"api_key": "abc", "thumb_size": 128})
            with open(target, encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data, {"api_key": "abc", "thumb_size": 128})

    def test_swallows_write_errors(self):
        # Pointing at a path inside a non-existent directory makes open() fail;
        # the function must log and return without raising.
        bad_path = os.path.join(os.sep + "nonexistent_dir_xyz", "preferences.json")
        with (
            mock.patch.object(pp.paths, "ensure_config_dir_exists"),
            mock.patch.object(pp, "get_preferences_path", return_value=bad_path),
        ):
            pp.write_preferences_to_JSON({"api_key": "abc"})  # must not raise


class TestLegacyAssetbarExpanded(unittest.TestCase):
    def test_explicit_key_wins(self):
        prefs = {"assetbar_expanded": True}
        user_prefs = SimpleNamespace()
        self.assertTrue(pp.get_legacy_assetbar_expanded_preference(prefs, user_prefs))

    def test_explicit_key_false(self):
        prefs = {"assetbar_expanded": 0}
        user_prefs = SimpleNamespace()
        self.assertFalse(pp.get_legacy_assetbar_expanded_preference(prefs, user_prefs))

    def test_falls_back_to_property_set(self):
        prefs = {}
        user_prefs = SimpleNamespace(
            assetbar_expanded=True,
            is_property_set=lambda name: name == "assetbar_expanded",
            maximized_assetbar_rows=1,
        )
        self.assertTrue(pp.get_legacy_assetbar_expanded_preference(prefs, user_prefs))

    def test_infers_expanded_from_saved_rows_gt_one(self):
        prefs = {"maximized_assetbar_rows": 3}
        user_prefs = SimpleNamespace(
            is_property_set=lambda name: False,
            maximized_assetbar_rows=1,
        )
        self.assertTrue(pp.get_legacy_assetbar_expanded_preference(prefs, user_prefs))

    def test_infers_collapsed_from_single_row(self):
        prefs = {}
        user_prefs = SimpleNamespace(
            is_property_set=lambda name: False,
            maximized_assetbar_rows=1,
        )
        self.assertFalse(pp.get_legacy_assetbar_expanded_preference(prefs, user_prefs))


class TestLoadPreferencesEarlyReturns(unittest.TestCase):
    def test_missing_file_returns_current_prefs(self):
        sentinel = {"current": True}
        with (
            mock.patch.object(
                pp,
                "get_preferences_path",
                return_value=os.path.join(os.sep + "no_such_dir", "preferences.json"),
            ),
            mock.patch.object(
                pp.utils, "get_preferences_as_dict", return_value=sentinel
            ),
        ):
            result = pp.load_preferences_from_JSON()
        self.assertIs(result, sentinel)

    def test_corrupt_file_is_removed_and_current_prefs_returned(self):
        sentinel = {"current": True}
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "preferences.json")
            with open(target, "w", encoding="utf-8") as f:
                f.write("{ this is not valid json ")
            with (
                mock.patch.object(pp, "get_preferences_path", return_value=target),
                mock.patch.object(
                    pp.utils, "get_preferences_as_dict", return_value=sentinel
                ),
            ):
                result = pp.load_preferences_from_JSON()
            self.assertIs(result, sentinel)
            self.assertFalse(os.path.exists(target))


class TestPropertyKeepPreferencesUpdated(unittest.TestCase):
    def test_keep_true_just_saves(self):
        user_prefs = SimpleNamespace(keep_preferences=True)
        with (
            mock.patch.object(pp.utils, "save_prefs") as save_prefs,
            mock.patch.object(pp, "get_preferences_path") as get_path,
        ):
            pp.property_keep_preferences_updated(user_prefs, None)
        save_prefs.assert_called_once_with(user_prefs, None)
        get_path.assert_not_called()

    def test_keep_false_no_file_just_saves(self):
        user_prefs = SimpleNamespace(keep_preferences=False)
        missing = os.path.join(os.sep + "no_such_dir", "preferences.json")
        with (
            mock.patch.object(pp, "get_preferences_path", return_value=missing),
            mock.patch.object(pp.utils, "save_prefs") as save_prefs,
        ):
            pp.property_keep_preferences_updated(user_prefs, None)
        save_prefs.assert_called_once_with(user_prefs, None)

    def test_keep_false_existing_file_is_deleted(self):
        user_prefs = SimpleNamespace(keep_preferences=False)
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "preferences.json")
            with open(target, "w", encoding="utf-8") as f:
                f.write("{}")
            with (
                mock.patch.object(pp, "get_preferences_path", return_value=target),
                mock.patch.object(pp.utils, "save_prefs") as save_prefs,
            ):
                pp.property_keep_preferences_updated(user_prefs, None)
            self.assertFalse(os.path.exists(target))
            save_prefs.assert_called_once_with(user_prefs, None)


if __name__ == "__main__":
    unittest.main()
