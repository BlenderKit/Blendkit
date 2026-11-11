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

import copy
import unittest
from unittest.mock import Mock, patch

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import client_tasks, datas, global_vars, search


def mocked_preferences() -> Mock:
    """Get Mock of the add-on preferences with default values."""
    preferences = Mock()
    preferences.nsfw_filter = True
    return preferences


def mocked_common_props() -> Mock:
    """Get Mock of the props shared across asset types."""
    props = Mock()
    props.search_verification_status = "ALL"
    props.unrated_quality_only = False
    props.unrated_wh_only = False
    props.search_file_size = False
    return props


def mocked_ui_props() -> Mock:
    """Get Mock of the UI properties."""
    ui_props = Mock()
    ui_props.quality_limit = 0
    ui_props.search_bookmarks = False
    ui_props.search_license = "ANY"
    ui_props.search_blender_version = False
    ui_props.search_keywords = ""
    ui_props.free_only = False
    ui_props.own_only = False
    ui_props.search_sort_by = "default"
    return ui_props


# TODO: Add test for build_common_query()


class TestDecideOrdering(unittest.TestCase):
    def test_default_sorting(self):
        query = {"free_first": False, "search_order_by": "default"}
        order = search.decide_ordering(query)
        expected = ["-last_blend_upload", "-last_zip_file_upload"]
        self.assertEqual(order, expected)

    def test_bookmarks_sorting(self):
        query = {"free_first": False, "search_order_by": "-bookmarks"}
        order = search.decide_ordering(query)
        expected = ["-bookmarks"]
        self.assertEqual(order, expected)

    def test_default_sorting_free_first(self):
        query = {"free_first": True, "search_order_by": "default"}
        order = search.decide_ordering(query)
        expected = ["-is_free", "-last_blend_upload", "-last_zip_file_upload"]
        self.assertEqual(order, expected)

    def test_bookmarks_sorting_free_first(self):
        query = {"free_first": True, "search_order_by": "bookmarks"}
        order = search.decide_ordering(query)
        expected = ["-is_free", "bookmarks"]
        self.assertEqual(order, expected)


