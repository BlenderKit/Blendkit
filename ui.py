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

import logging
import os
from typing import Any

import bpy
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty, StringProperty

from . import (
    colors,
    global_vars,
    keymap_utils,
    paths,
    search,
    ui_bgl,
    utils,
)


draw_time = 0
eval_time = 0

bk_logger = logging.getLogger(__name__)

verification_icons = {
    "ready": "vs_ready.png",
    "deleted": "vs_deleted.png",
    "uploaded": "vs_uploaded.png",
    "uploading": "vs_uploading.png",
    "on_hold": "vs_on_hold.png",
    "validated": None,
    "rejected": "vs_rejected.png",
}


def get_approximate_text_width(st):
    size = 10
    for s in st:
        if s in "i|":
            size += 2
        elif s in " ":
            size += 4
        elif s in "sfrt":
            size += 5
        elif s in "ceghkou":
            size += 6
        elif s in "PadnBCST3E":
            size += 7
        elif s in "GMODVXYZ":
            size += 8
        elif s in "w":
            size += 9
        elif s in "m":
            size += 10
        else:
            size += 7
    return size  # Convert to picas


def draw_text_block(
    x=0, y=0, width=40, font_size=10, line_height=15, text="", color=colors.TEXT
):
    lines = text.split("\n")
    nlines = []
    for l in lines:
        nlines.extend(
            search.split_subs(
                l,
            )
        )

    column_lines = 0
    for l in nlines:
        ytext = y - column_lines * line_height
        column_lines += 1
        ui_bgl.draw_text(l, x, ytext, font_size, color)


def get_large_thumbnail_path(asset_data) -> str:
    """Cache path of the large thumbnail file in the search temp dir (may not exist yet)."""
    thumbnail = asset_data.get("thumbnail")
    if not thumbnail:
        return ""
    ui_props = bpy.context.window_manager.blenderkitUI
    # Use the asset's own type, not the currently active UI asset type: these can
    # differ (e.g. the rating nudge popup rates an asset outside the current search).
    asset_type = asset_data.get("assetType") or ui_props.asset_type
    directory = paths.get_temp_dir(f"{asset_type.lower()}_search")
    if not directory:
        return ""
    return os.path.join(directory, thumbnail)


def get_large_thumbnail_image(asset_data):
    """Get thumbnail image from asset data"""
    ui_props = bpy.context.window_manager.blenderkitUI
    iname = utils.previmg_name(ui_props.active_index, fullsize=True)
    tpath = get_large_thumbnail_path(asset_data)
    image_ready = global_vars.DATA["images available"].get(tpath)
    # "images available" is only populated while thumbnails download in the current
    # session; fall back to the cached file on disk so previously downloaded thumbnails
    # (e.g. for a rating nudge) still show instead of a permanent "loading" placeholder.
    if image_ready is None and tpath and os.path.exists(tpath):
        image_ready = True
    if image_ready is False or not tpath:
        tpath = paths.get_addon_thumbnail_path("thumbnail_not_available.jpg")
    elif image_ready is None:
        tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")

    img = utils.get_hidden_image(tpath, iname, colorspace="")
    return img


def get_full_thumbnail_variant(asset_data, variant: str):
    """Get full thumbnail variant from asset data.

    Args:
        asset_data: The asset data dictionary.
        variant (str): The variant type to retrieve ('photo' or 'wire').
    Returns:
        The Blender image object for the requested variant, or None if not found.
    """
    # Find the file corresponding to the requested variant
    file_data = None
    for file in asset_data.get("files", []):
        if file.get("fileType") == f"{variant.lower()}_thumbnail":
            file_data = file
            break

    if file_data is None:
        bk_logger.log(1, f"No {variant} thumbnail file found in asset data")
        return None

    file_url = file_data.get("thumbnailMiddleUrl")
    if file_url is None:
        bk_logger.warning(f"No thumbnail URL found in {variant} file")
        return None

    # Get the directory and construct the path
    ui_props = bpy.context.window_manager.blenderkitUI
    directory = paths.get_temp_dir(f"{ui_props.asset_type.lower()}_search")
    file_name = os.path.basename(file_url)
    tpath = os.path.join(directory, file_name)

    # Check if the download succeeded/failed via the images available dict
    image_ready = global_vars.DATA["images available"].get(tpath)
    if image_ready is False:
        bk_logger.debug(f"{variant} thumbnail download failed: {tpath}")
        return None
    if image_ready is None:
        bk_logger.log(1, f"{variant} thumbnail not yet downloaded: {tpath}")
        return None

    # Load the image into Blender (get_hidden_image handles missing files with a placeholder)
    img = utils.get_hidden_image(tpath, file_name, colorspace="")
    bk_logger.debug(f"{variant} thumbnail loaded from path: {tpath}")
    return img


