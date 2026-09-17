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

import unittest
from unittest.mock import Mock

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import search, utils


class TestOperatorPoll(unittest.TestCase):
    """Call poll() on key operators in background mode.
    They should return False (no viewport) without crashing.
    """

    OPERATORS = [
        "view3d.blenderkit_asset_bar_widget",
        "view3d.asset_drag_drop",
        "view3d.blenderkit_search",
        "scene.blenderkit_download",
        "object.blenderkit_upload",
        "object.blenderkit_generate_thumbnail",
    ]

    def test_operator_poll_no_crash(self):
        for op_idname in self.OPERATORS:
            category, name = op_idname.split(".")
            op = getattr(getattr(bpy.ops, category), name)
            result = op.poll()
            self.assertIsInstance(result, bool, f"{op_idname}.poll() returned non-bool")


class TestUtilsStringConversions(unittest.TestCase):
    def test_string2list(self):
        self.assertEqual(utils.string2list("a, b, c"), ["a", "b", "c"])
        self.assertEqual(utils.string2list("  one  "), ["one"])
        self.assertEqual(utils.string2list(""), [])
        self.assertEqual(utils.string2list(",,,"), [])

    def test_list2string(self):
        self.assertEqual(utils.list2string(["a", "b", "c"]), "a, b, c")
        self.assertEqual(utils.list2string(["single"]), "single")


class TestUtilsShortenText(unittest.TestCase):
    def test_no_shortening(self):
        self.assertEqual(utils.shorten_text("hello", -1), "hello")

    def test_short_enough(self):
        self.assertEqual(utils.shorten_text("hi", 10), "hi")

    def test_shortened(self):
        result = utils.shorten_text("hello world", 6)
        self.assertEqual(len(result), 6)
        self.assertTrue(result.endswith("…"))


class TestUtilsHasUrl(unittest.TestCase):
    def test_no_url(self):
        urls, text = utils.has_url("plain text")
        self.assertEqual(urls, [])
        self.assertEqual(text, "plain text")

    def test_markdown_url(self):
        urls, text = utils.has_url("Check [Blendkit](https://www.blendkit.com) now")
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0][0], "Blendkit")
        self.assertEqual(urls[0][1], "https://www.blendkit.com")


class TestUtilsRemoveUrlProtocol(unittest.TestCase):
    def test_https(self):
        self.assertEqual(
            utils.remove_url_protocol("https://example.com"), "example.com"
        )

    def test_http(self):
        self.assertEqual(utils.remove_url_protocol("http://example.com"), "example.com")

    def test_no_protocol(self):
        self.assertEqual(utils.remove_url_protocol("example.com"), "example.com")


class TestAssetFromNewerBlenderVersion(unittest.TestCase):
    def test_older_minor_asset(self):
        asset = {"assetType": "model", "sourceAppVersion": "4.0.0"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 1, 0))
        self.assertFalse(has_warning)

    def test_newer_major(self):
        asset = {"assetType": "model", "sourceAppVersion": "5.0.0"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 0, 0))
        self.assertTrue(has_warning)
        self.assertEqual(level, "major_newer")

    def test_newer_minor(self):
        asset = {"assetType": "model", "sourceAppVersion": "4.2.0"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 1, 0))
        self.assertTrue(has_warning)
        self.assertEqual(level, "minor")

    def test_newer_patch(self):
        asset = {"assetType": "model", "sourceAppVersion": "4.0.3"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 0, 2))
        self.assertTrue(has_warning)
        self.assertEqual(level, "patch")

    def test_same_version(self):
        asset = {"assetType": "model", "sourceAppVersion": "4.0.0"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 0, 0))
        self.assertFalse(has_warning)

    def test_addon_type_always_false(self):
        asset = {"assetType": "addon", "sourceAppVersion": "99.0.0"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 0, 0))
        self.assertFalse(has_warning)

    def test_short_version_string(self):
        asset = {"assetType": "model", "sourceAppVersion": "4"}
        has_warning, level = utils.asset_from_newer_blender_version(asset, (4, 0, 0))
        self.assertFalse(has_warning)


class TestAssetVersionAsTuple(unittest.TestCase):
    def test_conversion(self):
        asset = {"sourceAppVersion": "4.2.1"}
        self.assertEqual(utils.asset_version_as_tuple(asset), (4, 2, 1))


class TestBuildQueryCommon(unittest.TestCase):
    """Test the build_query_common function that adds shared parameters."""

    def _mock_props(self, **overrides):
        props = Mock()
        props.search_verification_status = "ALL"
        props.unrated_quality_only = False
        props.unrated_wh_only = False
        props.search_file_size = False
        for k, v in overrides.items():
            setattr(props, k, v)
        return props

    def _mock_ui_props(self, **overrides):
        ui_props = Mock()
        ui_props.quality_limit = 0
        ui_props.search_bookmarks = False
        ui_props.search_license = "ANY"
        ui_props.search_blender_version = False
        ui_props.search_keywords = ""
        for k, v in overrides.items():
            setattr(ui_props, k, v)
        return ui_props

    def test_empty_query_no_modifications(self):
        query = {"asset_type": "model"}
        result = search.build_query_common(
            query, self._mock_props(), self._mock_ui_props()
        )
        self.assertEqual(result, {"asset_type": "model"})

    def test_keywords_added(self):
        ui_props = self._mock_ui_props(search_keywords="cat toy")
        result = search.build_query_common({}, self._mock_props(), ui_props)
        self.assertIn("query", result)
        self.assertIn("cat toy", result["query"])

    def test_keywords_ampersand_escaped(self):
        ui_props = self._mock_ui_props(search_keywords="rock & stone")
        result = search.build_query_common({}, self._mock_props(), ui_props)
        self.assertIn("%26", result["query"])
        self.assertNotIn("&", result["query"])

    def test_file_size_filter(self):
        props = self._mock_props(
            search_file_size=True,
            search_file_size_min=1,
            search_file_size_max=10,
        )
        result = search.build_query_common({}, props, self._mock_ui_props())
        self.assertEqual(result["files_size_gte"], 1 * 1024 * 1024)
        self.assertEqual(result["files_size_lte"], 10 * 1024 * 1024)

    def test_quality_limit(self):
        ui_props = self._mock_ui_props(quality_limit=3)
        result = search.build_query_common({}, self._mock_props(), ui_props)
        self.assertEqual(result["quality_gte"], 3)

    def test_bookmarks_filter(self):
        ui_props = self._mock_ui_props(search_bookmarks=True)
        result = search.build_query_common({}, self._mock_props(), ui_props)
        self.assertEqual(result["bookmarks_rating"], 1)

    def test_license_filter(self):
        ui_props = self._mock_ui_props(search_license="cc0")
        result = search.build_query_common({}, self._mock_props(), ui_props)
        self.assertEqual(result["license"], "cc0")

    def test_does_not_mutate_input(self):
        original = {"asset_type": "model"}
        search.build_query_common(original, self._mock_props(), self._mock_ui_props())
        self.assertEqual(original, {"asset_type": "model"})


class TestGetBlenderVersion(unittest.TestCase):
    def test_format(self):
        ver = utils.get_blender_version()
        parts = ver.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            int(part)  # should not raise


class TestGetAddonVersion(unittest.TestCase):
    def test_format(self):
        ver = utils.get_addon_version()
        parts = ver.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            int(part)  # should not raise