class TestQueryToURL(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None  # no limit for printing assert errors
        self.addon_version = "3.16.1"
        self.blender_version = "5.0.0"
        self.scene_uuid = "12345678-abcd-abcd-abcd-12345678abcd"
        self.page_size = 15
        self.default_query = {
            "asset_type": "model",
            "sexualizedContent": "",
            "free_first": False,
            "search_order_by": "default",
        }

    def test_default_model_query(self):
        url = search.query_to_url(
            self.default_query,
            addon_version=self.addon_version,
            blender_version=self.blender_version,
            scene_uuid=self.scene_uuid,
            page_size=self.page_size,
        )
        expected = "https://www.blendkit.com/api/v1/search/?query=+asset_type:model+sexualizedContent:+order:-last_blend_upload,-last_zip_file_upload&dict_parameters=1&page_size=15&addon_version=3.16.1&blender_version=5.0.0&scene_uuid=12345678-abcd-abcd-abcd-12345678abcd"
        self.assertEqual(url, expected)

    def test_sorted_model_query(self):
        query = self.default_query
        query["search_order_by"] = "-working_hours"
        url = search.query_to_url(
            self.default_query,
            addon_version=self.addon_version,
            blender_version=self.blender_version,
            scene_uuid=self.scene_uuid,
            page_size=self.page_size,
        )
        expected = "https://www.blendkit.com/api/v1/search/?query=+asset_type:model+sexualizedContent:+order:-working_hours&dict_parameters=1&page_size=15&addon_version=3.16.1&blender_version=5.0.0&scene_uuid=12345678-abcd-abcd-abcd-12345678abcd"
        self.assertEqual(url, expected)

    def test_sorted_freefirst_material_query(self):
        query = self.default_query
        query["search_order_by"] = "-quality"
        query["free_first"] = True
        query["asset_type"] = "material"
        url = search.query_to_url(
            self.default_query,
            addon_version=self.addon_version,
            blender_version=self.blender_version,
            scene_uuid=self.scene_uuid,
            page_size=self.page_size,
        )
        expected = "https://www.blendkit.com/api/v1/search/?query=+asset_type:material+sexualizedContent:+order:-is_free,-quality&dict_parameters=1&page_size=15&addon_version=3.16.1&blender_version=5.0.0&scene_uuid=12345678-abcd-abcd-abcd-12345678abcd"
        self.assertEqual(url, expected)


class TestBuildQueryModel(unittest.TestCase):
    def setUp(self):
        self.preferences = mocked_preferences()
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_style = "ANY"
        self.props.search_condition = "UNSPECIFIED"
        self.props.search_design_year = False
        self.props.search_polycount = False
        self.props.search_texture_resolution = False
        self.props.search_animated = False
        self.props.search_geometry_nodes = False

    def test_default_model_query(self):
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {"asset_type": "model", "sexualizedContent": False}
        self.assertEqual(query, expected)

    def test_style_other(self):
        self.props.search_style = "OTHER"
        self.props.search_style_other = "custom_style"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modelStyle": "custom_style",
        }
        self.assertEqual(query, expected)

    def test_style_specific(self):
        self.props.search_style = "REALISTIC"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modelStyle": "REALISTIC",
        }
        self.assertEqual(query, expected)

    def test_search_condition(self):
        self.props.search_condition = "NEW"
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "condition": "NEW",
        }
        self.assertEqual(query, expected)

    def test_design_year_range(self):
        self.props.search_design_year = True
        self.props.search_design_year_min = 1900
        self.props.search_design_year_max = 2000
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "designYear_gte": 1900,
            "designYear_lte": 2000,
        }
        self.assertEqual(query, expected)

    def test_polycount_range(self):
        self.props.search_polycount = True
        self.props.search_polycount_min = 1000
        self.props.search_polycount_max = 10000
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "faceCount_gte": 1000,
            "faceCount_lte": 10000,
        }
        self.assertEqual(query, expected)

    def test_texture_resolution(self):
        self.props.search_texture_resolution = True
        self.props.search_texture_resolution_min = 512
        self.props.search_texture_resolution_max = 4096
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        self.assertEqual(query["textureResolutionMax_gte"], 512)
        self.assertEqual(query["textureResolutionMax_lte"], 4096)

    def test_animated_flag(self):
        self.props.search_animated = True
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {"asset_type": "model", "sexualizedContent": False, "animated": True}
        self.assertEqual(query, expected)

    def test_geometry_nodes(self):
        self.props.search_geometry_nodes = True
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = {
            "asset_type": "model",
            "sexualizedContent": False,
            "modifiers": "nodes",
        }
        self.assertEqual(query, expected)

    def test_nsfw_filter_off(self):
        """Turned-off NSFW filter means all sexualizedContent is allowed, we expect empty string there."""
        self.preferences.nsfw_filter = False
        query = search.build_query_model(self.props, self.ui_props, self.preferences)
        expected = expected = {"asset_type": "model", "sexualizedContent": ""}
        self.assertEqual(query, expected)


class TestBuildQueryScene(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()

    def test_default_scene_query(self):
        query = search.build_query_scene(self.props, self.ui_props)
        expected = {"asset_type": "scene"}
        self.assertEqual(query, expected)


class TestBuildQueryHDR(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_texture_resolution = False  # TODO: test alternations of this
        self.props.true_hdr = True  # TODO: test alternations of this

    def test_default_HDR_query(self):
        query = search.build_query_HDR(self.props, self.ui_props)
        expected = {"asset_type": "hdr", "trueHDR": True}
        self.assertEqual(query, expected)


# TODO: Add test for MATERIAL
class TestBuildQueryMaterial(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.props.search_style = "ANY"
        self.props.search_procedural = "BOTH"

    def test_query_default(self):
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material"}
        self.assertEqual(query, expected)

    def test_query_search_style(self):
        self.props.search_style = "REALISTIC"
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "style": "REALISTIC"}
        self.assertEqual(query, expected)

    def test_query_search_style_other(self):
        self.props.search_style = "OTHER"
        self.props.search_style_other = ""
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "style": ""}
        self.assertEqual(query, expected)

    def test_query_search_procedural_texture_based_default_resolution(self):
        self.props.search_procedural = "TEXTURE_BASED"
        self.props.search_texture_resolution = False
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "textureResolutionMax_gte": 0}
        self.assertEqual(query, expected)

    def test_query_search_procedural_texture_based_default(self):
        self.props.search_procedural = "TEXTURE_BASED"
        self.props.search_texture_resolution = True
        self.props.search_texture_resolution_min = 256
        self.props.search_texture_resolution_max = 4096
        query = search.build_query_material(self.props, self.ui_props)
        expected = {
            "asset_type": "material",
            "textureResolutionMax_gte": 256,
            "textureResolutionMax_lte": 4096,
        }
        self.assertEqual(query, expected)

    def test_query_search_procedural_procedural_based(self):
        self.props.search_procedural = "PROCEDURAL"
        query = search.build_query_material(self.props, self.ui_props)
        expected = {"asset_type": "material", "files_size_lte": 1024 * 1024}
        self.assertEqual(query, expected)


