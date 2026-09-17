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

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the
# ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]


class TestOperatorsRegistered(unittest.TestCase):
    """Verify key operators from each module are registered."""

    OPERATORS = [
        # ui.py
        "view3d.run_assetbar_fix_context",
        "view3d.run_assetbar_start_modal",
        # ui_panels.py
        "wm.blenderkit_welcome",
        "wm.blenderkit_popup_dialog",
        "wm.blenderkit_url_dialog",
        "wm.blenderkit_login_dialog",
        "wm.blenderkit_show_validation_popup",
        "wm.blenderkit_mark_notification_read",
        "wm.blenderkit_open_addon_directory",
        "wm.blenderkit_asset_popup",
        "view3d.blenderkit_set_category",
        "view3d.blenderkit_clear_search_keywords",
        # asset_bar_op.py
        "view3d.blenderkit_asset_bar_widget",
        # asset_drag_op.py
        "view3d.asset_drag_drop",
        # download.py
        "scene.blenderkit_download",
        "scene.blenderkit_download_kill",
        # upload.py
        "object.blenderkit_upload",
        "wm.blenderkit_fast_metadata",
        # search.py
        "view3d.blenderkit_search",
        # ratings.py
        "wm.blenderkit_menu_rating_upload",
        "wm.blenderkit_bookmark_asset",
        # autothumb.py
        "object.blenderkit_generate_thumbnail",
        "object.blenderkit_generate_material_thumbnail",
    ]

    def test_operators_exist(self):
        for op_idname in self.OPERATORS:
            category, name = op_idname.split(".")
            ops_category = getattr(bpy.ops, category, None)
            self.assertIsNotNone(ops_category, f"bpy.ops.{category} not found")
            self.assertTrue(
                hasattr(ops_category, name),
                f"Operator {op_idname} not registered",
            )


class TestPanelsRegistered(unittest.TestCase):
    """Verify key panels are registered as bpy.types."""

    PANELS = [
        "VIEW3D_PT_blenderkit_unified",
        "VIEW3D_PT_blenderkit_downloads",
        "VIEW3D_PT_blenderkit_profile",
        "VIEW3D_PT_blenderkit_categories",
        "VIEW3D_PT_blenderkit_import_settings",
        "VIEW3D_PT_blenderkit_model_properties",
        "VIEW3D_PT_blenderkit_advanced_model_search",
        "VIEW3D_PT_blenderkit_advanced_material_search",
        "VIEW3D_PT_blenderkit_advanced_scene_search",
        "VIEW3D_PT_blenderkit_advanced_brush_search",
        "VIEW3D_PT_blenderkit_advanced_HDR_search",
        "VIEW3D_PT_blenderkit_advanced_nodegroup_search",
        "VIEW3D_PT_blenderkit_advanced_printable_search",
        "VIEW3D_PT_blenderkit_advanced_addon_search",
        "VIEW3D_PT_blenderkit_advanced_author_search",
    ]

    def test_panels_exist(self):
        for panel_name in self.PANELS:
            self.assertTrue(
                hasattr(bpy.types, panel_name),
                f"Panel {panel_name} not registered",
            )


class TestPointerPropertiesRegistered(unittest.TestCase):
    """Verify PointerProperties are set on Blender types."""

    PROPERTIES = [
        (bpy.types.WindowManager, "blenderkitUI"),
        (bpy.types.WindowManager, "blenderkit_models"),
        (bpy.types.WindowManager, "blenderkit_scene"),
        (bpy.types.WindowManager, "blenderkit_HDR"),
        (bpy.types.WindowManager, "blenderkit_mat"),
        (bpy.types.WindowManager, "blenderkit_brush"),
        (bpy.types.WindowManager, "blenderkit_nodegroup"),
        (bpy.types.WindowManager, "blenderkit_addon"),
        (bpy.types.Object, "blenderkit"),
        (bpy.types.Scene, "blenderkit"),
        (bpy.types.Image, "blenderkit"),
        (bpy.types.Material, "blenderkit"),
        (bpy.types.Brush, "blenderkit"),
    ]

    def test_pointer_properties_exist(self):
        for bpy_type, prop_name in self.PROPERTIES:
            self.assertTrue(
                hasattr(bpy_type, prop_name),
                f"{bpy_type.__name__}.{prop_name} not registered",
            )


class TestPreferencesAccessible(unittest.TestCase):
    """Verify addon preferences are accessible and have key attributes."""

    def test_preferences_exist(self):
        prefs = bpy.context.preferences.addons[__package__].preferences
        self.assertIsNotNone(prefs)

    def test_preferences_attributes(self):
        prefs = bpy.context.preferences.addons[__package__].preferences
        for attr in ("api_key", "global_dir", "thumb_size", "client_port"):
            self.assertTrue(
                hasattr(prefs, attr),
                f"Preference attribute '{attr}' missing",
            )
