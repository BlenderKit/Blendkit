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

import types
import unittest
from unittest import mock

import bpy
from mathutils import Vector

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module for the relative import below.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import ratings, utils


ASSET_DATA = {"id": "abc123", "assetType": "model", "name": "Test Asset"}


def _event(x=10, y=20):
    return types.SimpleNamespace(mouse_region_x=x, mouse_region_y=y)


def _context(space_type, region=None, region_data=None, **extra):
    space = types.SimpleNamespace(type=space_type) if space_type else None
    return types.SimpleNamespace(
        region=region,
        region_data=region_data,
        space_data=space,
        **extra,
    )


class AssetUnderCursorGuardsTest(unittest.TestCase):
    def test_no_region_returns_none(self):
        ctx = _context("VIEW_3D", region=None, region_data=object())
        self.assertEqual(ratings._asset_under_cursor(ctx, _event()), (None, None))

    def test_no_space_returns_none(self):
        ctx = _context(None, region=object(), region_data=object())
        self.assertEqual(ratings._asset_under_cursor(ctx, _event()), (None, None))

    def test_unsupported_space_returns_none(self):
        ctx = _context("IMAGE_EDITOR", region=object(), region_data=object())
        self.assertEqual(ratings._asset_under_cursor(ctx, _event()), (None, None))


class AssetUnderCursorOutlinerTest(unittest.TestCase):
    def setUp(self):
        self._to_cleanup_objects = []
        self._to_cleanup_collections = []

    def tearDown(self):
        for ob in self._to_cleanup_objects:
            try:
                bpy.data.objects.remove(ob)
            except Exception:
                pass
        for coll in self._to_cleanup_collections:
            try:
                bpy.data.collections.remove(coll)
            except Exception:
                pass

    def _new_object(self, name):
        ob = bpy.data.objects.new(name, None)
        self._to_cleanup_objects.append(ob)
        return ob

    def _new_collection(self, name):
        coll = bpy.data.collections.new(name)
        self._to_cleanup_collections.append(coll)
        return coll

    def test_hovered_object_is_returned(self):
        ob = self._new_object("BKRateObj")
        ob["asset_data"] = dict(ASSET_DATA)
        ctx = _context(
            "OUTLINER",
            region=object(),
            region_data=object(),
            window=None,
            area=None,
        )
        with mock.patch.object(
            ratings.utils, "get_outliner_element_under_mouse", return_value=ob
        ):
            result_ob, result_ad = ratings._asset_under_cursor(ctx, _event())
        self.assertIs(result_ob, ob)
        self.assertEqual(result_ad["id"], "abc123")

    def test_hovered_collection_resolves_to_instance_empty(self):
        coll = self._new_collection("BKRateColl")
        coll["asset_data"] = dict(ASSET_DATA)
        empty = self._new_object("BKRateEmpty")
        empty.instance_type = "COLLECTION"
        empty.instance_collection = coll
        ctx = _context(
            "OUTLINER",
            region=object(),
            region_data=object(),
            window=None,
            area=None,
            view_layer=types.SimpleNamespace(objects=[empty]),
        )
        with mock.patch.object(
            ratings.utils, "get_outliner_element_under_mouse", return_value=coll
        ):
            result_ob, result_ad = ratings._asset_under_cursor(ctx, _event())
        self.assertIs(result_ob, empty)
        self.assertEqual(result_ad["id"], "abc123")

    def test_nothing_hovered_returns_none(self):
        ctx = _context(
            "OUTLINER",
            region=object(),
            region_data=object(),
            window=None,
            area=None,
        )
        with mock.patch.object(
            ratings.utils, "get_outliner_element_under_mouse", return_value=None
        ):
            self.assertEqual(ratings._asset_under_cursor(ctx, _event()), (None, None))


class AssetUnderCursorViewportTest(unittest.TestCase):
    def setUp(self):
        self.ob = bpy.data.objects.new("BKRateViewportObj", None)
        self.ob["asset_data"] = dict(ASSET_DATA)

    def tearDown(self):
        try:
            bpy.data.objects.remove(self.ob)
        except Exception:
            pass

    def _viewport_context(self, ray_result):
        scene = types.SimpleNamespace(ray_cast=lambda *a, **k: ray_result)
        return _context(
            "VIEW_3D",
            region=object(),
            region_data=object(),
            scene=scene,
            evaluated_depsgraph_get=lambda: None,
        )

    def test_raycast_hit_returns_asset(self):
        ctx = self._viewport_context(
            (True, Vector(), Vector((0, 0, 1)), 0, self.ob, None)
        )
        with (
            mock.patch.object(
                ratings.view3d_utils,
                "region_2d_to_vector_3d",
                return_value=Vector((0, 0, -1)),
            ),
            mock.patch.object(
                ratings.view3d_utils,
                "region_2d_to_origin_3d",
                return_value=Vector((0, 0, 10)),
            ),
        ):
            result_ob, result_ad = ratings._asset_under_cursor(ctx, _event())
        self.assertIs(result_ob, self.ob)
        self.assertEqual(result_ad["id"], "abc123")

    def test_raycast_miss_returns_none(self):
        ctx = self._viewport_context((False, Vector(), Vector(), 0, None, None))
        with (
            mock.patch.object(
                ratings.view3d_utils,
                "region_2d_to_vector_3d",
                return_value=Vector((0, 0, -1)),
            ),
            mock.patch.object(
                ratings.view3d_utils,
                "region_2d_to_origin_3d",
                return_value=Vector((0, 0, 10)),
            ),
        ):
            self.assertEqual(ratings._asset_under_cursor(ctx, _event()), (None, None))


if __name__ == "__main__":
    unittest.main()