class TestBuildQueryBrush(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()
        self.image_paint_object = None  # TODO: test alternations of this

    def test_default_brush_query(self):
        query = search.build_query_brush(
            self.props, self.ui_props, self.image_paint_object
        )
        expected = {"asset_type": "brush", "mode": "sculpt"}
        self.assertEqual(query, expected)


class TestBuildQueryNodegroup(unittest.TestCase):
    def setUp(self):
        self.ui_props = mocked_ui_props()
        self.props = mocked_common_props()

    def test_default_nodegroup_query(self):
        query = search.build_query_nodegroup(self.props, self.ui_props)
        expected = {"asset_type": "nodegroup"}
        self.assertEqual(query, expected)


class TestFailedSearchHistory(unittest.TestCase):
    """Repeated or failed searches must not clutter the search history."""

    def setUp(self):
        self._orig_tabs = copy.deepcopy(global_vars.TABS)
        self._orig_steps = dict(global_vars.DATA["history steps"])
        self._orig_search_tasks = dict(search.search_tasks)
        global_vars.TABS["active_tab"] = 0
        global_vars.TABS["tabs"] = [
            {"name": "Default", "history": [], "history_index": -1}
        ]
        global_vars.DATA["history steps"] = {}
        search.search_tasks.clear()

    def tearDown(self):
        global_vars.TABS.clear()
        global_vars.TABS.update(self._orig_tabs)
        global_vars.DATA["history steps"] = self._orig_steps
        search.search_tasks.clear()
        search.search_tasks.update(self._orig_search_tasks)

    @property
    def tab(self) -> dict:
        return global_vars.TABS["tabs"][0]

    def add_step(self, step_id: str, results=None) -> dict:
        """Add a history step to the tab, with results if given (a finished search)."""
        step = {"id": step_id, "ui_state": {}, "is_searching": results is None}
        if results is not None:
            step["search_results"] = results
        self.tab["history"].append(step)
        self.tab["history_index"] = len(self.tab["history"]) - 1
        global_vars.DATA["history steps"][step_id] = step
        return step

    def fail_search(self, step_id: str, get_next: bool = False) -> None:
        """Deliver an error for a search task belonging to the given step."""
        task = client_tasks.Task(
            data={"history_id": step_id, "get_next": get_next},
            app_id="1",
            task_type="search",
            status="error",
            message="Search failed",
        )
        search.search_tasks[task.task_id] = datas.SearchData(
            PREFS={},
            tempdir="",
            urlquery="",
            asset_type="model",
            scene_uuid="",
            get_next=get_next,
            page_size=1,
            blender_version="",
            history_id=step_id,
        )
        with patch.object(search.reports, "add_report"):
            search.handle_search_task_error(task)

    def history_ids(self) -> list:
        return [step["id"] for step in self.tab["history"]]

    def finish_search(self, step_id: str, asset_ids: list, state=None) -> None:
        """Store results on a step the way a finished search does, then merge."""
        step = global_vars.DATA["history steps"][step_id]
        step["ui_state"] = state or {"query": "tree"}
        step["search_results"] = [{"assetBaseId": asset_id} for asset_id in asset_ids]
        step["is_searching"] = False
        search.merge_duplicate_history_step(step_id)

    def test_failed_search_stays_in_history_with_empty_results(self):
        step = self.add_step("a")
        self.fail_search("a")
        self.assertEqual(self.history_ids(), ["a"])
        self.assertEqual(step["search_results"], [])
        self.assertTrue(step["search_failed"])
        self.assertFalse(step["is_searching"])

    def test_failed_search_does_not_show_previous_results(self):
        self.add_step("a", results=[{"assetBaseId": "x"}])
        self.add_step("b")
        self.fail_search("b")
        self.assertEqual(self.history_ids(), ["a", "b"])
        self.assertEqual(self.tab["history_index"], 1)
        self.assertEqual(search.get_search_results(), [])

    def test_repeated_failed_search_is_merged(self):
        self.add_step("a")
        self.fail_search("a")
        self.add_step("b")
        self.fail_search("b")
        self.add_step("c")
        self.fail_search("c")
        self.assertEqual(self.history_ids(), ["a"])
        self.assertEqual(self.tab["history_index"], 0)
        self.assertEqual(list(global_vars.DATA["history steps"]), ["a"])

    def test_failed_search_with_other_query_is_kept(self):
        self.add_step("a")
        self.fail_search("a")
        b = self.add_step("b")
        b["ui_state"] = {"query": "dog"}
        self.fail_search("b")
        self.assertEqual(self.history_ids(), ["a", "b"])

    def test_failed_search_after_successful_one_is_kept(self):
        self.add_step("a", results=[])
        self.add_step("b")
        self.fail_search("b")
        self.assertEqual(self.history_ids(), ["a", "b"])

    def test_failed_pagination_keeps_step_with_results(self):
        step = self.add_step("a", results=[{"assetBaseId": "x"}])
        step["is_searching"] = True
        self.fail_search("a", get_next=True)
        self.assertEqual(self.history_ids(), ["a"])
        self.assertEqual(step["search_results"], [{"assetBaseId": "x"}])
        self.assertNotIn("search_failed", step)
        self.assertFalse(step["is_searching"])

    def test_failed_refresh_keeps_existing_results(self):
        step = self.add_step("a", results=[{"assetBaseId": "x"}])
        step["is_searching"] = True
        self.fail_search("a")
        self.assertEqual(step["search_results"], [{"assetBaseId": "x"}])
        self.assertNotIn("search_failed", step)

    def test_failure_of_unknown_step_is_ignored(self):
        self.add_step("a", results=[{"assetBaseId": "x"}])
        self.fail_search("missing")
        self.assertEqual(self.history_ids(), ["a"])
        self.assertEqual(self.tab["history_index"], 0)

    def test_identical_consecutive_results_are_merged(self):
        self.add_step("a")
        self.finish_search("a", ["x", "y"])
        self.add_step("b")
        self.finish_search("b", ["x", "y"])
        self.assertEqual(self.history_ids(), ["a"])
        self.assertEqual(self.tab["history_index"], 0)
        self.assertNotIn("b", global_vars.DATA["history steps"])

    def test_different_results_are_kept(self):
        self.add_step("a")
        self.finish_search("a", ["x", "y"])
        self.add_step("b")
        self.finish_search("b", ["x", "z"])
        self.assertEqual(self.history_ids(), ["a", "b"])
        self.assertEqual(self.tab["history_index"], 1)

    def test_same_results_for_different_query_are_kept(self):
        self.add_step("a")
        self.finish_search("a", ["x"], state={"query": "tree"})
        self.add_step("b")
        self.finish_search("b", ["x"], state={"query": "plant"})
        self.assertEqual(self.history_ids(), ["a", "b"])

    def test_first_step_is_never_merged(self):
        self.add_step("a")
        self.finish_search("a", ["x"])
        self.assertEqual(self.history_ids(), ["a"])

    def test_merge_keeps_index_when_step_is_not_current(self):
        self.add_step("a")
        self.finish_search("a", ["x"])
        self.add_step("b")
        self.finish_search("b", ["x"])
        self.add_step("c")
        self.finish_search("c", ["y"])
        self.assertEqual(self.history_ids(), ["a", "c"])
        self.assertEqual(self.tab["history_index"], 1)

    def test_merge_of_unknown_step_does_nothing(self):
        self.add_step("a", results=[])
        self.assertFalse(search.merge_duplicate_history_step("missing"))
        self.assertEqual(self.history_ids(), ["a"])