def get_full_photo_thumbnail(asset_data):
    """Get full photo thumbnail from asset data. This is different from the large thumbnail
    as the photo_thumbnails are not available on the asset data root, but inside the files[].
    We need to get the data from files[] where assetType=='photo_thumbnail'."""
    # Find the photo thumbnail file
    thumb = get_full_thumbnail_variant(asset_data, "photo")
    return thumb


def get_full_wire_thumbnail(asset_data):
    """Get full wireframe thumbnail from asset data."""
    # Find the photo thumbnail file
    thumb = get_full_thumbnail_variant(asset_data, "wire")
    return thumb


def is_rating_possible() -> tuple[bool, bool, Any, Any]:
    # TODO remove this, but first check and reuse the code for new rating system...
    ao = bpy.context.active_object
    ui = bpy.context.window_manager.blenderkitUI  # type: ignore[attr-defined]
    preferences = bpy.context.preferences.addons[__package__].preferences  # type: ignore
    # first test if user is logged in.
    if preferences.api_key == "":  # type: ignore
        return False, False, None, None
    if global_vars.RATINGS is not None and ui.down_up == "SEARCH":
        if bpy.context.mode in ("SCULPT", "PAINT_TEXTURE"):
            b = utils.get_active_brush()
            ad = b.get("asset_data")
            if ad is not None:
                rated = bpy.context.scene["assets rated"].get(ad["assetBaseId"])  # type: ignore
                return True, rated, b, ad
        if ao is not None:
            ad = None
            # crawl parents to reach active asset. there could have been parenting so we need to find the first onw
            ao_check = ao
            while ad is None or (ad is None and ao_check.parent is not None):
                s = bpy.context.scene
                ad = ao_check.get("asset_data")  # type: ignore[attr-defined]
                if ad is not None and ad.get("assetBaseId") is not None:
                    s["assets rated"] = s.get("assets rated", {})  # type: ignore
                    rated = s["assets rated"].get(ad["assetBaseId"])  # type: ignore
                    # originally hidden for already rated assets
                    return True, rated, ao_check, ad
                elif ao_check.parent is not None:
                    ao_check = ao_check.parent
                else:
                    break
            # check also materials
            m = ao.active_material
            if m is not None:
                ad = m.get("asset_data")  # type: ignore

                if ad is not None and ad.get("assetBaseId"):
                    rated = bpy.context.scene["assets rated"].get(ad["assetBaseId"])  # type: ignore
                    return True, rated, m, ad

        # if t>2 and t<2.5:
        #     ui_props.rating_on = False

    return False, False, None, None


def mouse_in_region(r, mx, my):
    if 0 < my < r.height and 0 < mx < r.width:
        return True
    else:
        return False


class ParticlesDropDialog(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "object.blenderkit_particles_drop"
    bl_label = "Blendkit particle plants object drop"
    bl_options = {"REGISTER", "INTERNAL"}

    asset_search_index: IntProperty(  # type: ignore[valid-type]
        name="Asset index",
        description="Index of the asset in asset bar",
        default=0,
    )

    model_location: FloatVectorProperty(name="Location", default=(0, 0, 0))  # type: ignore[valid-type]

    model_rotation: FloatVectorProperty(  # type: ignore[valid-type]
        name="Rotation", default=(0, 0, 0), subtype="QUATERNION"
    )

    target_object: StringProperty(  # type: ignore[valid-type]
        name="Target object",
        description="The object to which the particles will get applied",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports ui)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        layout = self.layout
        message = (
            "This asset is a particle setup. Blendkit can apply particles to the active/drag-drop object."
            "The number of particles is calculated automatically, but if there are too many particles,"
            " Blendkit can do the following steps to make sure Blender continues to run:\n"
            "\n1.Switch to bounding box view of the particles."
            "\n2.Turn down number of particles that are shown in the view."
            "\n3.Hide the particle system completely from the 3D view."
            "as a result of this, it's possible you'll see the particle setup only in render view or "
            "rendered images. You should still be careful and test particle systems on smaller objects first."
        )
        utils.label_multiline(layout, text=message, width=600)
        row = layout.row()
        op = row.operator("scene.blenderkit_download", text="Append as plane")
        op.tooltip = "Append particles as stored in the asset file.\n You can link the particles to your target object manually"
        op.asset_index = self.asset_search_index
        op.model_location = self.model_location
        op.model_rotation = self.model_rotation
        op.target_object = ""
        op.replace = False
        op.replace_resolution = False

        op = row.operator("scene.blenderkit_download", text="Append on target")
        op.tooltip = (
            "Append and adjust particles counts automatically to the target object."
        )
        op.asset_index = self.asset_search_index
        op.model_location = self.model_location
        op.model_rotation = self.model_rotation
        op.target_object = self.target_object
        op.replace = False
        op.replace_resolution = False

    def execute(self, context):
        wm = context.window_manager
        return wm.invoke_popup(self, width=600)


# class MaterialDropDialog(bpy.types.Operator):
#     """Tooltip"""
#     bl_idname = "object.blenderkit_material_drop"
#     bl_label = "Blendkit material drop on linked objects"
#     bl_options = {'REGISTER', 'INTERNAL'}
#
#     asset_search_index: IntProperty(name="Asset index",
#                                     description="Index of the asset in asset bar",
#                                     default=0,
#                                     )
#
#     model_location: FloatVectorProperty(name="Location",
#                                         default=(0, 0, 0))
#
#     model_rotation: FloatVectorProperty(name="Rotation",
#                                         default=(0, 0, 0),
#                                         subtype='QUATERNION')
#
#     target_object: StringProperty(
#         name="Target object",
#         description="The object to which the particles will get applied",
#         default="", options={'SKIP_SAVE'})
#
#     target_material_slot: IntProperty(name="Target material slot",
#                                     description="Index of the material on the object to be changed",
#                                     default=0,
#                                     )
#
#     @classmethod
#     def poll(cls, context):
#         return True
#
#     def draw(self, context):
#         layout = self.layout
#         message = "This asset is linked to the scene from an external file and cannot have material appended." \
#                   " Do you want to bring it into Blender Scene?"
#         utils.label_multiline(layout, text=message, width=400)
#
#     def execute(self, context):
#         for c in bpy.data.collections:
#             for o in c.objects:
#                 if o.name != self.target_object:
#                     continue;
#                 for empty in bpy.context.visible_objects:
#                     if not(empty.instance_type == 'COLLECTION' and empty.instance_collection == c):
#                         continue;
#                     utils.activate(empty)
#                     break;
#         bpy.ops.object.blenderkit_bring_to_scene()
#         bpy.ops.scene.blenderkit_download(True,
#                                           # asset_type=ui_props.asset_type,
#                                           asset_index=self.asset_search_index,
#                                           model_location=self.model_rotation,
#                                           model_rotation=self.model_rotation,
#                                           target_object=self.target_object,
#                                           material_target_slot = self.target_slot)
#         return {'FINISHED'}
#
#     def invoke(self, context, event):
#         wm = context.window_manager
#         return wm.invoke_props_dialog(self, width=400)


class TransferBlenderkitData(bpy.types.Operator):
    """Regenerate cobweb"""

    bl_idname = "object.blenderkit_data_trasnfer"
    bl_label = "Transfer Blendkit data"
    bl_description = "Transfer Blendkit metadata from one object to another when fixing uploads with wrong parenting"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source_ob = bpy.context.active_object
        for target_ob in bpy.context.selected_objects:
            if target_ob != source_ob:
                # target_ob.property_unset('blenderkit')
                for k in source_ob.blenderkit.keys():
                    if k in ("name",):
                        continue
                    target_ob.blenderkit[k] = source_ob.blenderkit[k]
        # source_ob.property_unset('blenderkit')
        return {"FINISHED"}


class ModalTimerOperator(bpy.types.Operator):
    """Operator which runs its self from a timer"""

    bl_idname = "wm.modal_timer_operator"
    bl_label = "Modal Timer Operator"

    _timer = None

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self.cancel(context)
            return {"CANCELLED"}

        if event.type == "TIMER":
            # change theme color, silly!
            color = context.preferences.themes[0].view_3d.space.gradients.high_gradient
            color.s = 1.0
            color.h += 0.01

        return {"PASS_THROUGH"}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


class AssetBarModalStarter(bpy.types.Operator):
    """Needed for starting asset bar with correct context"""

    bl_idname = "view3d.run_assetbar_start_modal"
    bl_label = "Blendkit assetbar modal starter"
    bl_description = "Assetbar modal starter"
    bl_options = {"INTERNAL"}

    keep_running: BoolProperty(  # type: ignore[valid-type]
        name="Keep Running", description="", default=True, options={"SKIP_SAVE"}
    )
    do_search: BoolProperty(  # type: ignore[valid-type]
        name="Run Search", description="", default=False, options={"SKIP_SAVE"}
    )
    _timer = None

    def modal(self, context, event):
        if event.type == "TIMER":
            # change theme color, silly!
            if bpy.app.version < (4, 0, 0):
                C_dict = bpy.context.copy()  # let's try to get the right context
                bpy.ops.view3d.blenderkit_asset_bar_widget(
                    C_dict,
                    "INVOKE_REGION_WIN",
                    keep_running=self.keep_running,
                    do_search=self.do_search,
                )
            else:
                bpy.ops.view3d.blenderkit_asset_bar_widget(
                    "INVOKE_REGION_WIN",
                    keep_running=self.keep_running,
                    do_search=self.do_search,
                )
            self.cancel(context)
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


class RunAssetBarWithContext(bpy.types.Operator):
    """This operator can run from a timer and assign a context to modal starter"""

    bl_idname = "view3d.run_assetbar_fix_context"
    bl_label = "Blendkit assetbar with fixed context"
    bl_description = "Run assetbar with fixed context"
    bl_options = {"INTERNAL"}

    keep_running: BoolProperty(  # type: ignore[valid-type]
        name="Keep Running", description="", default=True, options={"SKIP_SAVE"}
    )
    do_search: BoolProperty(  # type: ignore[valid-type]
        name="Run Search", description="", default=False, options={"SKIP_SAVE"}
    )

    # def modal(self, context, event):
    #     return {'RUNNING_MODAL'}

    def execute(self, context):
        # possibly only since blender 3.0?
        # if check_context(context):
        #     bpy.ops.view3d.blenderkit_asset_bar_widget('INVOKE_REGION_WIN', keep_running=self.keep_running,
        #                                            do_search=self.do_search)

        C_dict = utils.get_fake_context()

        if bpy.app.version < (4, 0, 0):
            if C_dict.get("window"):  # no 3d view, no asset bar.
                bpy.ops.view3d.run_assetbar_start_modal(
                    C_dict, keep_running=self.keep_running, do_search=self.do_search
                )
        else:
            with context.temp_override(**C_dict):
                bpy.ops.view3d.run_assetbar_start_modal(
                    keep_running=self.keep_running, do_search=self.do_search
                )

        return {"FINISHED"}


classes = (
    AssetBarModalStarter,
    RunAssetBarWithContext,
    TransferBlenderkitData,
    ParticlesDropDialog,
)


# @persistent
def pre_load(context):
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.assetbar_on = False
    ui_props.turn_off = True
    # TODO: is this needed?
    # preferences = bpy.context.preferences.addons[__package__].preferences
    # preferences.login_attempt = False


def register_ui():
    for c in classes:
        bpy.utils.register_class(c)

    keymap_utils.register_keymaps()


def unregister_ui():
    pre_load(bpy.context)

    for c in classes:
        bpy.utils.unregister_class(c)

    keymap_utils.unregister_keymaps()
