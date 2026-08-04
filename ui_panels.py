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


from __future__ import annotations

import logging
import os
import platform
import random
import sys
import time
from typing import Any
from urllib.parse import quote
from webbrowser import open_new_tab

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Context, Menu, Panel, UILayout

from .asset_bar import asset_bar_op
from . import (
    addon_updater_ops,
    autothumb,
    categories,
    client_lib,
    comments_utils,
    datas,
    download,
    global_vars,
    icons,
    image_utils,
    keymap_utils,
    paths,
    ratings,
    ratings_utils,
    search,
    ui,
    upload,
    utils,
)

ACCEPTABLE_ENGINES = ("CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")

bk_logger = logging.getLogger(__name__)

# Images currently being drawn by AssetPopupCard (protected from timer_image_cleanup).
# Populated during draw(), cleared each timer_image_cleanup() cycle.
_protected_images: set[str] = set()

# Maximum length for manufacturer labels before truncation (e.g. "Ford motor company")
MAX_MANUFACTURER_LABEL_LEN = 17

INVALID_TOKENS = {
    "me",
    "unknown",
    "self",
    "none",
    "n/a",
}

last_time_overlay_panel_active = 0.0


def set_overlay_panel_active():
    """Record the time a BlenderKit popup/panel/popover was last drawn.

    This is read in asset_bar_op.py to cancel asset drag-drop and to ignore
    keyboard shortcuts for a short window afterwards. Without it, click-through
    events that pass through a popup down to the asset bar underneath would be
    wrongly interpreted as clicks/double-clicks on the asset bar.

    Every operator popup, dialog and popover that can appear over the asset bar
    should call this at the start of its draw() method.
    """
    global last_time_overlay_panel_active
    last_time_overlay_panel_active = time.time()


def draw_not_logged_in(source, message="Please Login/Signup to use this feature"):
    title = "You aren't logged in"

    def draw_message(source, context):
        set_overlay_panel_active()
        layout = source.layout
        utils.label_multiline(layout, text=message)
        draw_login_buttons(layout)

    bpy.context.window_manager.popup_menu(draw_message, title=title, icon="INFO")


def draw_upload_common(layout, props, asset_type, context):
    if asset_type == "MODEL":
        url = paths.BLENDKIT_MODEL_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "MATERIAL":
        url = paths.BLENDKIT_MATERIAL_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "BRUSH":
        url = paths.BLENDKIT_BRUSH_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "SCENE":
        url = paths.BLENDKIT_SCENE_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "HDR":
        url = paths.BLENDKIT_HDR_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "NODEGROUP":
        url = ""  # paths.BLENDKIT_NODEGROUP_UPLOAD_INSTRUCTIONS_URL
    if asset_type == "PRINTABLE":
        url = (
            paths.BLENDKIT_PRINTABLE_UPLOAD_INSTRUCTIONS_URL
        )  # Reuse model instructions since prints are similar
    if asset_type == "ADDON":
        url = paths.BLENDKIT_ADDON_UPLOAD_INSTRUCTIONS_URL
    op = layout.operator(
        "wm.url_open", text=f"Read {asset_type} upload instructions", icon="QUESTION"
    )
    op.url = paths.url_with_utm(url, "upload_docs") if url else url

    row = layout.row(align=True)
    if props.upload_state != "":
        state_lower = props.upload_state.lower()
        is_error = any(
            k in state_lower
            for k in (
                "error",
                "fail",
                "exceed",
                "denied",
                "invalid",
                "remaining",
                "quota",
            )
        )
        if is_error:
            box = layout.box()
            box.alert = True
            utils.label_multiline(
                box,
                text=props.upload_state,
                icon="ERROR",
                width=context.region.width,
            )
        else:
            utils.label_multiline(
                layout, text=props.upload_state, width=context.region.width
            )
    if props.uploading:
        op = layout.operator("object.kill_bg_process", text="", icon="CANCEL")
        op.process_source = asset_type
        op.process_type = "UPLOAD"
        layout = layout.column()
        layout.enabled = False

    # PRE-RELEASED WARNING
    if props.is_private == "PUBLIC" and bpy.app.version_cycle != "release":
        layout.row()
        utils.label_multiline(
            layout,
            text="Uploading from Alpha, Beta, or Release Candidate versions of Blender is not recommended. Please use a Stable version.",
            icon="ERROR",
            width=210,
        )

    if props.asset_base_id == "":
        optext = "Upload %s" % asset_type.lower()
        op = layout.operator("object.blenderkit_upload", text=optext, icon="EXPORT")
        op.asset_type = asset_type
        op.reupload = False
        # make sure everything gets uploaded.
        op.main_file = True
        op.metadata = True
        op.thumbnail = True

    if utils.profile_is_validator():
        op = layout.operator(
            "object.blenderkit_dry_run_export",
            text="Dry Run Export (validator)",
            icon="CHECKBOX_HLT",
        )
        op.asset_type = asset_type

    if props.asset_base_id != "":
        op = layout.operator(
            "wm.blenderkit_url", text="Edit Details", icon="GREASEPENCIL"
        )
        op.url = paths.url_with_utm(
            f"{paths.BLENDKIT_USER_ASSETS_URL}/{props.asset_base_id}/?edit#",
            "uploads_edit",
        )

        op = layout.operator(
            "object.blenderkit_upload", text="Reupload asset", icon="EXPORT"
        )
        op.asset_type = asset_type
        op.reupload = True

        op = layout.operator(
            "object.blenderkit_upload", text="Upload as new asset", icon="EXPORT"
        )
        op.asset_type = asset_type
        op.reupload = False

        layout.label(text="asset has a version online.")

    row = layout.row()
    if props.is_private == "PUBLIC" and props.category == "NONE":
        row.alert = True
    row.prop(props, "category")
    if props.category != "NONE" and props.subcategory != "EMPTY":
        row = layout.row()
        if props.is_private == "PUBLIC" and props.subcategory == "NONE":
            row.alert = True
        row.prop(props, "subcategory")
    if props.subcategory != "NONE" and props.subcategory1 != "EMPTY":
        row = layout.row()
        if props.is_private == "PUBLIC" and props.subcategory1 == "NONE":
            row.alert = True
        row.prop(props, "subcategory1")

    layout.prop(props, "is_private", expand=True)
    if props.is_private == "PUBLIC":
        layout.prop(props, "license")
        layout.prop(props, "is_free", expand=True)

    prop_needed(layout, props, "name", props.name)
    if props.is_private == "PUBLIC":
        prop_needed(layout, props, "description", props.description)
        prop_needed(layout, props, "tags", props.tags)
    else:
        layout.prop(props, "description")
        layout.prop(props, "tags")


def prop_needed(layout, props, name, value: Any = "", is_not_filled: Any = ""):
    row = layout.row()
    if value == is_not_filled:
        row.alert = True
        row.prop(props, name)  # , icon="ERROR")
        row.alert = False
    else:
        row.prop(props, name)


class BLENDERKIT_OT_show_validation_popup(bpy.types.Operator):
    bl_idname = "wm.blenderkit_show_validation_popup"
    bl_label = "Manufacturer Validation Result"
    bl_options = {"REGISTER", "INTERNAL"}

    message: StringProperty(name="Message", default="", options={"SKIP_SAVE"})  # type: ignore

    def invoke(self, context, event):
        # Ensure we always have something to show so the dialog renders on older Blender versions.
        if not self.message:
            self.message = "No validation output available."
        return context.window_manager.invoke_props_dialog(self, width=500)

    def execute(self, context):
        # The dialog is read-only; nothing to execute beyond closing it.
        return {"FINISHED"}

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        clean_text = self.message.replace("\r\n", "\n").replace("\r", "\n")
        # Keep rendering even if the text is short or empty.
        if not clean_text.strip():
            layout.label(text="No validation output available.")
            return

        for paragraph in clean_text.split("\n"):
            utils.label_multiline(layout, text=paragraph, width=480)


class BLENDERKIT_OT_permissions_error_popup(bpy.types.Operator):
    """Show a large centered dialog when Blendkit cannot write to the asset directory.
    Dynamically updates to show success when the path is fixed.
    """

    bl_idname = "wm.blenderkit_permissions_error_popup"
    bl_label = "Blendkit - Directory Permission Error"
    bl_options = {"REGISTER", "INTERNAL"}

    error_message: StringProperty(name="Error", default="", options={"SKIP_SAVE"})  # type: ignore
    directory_path: StringProperty(name="Path", default="", options={"SKIP_SAVE"})  # type: ignore

    def invoke(self, context, event):
        wm = context.window_manager
        try:
            return wm.invoke_props_dialog(
                self, width=600, confirm_text="Open Preferences"
            )
        except TypeError:
            return wm.invoke_props_dialog(self, width=600)

    def execute(self, context):
        # Check if path is already fixed (e.g. user clicked Set Default Folder)
        current_dir = context.preferences.addons[__package__].preferences.global_dir
        current_dir = os.path.normpath(bpy.path.abspath(current_dir))
        current_ok, _ = utils._check_dir_permissions(current_dir, "Global directory")
        if not current_ok:
            bpy.ops.preferences.addon_show(module=__package__)
        return {"FINISHED"}

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout

        # Light check for live UI — draw() runs on each redraw, avoid file I/O here
        current_dir = context.preferences.addons[__package__].preferences.global_dir
        current_dir = os.path.normpath(bpy.path.abspath(current_dir))
        current_ok = os.path.isdir(current_dir)

        if current_ok:
            # === PATH IS NOW FIXED — show success ===
            layout.separator()
            row = layout.row()
            row.scale_y = 2.0
            row.alert = False
            row.label(text="  Directory is now accessible!", icon="CHECKMARK")
            layout.separator()
            layout.label(text=f"Path: {current_dir}")
            layout.separator()
            layout.label(text="You can close this dialog now.")
            return

        # === PATH IS BROKEN — show big red warning ===
        # Large red alert header
        box_header = layout.box()
        box_header.alert = True
        row = box_header.row()
        row.scale_y = 2.0
        row.alignment = "CENTER"
        row.label(text="  CANNOT ACCESS DOWNLOAD FOLDER  ", icon="ERROR")

        layout.separator()

        # Error details
        clean_text = self.error_message.replace("\r\n", "\n").replace("\r", "\n")
        for paragraph in clean_text.split("\n"):
            if paragraph.strip():
                utils.label_multiline(layout, text=paragraph, width=560)

        layout.separator()

        # === Fix options ===
        box = layout.box()
        box.label(text="How to fix this:", icon="TOOL_SETTINGS")
        box.separator(factor=0.5)

        # Option 1: Set default folder (show if parent dir exists)
        default_dir = paths.default_global_dict()
        default_parent = os.path.dirname(default_dir)
        if os.path.isdir(default_dir) or os.path.isdir(default_parent):
            row = box.row()
            row.scale_y = 1.5
            row.operator(
                "wm.blenderkit_set_default_directory",
                text=f"  Set Default Folder:  {default_dir}  ",
                icon="CHECKMARK",
            )
            box.separator(factor=0.5)

        # Option 2: Open preferences
        col = box.column(align=True)
        col.label(text="Or click 'Open Preferences' below to choose a folder manually.")

        layout.separator()

        # Current broken path
        row = layout.row()
        row.alert = True
        row.label(text=f"Current folder: {self.directory_path}", icon="INFO")


class BLENDERKIT_OT_set_default_directory(bpy.types.Operator):
    """Set the Global Directory to the default blenderkit_data folder"""

    bl_idname = "wm.blenderkit_set_default_directory"
    bl_label = "Set Default Folder"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        default_dir = paths.default_global_dict()
        ok, message = utils._check_dir_permissions(default_dir, "Default directory")
        if not ok:
            self.report({"ERROR"}, f"Default folder is not writable: {message}")
            return {"CANCELLED"}

        preferences = context.preferences.addons[__package__].preferences
        preferences.global_dir = default_dir
        self.report({"INFO"}, f"Global directory set to: {default_dir}")
        utils.restart_client_after_path_fix()
        return {"FINISHED"}


def draw_validated_manufacturer(
    layout: bpy.types.UILayout, asset: Any, props: Any = None
) -> None:
    """Show manufacturer validation output when present on an asset's dictParameters."""
    if asset is None:
        return

    asset_data = None
    try:
        if hasattr(asset, "get"):
            asset_data = asset.get("asset_data")
    except Exception:
        asset_data = None

    if asset_data is None:
        asset_data = getattr(asset, "asset_data", None)

    if not asset_data:
        return

    validated_output = asset_data.get("dictParameters", {}).get(
        "validatedManufacturerOutput"
    )
    if not validated_output:
        return

    box = layout.box()
    row = box.row(align=True)
    row.label(text="Manufacturer validation", icon="ERROR")
    row.operator_context = "INVOKE_DEFAULT"
    op = row.operator(
        "wm.blenderkit_show_validation_popup",
        text="Show result",
        icon="VIEWZOOM",
        emboss=True,
    )
    op.message = str(validated_output)


def draw_panel_hdr_upload(self, context):
    layout = self.layout
    ui_props = bpy.context.window_manager.blenderkitUI

    layout.prop(ui_props, "hdr_upload_image")

    tone_box = layout.box()
    tone_box.label(text="Thumbnail Conversion", icon="IMAGE_RGB")
    tone_box.prop(ui_props, "hdr_use_custom_thumbnail_tone")

    hdr = utils.get_active_HDR()

    if hdr is not None:
        props = hdr.blenderkit

        layout = self.layout

        draw_upload_common(layout, props, "HDR", context)


def draw_search_text_field(
    layout: UILayout, ui_props: Any, context: bpy.types.Context
) -> None:
    """Draw the search text field and asset bar toggle for asset search panels."""
    row = layout.row(align=True)

    kwargs = {"text": "", "icon": "VIEWZOOM"}
    if bpy.app.version >= (4, 2, 0):
        kwargs["placeholder"] = "Search Blendkit"
    row.prop(ui_props, "search_keywords", **kwargs)

    if (context.region.width) > 700:
        row.ui_units_x = 5 + int(context.region.width / 200)
    search_field_width = bpy.context.preferences.addons[
        __package__
    ].preferences.search_field_width

    has_search_keywords = ui_props.search_keywords != ""

    if search_field_width > 0:
        row.ui_units_x = search_field_width - has_search_keywords * 0.5

    # if there are search keywords, draw an x icon to clear the search keywords
    if has_search_keywords:
        row.operator("view3d.blenderkit_clear_search_keywords", text="", icon="X")

    shortcut = keymap_utils.get_shortcut_label(
        "view3d.run_assetbar_fix_context", fallback=""
    )
    shortcut_hint = f"\nShortcut: {shortcut}" if shortcut else ""

    if ui_props.assetbar_on:
        icon = "HIDE_OFF"
        ttip = f"Click to Hide Asset Bar.{shortcut_hint}"
    else:
        icon = "HIDE_ON"
        ttip = f"Click to Show Asset Bar.{shortcut_hint}"

    op = row.operator("view3d.blenderkit_asset_bar_widget", text="", icon=icon)
    op.keep_running = False
    op.do_search = False
    op.tooltip = ttip


def draw_panel_hdr_search(self, context):
    s = context.scene
    wm = context.window_manager
    props = wm.blenderkit_HDR
    ui_props = wm.blenderkitUI

    layout = self.layout
    draw_search_text_field(
        layout, ui_props, context
    )  # Ensure search field is drawn in HDR search panel
    utils.label_multiline(layout, text=props.report)


def draw_panel_addon_search(self, context):
    wm = context.window_manager
    ui_props = wm.blenderkitUI
    addon_props = wm.blenderkit_addon

    layout = self.layout
    draw_search_text_field(
        layout, ui_props, context
    )  # Ensure search field is drawn in addon search panel
    utils.label_multiline(layout, text=addon_props.report)


def draw_panel_author_search(self, context):
    wm = context.window_manager
    ui_props = wm.blenderkitUI
    author_props = wm.blenderkit_author

    layout = self.layout
    draw_search_text_field(
        layout, ui_props, context
    )  # Ensure search field is drawn in author search panel
    utils.label_multiline(layout, text=author_props.report)


def draw_panel_nodegroup_upload(self, context):
    layout = self.layout
    ui_props = bpy.context.window_manager.blenderkitUI
    layout.enabled = True

    layout.template_ID(ui_props, "nodegroup_upload")
    nodegroup = utils.get_active_nodegroup()

    if nodegroup is not None:
        props = nodegroup.blenderkit

        layout = self.layout

        draw_upload_common(layout, props, "NODEGROUP", context)
        layout.prop(props, "thumbnail")


def draw_panel_nodegroup_search(self, context):
    s = context.scene
    wm = context.window_manager
    props = wm.blenderkit_nodegroup
    ui_props = wm.blenderkitUI

    layout = self.layout
    draw_search_text_field(
        layout,
        ui_props,
        context,
    )  # Ensure search field is drawn in nodegroup search panel
    utils.label_multiline(layout, text=props.report)


def draw_common_filters(layout, ui_props):
    """Draw common filter elements shared by multiple asset type panels.

    Args:
        layout: The UI layout to draw in
        ui_props: The UI properties containing filter settings
    """
    # All "Search filters" panels are shown as popovers over the asset bar,
    # so record the redraw time to prevent click-through to the asset bar.
    set_overlay_panel_active()

    layout.separator()

    row = layout.row()
    row.prop(ui_props, "search_bookmarks", text="Bookmarks", icon="BOOKMARKS")
    row.prop(ui_props, "own_only", icon="USER")
    if ui_props.own_only:
        layout.prop(ui_props, "own_verification_status", text="Status", icon="LOCKED")
    layout.prop(ui_props, "free_only")
    layout.prop(ui_props, "quality_limit", slider=True)
    layout.prop(ui_props, "search_license")
    layout.prop(ui_props, "search_order_by")


def draw_thumbnail_upload_panel(layout, props):
    tex = autothumb.get_texture_ui(props.thumbnail, ".upload_preview")
    if not tex or not tex.image:
        return
    box = layout.box()
    box.template_icon(icon_value=tex.image.preview.icon_id, scale=6.0)


def draw_wire_thumbnail_upload_panel(layout, props):
    tex = autothumb.get_texture_ui(props.wire_thumbnail, ".upload_preview_wire")
    if not tex or not tex.image:
        return
    box = layout.box()
    box.template_icon(icon_value=tex.image.preview.icon_id, scale=6.0)


def draw_panel_model_upload(self, context):
    """Draw upload panel for model and printable assets"""
    ob = utils.get_active_model()
    while ob.parent is not None:
        ob = ob.parent
    props = ob.blenderkit

    layout = self.layout
    asset_type = bpy.context.window_manager.blenderkitUI.asset_type

    draw_upload_common(layout, props, asset_type, context)

    # Add the photo thumbnail field only for printable assets

    if asset_type == "PRINTABLE":
        layout.prop(props, "photo_thumbnail_will_upload_on_website")
        if not props.photo_thumbnail_will_upload_on_website:
            col = layout.column()
            prop_needed(col, props, "photo_thumbnail", props.photo_thumbnail)

    # Wireframe thumbnail is an experimental feature. When enabled, the regular
    # "Generate thumbnail" dialog exposes a Regular/Wireframe switch that renders
    # into this slot. The wireframe thumbnail is optional and only uploaded when a
    # valid image is provided here.
    wire_upload_enabled = utils.experimental_enabled()

    # Thumbnail previews. When the experimental wireframe feature is enabled show
    # the regular and wireframe previews side by side so both can be reviewed at
    # the same time; otherwise just show the regular preview.
    preview_row = layout.row()
    reg_preview = preview_row.column()
    reg_preview.enabled = not props.is_generating_thumbnail
    if wire_upload_enabled:
        reg_preview.label(text="Regular")
    draw_thumbnail_upload_panel(reg_preview, props)

    if wire_upload_enabled:
        wire_preview = preview_row.column()
        wire_preview.enabled = not getattr(props, "is_generating_wire_thumbnail", False)
        wire_preview.label(text="Wireframe")
        draw_wire_thumbnail_upload_panel(wire_preview, props)

    col = layout.column()

    if props.is_generating_thumbnail:
        col.enabled = False

    prop_needed(col, props, "thumbnail", props.thumbnail)
    # Thumbnail generation relies on the background thumbnailer which requires
    # Blender 4.2+, so only expose the button on supported versions.
    if bpy.context.scene.render.engine in ACCEPTABLE_ENGINES and bpy.app.version >= (
        4,
        2,
        0,
    ):
        col.operator_context = "INVOKE_DEFAULT"
        op = col.operator(
            "object.blenderkit_generate_thumbnail",
            text="Generate thumbnail",
            icon="IMAGE",
        )

    if wire_upload_enabled:
        col = layout.column()
        if getattr(props, "is_generating_wire_thumbnail", False):
            col.enabled = False
        col.prop(props, "wire_thumbnail")

    if props.is_generating_thumbnail:
        row = layout.row(align=True)
        row.label(text=props.thumbnail_generating_state)
        op = row.operator("object.kill_bg_process", text="", icon="CANCEL")
        op.process_source = asset_type
        op.process_type = "THUMBNAILER"
    elif props.thumbnail_generating_state != "":
        utils.label_multiline(layout, text=props.thumbnail_generating_state)

    # must be experimental feature enabled
    if wire_upload_enabled:
        if getattr(props, "is_generating_wire_thumbnail", False):
            row = layout.row(align=True)
            row.label(text=props.wire_thumbnail_generating_state)
            op = row.operator("object.kill_bg_process", text="", icon="CANCEL")
            op.process_source = asset_type
            op.process_type = "THUMBNAILER"
        elif getattr(props, "wire_thumbnail_generating_state", "") != "":
            utils.label_multiline(layout, text=props.wire_thumbnail_generating_state)

    # Only show these properties for MODEL type
    if asset_type == "MODEL":
        layout.prop(props, "style")
        layout.prop(props, "production_level")
        layout.prop(props, "condition")
        layout.prop(props, "pbr")

    design_box = layout.box()
    design_box.alignment = "EXPAND"
    design_box.label(text="Design properties:")
    design_box.prop(props, "manufacturer")
    design_box.prop(props, "designer")
    design_box.prop(props, "design_collection")
    design_box.prop(props, "design_variant")
    design_box.prop(props, "use_design_year")
    if props.use_design_year:
        design_box.prop(props, "design_year")

    # Show manufacturer validation feedback when available on the asset.
    draw_validated_manufacturer(design_box, ob)

    row = layout.row()
    row.prop(props, "work_hours")

    # CONTENT FLAGS
    content_flag_box = layout.box()
    content_flag_box.alignment = "EXPAND"
    content_flag_box.label(text="Sensitive Content Flags:")
    content_flag_box.prop(props, "sexualized_content")


def draw_panel_scene_upload(self, context):
    s = bpy.context.scene
    props = s.blenderkit

    layout = self.layout

    draw_upload_common(layout, props, "SCENE", context)

    col = layout.column()

    draw_thumbnail_upload_panel(col, props)

    prop_needed(col, props, "thumbnail", props.has_thumbnail, False)

    layout.prop(props, "style")
    layout.prop(props, "production_level")
    layout.prop(props, "use_design_year")
    if props.use_design_year:
        layout.prop(props, "design_year")
    layout.prop(props, "condition")
    draw_validated_manufacturer(layout, s)
    row = layout.row()
    row.prop(props, "work_hours")


def draw_panel_model_search(self, context):
    wm = bpy.context.window_manager
    props = wm.blenderkit_models
    ui_props = wm.blenderkitUI

    layout = self.layout

    draw_search_text_field(layout, ui_props, context)

    icon = "NONE"
    if props.report == "You need Full plan to get this item.":
        icon = "ERROR"
    utils.label_multiline(layout, text=props.report, icon=icon)
    if props.report == "You need Full plan to get this item.":
        layout.operator("wm.url_open", text="Get Full plan", icon="URL").url = (
            paths.url_with_utm(paths.BLENDKIT_PLANS_URL, "premium_wall_panel")
        )


def draw_panel_scene_search(self, context):
    wm = bpy.context.window_manager
    props = wm.blenderkit_scene
    ui_props = wm.blenderkitUI
    layout = self.layout
    draw_search_text_field(layout, ui_props, context)
    utils.label_multiline(layout, text=props.report)
    layout.separator()


def draw_model_context_menu(self, context):
    # draw asset properties here
    layout = self.layout

    o = utils.get_active_model()
    if not o:
        return
    ad = utils.get_asset_data_from_ob(o)
    if ad is None:
        utils.label_multiline(
            layout,
            text="To upload this asset to Blendkit, go to the Find and Upload Assets panel.",
        )
        layout.prop(o, "name")
    else:
        layout.label(text=str(ad["name"]))
        if o.instance_type == "COLLECTION" and o.instance_collection is not None:
            layout.operator("object.blenderkit_bring_to_scene", text="Bring to scene")

        layout.label(text="Asset tools:")
        draw_asset_context_menu(self.layout, context, ad, from_panel=True)


class VIEW3D_PT_blenderkit_model_properties(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_model_properties"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Selected Model"
    bl_context = "objectmode"

    @classmethod
    def poll(cls, context):
        if bpy.context.view_layer.objects.active is None:
            return False
        preferences = bpy.context.preferences.addons[__package__].preferences
        return not preferences.sidebar_panels

    def draw(self, context):
        draw_model_context_menu(self, context)


class VIEW3D_MT_blenderkit_model_properties(Menu):
    bl_idname = "VIEW3D_MT_blenderkit_model_properties"
    bl_label = "Selected Model"

    def draw(self, context):
        draw_model_context_menu(self, context)


class NODE_PT_blenderkit_nodegroup_properties(Panel):
    bl_category = "Blendkit"
    bl_idname = "NODE_PT_blenderkit_nodegroup_properties"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_label = "Selected Geonode tool"

    @classmethod
    def poll(cls, context):
        if bpy.context.space_data.tree_type != "GeometryNodeTree":
            return False
        if not bpy.context.space_data.edit_tree:
            return False
        return bpy.context.space_data.edit_tree.is_tool

    def draw(self, context):
        # draw asset properties here
        layout = self.layout

        et = bpy.context.space_data.edit_tree
        if et.get("asset_data") is None:
            utils.label_multiline(
                layout,
                text="To upload this asset to Blendkit, go to the Find and Upload Assets panel.",
            )
            layout.prop(et, "name")

        if et.get("asset_data") is not None:
            ad = et["asset_data"]
            layout.label(text=str(ad["name"]))

            layout.label(text="Asset tools:")
            draw_asset_context_menu(self.layout, context, ad, from_panel=True)


class NODE_PT_blenderkit_material_properties(Panel):
    bl_category = "Blendkit"
    bl_idname = "NODE_PT_blenderkit_material_properties"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_label = "Selected Material"
    bl_context = "objectmode"

    @classmethod
    def poll(cls, context):
        if bpy.context.space_data.tree_type != "ShaderNodeTree":
            return False
        p = (
            bpy.context.view_layer.objects.active is not None
            and bpy.context.active_object.active_material is not None
        )
        return p

    def draw(self, context):
        # draw asset properties here
        layout = self.layout

        m = bpy.context.active_object.active_material
        if m.get("asset_data") is None and m.blenderkit.id == "":
            utils.label_multiline(
                layout,
                text="To upload this asset to Blendkit, go to the Find and Upload Assets panel.",
            )
            layout.prop(m, "name")

        if m.get("asset_data") is not None:
            ad = m["asset_data"]
            layout.label(text=str(ad["name"]))

            layout.label(text="Asset tools:")
            draw_asset_context_menu(self.layout, context, ad, from_panel=True)


def draw_rating_asset(self, context, layout, index=0):
    ### draws single asset rating.
    # Todo: resolve multiple objects for display, now the props are on respective panel, which isn't great.

    col = layout.box()

    directory = paths.get_temp_dir(f"{self.asset_data['assetType']}_search")
    tpath = os.path.join(directory, self.asset_data["thumbnail_small"])
    for image in bpy.data.images:
        if image.filepath == tpath:
            col.template_icon(icon_value=image.preview.icon_id, scale=6.0)
            break

    col.label(text=self.asset_data["name"])
    ratings.draw_ratings_menu(
        bpy.context.window_manager.blenderkit_ratings[index], context, col
    )


class VIEW3D_PT_blenderkit_ratings(Panel, ratings_utils.RatingProperties):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_ratings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Rate assets"
    bl_context = "objectmode"

    @classmethod
    def poll(cls, context):
        #
        p = bpy.context.view_layer.objects.active is not None
        return p

    def draw(self, context):
        # TODO make a list of assets inside asset appending code, to happen only when assets are added to the scene.
        # draw asset properties here
        layout = self.layout
        assets = ratings.get_assets_for_rating()
        if len(assets) > 0:
            utils.label_multiline(
                layout, text="Please help Blendkit community by rating these assets:"
            )
            ad = assets[0].get("asset_data")
            reference = bpy.context.window_manager.blenderkit_ratings[0]
            reference.asset_data = ad
            reference.asset_id = self.asset_data["id"]
            reference.asset_type = reference.asset_data["assetType"]
            draw_rating_asset(reference, context, layout, index=0)


def draw_login_progress(layout):
    layout.label(text="Login through browser")
    layout.label(text="in progress.")
    layout.operator("wm.blenderkit_login_cancel", text="Cancel", icon="CANCEL")


class VIEW3D_PT_blenderkit_profile(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_profile"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = ""
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        preferences = bpy.context.preferences.addons[__package__].preferences
        return not preferences.sidebar_panels

    def draw_header(self, context):
        layout = self.layout
        layout.emboss = "NORMAL"
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        if user_preferences.api_key != "":
            layout.label(text="Blendkit Profile", icon="USER")
        else:
            layout.label(text="Blendkit Login", icon="USER")

    def draw(self, context):
        layout = self.layout
        # don't draw when not online

        if not global_vars.CLIENT_RUNNING:
            layout.label(text="Client not running")
            return

        user_preferences = bpy.context.preferences.addons[__package__].preferences

        if user_preferences.login_attempt:
            draw_login_progress(layout)
            return

        if user_preferences.api_key != "":
            me = global_vars.BKIT_PROFILE
            if me is not None:
                # profile picture is retrieved from author's list, for coherency we store the profile images there.
                authors = global_vars.BKIT_AUTHORS
                me_id = int(me.id)
                if authors.get(me_id) is not None and authors[me_id].gravatarImg:
                    profile_img = autothumb.get_texture_ui(
                        authors[me_id].gravatarImg, ".blenderkit_profile_picture"
                    )
                    if profile_img and profile_img.image:
                        # draw the profile picture
                        box = layout.box()
                        box.template_icon(
                            icon_value=profile_img.image.preview.icon_id, scale=6.0
                        )

                # user name
                if len(me.firstName) > 0 or len(me.lastName) > 0:
                    layout.label(text=f"Me: {me.firstName} {me.lastName}")
                else:
                    layout.label(text=f"Me: {me.email}")

                # plan information
                if me.currentPlanName is not None:
                    pcoll = icons.icon_collections["main"]
                    if me.currentPlanName == "Free":
                        my_icon = pcoll["free"]
                    else:
                        my_icon = pcoll["full"]

                    row = layout.row()
                    row.label(text="My plan:")
                    row.label(
                        text=f"{me.currentPlanName} plan", icon_value=my_icon.icon_id
                    )
                    if me.currentPlanName == "Free":
                        layout.operator(
                            "wm.url_open", text="Change plan", icon="URL"
                        ).url = paths.url_with_utm(
                            paths.BLENDKIT_PLANS_URL, "profile_change_plan"
                        )

                # STORAGE STATISTICS
                if (
                    me.sumPrivateAssetFilesSize != None
                    and me.remainingPrivateQuota != None
                ):
                    plan_storage = (
                        me.sumPrivateAssetFilesSize + me.remainingPrivateQuota
                    )
                    sum_str = utils.files_size_to_text(plan_storage)
                    row = layout.row()
                    row.label(text=f"Plan storage:")
                    row.label(text=sum_str)
                if me.remainingPrivateQuota is not None:
                    row = layout.row()
                    size_str = utils.files_size_to_text(me.remainingPrivateQuota)
                    row.label(text=f"Remaining:")
                    row.label(text=size_str)

            layout.operator("wm.url_open", text="See my uploads", icon="URL").url = (
                paths.url_with_utm(paths.BLENDKIT_USER_ASSETS_URL, "profile_my_uploads")
            )

        draw_login_buttons(layout)
        if user_preferences.api_key == "":
            layout.label(text="Log in to bookmark assets.")

        addon_updater_ops.update_notice_box_ui(self, context)


class MarkNotificationRead(bpy.types.Operator):
    """Mark notification as read here and also on Blendkit server"""

    bl_idname = "wm.blenderkit_mark_notification_read"
    bl_label = "Mark notification as read"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    notification_id: IntProperty(  # type: ignore[valid-type]
        name="Id", description="notification id", default=-1
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        notifications = global_vars.DATA["bkit notifications"]
        for n in notifications["results"]:
            if n["id"] == self.notification_id:
                n["unread"] = 0
        comments_utils.check_notifications_read()
        client_lib.mark_notification_read(self.notification_id)
        return {"FINISHED"}


class MarkAllNotificationsRead(bpy.types.Operator):
    """Mark all notifications as read here and also on Blendkit server"""

    bl_idname = "wm.blenderkit_mark_notifications_read_all"
    bl_label = "Mark all notifications as read"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        notifications = global_vars.DATA["bkit notifications"]
        for n in notifications.get("results"):
            if n["unread"] == 1:
                n["unread"] = 0
                client_lib.mark_notification_read(n["id"])

        comments_utils.check_notifications_read()
        return {"FINISHED"}


class NotificationOpenTarget(bpy.types.Operator):
    """Open notification target and mark notification as read"""

    bl_idname = "wm.blenderkit_open_notification_target"
    bl_label = ""
    bl_description = "Open notification target and mark notification as read"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooltip: StringProperty(default="Open a web page")  # type: ignore[valid-type]
    url: StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )
    notification_id: IntProperty(  # type: ignore[valid-type]
        name="Id", description="notification id", default=-1
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def execute(self, context):
        bpy.ops.wm.blenderkit_mark_notification_read(
            notification_id=self.notification_id
        )
        bpy.ops.wm.url_open(url=self.url)
        return {"FINISHED"}


class UpvoteComment(bpy.types.Operator):
    """Up or downvote comment"""

    bl_idname = "wm.blenderkit_upvote_comment"
    bl_label = "Blendkit up-downvote comment"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    asset_id: StringProperty(  # type: ignore[valid-type]
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    comment_id: IntProperty(name="Id", description="comment id", default=-1)  # type: ignore[valid-type]

    flag: StringProperty(  # type: ignore[valid-type]
        name="flag", description="Upvote/downvote comment", default="like"
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        api_key = user_preferences.api_key
        comments = comments_utils.get_comments_local(self.asset_id)
        profile = global_vars.BKIT_PROFILE
        for comment in comments:
            if comment["id"] != self.comment_id:
                continue
            comment["flags"].append({"flag": self.flag, "user": "", "id": profile.id})
            for flag in comment["flags"]:
                if flag["id"] == profile.id and flag["flag"] != self.flag:
                    comment["flags"].remove(flag)
                    break
        client_lib.feedback_comment(self.asset_id, self.comment_id, api_key, self.flag)
        return {"FINISHED"}


class SetPrivateComment(bpy.types.Operator):
    """Set comment private or public"""

    bl_idname = "wm.blenderkit_is_private_comment"
    bl_label = "Blendkit set comment or thread private or public"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    asset_id: StringProperty(  # type: ignore[valid-type]
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    comment_id: IntProperty(name="Id", description="comment id", default=-1)  # type: ignore[valid-type]

    is_private: BoolProperty(  # type: ignore[valid-type]
        name="Is private",
        description="set comment/thread private or public",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        api_key = user_preferences.api_key
        comments = comments_utils.get_comments_local(self.asset_id)
        if comments is not None:
            for comment in comments:
                if comment["id"] == self.comment_id:
                    comment["isPrivate"] = self.is_private
        client_lib.mark_comment_private(
            self.asset_id, self.comment_id, api_key, self.is_private
        )
        return {"FINISHED"}


class PostComment(bpy.types.Operator):
    """Post a comment to Blendkit server"""

    bl_idname = "wm.blenderkit_post_comment"
    bl_label = "Blendkit post a new comment"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    asset_id: StringProperty(  # type: ignore[valid-type]
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    comment_id: IntProperty(  # type: ignore[valid-type]
        name="Reply to Id", description="reply to comment id", default=0
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        ui_props = bpy.context.window_manager.blenderkitUI
        api_key = user_preferences.api_key

        # Store comment locally first for immediate display
        # need to fill in everything to satisfy the drawing of the comment
        comment_data = {
            "comment": ui_props.new_comment,
            "created": "just now",
            "author": global_vars.BKIT_PROFILE,
            "id": -1,  # Temporary ID until server response
            "level": self.comment_id != 0 and 1 or 0,  # If replying, set level 1
            "parentComment": self.comment_id if self.comment_id != 0 else None,
            "replies": [],
            "feedback": {"flags": [], "score": 0},
            "isPrivate": False,
            "canChangeIsPrivate": True,
            "userModerator": False,
            "isDeleted": False,
            "flags": [],  # For storing like/dislike flags
            "asset": self.asset_id,  # Reference to the asset being commented on
            "canEdit": True,  # User can edit their own new comments
            "submitDate": "just now",  # Server-generated timestamp
            "userName": global_vars.BKIT_PROFILE.firstName
            + " "
            + global_vars.BKIT_PROFILE.lastName,
        }
        comments = comments_utils.get_comments_local(self.asset_id) or []
        comments.append(comment_data)
        comments_utils.store_comments_local(self.asset_id, comments)

        # Send to server
        client_lib.create_comment(
            self.asset_id, ui_props.new_comment, api_key, self.comment_id
        )
        ui_props.new_comment = ""
        return {"FINISHED"}


def draw_notification(self, notification, width=600):
    layout = self.layout
    box = layout.box()
    actor = notification.get("actor", {}).get("string", "")
    verb = notification.get("verb", "")
    target = notification.get("target", {})
    if target is None:
        target = {}
    target_string = target.get("string", "")
    firstline = f"{actor} {verb} {target_string}"
    box1 = box.box()

    split_last = 0.7
    if notification["description"]:
        split_last = 0

    rows = utils.label_multiline(
        box1, text=firstline, width=width, split_last=split_last
    )

    if notification["description"]:
        rows = utils.label_multiline(
            box, text=notification["description"], width=width, split_last=0.7
        )

    if notification["target"]:
        row = rows[-1]
        row = row.row(align=False)

        op = row.operator(
            "wm.blenderkit_open_notification_target", text="Open page", icon="HIDE_OFF"
        )
        op.tooltip = "Open the browser on the asset page to comment"
        op.url = global_vars.SERVER + notification["target"]["url"]
        op.notification_id = notification["id"]

        op = row.operator(
            "wm.blenderkit_mark_notification_read", text="", icon="CANCEL"
        )
        op.notification_id = notification["id"]


def draw_notifications(self, context, width=600):
    layout = self.layout
    notifications = global_vars.DATA.get("bkit notifications")
    if notifications is not None and notifications.get("count") > 0:
        row = layout.row()
        # row.alert = True
        split = row.split(factor=0.7)
        split.label(text="")
        split = split.split()
        split.operator(
            "wm.blenderkit_mark_notifications_read_all",
            text="Mark All Read",
            icon="CANCEL",
        )
        for notification in notifications["results"]:
            if notification["unread"] == 1:
                draw_notification(self, notification, width=width)


class LogoStatus(bpy.types.Operator):
    """Blendkit status"""

    bl_idname = "wm.logo_status"
    bl_label = "BLENDKIT STATUS"
    bl_options = {"REGISTER", "UNDO"}

    logo: StringProperty(name="logo", default="logo_offline")  # type: ignore[valid-type]


class ShowNotifications(bpy.types.Operator):
    """Show notifications"""

    bl_idname = "wm.show_notifications"
    bl_label = "Show Blendkit notifications"
    bl_options = {"REGISTER", "UNDO"}

    notification_id: IntProperty(  # type: ignore[valid-type]
        name="Id", description="notification id", default=-1
    )

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        set_overlay_panel_active()
        draw_notifications(self, context, width=600)

    def execute(self, context):
        wm = bpy.context.window_manager
        return wm.invoke_popup(self, width=600)


class VIEW3D_PT_blenderkit_notifications(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_notifications"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Blendkit Notifications"

    @classmethod
    def poll(cls, context):
        notifications = global_vars.DATA.get("bkit notifications")
        if notifications is not None and len(notifications["results"]) > 0:
            return True
        return False

    def draw(self, context):
        draw_notifications(self, context)


class VIEW3D_PT_blenderkit_login(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_login"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Blendkit Login"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        # don't draw when not online
        if not global_vars.CLIENT_RUNNING:
            layout.label(text="Client not running")
            return
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        if user_preferences.login_attempt:
            draw_login_progress(layout)
            return

        draw_login_buttons(layout)


def draw_panel_material_upload(self, context):
    o = bpy.context.active_object
    mat = bpy.context.active_object.active_material

    props = mat.blenderkit
    layout = self.layout

    draw_upload_common(layout, props, "MATERIAL", context)

    # THUMBNAIL
    row = layout.column()
    if props.is_generating_thumbnail:
        row.enabled = False

    draw_thumbnail_upload_panel(row, props)

    prop_needed(row, props, "thumbnail", props.has_thumbnail, False)

    # Thumbnail generation relies on the background thumbnailer which requires
    # Blender 4.2+, so only expose the button on supported versions.
    if bpy.context.scene.render.engine in ACCEPTABLE_ENGINES and bpy.app.version >= (
        4,
        2,
        0,
    ):
        layout.operator(
            "object.blenderkit_generate_material_thumbnail",
            text="Render thumbnail",
            icon="EXPORT",
        )
    if props.is_generating_thumbnail:
        row = layout.row(align=True)
        row.label(text=props.thumbnail_generating_state, icon="RENDER_STILL")
        op = row.operator("object.kill_bg_process", text="", icon="CANCEL")
        op.process_source = "MATERIAL"
        op.process_type = "THUMBNAILER"
    elif props.thumbnail_generating_state != "":
        utils.label_multiline(layout, text=props.thumbnail_generating_state)

    layout.prop(props, "style")

    layout.prop(props, "pbr")
    layout.prop(props, "uv")
    layout.prop(props, "animated")
    layout.prop(props, "texture_size_meters")

    draw_validated_manufacturer(layout, mat)


def draw_panel_material_search(self, context):
    wm = context.window_manager
    props = wm.blenderkit_mat
    ui_props = wm.blenderkitUI

    layout = self.layout
    draw_search_text_field(layout, ui_props, context)
    utils.label_multiline(layout, text=props.report)


def draw_panel_brush_upload(self, context):
    brush = utils.get_active_brush()
    if brush is not None:
        props = brush.blenderkit

        layout = self.layout

        draw_upload_common(layout, props, "BRUSH", context)

        col = layout.column()
        draw_thumbnail_upload_panel(col, props)
        prop_needed(col, props, "thumbnail", props.thumbnail)


def draw_panel_brush_search(self, context):
    wm = context.window_manager
    props = wm.blenderkit_brush
    ui_props = wm.blenderkitUI

    layout = self.layout
    draw_search_text_field(layout, ui_props, context)

    if not context.sculpt_object and not context.image_paint_object:
        utils.label_multiline(
            layout,
            text="Switch to paint or sculpt mode.",
            width=context.region.width,
        )

    utils.label_multiline(layout, text=props.report)


def draw_login_buttons(layout, invoke=False):
    user_preferences = bpy.context.preferences.addons[__package__].preferences

    if user_preferences.login_attempt:
        draw_login_progress(layout)
    else:
        if invoke:
            layout.operator_context = "INVOKE_DEFAULT"
        else:
            layout.operator_context = "EXEC_DEFAULT"
        if not utils.user_logged_in():
            op_login = layout.operator("wm.blenderkit_login", text="Login", icon="URL")
            op_login.signup = False
            op_login.placement = "login_panel"
            op_signup = layout.operator(
                "wm.blenderkit_login", text="Sign up", icon="URL"
            )
            op_signup.signup = True
            op_signup.placement = "login_panel"

        else:
            layout.operator("wm.blenderkit_logout", text="Logout", icon="URL")


class OpenBlenderKitDiscord(bpy.types.Operator):
    """Connect with our team, creators, and fellow users to discuss assets and the add-on"""

    bl_idname = "wm.blenderkit_join_discord"
    bl_label = "Open Discord"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        open_new_tab(global_vars.DISCORD_INVITE_URL)
        return {"FINISHED"}


def get_environment_info() -> dict:
    info = {}
    ver = global_vars.VERSION
    info["addon_version"] = f"{ver[0]}.{ver[1]}.{ver[2]}.{ver[3]}"
    info["blender_version"] = bpy.app.version_string
    info["python_version"] = sys.version
    info["os"] = f"{platform.system()} {platform.release()} ({platform.machine()})"
    info["proxy_which"] = bpy.context.preferences.addons[
        __package__
    ].preferences.proxy_which
    info["proxy_address"] = bpy.context.preferences.addons[
        __package__
    ].preferences.proxy_address
    info["trusted_ca_certs"] = bpy.context.preferences.addons[
        __package__
    ].preferences.trusted_ca_certs
    info["ssl_context"] = bpy.context.preferences.addons[
        __package__
    ].preferences.ssl_context
    info["ip_version"] = bpy.context.preferences.addons[
        __package__
    ].preferences.ip_version
    return info


def get_environment_info_string() -> str:
    """Get formatted environment info for bug reports and clipboard."""
    info = get_environment_info()
    proxy = f"{info['proxy_which']}"
    if info["proxy_which"] == "CUSTOM":
        proxy += f" ({info['proxy_address']})"
    return (
        f"- Blendkit version: v{info['addon_version']}\n"
        f"- Blender version: v{info['blender_version']} (from: )\n"
        f"- Python version: {info['python_version']}\n"
        f"- Operating system & architecture: {info['os']}\n"
        f"- Proxy setting: {proxy}\n"
        f"- Trusted CA certs path: {info['trusted_ca_certs']}\n"
        f"- SSL verification: {info['ssl_context']}\n"
        f"- IP version: {info['ip_version']}\n"
        "- Using VPN, proxy, or firewall? "
    )


class CopyEnvironmentInfo(bpy.types.Operator):
    """Copy the BlendKit and Blender versions, operating system, and other environment details to the clipboard.
    Include this information in your bug report or support email to help us diagnose the issue"""  # fmt: skip

    bl_idname = "wm.blenderkit_copy_environment_info"
    bl_label = "Copy Environment Info"

    def execute(self, context):
        context.window_manager.clipboard = get_environment_info_string()
        bk_logger.info("Environment info copied to clipboard")
        return {"FINISHED"}


def get_report_bug_url() -> str:
    """Build GitHub issue URL with pre-filled environment information.
    Do not set the title and description, we require the user to fill those fields manually.
    File is located at: .github/ISSUE_TEMPLATE/bug-report-prefilled.yaml
    """

    info = get_environment_info()
    proxy = f"{info['proxy_which']}"
    if info["proxy_which"] == "CUSTOM":
        proxy += f" ({info['proxy_address']})"

    return (
        "https://github.com/BlenderKit/blenderkit/issues/new"
        f"?template=bug-report-prefilled.yaml"
        f"&blendkit_version={quote(info['addon_version'])}"
        f"&blender_version={quote(info['blender_version'])}"
        f"&operating_system={quote(info['os'])}"
        f"&python_version={quote(info['python_version'])}"
        f"&proxy={quote(proxy)}"
        f"&ip_version={quote(info['ip_version'])}"
        f"&ssl_context={quote(info['ssl_context'])}"
        f"&trusted_ca_certs={quote(info['trusted_ca_certs'])}"
    )


class ReportBug(bpy.types.Operator):
    """Open a prefilled GitHub issue in your browser. The report includes BlendKit and Blender versions,
    operating system info, and other environment details which help us diagnose your problem"""  # fmt: skip

    bl_idname = "wm.blenderkit_report_bug"
    bl_label = "Report a Bug"

    def execute(self, context):
        bpy.ops.wm.url_open(url=get_report_bug_url())
        return {"FINISHED"}


class VIEW3D_PT_blenderkit_advanced_model_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_model_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type in (
            "MODEL",
            "PRINTABLE",
        )

    def draw_layout(self, layout):
        # Shown as a popover over the asset bar — record redraw time to
        # prevent click-through to the asset bar.
        set_overlay_panel_active()

        wm = bpy.context.window_manager
        props = wm.blenderkit_models
        ui_props = wm.blenderkitUI
        preferences = bpy.context.preferences.addons[__package__].preferences
        layout.separator()

        row = layout.row()
        row.prop(ui_props, "search_bookmarks", text="Bookmarks", icon="BOOKMARKS")
        row.prop(ui_props, "own_only", icon="USER")
        if ui_props.own_only:
            layout.prop(
                ui_props, "own_verification_status", text="Status", icon="LOCKED"
            )
        # row = layout.row()

        layout.prop(ui_props, "free_only")

        if ui_props.asset_type == "MODEL":
            layout.prop(props, "search_style")
            layout.prop(props, "search_geometry_nodes", text="Geometry Nodes")

        # DESIGN YEAR
        layout.prop(props, "search_design_year", text="Designed in Year")
        if props.search_design_year:
            row = layout.row(align=True)
            row.prop(props, "search_design_year_min", text="Min")
            row.prop(props, "search_design_year_max", text="Max")

        if ui_props.asset_type == "MODEL":
            # POLYCOUNT
            layout.prop(props, "search_polycount", text="Poly Count ")
            if props.search_polycount:
                row = layout.row(align=True)
                row.prop(props, "search_polycount_min", text="Min")
                row.prop(props, "search_polycount_max", text="Max")

            # TEXTURE RESOLUTION
            layout.prop(props, "search_texture_resolution", text="Texture Resolutions")
            if props.search_texture_resolution:
                row = layout.row(align=True)
                row.prop(props, "search_texture_resolution_min", text="Min")
                row.prop(props, "search_texture_resolution_max", text="Max")

            # FILE SIZE
            layout.prop(props, "search_file_size", text="File Size (MB)")
            if props.search_file_size:
                row = layout.row(align=True)
                row.prop(props, "search_file_size_min", text="Min")
                row.prop(props, "search_file_size_max", text="Max")

            # AGE
            layout.prop(props, "search_condition", text="Condition")
            layout.prop(props, "search_animated", text="Animated")
            layout.prop(ui_props, "quality_limit", slider=True)

        # LICENSE
        layout.prop(ui_props, "search_license")

        if ui_props.asset_type == "MODEL":
            # LIMIT BLENDER VERSION
            layout.prop(
                ui_props, "search_blender_version", text="Asset's Blender Version"
            )
            if ui_props.search_blender_version:
                row = layout.row(align=True)
                row.prop(ui_props, "search_blender_version_min", text="Min")
                row.prop(ui_props, "search_blender_version_max", text="Max")

        # NSFW filter
        layout.prop(preferences, "nsfw_filter")

        # ORDER
        layout.prop(ui_props, "search_order_by")

    def draw(self, context):
        self.draw_layout(self.layout)


def draw_panel_printable_upload(self, context):
    """Draw upload panel for printable assets"""
    layout = self.layout
    props = utils.get_upload_props()
    draw_upload_common(layout, props, "PRINTABLE", context)


class VIEW3D_PT_blenderkit_advanced_material_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_material_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "MATERIAL"

    def draw_layout(self, layout):
        # Shown as a popover over the asset bar — record redraw time to
        # prevent click-through to the asset bar.
        set_overlay_panel_active()

        wm = bpy.context.window_manager
        props = wm.blenderkit_mat
        ui_props = wm.blenderkitUI

        layout.separator()

        row = layout.row()
        row.prop(ui_props, "search_bookmarks", text="Bookmarks", icon="BOOKMARKS")
        row.prop(ui_props, "own_only", icon="USER")
        if ui_props.own_only:
            layout.prop(
                ui_props, "own_verification_status", text="Status", icon="LOCKED"
            )

        layout.label(text="Texture:")
        col = layout.column()
        col.prop(props, "search_procedural", expand=True)

        if props.search_procedural == "TEXTURE_BASED":
            # TEXTURE RESOLUTION
            layout.prop(props, "search_texture_resolution", text="Texture Resolution")
            if props.search_texture_resolution:
                row = layout.row(align=True)
                row.prop(props, "search_texture_resolution_min", text="Min")
                row.prop(props, "search_texture_resolution_max", text="Max")

        # FILE SIZE
        layout.prop(props, "search_file_size", text="File size (MB)")
        if props.search_file_size:
            row = layout.row(align=True)
            row.prop(props, "search_file_size_min", text="Min")
            row.prop(props, "search_file_size_max", text="Max")
        layout.prop(ui_props, "quality_limit", slider=True)
        layout.prop(ui_props, "search_license")

        # ORDER
        layout.prop(ui_props, "search_order_by")

    def draw(self, context):
        self.draw_layout(self.layout)


class VIEW3D_PT_blenderkit_advanced_scene_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_scene_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        s = context.scene
        ui_props = bpy.context.window_manager.blenderkitUI
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "SCENE"

    def draw_layout(self, layout):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(layout, ui_props)

    def draw(self, context):
        self.draw_layout(self.layout)


class VIEW3D_PT_blenderkit_advanced_HDR_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_HDR_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "HDR"

    def draw(self, context):
        wm = context.window_manager
        props = wm.blenderkit_HDR
        ui_props = wm.blenderkitUI

        layout = self.layout
        draw_common_filters(layout, ui_props)

        layout.prop(props, "true_hdr")
        layout.prop(props, "search_texture_resolution", text="Texture Resolutions")
        if props.search_texture_resolution:
            row = layout.row(align=True)
            row.prop(props, "search_texture_resolution_min", text="Min")
            row.prop(props, "search_texture_resolution_max", text="Max")


class VIEW3D_PT_blenderkit_advanced_brush_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_brush_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "BRUSH"

    def draw_layout(self, layout):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(layout, ui_props)

    def draw(self, context):
        self.draw_layout(self.layout)


class VIEW3D_PT_blenderkit_advanced_nodegroup_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_nodegroup_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "NODEGROUP"

    def draw(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(self.layout, ui_props)


class VIEW3D_PT_blenderkit_advanced_addon_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_addon_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "ADDON"

    def draw(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(self.layout, ui_props)
        layout = self.layout
        addon_props = bpy.context.window_manager.blenderkit_addon
        # Add installed filter for addons
        row = layout.row()
        row.prop(addon_props, "search_installed", text="Installed Only")
        row = layout.row()
        row.prop(addon_props, "search_compatible_only", text="Compatible Only")


class VIEW3D_PT_blenderkit_advanced_author_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_author_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "AUTHOR"

    def draw(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(self.layout, ui_props)


class VIEW3D_PT_blenderkit_advanced_printable_search(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_advanced_printable_search"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Search filters"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH" and ui_props.asset_type == "PRINTABLE"

    def draw_layout(self, layout):
        ui_props = bpy.context.window_manager.blenderkitUI
        draw_common_filters(layout, ui_props)

    def draw(self, context):
        self.draw_layout(self.layout)


class VIEW3D_PT_blenderkit_categories(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_categories"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Categories"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        return ui_props.down_up == "SEARCH"

    def draw(self, context):
        # measure time since last dropdown activation/ mouse hover e.t.c.
        # this is then used in asset_bar_op.py to cancel asset drag drop if the time is too small and thus means double clicking.
        set_overlay_panel_active()
        draw_panel_categories(self.layout, context)


def draw_scene_import_settings(self, context):
    wm = bpy.context.window_manager
    props = wm.blenderkit_scene
    layout = self.layout
    layout.prop(props, "switch_after_append")
    row = layout.row()
    row.prop(props, "append_link", expand=True, icon_only=False)


class VIEW3D_PT_blenderkit_import_settings(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_import_settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Import settings"
    bl_parent_id = "VIEW3D_PT_blenderkit_unified"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        if not global_vars.CLIENT_RUNNING:
            return False
        if ui_props.asset_type not in ["MATERIAL", "MODEL", "SCENE", "HDR"]:
            return False
        return ui_props.down_up == "SEARCH"

    def draw(self, context):
        layout = self.layout

        s = context.scene
        wm = bpy.context.window_manager
        ui_props = bpy.context.window_manager.blenderkitUI
        preferences = bpy.context.preferences.addons[__package__].preferences

        if ui_props.asset_type == "MODEL":
            # noinspection PyCallByClass
            props = wm.blenderkit_models
            layout.prop(props, "randomize_rotation")
            if props.randomize_rotation:
                layout.prop(props, "randomize_rotation_amount")
            layout.prop(props, "perpendicular_snap")

            layout.label(text="Import method:")
            row = layout.row()
            row.prop(props, "import_method", expand=True, icon_only=False)

        if ui_props.asset_type == "MATERIAL":
            props = wm.blenderkit_mat
            layout.prop(preferences, "material_import_automap")
            layout.label(text="Import method:")
            row = layout.row()

            row.prop(props, "import_method", expand=True, icon_only=False)
        if ui_props.asset_type == "SCENE":
            draw_scene_import_settings(self, context)

        if ui_props.asset_type == "HDR":
            props = wm.blenderkit_HDR

        if ui_props.asset_type in [
            "MATERIAL",
            "MODEL",
            "SCENE",
            "PRINTABLE",
            "NODEGROUP",
            "MATERIAL",
            "BRUSH",
        ]:
            layout.prop(preferences, "unpack_files")
            layout.prop(preferences, "create_asset_library")
            layout.prop(preferences, "resolution")
        elif ui_props.asset_type in ["HDR"]:
            layout.prop(preferences, "resolution")

        # general settings
        # show toggle for clipboard scan
        layout.prop(preferences, "use_clipboard_scan")


def deferred_set_name(props, expected_obj_name):
    """Deferred timer to set empty name of uploaded asset to active Object's name.
    We check if the names of active_now object and expected object are the same, because active object could have changed.
    This is one-shot timer = return None.
    """
    active_now = utils.get_active_asset()
    if props.name != "":
        return None
    if not active_now:
        return None
    if active_now.name != expected_obj_name:
        return None  # active object is different from the one on which we have called the timer
    props.name_old = (
        expected_obj_name  # prevents utils.name_update() from running twice
    )
    props.name = expected_obj_name  # this ultimately triggers utils.name_update()
    return None


class VIEW3D_PT_blenderkit_unified(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_unified"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {
        "HEADER_LAYOUT_EXPAND",
    }
    bl_label = ""

    @classmethod
    def poll(cls, context):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        return not user_preferences.sidebar_panels

    def draw_header(self, context):
        layout = self.layout
        ui_props = bpy.context.window_manager.blenderkitUI
        pcoll = icons.icon_collections["main"]
        layout.label(
            text="Find and Upload Assets",
            icon_value=pcoll[ui_props.logo_status].icon_id,
        )

    def draw(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        user_preferences = bpy.context.preferences.addons[__package__].preferences

        layout = self.layout
        # layout.prop_tabs_enum(ui_props, "asset_type", icon_only = True)
        if not global_vars.CLIENT_RUNNING:
            layout.label(text="Client not running")
            return

        row = layout.row()
        row.prop(ui_props, "down_up", expand=True, icon_only=False)

        row = layout.row(align=True)
        row.scale_x = 1.6
        row.scale_y = 1.6

        expand_icon = "TRIA_DOWN"
        if ui_props.asset_type_fold:
            expand_icon = "TRIA_RIGHT"
        row = layout.row()
        split = row.split(factor=0.15)
        split.prop(
            ui_props, "asset_type_fold", icon=expand_icon, icon_only=True, emboss=False
        )

        if ui_props.asset_type_fold:
            # expanded interface with names in column
            split = split.row()
            split.scale_x = 8
            split.scale_y = 1.6
        else:
            split = split.column()

        split.prop(
            ui_props, "asset_type", expand=True, icon_only=ui_props.asset_type_fold
        )

        if user_preferences.login_attempt:
            draw_login_progress(layout)
            return

        if (
            len(user_preferences.api_key) < 20
            and user_preferences.download_counter > 20
        ):
            draw_login_buttons(layout)
            layout.separator()

        if ui_props.down_up == "SEARCH":
            self.draw_search(context, layout, ui_props)

        if ui_props.down_up == "UPLOAD":
            self.draw_upload(context, layout, ui_props)

    def draw_search(self, context, layout, ui_props):
        if utils.profile_is_validator():
            search_props = utils.get_search_props()
            layout.prop(search_props, "search_verification_status")
            layout.prop(search_props, "unrated_quality_only")
            layout.prop(search_props, "unrated_wh_only")

        if ui_props.asset_type == "MODEL" or ui_props.asset_type == "PRINTABLE":
            return draw_panel_model_search(self, context)

        if ui_props.asset_type == "SCENE":
            return draw_panel_scene_search(self, context)

        if ui_props.asset_type == "HDR":
            return draw_panel_hdr_search(self, context)

        if ui_props.asset_type == "MATERIAL":
            return draw_panel_material_search(self, context)

        if ui_props.asset_type == "BRUSH":
            return draw_panel_brush_search(self, context)

        if ui_props.asset_type == "NODEGROUP":
            return draw_panel_nodegroup_search(self, context)

        if ui_props.asset_type == "ADDON":
            return draw_panel_addon_search(self, context)

        if ui_props.asset_type == "AUTHOR":
            return draw_panel_author_search(self, context)

    def draw_upload(self, context, layout, ui_props):
        obj = utils.get_active_asset()
        props = getattr(obj, "blenderkit", None)
        if props and not props.name:
            bpy.app.timers.register(
                lambda p=props, n=obj.name: deferred_set_name(p, n), first_interval=0.0
            )

        if ui_props.asset_type == "MODEL" or ui_props.asset_type == "PRINTABLE":
            if bpy.context.view_layer.objects.active is not None:
                return draw_panel_model_upload(self, context)
            layout.label(text="select object to upload")
            return

        if ui_props.asset_type == "SCENE":
            return draw_panel_scene_upload(self, context)

        if ui_props.asset_type == "HDR":
            return draw_panel_hdr_upload(self, context)

        if ui_props.asset_type == "MATERIAL":
            if (bpy.context.view_layer.objects.active is not None) and (
                bpy.context.active_object.active_material is not None
            ):
                return draw_panel_material_upload(self, context)

            utils.label_multiline(
                layout,
                text="select object with material to upload materials",
                width=context.region.width,
            )
            return

        if ui_props.asset_type == "BRUSH":
            if context.sculpt_object or context.image_paint_object:
                return draw_panel_brush_upload(self, context)
            layout.label(text="Switch to paint or sculpt mode.")
            return

        if ui_props.asset_type == "NODEGROUP":
            return draw_panel_nodegroup_upload(self, context)

        if ui_props.asset_type == "ADDON":
            layout.label(text="Add-on uploads are managed through")
            layout.label(text="the Blendkit website.")
            op = layout.operator(
                "wm.url_open", text="Go to Blendkit Website", icon="URL"
            )
            op.url = paths.url_with_utm(
                paths.BLENDKIT_ADDON_UPLOAD_INSTRUCTIONS_URL, "upload_docs"
            )
            return

        if ui_props.asset_type == "AUTHOR":
            layout.label(text="Author profiles are search-only.")
            return


class BlenderKitWelcomeOperator(bpy.types.Operator):
    """Login online on Blendkit webpage"""

    bl_idname = "wm.blenderkit_welcome"
    bl_label = "Welcome to Blendkit!"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    step: IntProperty(  # type: ignore[valid-type]
        name="step", description="Tutorial Step", default=0, options={"SKIP_SAVE"}
    )

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        if self.step == 0:
            layout.template_icon(icon_value=self.img.preview.icon_id, scale=18)

            op = layout.operator(
                "wm.url_open", text="Watch Video Tutorial", icon="QUESTION"
            )
            op.url = paths.BLENDKIT_MANUAL_URL

        else:
            message = "Operator Tutorial called with invalid step"

    def execute(self, context):
        if self.step == 0:
            ui_props = bpy.context.window_manager.blenderkitUI

            ui_props.asset_type = "MODEL"

            search.search(
                query={
                    "asset_type": "model",
                    "query": f"+is_free:true+score_gte:1000+order:-created",
                }
            )
        return {"FINISHED"}

    def invoke(self, context, event):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        if user_preferences.welcome_operator_counter > 10:
            return {"FINISHED"}
        user_preferences.welcome_operator_counter += 1

        wm = bpy.context.window_manager
        img = utils.get_thumbnail("intro.jpg")
        utils.img_to_preview(img, copy_original=True)
        self.img = img
        w, a, r = utils.get_largest_area(area_type="VIEW_3D")
        if a is not None:
            # Show regions in which the addon has UI
            a.spaces.active.show_region_ui = True
            a.spaces.active.show_region_tool_header = True

        return wm.invoke_props_dialog(self, width=500)


class OpenSystemDirectory(bpy.types.Operator):
    """Open directory in default system file explorer"""

    bl_idname = "wm.blenderkit_open_system_directory"
    bl_label = "Open system directory"
    bl_options = {"REGISTER", "UNDO"}
    directory: StringProperty(name="directory", default="")  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        if not os.path.exists(self.directory):
            self.report({"ERROR"}, "Directory not found.")
            return {"CANCELLED"}
        paths.open_path_in_file_browser(self.directory)
        return {"FINISHED"}


class OpenAssetDirectory(OpenSystemDirectory):
    """Open directory containing the asset data"""

    bl_idname = "wm.blenderkit_open_asset_directory"
    bl_label = "Open asset directory"

    def execute(self, context):
        if not os.path.exists(self.directory):
            self.report({"ERROR"}, "Directory not found. Asset not downloaded yet.")
            return {"CANCELLED"}
        paths.open_path_in_file_browser(self.directory)
        return {"FINISHED"}


class OpenAddonDirectory(OpenSystemDirectory):
    """Open the directory in which the Blendkit add-on is installed. Move one level up and delete it to hard-uninstall the add-on"""

    bl_idname = "wm.blenderkit_open_addon_directory"
    bl_label = "Open global directory"


class OpenGlobalDirectory(OpenSystemDirectory):
    """Open the Blendkit's Global directory. This is the directory where Blendkit stores downloaded assets. It also contains Client binary and log files"""

    bl_idname = "wm.blenderkit_open_global_directory"
    bl_label = "Open global directory"


class OpenClientLog(OpenSystemDirectory):
    """Open Log file of currently running Client. Client logs errors and other message in here. Inspect to see what is wrong with Client. Copy the contents when you make a bug report"""

    bl_idname = "wm.blenderkit_open_client_log"
    bl_label = "Open Client log"


class OpenTempDirectory(OpenSystemDirectory):
    """Open Blendkit's temporary directory. This is the directory where thumbnails and other temporary files are stored"""

    bl_idname = "wm.blenderkit_open_temp_directory"
    bl_label = "Open temp directory"


class BLENDERKIT_OT_hdr_thumbnail_tune(bpy.types.Operator):
    """Edit HDR thumbnail conversion settings with live preview."""

    bl_idname = "wm.blenderkit_hdr_thumbnail_tune"
    bl_label = "Edit Thumbnail Before Upload"
    bl_options = {"REGISTER", "INTERNAL"}

    use_custom_tone: BoolProperty(  # type: ignore[valid-type]
        name="Use Custom Thumbnail Tone",
        default=False,
    )
    exposure: FloatProperty(  # type: ignore[valid-type]
        name="Exposure",
        default=0.0,
        min=-5.0,
        max=5.0,
        soft_min=-2.0,
        soft_max=2.0,
        precision=3,
        step=1,
    )
    gamma: FloatProperty(  # type: ignore[valid-type]
        name="Gamma",
        default=1.0,
        min=0.2,
        max=3.0,
        soft_min=0.7,
        soft_max=1.6,
        precision=3,
        step=1,
    )

    _preview_image_prefix = "blenderkit_hdr_thumbnail_preview_"
    _created_preview_names: set[str] = set()
    preview_image_name: StringProperty(  # type: ignore[valid-type]
        name="Preview Image Name",
        default="",
        options={"SKIP_SAVE", "HIDDEN"},
    )
    _preview_error = ""

    trigger_upload: BoolProperty(  # type: ignore[valid-type]
        name="Trigger Upload",
        default=False,
        options={"SKIP_SAVE"},
    )
    upload_reupload: BoolProperty(  # type: ignore[valid-type]
        name="Reupload",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        ui_props = context.window_manager.blenderkitUI
        return ui_props.hdr_upload_image is not None

    def _cleanup_preview_image(self):
        # Cleanup only images created by this operator instance.
        for name in list(self._created_preview_names):
            img = bpy.data.images.get(name)
            if img is None:
                self._created_preview_names.discard(name)
                continue
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass
            self._created_preview_names.discard(name)

    def _refresh_preview(self, context):
        ui_props = context.window_manager.blenderkitUI
        hdr_image = ui_props.hdr_upload_image
        if hdr_image is None:
            return
        self._preview_error = ""
        try:
            preview_path = image_utils.generate_hdr_thumbnail_preview(
                hdr_image=hdr_image,
                use_custom_tone=self.use_custom_tone,
                exposure=self.exposure,
                gamma=self.gamma,
                max_preview_size=512,
            )
            preview_image = bpy.data.images.load(preview_path, check_existing=False)
            preview_image.name = f"{self._preview_image_prefix}{time.time_ns()}"
            preview_image.reload()
            if hasattr(preview_image, "preview"):
                preview_image.preview_ensure()
            self.preview_image_name = preview_image.name
            self._created_preview_names.add(preview_image.name)
        except Exception as e:
            self.preview_image_name = ""
            self._preview_error = str(e)

        # Force dialog refresh in Blender 3.x/4.x where icon updates can lag.
        if context.area is not None:
            context.area.tag_redraw()

    def check(self, context):
        self._refresh_preview(context)
        return True

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        layout.prop(self, "use_custom_tone")
        col = layout.column(align=True)
        col.enabled = self.use_custom_tone
        col.prop(self, "exposure")
        col.prop(self, "gamma")

        preview_box = layout.box()
        preview_box.label(text="Thumbnail Preview (live)", icon="IMAGE_DATA")

        preview_image = bpy.data.images.get(self.preview_image_name)
        if preview_image is not None:
            # Use preview icon rendering for reliable display in popup dialogs.
            if hasattr(preview_image, "preview"):
                preview_image.preview_ensure()
                preview_box.template_icon(
                    icon_value=preview_image.preview.icon_id,
                    scale=14,
                )
        elif self._preview_error:
            preview_box.label(
                text=f"Preview failed: {self._preview_error}", icon="ERROR"
            )
        else:
            preview_box.label(text="Preparing preview...", icon="TIME")

    def invoke(self, context, event):
        ui_props = context.window_manager.blenderkitUI
        self._cleanup_preview_image()
        self.preview_image_name = ""
        self.use_custom_tone = ui_props.hdr_use_custom_thumbnail_tone
        self.exposure = ui_props.hdr_thumbnail_exposure
        self.gamma = ui_props.hdr_thumbnail_gamma
        self._refresh_preview(context)
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        ui_props = context.window_manager.blenderkitUI
        ui_props.hdr_use_custom_thumbnail_tone = self.use_custom_tone
        ui_props.hdr_thumbnail_exposure = self.exposure
        ui_props.hdr_thumbnail_gamma = self.gamma
        self._cleanup_preview_image()

        if self.trigger_upload:
            bpy.ops.object.blenderkit_upload(
                "INVOKE_DEFAULT",
                asset_type="HDR",
                reupload=self.upload_reupload,
                skip_hdr_tune_popup=True,
            )
        return {"FINISHED"}

    def cancel(self, context):
        self._cleanup_preview_image()


def draw_asset_context_menu(
    layout, context: Context, asset_data: dict, from_panel: bool = False
):
    ui_props = context.window_manager.blenderkitUI  # type: ignore
    author_id = int(asset_data["author"].get("id"))
    layout.operator_context = "INVOKE_DEFAULT"

    if utils.user_logged_in() and asset_data.get("assetType") != "author":
        rating = ratings_utils.get_rating_local(asset_data["id"])
        if rating is None:
            rating = datas.AssetRating()
        if rating.bookmarks == 1:
            text = "Delete Bookmark"
            icon = "bookmark_full"
        else:
            text = "Bookmark"
            icon = "bookmark_empty"

        pcoll = icons.icon_collections["main"]
        op = layout.operator(
            "wm.blenderkit_bookmark_asset", text=text, icon_value=pcoll[icon].icon_id
        )
        op.asset_id = asset_data["id"]

    if from_panel and asset_data.get("assetType") != "author":
        op = layout.operator(
            "wm.blenderkit_menu_rating_upload", text="Add Rating", icon="SOLO_ON"
        )
        op.asset_name = asset_data["name"]
        op.asset_id = asset_data["id"]
        op.asset_type = asset_data["assetType"]

    if from_panel and global_vars.BKIT_AUTHORS is not None and author_id is not None:
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author is not None:
            op = layout.operator("wm.url_open", text="Open Author's Website")
            if author.aboutMeUrl:
                op.url = author.aboutMeUrl
            else:
                op.url = paths.get_author_gallery_url(author.id)
            op = layout.operator(
                "view3d.blenderkit_search", text="Show Assets By Author"
            )
            op.keywords = ""
            op.author_id = str(author_id)

    op = layout.operator("view3d.blenderkit_search", text="Search Similar")
    op.esc = True
    op.tooltip = "Search for similar assets in the library.\nShortcut: hover over asset in asset bar and press 'S'."
    op.keywords = search.get_search_similar_keywords(asset_data)

    op = layout.operator("wm.url_open", text="See online", icon="URL")
    if (
        utils.user_is_owner(asset_data)
        and asset_data["verificationStatus"] != "validated"
    ):
        op.url = paths.url_with_utm(
            f'{paths.BLENDKIT_USER_ASSETS_URL}/{asset_data["assetBaseId"]}/?preview#',
            "uploads_preview",
        )
    else:
        op.url = paths.get_asset_gallery_url(asset_data["id"])
        # TODO this is where validator should be able to go and see non-validated the assets in gallery,
        # by now there's nowhere to go.

    # enable opening the directory on drive
    dir_paths = paths.get_asset_directories(asset_data)
    if len(dir_paths) > 0 and os.path.exists(dir_paths[-1]):
        op = layout.operator(
            "wm.blenderkit_open_asset_directory",
            text="Open Directory",
            icon="FILE_FOLDER",
        )
        op.directory = dir_paths[-1]

    if asset_data.get("canDownload") != 0:
        if len(bpy.context.selected_objects) > 0 and ui_props.asset_type == "MODEL":
            aob = bpy.context.active_object
            if aob is None:
                aob = bpy.context.selected_objects[0]
            op = layout.operator(
                "scene.blenderkit_download", text="Replace Active Models"
            )
            op.tooltip = "Replace all selected models with this one"

            # this checks if the menu got called from right-click in assetbar(then index is 0 - x) or
            # from a panel(then replacement happens from the active model)
            if from_panel:
                # called from addon panel
                op.asset_base_id = asset_data["assetBaseId"]
            else:
                op.asset_index = ui_props.active_index

            op.model_location = aob.location
            op.model_rotation = aob.rotation_euler
            op.target_object = aob.name  # type: ignore
            op.material_target_slot = aob.active_material_index
            op.replace = True
            op.replace_resolution = False

        if (
            ui_props.asset_type in ("MODEL", "MATERIAL", "HDR")
            and utils.get_param(asset_data, "textureResolutionMax") is not None
            and utils.get_param(asset_data, "textureResolutionMax", 0) > 512
        ):
            s = bpy.context.scene

            col = layout.column()
            col.operator_context = "INVOKE_DEFAULT"

            if from_panel:
                # Called from addon panel

                if (
                    asset_data.get("resolution")
                    or asset_data.get("available_resolutions") is not None
                ):
                    op = col.operator(
                        "scene.blenderkit_download", text="Replace asset resolution"
                    )
                    op.asset_base_id = asset_data["assetBaseId"]
                    if asset_data["assetType"] == "model":
                        o = utils.get_active_model()
                        if o is not None:
                            op.model_location = o.location
                            op.model_rotation = o.rotation_euler
                            op.target_object = o.name
                            op.material_target_slot = o.active_material_index

                    elif asset_data["assetType"] == "material":
                        aob = bpy.context.active_object
                        op.model_location = aob.location
                        op.model_rotation = aob.rotation_euler
                        op.target_object = aob.name  # type: ignore
                        op.material_target_slot = aob.active_material_index
                    op.replace_resolution = True
                    op.replace = False

                    op.invoke_resolution = True
                    op.use_resolution_operator = True
                    op.max_resolution = asset_data.get(
                        "max_resolution", 0
                    )  # str(utils.get_param(asset_data, 'textureResolutionMax'))

            elif (
                asset_data["assetBaseId"] in s["assets used"].keys()  # type: ignore
                and asset_data["assetType"] != "hdr"
                and (
                    asset_data.get("resolution")
                    or asset_data.get("available_resolutions") is not None
                )
            ):
                # HDRs are excluded from replacement, since they are always replaced.
                # called from asset bar:
                op = col.operator(
                    "scene.blenderkit_download", text="Replace asset resolution"
                )

                op.asset_index = ui_props.active_index
                op.replace_resolution = True
                op.replace = False
                op.invoke_resolution = True
                op.use_resolution_operator = True
                o = utils.get_active_model()
                if o and o.get("asset_data"):
                    if (
                        o["asset_data"]["assetBaseId"]
                        == search.get_search_results()[ui_props.active_index]
                    ):
                        op.model_location = o.location
                        op.model_rotation = o.rotation_euler
                    else:
                        op.model_location = (0, 0, 0)
                        op.model_rotation = (0, 0, 0)
                op.max_resolution = asset_data.get(
                    "max_resolution", 0
                )  # str(utils.get_param(asset_data, 'textureResolutionMax'))

    profile = global_vars.BKIT_PROFILE
    if profile is None:
        return

    # validation
    if (
        author_id == profile.id or utils.profile_is_validator()
    ):  # was not working due to wrong types
        layout.label(text="Management tools:")

        row = layout.row()
        row.operator_context = "INVOKE_DEFAULT"
        op = layout.operator(
            "wm.blenderkit_fast_metadata", text="Edit Metadata", icon="GREASEPENCIL"
        )
        op.asset_id = asset_data["id"]
        op.asset_type = asset_data["assetType"]

        if author_id == str(profile.id):
            row.operator_context = "EXEC_DEFAULT"
            op = layout.operator(
                "wm.blenderkit_url",
                text="Edit Metadata (browser)",
                icon="GREASEPENCIL",
            )
            op.url = paths.url_with_utm(
                f'{paths.BLENDKIT_USER_ASSETS_URL}/{asset_data["assetBaseId"]}/?edit#',
                "uploads_edit",
            )

        row.operator_context = "INVOKE_DEFAULT"

        # Thumbnail regeneration relies on the background thumbnailer which
        # requires Blender 4.2+, so only expose it on supported versions.
        if bpy.app.version >= (4, 2, 0):
            if asset_data["assetType"] == "model":
                op = layout.operator(
                    "object.blenderkit_regenerate_thumbnail",
                    text="Regenerate thumbnail",
                )
                op.asset_index = ui_props.active_index
            elif asset_data["assetType"] == "material":
                op = layout.operator(
                    "object.blenderkit_regenerate_material_thumbnail",
                    text="Regenerate thumbnail",
                )
                op.asset_index = ui_props.active_index

    if author_id == profile.id:  # was not working because of wrong types
        row = layout.row()
        row.operator_context = "INVOKE_DEFAULT"
        op = row.operator("object.blenderkit_change_status", text="Delete")
        op.asset_id = asset_data["id"]
        op.state = "deleted"
        op.original_state = asset_data["verificationStatus"]

    if utils.profile_is_validator():
        layout.label(text="Dev Tools:")
        # edit asset online < currently here for testing,
        # this will soon be the main method to edit asset,
        # locally we will only generate scene metadata
        op = layout.operator(
            "wm.blenderkit_url",
            text="Edit Asset Online",
            icon="GREASEPENCIL",
        )
        op.url = f'{paths.BLENDKIT_ASSETS_EDIT_URL}/{asset_data["assetBaseId"]}/'

        # output asset debug info to console, for easier diagnostics
        op = layout.operator(
            "object.blenderkit_print_asset_debug", text="Print asset debug"
        )
        op.asset_id = asset_data["id"]


class OBJECT_MT_blenderkit_asset_menu(bpy.types.Menu):
    bl_label = "Asset options:"
    bl_idname = "OBJECT_MT_blenderkit_asset_menu"

    def draw(self, context):
        ui_props = context.window_manager.blenderkitUI
        sr = search.get_search_results()
        asset_data = sr[ui_props.active_index]
        draw_asset_context_menu(self.layout, context, asset_data, from_panel=False)


def numeric_to_str(s):
    if s:
        if s < 1:
            s = str(round(s, 1))
        else:
            s = str(round(s))
    else:
        s = "-"
    return s


def push_op_left(layout, strength=3):
    for _ in range(0, strength):
        layout.label(text="")


def label_or_url_or_operator(
    layout,
    text="",
    tooltip="",
    url="",
    operator=None,
    operator_kwargs=None,
    icon_value=None,
    icon=None,
    emboss=False,
):
    """automatically switch between different layout options for linking or tooltips"""
    layout.emboss = "NORMAL" if emboss else "NONE"
    if operator_kwargs is None:
        operator_kwargs = {}

    if operator is not None:
        if icon:
            op = layout.operator(operator, text=text, icon=icon, emboss=emboss)
        elif icon_value:
            op = layout.operator(
                operator, text=text, icon_value=icon_value, emboss=emboss
            )
        else:
            op = layout.operator(operator, text=text, emboss=emboss)
        for kwarg in operator_kwargs.keys():
            setattr(op, kwarg, operator_kwargs[kwarg])
        push_op_left(layout, strength=2)

        return
    if url != "":
        if icon:
            op = layout.operator(
                "wm.blenderkit_url", text=text, icon=icon, emboss=emboss
            )
        elif icon_value:
            op = layout.operator(
                "wm.blenderkit_url", text=text, icon_value=icon_value, emboss=emboss
            )
        else:
            op = layout.operator("wm.blenderkit_url", text=text, emboss=emboss)
        op.url = url
        op.tooltip = tooltip
        push_op_left(layout, strength=5)

        return
    if tooltip != "":
        if icon:
            op = layout.operator(
                "wm.blenderkit_tooltip", text=text, icon=icon, emboss=emboss
            )
        elif icon_value:
            op = layout.operator(
                "wm.blenderkit_tooltip", text=text, icon_value=icon_value, emboss=emboss
            )
        else:
            op = layout.operator("wm.blenderkit_tooltip", text=text, emboss=emboss)
        op.tooltip = tooltip

        # these are here to move the text to left, since operators can only center text by default
        push_op_left(layout, strength=3)
        return
    if icon:
        layout.label(text=text, icon=icon)
    elif icon_value:
        layout.label(text=text, icon_value=icon_value)
    else:
        layout.label(text=text)


THUMBNAIL_MODE_ITEMS = [
    ("main", "Render", "Show the standard asset thumbnail", "IMAGE_DATA", 0),
    ("photo", "Photo", "Show the photo reference thumbnail", "SCENE", 1),
    ("wire", "Wire", "Show the wireframe thumbnail", "SHADING_WIRE", 2),
]


def _comment_sort_key(comment):
    """Sortable key for a comment. Locally-posted comments use "just now" as
    their date - treat those as the newest so they sort after real dates."""
    date = comment.get("submitDate") or ""
    if date == "just now" or date == "":
        return "9999"
    return date


def order_comments_for_display(comments):
    """Reorder comment threads according to the user's preference.

    Comments arrive as a flat list where each top-level comment (level 0) is
    followed by its replies. Replies are kept attached to their parent - only
    the top-level threads are reordered by date.
    """
    order = bpy.context.preferences.addons[__package__].preferences.comments_order
    return _order_comments(comments, order)


def _order_comments(comments, order):
    """Pure reordering of a flat comment list. See order_comments_for_display."""
    if not comments:
        return comments
    if order == "default":
        return comments

    threads = []
    for comment in comments:
        if comment.get("level", 0) == 0 or not threads:
            threads.append([comment])
        else:
            threads[-1].append(comment)
    threads.sort(
        key=lambda thread: _comment_sort_key(thread[0]), reverse=(order == "newest")
    )

    ordered = []
    for thread in threads:
        ordered.extend(thread)
    return ordered


class AssetPopupCard(bpy.types.Operator, ratings_utils.RatingProperties):
    """
    This is the popup card that appears when you click on an asset in the asset bar.
    It shows the asset details and allows you to download the asset.
    """

    bl_idname = "wm.blenderkit_asset_popup"
    bl_label = "Blendkit asset popup"

    width = 800

    thumbnail_mode: EnumProperty(  # type: ignore[valid-type]
        name="Thumbnail Variant",
        description="Choose which preview image to display",
        items=THUMBNAIL_MODE_ITEMS,
        default="main",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return True

    def draw_menu(self, context, layout):
        draw_asset_context_menu(layout, context, self.asset_data, from_panel=False)

    def draw_property(
        self,
        layout,
        left,
        right,
        icon=None,
        icon_value=None,
        url="",
        tooltip="",
        operator=None,
        operator_kwargs=None,
        emboss=False,
    ):
        right = str(right)
        row = layout.row()
        split = row.split(factor=0.35)
        split.alignment = "RIGHT"
        split.label(text=left)
        split = split.split()
        split.alignment = "LEFT"
        # split for questionmark:
        split = split.split(factor=0.9)
        split.alignment = "LEFT"
        if operator_kwargs is None:
            operator_kwargs = {}
        label_or_url_or_operator(
            split,
            text=right,
            tooltip=tooltip,
            url=url,
            operator=operator,
            operator_kwargs=operator_kwargs,
            icon_value=icon_value,
            icon=icon,
            emboss=emboss,
        )
        # additional 'question mark' icon where it's important?
        # Embossed elements are visibly clickable, so we don't need the 'question mark' icon
        if url != "" and not emboss:
            split = split.split()
            op = split.operator("wm.blenderkit_url", text="", icon="QUESTION")
            op.url = url
            op.tooltip = tooltip

    def draw_asset_parameter(
        self, layout, key="", pretext="", do_search=False, decimal=True
    ):
        parameter = utils.get_param(self.asset_data, key)
        if parameter == None:
            return

        # Keep search value unformatted so server queries stay clean.
        search_value = parameter
        display_value = parameter

        if type(parameter) == int:
            if decimal:
                display_value = f"{parameter:,d}"
            else:
                display_value = f"{parameter}"
        elif type(parameter) == float:
            display_value = f"{parameter:,.1f}"
        elif isinstance(parameter, str):
            display_value = parameter.strip()
            search_value = display_value

            if key == "manufacturer":
                lowered = display_value.lower()
                # quick sanity checks to avoid garbage manufacturers
                is_url = (
                    lowered.startswith(("http://", "https://", "www."))
                    or "://" in lowered
                )
                tokens = (
                    lowered.replace(",", " ")
                    .replace("/", " ")
                    .replace("\\", " ")
                    .replace("|", " ")
                    .replace("-", " ")
                    .strip()
                    .split()
                )
                has_invalid_token = any(t in INVALID_TOKENS for t in tokens)

                if is_url or has_invalid_token:
                    return

                if len(display_value) > MAX_MANUFACTURER_LABEL_LEN:
                    display_value = (
                        display_value[: MAX_MANUFACTURER_LABEL_LEN - 3].rstrip() + "..."
                    )

        display_value = str(display_value)

        if do_search:
            kwargs = {
                "esc": True,
                "keywords": f"+{key}:{search_value}",
                "tooltip": f"search by {display_value}",
            }
            # search gets auto emboss
            self.draw_property(
                layout,
                pretext,
                display_value,
                operator="view3d.blenderkit_search",
                operator_kwargs=kwargs,
                emboss=True,
            )
        else:
            self.draw_property(layout, pretext, display_value)

    def draw_description(self, layout, width=250):
        if len(self.asset_data["description"]) > 0:
            box = layout.box()
            box.scale_y = 0.4
            box.label(text="Description")
            box.separator()
            link_more = utils.label_multiline(
                box, self.asset_data["description"], width=width, max_lines=10
            )
            if link_more:
                row = box.row()
                row.scale_y = 2
                op = row.operator(
                    "wm.blenderkit_url", text="See full description", icon="URL"
                )
                op.url = paths.get_asset_gallery_url(self.asset_data["assetBaseId"])
                op.tooltip = "Read full description on website"
            box.separator()

    def draw_properties(self, layout, width=250):
        mparams = self.asset_data["dictParameters"]

        pcoll = icons.icon_collections["main"]

        box = layout.box()

        box.scale_y = 0.6
        box.label(text="Properties")
        box.separator()

        if self.asset_data.get("license") == "cc_zero":
            text = "CC Zero          "
            icon = pcoll["cc0"]
        else:
            text = "Royalty free"
            icon = pcoll["royalty_free"]
        self.draw_property(
            box,
            "License",
            text,
            url=paths.url_with_utm(
                f"{global_vars.SERVER}/docs/licenses/", "license_docs"
            ),
            tooltip="All Blendkit assets are available for commercial use. \n"
            "Click to read more about Blendkit licenses on the website",
        )

        if upload.can_edit_asset(asset_data=self.asset_data):
            icon = pcoll[self.asset_data["verificationStatus"]]
            verification_status_tooltips = {
                "uploading": "Your asset got stuck during upload. Probably, your file was too large "
                "or your connection too slow or interrupting. If you have repeated issues, "
                "please contact us and let us know, it might be a bug",
                "uploaded": "Your asset uploaded successfully. Yay! If it's public, "
                "it's awaiting validation. If it's private, use it",
                "on_hold": "Your asset needs some (usually smaller) fixes, "
                "so we can make it public for everybody."
                " Please check validator comments under your asset to see the feedback "
                "that we send to every creator personally",
                "rejected": "The asset has serious quality issues, "
                "and it's probable that it might be good to start "
                "all over again or try with something simpler. "
                "You also get personal feedback into your e-mail, "
                "since we believe that together, we can all learn "
                "to become awesome 3D artists",
                "deleted": "You deleted this asset",
                "validated": "Your asset passed our validation process, "
                "and is now available to Blendkit users",
                "ready": "Your asset is validated and ready to be used by everyone",
            }
            self.draw_property(
                box,
                "Verification",
                self.asset_data["verificationStatus"],
                icon_value=icon.icon_id,
                url=paths.url_with_utm(
                    f"{global_vars.SERVER}/docs/validation-status/", "validation_docs"
                ),
                tooltip=verification_status_tooltips.get(
                    self.asset_data["verificationStatus"], "unknown status"
                ),
            )
        # resolution/s
        resolution = utils.get_param(self.asset_data, "textureResolutionMax")
        available_res = self.asset_data.get("available_resolutions")
        fs = self.asset_data["files"]

        if resolution is not None or len(available_res) > 0:
            if resolution is None:
                # this should get removed once all assets that have texture have proper resolution parameter fixed
                # by now part of assets that have texture don't have texture resolution marked
                ress = f"{int(round(available_res[-1] / 1024, 0))}K"
            else:
                ress = f"{int(round(resolution / 1024, 0))}K"
            self.draw_property(
                box,
                "Resolution",
                ress,
                tooltip="Maximal resolution of textures in this asset.\n"
                "Most texture asset have also lower resolutions generated.\n"
                "Go to Blendkit add-on import settings to set default resolution",
            )
            # this would normally show only when theres's texture resolution parameter.
            # but this parameter wasn't always uploaded correctly, that's why we need to check also for others
            if fs and len(fs) > 2:  # and utils.profile_is_validator():
                resolutions = ""
                list.sort(fs, key=lambda f: f["fileType"])
                for f in fs:
                    if f["fileType"].find("resolution") > -1:
                        resolutions += f["fileType"][11:] + " "
                resolutions = resolutions.replace("_", ".")
                self.draw_property(box, "Generated res", resolutions)

        self.draw_asset_parameter(
            box, key="designer", pretext="Designer", do_search=True
        )
        self.draw_asset_parameter(
            box, key="manufacturer", pretext="Manufacturer", do_search=True
        )
        self.draw_asset_parameter(
            box, key="designCollection", pretext="Collection", do_search=True
        )
        self.draw_asset_parameter(box, key="designVariant", pretext="Variant")
        self.draw_asset_parameter(
            box, key="designYear", pretext="Design year", decimal=False
        )

        self.draw_asset_parameter(box, key="faceCount", pretext="Face count")

        if utils.profile_is_validator():
            self.draw_asset_parameter(box, key="materialStyle", pretext="Style")
            self.draw_asset_parameter(box, key="modelStyle", pretext="Style")

        if utils.get_param(self.asset_data, "dimensionX"):
            text = utils.fmt_dimensions(mparams)
            self.draw_property(box, "Size", text)
        if self.asset_data.get("filesSize"):
            fs = self.asset_data["filesSize"] * 1024
            # multiply because the number is reduced when search is done to avoid C integer limit with large files
            fsmb = fs // (1024 * 1024)
            fskb = fs % 1024
            if fsmb == 0:
                self.draw_property(box, "Original size", f"{fskb} KB")
            else:
                self.draw_property(box, "Original size", f"{fsmb} MB")

        # Free/Full plan or private Access - with special handling for addons
        plans_tooltip = (
            "Blendkit has 2 plans:\n"
            "  *  Free plan - more than 50% of all assets\n"
            "  *  Full plan - unlimited access to everything\n"
            "Click to go to subscriptions page"
        )

        # Special pricing display for addons
        if self.asset_data.get("assetType") == "addon":

            can_download = self.asset_data.get("canDownload")
            is_free = self.asset_data.get("isFree")

            # Get pricing info from extensions cache
            user_price = self.asset_data.get("userPrice")
            base_price = self.asset_data.get("basePrice")
            is_for_sale = self.asset_data.get("isForSale")

            if self.asset_data["isPrivate"]:
                text = "Private"
                self.draw_property(box, "Access", text, icon="LOCKED")
            elif utils.profile_is_validator() and user_price and base_price:
                text = f"${user_price} (was ${base_price})"
                icon = pcoll["for_sale"]
                self.draw_property(
                    box,
                    "Pricing (Validator)",
                    text,
                    icon_value=icon.icon_id,
                )

            elif is_for_sale and not can_download and user_price and base_price:
                if str(user_price) != str(base_price):
                    text = f"${user_price} (was ${base_price})"
                else:
                    text = f"${base_price}"
                text += " (Not purchased)"
                icon = pcoll["for_sale"]
                self.draw_property(
                    box,
                    "Price",
                    text,
                    icon_value=icon.icon_id,
                    tooltip="This addon is for sale but you haven't purchased it yet.\nPrice shown is your discounted price / original price",
                )
            elif is_for_sale and not can_download and base_price:
                text = f"${base_price} (Not purchased)"
                icon = pcoll["for_sale"]
                self.draw_property(
                    box,
                    "Price",
                    text,
                    icon_value=icon.icon_id,
                    tooltip="This addon is for sale but you haven't purchased it yet",
                )
            elif is_for_sale and can_download and base_price:
                text = f"Purchased"
                icon = pcoll["for_sale"]
                self.draw_property(
                    box,
                    "Price",
                    text,
                    icon_value=icon.icon_id,
                    tooltip="You have purchased this addon",
                )
            elif not is_free and not is_for_sale:
                text = "Full plan"
                icon = pcoll["full"]
                self.draw_property(
                    box,
                    "Access",
                    text,
                    icon_value=icon.icon_id,
                    tooltip=plans_tooltip,
                    url=paths.url_with_utm(
                        paths.BLENDKIT_PLANS_URL, "asset_popup_access"
                    ),
                )
            else:
                text = "Free"
                icon = pcoll["free"]
                self.draw_property(
                    box,
                    "Access",
                    text,
                    icon_value=icon.icon_id,
                    tooltip="This addon is free to use",
                )

            # Display Blender version requirements for addons
            dict_params = self.asset_data.get("dictParameters", {})
            min_version = dict_params.get("blenderVersionMin")
            max_version = dict_params.get("blenderVersionMax")
            if min_version:
                min_version_tuple = tuple(map(int, min_version.split(".")))
            if max_version:
                max_version_tuple = tuple(map(int, max_version.split(".")))

            if min_version or max_version:
                version_text = ""
                if min_version and max_version:
                    version_text = f"{min_version} - {max_version}"
                elif min_version:
                    version_text = f"{min_version}+"
                elif max_version:
                    version_text = f"≤ {max_version}"

                # Check if current Blender version is compatible
                current_version = (
                    f"{bpy.app.version[0]}.{bpy.app.version[1]}.{bpy.app.version[2]}"
                )
                is_compatible = True

                if min_version:
                    if bpy.app.version < min_version_tuple:
                        is_compatible = False

                if max_version and is_compatible:
                    if bpy.app.version > max_version_tuple:
                        is_compatible = False

                # Display version requirement with appropriate warning
                if not is_compatible:
                    box.alert = True
                    self.draw_property(
                        box,
                        "Blender versions",
                        f"{version_text} (Incompatible!)",
                        icon="ERROR",
                        tooltip=f"This addon requires Blender {version_text}, but you're using {current_version}",
                    )
                    box.alert = False
                else:
                    self.draw_property(
                        box,
                        "Blender versions",
                        version_text,
                        icon="CHECKMARK",
                        tooltip=f"This addon is compatible with your Blender version ({current_version})",
                    )
        else:
            # Regular asset access display
            if self.asset_data["isPrivate"]:
                text = "Private"
                self.draw_property(box, "Access", text, icon="LOCKED")
            elif self.asset_data["isFree"]:
                text = "Free plan"
                icon = pcoll["free"]
                self.draw_property(
                    box,
                    "Access",
                    text,
                    icon_value=icon.icon_id,
                    tooltip=plans_tooltip,
                    url=paths.url_with_utm(
                        paths.BLENDKIT_PLANS_URL, "asset_popup_access"
                    ),
                )
            else:
                text = "Full plan"
                icon = pcoll["full"]
                self.draw_property(
                    box,
                    "Access",
                    text,
                    icon_value=icon.icon_id,
                    tooltip=plans_tooltip,
                    url=paths.url_with_utm(
                        paths.BLENDKIT_PLANS_URL, "asset_popup_access"
                    ),
                )

        if utils.profile_is_validator():
            date = self.asset_data["created"][:10]
            date = f"{date[8:10]}. {date[5:7]}. {date[:4]}"
            self.draw_property(box, "Created", date)
            self.draw_property(
                box,
                "Sexualized:",
                self.asset_data.get("dictParameters", {}).get("sexualizedContent"),
            )

        has_warning, difference = utils.asset_from_newer_blender_version(
            self.asset_data
        )
        if has_warning:
            if difference == "major_newer":
                warning = (
                    f"{self.asset_data['sourceAppVersion']} - newer major version!"
                )
            elif difference == "minor":
                warning = (
                    f"{self.asset_data['sourceAppVersion']} - newer minor version!"
                )
            box.alert = True
            self.draw_property(
                box,
                "Blender version",
                warning,
                icon="ERROR",
            )
            box.alert = False
        else:
            self.draw_property(
                box,
                "Blender version",
                self.asset_data["sourceAppVersion"],
            )

        # Add TwinBru specific parameters for material assets
        # only if they have 'twinbruReference' in the 'dictParameters'
        if self.asset_data.get("dictParameters").get("twinbruReference"):
            box.separator()
            box.label(text="TwinBru physical material categories")

            self.draw_asset_parameter(
                box,
                key="twinBruCatEndUse",
                pretext="End Use",
                do_search=True,
            )
            self.draw_asset_parameter(
                box,
                key="twinBruColourType",
                pretext="Colour Type",
                do_search=True,
            )
            self.draw_asset_parameter(
                box,
                key="twinBruCharacteristics",
                pretext="Characteristics",
                do_search=True,
            )
            self.draw_asset_parameter(
                box,
                key="twinBruDesignType",
                pretext="Design Type",
                do_search=True,
            )

        # Product Link for assets that have it.
        if self.asset_data.get("dictParameters").get("productLink"):
            self.draw_property(
                box,
                "Product Link",
                "View on manufacturer's website",
                url=self.asset_data["dictParameters"]["productLink"],
                icon="URL",
                emboss=True,
            )

        box.separator()

    def draw_author_area(self, context, layout, width=330):
        self.draw_author(context, layout, width=width)

    def draw_author(
        self, context: bpy.types.Context, layout: bpy.types.UILayout, width: int = 330
    ):
        image_split = 0.25
        text_width = width
        authors = global_vars.BKIT_AUTHORS
        author_id = int(self.asset_data["author"]["id"])
        author = authors.get(author_id)
        if author is None:
            return

        row = layout.row()
        author_box = row.box()
        author_box.scale_y = 0.6  # get text lines closer to each other
        author_box.label(text="Author")  # just one extra line to give spacing
        if hasattr(self, "gimg"):
            _protected_images.add(self.gimg.name)
            author_left = author_box.split(factor=image_split)
            author_left.template_icon(icon_value=self.gimg.preview.icon_id, scale=7)
            self.gimg.gl_touch()

            text_area = author_left.split()
            text_width = int(text_width * (1 - image_split))
        else:
            text_area = author_box

        author_right = text_area.column()
        row = author_right.row()
        col = row.column()

        utils.label_multiline(col, text=author.tooltip, width=text_width)
        # check if author didn't fill any data about himself and prompt him if that's the case
        if utils.user_is_owner(asset_data=self.asset_data) and not author.aboutMe:
            row = col.row()
            row.enabled = False
            row.label(text="Please introduce yourself to the community!")

            op = col.operator("wm.blenderkit_url", text="Edit your profile")
            op.url = paths.url_with_utm(f"{global_vars.SERVER}/profile", "profile_edit")  # type: ignore[attr-defined]
            op.tooltip = "Edit your profile on Blendkit webpage"  # type: ignore[attr-defined]

        pcoll = icons.icon_collections["main"]

        button_row = author_box.row()
        button_row.scale_y = 2.0

        # AUTHOR's ASSETS SEARCH
        op = button_row.operator(
            "view3d.blenderkit_search", text="Find Assets By Author", icon="VIEWZOOM"
        )
        op.tooltip = "Search all assets by this author.\nShortcut: Hover over the asset in the asset bar and press 'A'."  # type: ignore[attr-defined]
        op.esc = True  # type: ignore[attr-defined]
        op.keywords = ""  # type: ignore[attr-defined] # must not be empty otherwise search will use previous keywords
        op.author_id = str(author_id)  # type: ignore[attr-defined]

        button_row = button_row.row(align=True)

        # AUTHOR's BLENDKIT PROFILE
        url = paths.get_author_gallery_url(author.id)
        tooltip = "Go to author's profile on Blendkit web.\nShortcut: Hover over asset in the asset bar and press 'P'."
        icon_value = pcoll["logo"].icon_id
        op = button_row.operator("wm.blenderkit_url", text="", icon_value=icon_value)
        op.url = url  # type: ignore[attr-defined]
        op.tooltip = tooltip  # type: ignore[attr-defined]

        # ABOUT ME WEBPAGE
        text = None
        if author.aboutMeUrl:
            text = utils.remove_url_protocol(author.aboutMeUrl)
            text = utils.shorten_text(text, 45)
            op = button_row.operator("wm.blenderkit_url", text="", icon="URL")
            op.url = author.aboutMeUrl  # type: ignore[attr-defined]
            op.tooltip = f"Go to author's personal Webpage: {author.aboutMeUrl}\nShortcut: Hover over asset in the asset bar and press 'W'."  # type: ignore[attr-defined]

        # SOCIAL NETWORKS
        social_networks = author.socialNetworks
        for social_network in social_networks:
            url = social_network.url
            if url is None or text is None:
                continue

            icon_name = f"logo_{social_network.name.lower()}"
            if icon_name in pcoll:
                op = button_row.operator(
                    "wm.blenderkit_url", text="", icon_value=pcoll[icon_name].icon_id
                )
            else:
                bk_logger.warning(
                    f"Social network icon {icon_name} not found in icon collection"
                )
                op = button_row.operator("wm.blenderkit_url", text="", icon="URL")

            op.url = url  # type: ignore[attr-defined]
            op.tooltip = f"Go to {social_network.name} profile"  # type: ignore[attr-defined]

    def _get_active_thumbnail(self):
        mode = getattr(self, "thumbnail_mode", "main")
        if mode == "photo" and getattr(self, "full_photo_thumbnail", None):
            return self.full_photo_thumbnail
        if mode == "wire" and getattr(self, "full_wire_thumbnail", None):
            return self.full_wire_thumbnail
        return self.img

    def _has_additional_thumbnails(self):
        return bool(
            getattr(self, "full_photo_thumbnail", None)
            or getattr(self, "full_wire_thumbnail", None)
        )

    def draw_thumbnail_box(self, layout, width=250):
        layout.emboss = "NORMAL"

        box_thumbnail = layout.box()

        thumb_image = self._get_active_thumbnail()
        _protected_images.add(thumb_image.name)
        box_thumbnail.scale_y = 0.4
        box_thumbnail.template_icon(
            icon_value=thumb_image.preview.icon_id, scale=width * 0.12
        )
        thumb_image.gl_touch()

        if self._has_additional_thumbnails():
            selector_col = box_thumbnail.column()
            selector_col.separator()
            selector_col.label(text="Preview variations:")
            buttons = selector_col.row(align=True)
            buttons.alignment = "CENTER"
            buttons.scale_x = 1.3
            buttons.scale_y = 3.0

            buttons.prop_enum(
                self,
                "thumbnail_mode",
                "main",
                icon="IMAGE_DATA",
                text="",
            )
            if self.asset_data.get("assetType") == "printable" and getattr(
                self, "full_photo_thumbnail", None
            ):
                buttons.prop_enum(
                    self,
                    "thumbnail_mode",
                    "photo",
                    icon="SCENE",
                    text="",
                )
            if self.asset_data.get("assetType") in {
                "printable",
                "model",
                "scene",
            } and getattr(self, "full_wire_thumbnail", None):
                buttons.prop_enum(
                    self,
                    "thumbnail_mode",
                    "wire",
                    icon="SHADING_WIRE",
                    text="",
                )
            selector_col.separator()

        # From here on, only ratings are drawn, which won't be displayed for private assets from now on.

        rc = self.asset_data.get("ratingsCount")

        if (
            not self.asset_data["isPrivate"]
            and rc.get("quality") is not None
            and rc.get("workingHours") is not None
        ):
            row = box_thumbnail.row()
            row.alignment = "EXPAND"

            # display_ratings = can_display_ratings(self.asset_data)
            show_rating_threshold = 0
            show_rating_prompt_threshold = 5

            if rc:
                rcount = min(rc["quality"], rc["workingHours"])
            else:
                rcount = 0
            if rcount >= show_rating_threshold or upload.can_edit_asset(
                asset_data=self.asset_data
            ):
                s = numeric_to_str(self.asset_data["score"])
                q = numeric_to_str(self.asset_data["ratingsAverage"].get("quality"))
                c = numeric_to_str(self.asset_data["ratingsMedian"].get("workingHours"))
            else:
                s = "-"
                q = "-"
                c = "-"

            pcoll = icons.icon_collections["main"]

            row.emboss = "NONE"
            op = row.operator(
                "wm.blenderkit_tooltip", text=str(s), icon_value=pcoll["trophy"].icon_id
            )
            op.tooltip = (
                "Asset score calculated from user ratings. \n\n"
                "Score = average quality × median complexity × 10*\n\n *Happiness multiplier"
            )
            row.label(text="   ")

            tooltip_extension = f".\n\nRatings results are shown for assets with more than {show_rating_threshold} ratings"
            op = row.operator("wm.blenderkit_tooltip", text=str(q), icon="SOLO_ON")
            op.tooltip = (
                f"Quality, average from {rc['quality']} rating{'' if rc['quality'] == 1 else 's'}"
                f"{tooltip_extension if rcount <= show_rating_threshold else ''}"
            )
            row.label(text="   ")

            op = row.operator(
                "wm.blenderkit_tooltip",
                text=str(c),
                icon_value=pcoll["dumbbell"].icon_id,
            )
            op.tooltip = (
                f"Complexity, median from {rc['workingHours']} rating{'' if rc['workingHours'] == 1 else 's'}"
                f"{tooltip_extension if rcount <= show_rating_threshold else ''}"
            )

            if (
                rcount <= show_rating_prompt_threshold
                and self.rating_quality == 0
                and self.rating_work_hours == 0
            ):
                # if the asset has less than 5 ratings, and the user hasn't rated it yet, prompt them to do so
                box_thumbnail.alert = True
                box_thumbnail.label(text=f"")
                box_thumbnail.label(
                    text=f"This asset has only {rcount} rating{'' if rcount == 1 else 's'}, please rate."
                )

        row = box_thumbnail.row()
        row.alert = False

        row.scale_y = 3
        ui_props = bpy.context.window_manager.blenderkitUI
        if self.asset_data.get("canDownload", True):
            row.prop(
                ui_props,
                "drag_init_button",
                icon="MOUSE_LMB_DRAG",
                text="Click / Drag from here",
                emboss=True,
            )
        else:
            variant = unlock_options.get_unlock_variant()
            op = layout.operator(
                "wm.blenderkit_url", text=variant.button_text, icon="UNLOCKED"
            )
            op.url = paths.get_unlock_asset_url(
                self.asset_data["id"], "asset_unlock_panel", variant.identifier
            )

    def draw_menu_desc_author(self, context, layout, width=330):
        box = layout.column()

        box.emboss = "NORMAL"
        # left - tooltip & params
        row = box.row()
        split_factor = 0.7
        split_left = row.split(factor=split_factor)
        col = split_left.column()
        width_left = int(width * split_factor)
        self.draw_description(col, width=width_left)

        self.draw_properties(col, width=width_left)

        # right - menu
        split_right = split_left.split()
        col = split_right.column()
        self.draw_menu(context, col)

        # author
        self.draw_author_area(context, box, width=width)

    def draw_titlebar(self, context, layout):
        top_drag_bar = layout.box()
        bcats = global_vars.DATA["bkit_categories"]

        cat_path = categories.get_category_path(bcats, self.asset_data["category"])[1:]

        cat_path_names = categories.get_category_name_path(
            bcats, self.asset_data["category"]
        )[1:]

        aname = self.asset_data["displayName"]
        aname = aname[0].upper() + aname[1:]

        name_row = top_drag_bar.row()

        pcoll = icons.icon_collections["main"]

        name_row.label(text="", icon_value=pcoll["logo"].icon_id)

        for i, c in enumerate(cat_path):
            cat_name = cat_path_names[i]
            ui_props = bpy.context.window_manager.blenderkitUI
            if i < len(cat_path) - 1:
                bl_id = "view3d.blenderkit_set_category_in_popup_card"
            else:
                bl_id = "view3d.blenderkit_set_category_in_popup_card_last"
            op = name_row.operator(bl_id, text=cat_name + "     >", emboss=True)
            op.asset_type = ui_props.asset_type
            # this gets filled not to change anything in browsing categories
            op.category_browse = global_vars.DATA["active_category_browse"][
                ui_props.asset_type
            ][-1]
            # but enables to directly browse the category clicked.
            op.category_search = c

        name_row.label(text=aname)
        push_op_left(name_row, strength=1)
        op = name_row.operator("view3d.close_popup_button", text="", icon="CANCEL")

    def draw_comment_response(self, context, layout, comment_id):
        if not utils.user_logged_in():
            return
        pcoll = icons.icon_collections["main"]

        layout.separator()

        row = layout.row()
        ui_props = bpy.context.window_manager.blenderkitUI
        split = row.split(factor=0.8, align=True)
        split.active = True
        split.prop(ui_props, "new_comment", text="", icon="GREASEPENCIL")
        split = split.split()
        op = split.operator(
            "wm.blenderkit_post_comment",
            text="post comment",
            icon_value=pcoll["post_comment"].icon_id,
        )
        op.asset_id = self.asset_data["assetBaseId"]
        op.comment_id = comment_id

        layout.separator()

    def draw_comment(
        self, context: Context, layout: UILayout, comment: dict, width: int = 330
    ):
        row = layout.row()
        if comment["level"] > 0:
            split = row.split(factor=0.05 * comment["level"])
            split.label(text="")
            row = split.split()
        box = row.box()
        box.emboss = "NORMAL"
        row = box.row()
        factor = 0.8
        if comment["canChangeIsPrivate"]:
            factor = 0.7
        split = row.split(factor=factor)
        is_moderator = comment["userModerator"]
        if is_moderator:
            role_text = f" - moderator"
        else:
            role_text = ""
        row = split.row()
        row.enabled = False
        row.label(text=f"{comment['submitDate']} - {comment['userName']}{role_text}")

        if comment["canChangeIsPrivate"]:
            if comment["isPrivate"]:
                ptext = "Private"
                val = False
            else:
                ptext = "Public"
                val = True
            split = split.split()
            split = split.split(factor=0.333)
            split.enabled = True
            op = split.operator(
                "wm.blenderkit_is_private_comment", text=ptext
            )  # , icon='TRIA_DOWN')
            op.asset_id = self.asset_data["assetBaseId"]  # type: ignore
            op.comment_id = comment["id"]  # type: ignore
            op.is_private = val  # type: ignore

        removal = False
        likes = 0
        dislikes = 0
        user_liked = False
        user_disliked = False
        profile = global_vars.BKIT_PROFILE

        for l in comment["flags"]:
            if l["flag"] == "like":
                likes += 1
                if profile is not None:
                    if l["id"] == profile.id:
                        user_liked = True
            if l["flag"] == "dislike":
                dislikes += 1
                if profile is not None:
                    if l["id"] == profile.id:
                        user_disliked = True

            if l["flag"] == "removal":
                removal = True

        split = split.split()
        split_like = split.split(factor=0.5)
        sub_like = split_like.row()
        sub_like.enabled = utils.user_logged_in() and not user_liked

        op = sub_like.operator(
            "wm.blenderkit_upvote_comment", text=str(likes), icon="TRIA_UP"
        )
        op.asset_id = self.asset_data["assetBaseId"]  # type: ignore
        op.comment_id = comment["id"]  # type: ignore
        op.flag = "like"  # type: ignore

        split_dislike = split_like.split()
        split_dislike = split_dislike.row()
        split_dislike.enabled = utils.user_logged_in() and not user_disliked
        op = split_dislike.operator(
            "wm.blenderkit_upvote_comment", text=str(dislikes), icon="TRIA_DOWN"
        )
        op.asset_id = self.asset_data["assetBaseId"]  # type: ignore
        op.comment_id = comment["id"]  # type: ignore
        op.flag = "dislike"  # type: ignore

        if removal:
            row.alert = True
            row.label(text="", icon="ERROR")
        rows = utils.label_multiline(
            box,
            text=comment["comment"],
            width=width * (1 - 0.05 * comment["level"]),
            use_urls=True,
            max_lines=1000000,
        )

        if utils.profile_is_validator():
            row = box.row()
            split = row.split(factor=0.95)
            split.label(text="")
            split = split.split()
            row.alert = False
            op = row.operator("wm.url_open", text="", icon="GREASEPENCIL")
            op.url = f'{global_vars.SERVER}/bksecretadmin/django_comments_xtd/xtdcomment/{comment["id"]}/change/'  # type: ignore

        if utils.user_logged_in():
            # row = rows[-1]
            row = layout.row()
            split = row.split(factor=0.8)
            split.label(text="")
            split = split.split()
            op = split.operator(
                "view3d.blenderkit_set_comment_reply_id",
                text="Reply",
                icon="GREASEPENCIL",
            )
            op.comment_id = comment["id"]  # type: ignore

    def draw(self, context):
        set_overlay_panel_active()

        layout = self.layout
        # top draggable bar with name of the asset
        top_row = layout.row()
        self.draw_titlebar(context, top_row)
        # left side
        row = layout.row(align=True)
        split_ratio = 0.45
        split_left = row.split(factor=split_ratio)
        left_column = split_left.column()

        self.draw_thumbnail_box(left_column, width=int(self.width * split_ratio))

        if not utils.user_is_owner(asset_data=self.asset_data) and self.asset_data.get(
            "assetType"
        ) not in ("addon", "author"):
            # Draw ratings, but not for owners of assets - doesn't make sense.
            # also addons and authors are excluded.
            ratings_box = left_column.box()
            self.prefill_ratings()
            ratings.draw_ratings_menu(self, context, ratings_box)
        # self.draw_description(left_column, width = int(self.width*split_ratio))
        # right split
        split_right = split_left.split()
        self.draw_menu_desc_author(
            context, split_right, width=int(self.width * (1 - split_ratio))
        )

        tip_box = layout.box()
        tip_box.label(text=self.tip)
        # comments
        ui_props = bpy.context.window_manager.blenderkitUI
        if ui_props.reply_id == 0:
            self.draw_comment_response(context, layout, 0)
        comments = global_vars.DATA.get("asset comments", {})
        self.comments = comments.get(self.asset_data["assetBaseId"], [])
        if self.comments is not None:
            for comment in order_comments_for_display(self.comments):
                self.draw_comment(context, layout, comment, width=self.width)
                if ui_props.reply_id == comment["id"]:
                    self.draw_comment_response(context, layout, comment["id"])

    def execute(self, context):
        wm = context.window_manager
        ui_props = context.window_manager.blenderkitUI
        ui_props.draw_tooltip = False
        ui_props.reply_id = 0

        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[ui_props.active_index]
        self.asset_data = asset_data

        self.img = ui.get_large_thumbnail_image(asset_data)
        utils.img_to_preview(self.img, copy_original=True)

        if asset_data["assetType"] == "printable":
            self.full_photo_thumbnail = ui.get_full_photo_thumbnail(asset_data)
            if self.full_photo_thumbnail:
                utils.img_to_preview(self.full_photo_thumbnail, copy_original=True)

        # NOTE: not used currently
        if asset_data["assetType"] in {"printable", "model", "scene"}:
            self.full_wire_thumbnail = ui.get_full_wire_thumbnail(asset_data)
            if self.full_wire_thumbnail:
                utils.img_to_preview(self.full_wire_thumbnail, copy_original=True)

        self.thumbnail_mode = "main"

        self.asset_type = asset_data["assetType"]
        self.asset_id = asset_data["id"]

        author_id = int(asset_data["author"]["id"])
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author and author.gravatarImg and author.gravatarHash:
            self.gimg = utils.get_hidden_image(author.gravatarImg, author.gravatarHash)

        self.tip = f"Tip: {random.choice(global_vars.TIPS)[0]}"

        if utils.user_logged_in() and asset_data.get("assetType") != "author":
            ratings_utils.ensure_rating(self.asset_id)
            # pre-fill ratings
            self.prefill_ratings()

        user_preferences = bpy.context.preferences.addons[__package__].preferences
        if (
            user_preferences.asset_popup_counter
            < user_preferences.asset_popup_counter_max
        ):
            user_preferences.asset_popup_counter += 1
        # get comments
        api_key = user_preferences.api_key
        if asset_data.get("assetType") != "author":
            # always get fresh comments for the asset, as they can change frequently
            client_lib.get_comments(asset_data["assetBaseId"], api_key)
            comments = global_vars.DATA.get("asset comments", {}).get(
                asset_data["assetBaseId"], []
            )

            # # Lazy / dedup'd fetch — avoid hammering the rate-limited backend
            # # when many tooltips/popups open in quick succession.
            # comments = comments_utils.request_comments_if_needed(
            #     asset_data["assetBaseId"], api_key
            # )

            # If the request just went out the cache will still be empty here;
            # the asset bar / next popup will pick it up once it arrives.
            if comments is None:
                comments = global_vars.DATA.get("asset comments", {}).get(
                    asset_data["assetBaseId"], []
                )
            self.comments = comments
        else:
            self.comments = []

        return wm.invoke_popup(self, width=self.width)


class OBJECT_MT_blenderkit_login_menu(bpy.types.Menu):
    bl_label = "Blendkit login/signup:"
    bl_idname = "OBJECT_MT_blenderkit_login_menu"

    def draw(self, context):
        layout = self.layout

        draw_login_buttons(layout)


class SetCommentReplyId(bpy.types.Operator):
    """Set comment reply ID, setting to which comment it is replied to and where the input box should be shown."""

    bl_idname = "view3d.blenderkit_set_comment_reply_id"
    bl_label = "Blendkit Set Comment reply ID"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    comment_id: IntProperty(  # type: ignore[valid-type]
        name="Category", description="set this category active", default=0
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.reply_id = self.comment_id
        return {"FINISHED"}


class SetCategoryOperatorOrigin(bpy.types.Operator):
    bl_idname = "view3d.blenderkit_set_category_origin"
    bl_label = "Blendkit Set Active Category"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    category_browse: StringProperty(  # type: ignore[valid-type]
        name="Category browse",
        description="set this category active for browsing",
        default="",
    )
    category_search: StringProperty(  # type: ignore[valid-type]
        name="Category search",
        description="set this category active for search",
        default="",
    )

    asset_type: StringProperty(  # type: ignore[valid-type]
        name="Asset Type", description="asset type", default="MODEL"
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        acat = global_vars.DATA["active_category_browse"][self.asset_type]
        if self.category_browse == "":
            # Go up to the parent category. Keep at least the root entry
            # to avoid IndexError on subsequent acat[-1] access.
            if len(acat) > 1:
                acat.pop()
        elif acat and self.category_browse == acat[-1]:
            # don't change category if it is the same
            pass
        else:
            acat.append(self.category_browse)
        search_props = utils.get_search_props()
        search_props.search_category = self.category_search
        # we have to write back to wm. Thought this should happen with original list.
        global_vars.DATA["active_category_browse"][self.asset_type] = acat
        return {"FINISHED"}


# TODO: Handle here SelectSubcategory/SelectCategory
# and VisitSubcategory/VisitCategory and VisitUpperCategory/VisitUpperSubcategory
class SetCategoryOperator(SetCategoryOperatorOrigin):
    """Visit subcategory"""

    bl_idname = "view3d.blenderkit_set_category"


class SetCategoryOperatorInPopupCard(SetCategoryOperatorOrigin):
    """Subcategory of the asset. Click to search this subcategory."""

    bl_idname = "view3d.blenderkit_set_category_in_popup_card"


class SetCategoryOperatorLastInPopupCard(SetCategoryOperatorOrigin):
    """Subcategory of the asset. Click to search this subcategory. Shortcut: Hover over asset in the asset bar and press 'C'."""

    bl_idname = "view3d.blenderkit_set_category_in_popup_card_last"


class ToggleClipboardScan(bpy.types.Operator):
    """Toggle whether asset links are set from clipboard when copied."""

    bl_idname = "wm.blenderkit_toggle_clipboard_scan"
    bl_label = "Toggle Clipboard Scan"

    def execute(self, context):
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        user_preferences.use_clipboard_scan = not user_preferences.use_clipboard_scan
        return {"FINISHED"}


class ClearSearchKeywords(bpy.types.Operator):
    """Clear search keywords"""

    bl_idname = "view3d.blenderkit_clear_search_keywords"
    bl_label = "Clear search keywords"

    def execute(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_keywords = ""
        return {"FINISHED"}


class ClosePopupButton(bpy.types.Operator):
    """Close the popup window. It can also be closed by pressing Esc or clicking outside it."""

    bl_idname = "view3d.close_popup_button"
    bl_label = "Close Popup"
    bl_options = {"REGISTER", "INTERNAL"}

    def invoke(self, context, event):
        """Force the (containing, parent) popup to close.
        This was done by emulating Esc or hacking mouse, but stopped working in B5.
        But can be effectively done by just tweaking screen: https://blender.stackexchange.com/a/329900
        """
        bpy.context.window.screen = bpy.context.window.screen
        return {"FINISHED"}


class PopupDialog(bpy.types.Operator):
    """Small popup dialog to inform user."""

    bl_idname = "wm.blenderkit_popup_dialog"
    bl_label = "Blendkit message:"
    bl_options = {"REGISTER", "INTERNAL"}

    message: StringProperty(default="")  # type: ignore[valid-type]
    width: IntProperty(default=300)  # type: ignore[valid-type]

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        row = layout.row()
        row.label(text=self.message)
        row.operator("view3d.close_popup_button", text="", icon="CANCEL")
        layout.active_default = True

    def execute(self, context):
        wm = bpy.context.window_manager
        return wm.invoke_popup(self, width=self.width)


class UrlPopupDialog(bpy.types.Operator):
    """Show a popup asking the user to subscribe or log in to access the locked asset"""

    bl_idname = "wm.blenderkit_url_dialog"
    bl_label = "Blendkit message:"
    bl_options = {"REGISTER", "INTERNAL"}

    url: StringProperty(name="Url", description="url", default="")  # type: ignore[valid-type]

    link_text: StringProperty(  # type: ignore[valid-type]
        name="Url", description="url", default="Go to website"
    )

    header: StringProperty(name="Header", description="header", default="")  # type: ignore[valid-type]

    message: StringProperty(name="Text", description="text", default="")  # type: ignore[valid-type]

    width: IntProperty(name="width", description="width", default=300)  # type: ignore[valid-type]

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        row = layout.row()
        if self.header:
            row.label(text=self.header)
        row.operator("view3d.close_popup_button", text="", icon="CANCEL")
        utils.label_multiline(layout, text=self.message, width=300, align="CENTER")

        layout.active_default = True
        op = layout.operator("wm.url_open", text=self.link_text, icon="QUESTION")
        if not utils.user_logged_in():
            if self.message.find("purchased") != -1:
                text = "purchased"
            else:
                text = "subscribed"

            layout.separator()
            login_row = layout.row(align=True)
            login_row.active_default = False
            login_row.operator_context = "EXEC_DEFAULT"
            split = login_row.split(factor=0.6)
            split.label(text=f"Already {text}?")
            op_login = split.operator("wm.blenderkit_login", text="Log in", icon="USER")
            op_login.signup = False
            op_login.placement = "premium_popup"
        op.url = self.url

    def execute(self, context):
        wm = bpy.context.window_manager
        return wm.invoke_popup(self, width=self.width)


class LoginPopupDialog(bpy.types.Operator):
    """Popup a dialog which enables the user to log in after being logged out automatically."""

    bl_idname = "wm.blenderkit_login_dialog"
    bl_label = "Blendkit login"
    bl_options = {"REGISTER", "INTERNAL"}

    message: StringProperty(  # type: ignore[valid-type]
        name="Message",
        description="",
        default="Your were logged out from . Please login again. ",
    )

    link_text: StringProperty(  # type: ignore[valid-type]
        name="Url", description="url", default="Login to Blendkit"
    )

    placement: StringProperty(  # type: ignore[valid-type]
        name="Placement",
        description="Which add-on surface triggered the login, for web analytics",
        default="login_dialog",
    )

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout
        utils.label_multiline(layout, text=self.message, width=300)

        layout.active_default = True
        layout.operator_context = "EXEC_DEFAULT"
        op_login = layout.operator(
            "wm.blenderkit_login", text=self.link_text, icon="URL"
        )
        op_login.signup = False
        op_login.placement = self.placement

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=300)


def draw_panel_categories(layout, context):
    ui_props = bpy.context.window_manager.blenderkitUI
    user_preferences = bpy.context.preferences.addons[__package__].preferences

    search_props = utils.get_search_props()
    acat_search = search_props.search_category

    if global_vars.DATA.get("bkit_categories") == None:
        return
    col = layout.column(align=True)
    acat = []
    if global_vars.DATA.get("active_category_browse") is not None:
        acat = global_vars.DATA["active_category_browse"][ui_props.asset_type]
        if len(acat) > 1:
            # we are in subcategory, so draw the parent button
            op = col.operator(
                "view3d.blenderkit_set_category",
                text="...",
                icon="FILE_PARENT",
            )
            op.asset_type = ui_props.asset_type
            op.category_browse = ""
            op.category_search = acat[-2]
        elif acat_search not in ("", ui_props.asset_type.lower()):
            # we are in subcategory, so draw the parent button
            op = col.operator(
                "view3d.blenderkit_set_category",
                text="[All]",
                icon="FILE_PARENT",
            )
            op.asset_type = ui_props.asset_type
            op.category_browse = acat[-1]
            op.category_search = acat[-1]

    cats = categories.get_category(global_vars.DATA["bkit_categories"], cat_path=acat)

    for c in cats["children"]:
        if c["assetCount"] > 0 or (
            utils.profile_is_validator() and user_preferences.categories_fix
        ):
            row = col.row(align=True)
            if (
                len(c["children"]) > 0
                and c["assetCount"] > 15
                or (utils.profile_is_validator() and user_preferences.categories_fix)
            ):
                row = row.split(factor=0.8, align=True)
            ctext = "%s (%i)" % (c["name"], c["assetCount"])

            emboss = acat_search == c["slug"]
            op = row.operator(
                "view3d.blenderkit_set_category", text=ctext, depress=emboss
            )
            op.asset_type = ui_props.asset_type
            op.category_browse = acat[-1]
            op.category_search = c["slug"]

            if (
                len(c["children"]) > 0
                and c["assetCount"] > 15
                or (utils.profile_is_validator() and user_preferences.categories_fix)
            ):
                op = row.operator("view3d.blenderkit_set_category", text=">>")
                op.asset_type = ui_props.asset_type
                op.category_browse = c["slug"]
                op.category_search = c["slug"]


class VIEW3D_PT_blenderkit_downloads(Panel):
    bl_category = "Blendkit"
    bl_idname = "VIEW3D_PT_blenderkit_downloads"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_label = "Downloads"

    @classmethod
    def poll(cls, context):
        return len(download.download_tasks) > 0

    def draw(self, context):
        layout = self.layout
        for key, data in download.download_tasks.items():
            row = layout.row()
            row.label(text=data["asset_data"]["name"])
            row.label(text=str(int(data["progress"])) + " %")
            op = row.operator("scene.blenderkit_download_kill", text="", icon="CANCEL")
            op.task_id = key
            if data.get("retry_counter", 0) > 0:
                row = layout.row()
                row.label(text="failed. retrying ... ", icon="ERROR")
                row.label(text=str(data["retry_counter"]))

                layout.separator()


def update_header_menu_fold(self, context):
    preferences = bpy.context.preferences.addons[__package__].preferences
    if preferences.header_menu_fold and asset_bar_op.asset_bar_operator is not None:
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=False, do_search=False)
    elif not preferences.header_menu_fold and asset_bar_op.asset_bar_operator is None:
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)


def header_search_draw(self, context):
    """Top bar menu in 3D view"""
    if not utils.guard_from_crash():
        return

    preferences = bpy.context.preferences.addons[__package__].preferences
    if not preferences.search_in_header:
        return
    if context.mode not in ("PAINT_TEXTURE", "OBJECT", "SCULPT", "POSE"):
        return

    layout = self.layout
    wm = bpy.context.window_manager
    ui_props = bpy.context.window_manager.blenderkitUI

    props_dict = {
        "MODEL": wm.blenderkit_models,
        "PRINTABLE": wm.blenderkit_models,  # PRINTABLE assets use same props as MODEL
        "MATERIAL": wm.blenderkit_mat,
        "BRUSH": wm.blenderkit_brush,
        "HDR": wm.blenderkit_HDR,
        "SCENE": wm.blenderkit_scene,
        "NODEGROUP": wm.blenderkit_nodegroup,
        "ADDON": wm.blenderkit_addon,
        "AUTHOR": wm.blenderkit_author,
    }
    props = props_dict[ui_props.asset_type]
    pcoll = icons.icon_collections["main"]
    icons_dict = {
        "MODEL": "OBJECT_DATAMODE",
        "PRINTABLE": pcoll[
            "asset_type_printable"
        ].icon_id,  # Using our custom printable icon
        "MATERIAL": "MATERIAL",
        "BRUSH": "BRUSH_DATA",
        "HDR": "WORLD",
        "SCENE": "SCENE_DATA",
        "NODEGROUP": "NODETREE",
        "ADDON": "PLUGIN",
        "AUTHOR": pcoll["asset_type_author"].icon_id,
    }

    asset_type_icon = icons_dict[ui_props.asset_type]

    row = layout.row(align=True)
    row.scale_x = 0.9

    if preferences.header_menu_fold:
        row.prop(
            preferences, "header_menu_fold", text="", icon="RIGHTARROW", emboss=False
        )
        row.prop(
            preferences,
            "header_menu_fold",
            text="",
            icon_value=pcoll[ui_props.logo_status].icon_id,
            emboss=False,
        )
        return
    else:
        row.prop(
            preferences, "header_menu_fold", text="", icon="DOWNARROW_HLT", emboss=False
        )

    # draw logo as part of the folding UI, it is better clickable.
    row.prop(
        preferences,
        "header_menu_fold",
        text="",
        icon_value=pcoll[ui_props.logo_status].icon_id,
        emboss=False,
    )

    layout = layout.row(align=True)

    if not global_vars.CLIENT_RUNNING:
        layout.label(text="Waiting for Client")
        return

    layout.prop(
        ui_props,
        "asset_type",
        expand=True,
        icon_only=True,
        text="",
        icon="NONE" if isinstance(asset_type_icon, int) else asset_type_icon,
        icon_value=asset_type_icon if isinstance(asset_type_icon, int) else 0,
    )

    draw_search_text_field(
        layout, ui_props, context
    )  # Ensure search field is drawn in HDR search panel

    layout.prop(ui_props, "search_bookmarks", text="", icon="BOOKMARKS")
    if (
        props.search_category == ui_props.asset_type.lower()
        or props.search_category == ""
    ):
        icon_id = pcoll["categories"].icon_id
    else:
        icon_id = pcoll["categories_active"].icon_id

    layout.popover(
        panel="VIEW3D_PT_blenderkit_categories",
        text="",
        icon_value=icon_id,
    )

    # FILTER ICON: filters are default or modified
    if props.use_filters:
        icon_id = pcoll["filter_active"].icon_id
    else:
        icon_id = pcoll["filter"].icon_id

    if context.mode == "EDIT_MESH":
        # geo node tools right now.
        pass

    elif ui_props.asset_type == "MODEL":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_model_search",
            text="",
            icon_value=icon_id,
        )

    elif ui_props.asset_type == "MATERIAL":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_material_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "SCENE":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_scene_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "HDR":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_HDR_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "BRUSH":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_brush_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "NODEGROUP":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_nodegroup_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "ADDON":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_addon_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "AUTHOR":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_author_search",
            text="",
            icon_value=icon_id,
        )
    elif ui_props.asset_type == "PRINTABLE":
        layout.popover(
            panel="VIEW3D_PT_blenderkit_advanced_printable_search",
            text="",
            icon_value=icon_id,
        )

    # NSFW filter shield badge - only for models right now
    if preferences.nsfw_filter and ui_props.asset_type == "MODEL":
        layout.prop(
            preferences,
            "nsfw_filter",
            text="",
            icon_value=pcoll["nsfw"].icon_id,
            emboss=False,
        )

    notifications = global_vars.DATA.get("bkit notifications")
    if notifications is not None and notifications.get("count", 0) > 0:
        layout.operator(
            "wm.show_notifications", text="", icon_value=pcoll["bell"].icon_id
        )

    if utils.profile_is_validator():
        search_props = utils.get_search_props()
        layout.prop(search_props, "search_verification_status", text="")


def ui_message(title, message):
    def draw_message(self, context):
        set_overlay_panel_active()
        layout = self.layout
        utils.label_multiline(layout, text=message, width=400)

    bpy.context.window_manager.popup_menu(draw_message, title=title, icon="INFO")


class NodegroupDropDialog(bpy.types.Operator):
    """Dialog for choosing how to add a nodegroup when dropped on an object or in node editor"""

    bl_idname = "wm.blenderkit_nodegroup_drop_dialog"
    bl_label = "Add Nodegroup"
    bl_options = {"REGISTER", "INTERNAL"}

    # Store the parameters needed for the download
    asset_search_index: IntProperty(default=-1)  # type: ignore[valid-type]
    target_object_name: StringProperty(default="")  # type: ignore[valid-type]
    snapped_location: FloatVectorProperty(size=3)  # type: ignore[valid-type]
    snapped_rotation: FloatVectorProperty(size=3)  # type: ignore[valid-type]

    # Node editor positioning (when dropped in node editor)
    node_x: FloatProperty(default=0.0)  # type: ignore[valid-type]
    node_y: FloatProperty(default=0.0)  # type: ignore[valid-type]

    # Option for how to add the nodegroup
    add_mode: EnumProperty(  # type: ignore[valid-type]
        name="Add Mode",
        description="How to add the nodegroup",
        items=[
            (
                "MODIFIER",
                "As Modifier",
                "Add the nodegroup as a new modifier on the object",
            ),
            ("NODE", "As Node", "Add the nodegroup as a node in an existing node tree"),
        ],
        default="MODIFIER",
    )

    # Option for overwriting existing geometry nodes modifier
    overwrite_modifier: BoolProperty(  # type: ignore[valid-type]
        name="Overwrite Last Geometry Nodes Modifier",
        description="Replace the last geometry nodes modifier instead of creating a new one (recommended to avoid recursion)",
        default=True,
    )

    def get_existing_geometry_modifiers(self, target_obj):
        """Get list of existing geometry nodes modifiers on target object"""
        if not target_obj:
            return []
        return [mod for mod in target_obj.modifiers if mod.type == "NODES"]

    def draw(self, context):
        set_overlay_panel_active()
        layout = self.layout

        # Get asset data for display
        sr = search.get_search_results()
        if self.asset_search_index >= 0 and self.asset_search_index < len(sr):
            asset_data = sr[self.asset_search_index]

            col = layout.column(align=True)
            col.label(text=f"Adding nodegroup: {asset_data['displayName']}")

            # Get target object and check for existing geometry nodes modifiers
            target_obj = None
            existing_geo_modifiers = []
            if self.target_object_name:
                target_obj = bpy.data.objects.get(self.target_object_name)
                existing_geo_modifiers = self.get_existing_geometry_modifiers(
                    target_obj
                )
                col.label(text=f"To object: {self.target_object_name}")
            else:
                col.label(text="A new target object will be created")

            col.separator()

            col.prop(self, "add_mode", expand=True)

            # Show overwrite option only for MODIFIER mode when there are existing geometry nodes modifiers
            if self.add_mode == "MODIFIER" and existing_geo_modifiers:
                col.separator()

                # Show info about existing modifiers
                if len(existing_geo_modifiers) == 1:
                    col.label(text=f"Found 1 geometry nodes modifier:", icon="INFO")
                else:
                    col.label(
                        text=f"Found {len(existing_geo_modifiers)} geometry nodes modifiers:",
                        icon="INFO",
                    )

                # Show the last modifier name
                last_modifier = existing_geo_modifiers[-1]
                col.label(text=f"  • {last_modifier.name} (will be affected)")

                col.separator()
                col.prop(self, "overwrite_modifier")

            col.separator()

            # Add description based on selected mode
            if self.add_mode == "MODIFIER":
                if self.target_object_name:
                    if existing_geo_modifiers and self.overwrite_modifier:
                        col.label(text="The last geometry nodes modifier will be")
                        col.label(text="replaced with the new nodegroup.")
                        col.label(
                            text="(Recommended to avoid recursion)", icon="CHECKMARK"
                        )
                    else:
                        col.label(text="The nodegroup will be added as a new")
                        col.label(text="geometry nodes modifier on the object.")
                        if existing_geo_modifiers:
                            col.label(text="⚠ May cause recursion issues", icon="ERROR")
                else:
                    col.label(text="A new cube will be created and the")
                    col.label(text="nodegroup added as a modifier.")
            else:
                if self.target_object_name:
                    col.label(text="The nodegroup will be added as a node")
                    col.label(text="in the geometry nodes editor.")
                else:
                    col.label(text="A new cube will be created and the")
                    col.label(text="nodegroup added as a node.")
                # Show node position if we have it
                if self.node_x != 0.0 or self.node_y != 0.0:
                    col.label(
                        text=f"Position: ({self.node_x:.1f}, {self.node_y:.1f})",
                        icon="NODE",
                    )

    def execute(self, context):
        # Download the nodegroup with the specified mode
        target_object = ""
        if self.target_object_name:
            target_object = self.target_object_name

        # Handle modifier overwrite if requested
        if self.add_mode == "MODIFIER" and self.overwrite_modifier and target_object:

            target_obj = bpy.data.objects.get(target_object)
            if target_obj:
                existing_geo_modifiers = self.get_existing_geometry_modifiers(
                    target_obj
                )
                if existing_geo_modifiers:
                    # Remove the last geometry nodes modifier
                    last_modifier = existing_geo_modifiers[-1]
                    bk_logger.info(
                        f"Removed geometry nodes modifier '{last_modifier.name}' before adding new nodegroup"
                    )
                    target_obj.modifiers.remove(last_modifier)

        # When adding as a node, use node positioning; when adding as modifier, use 3D positioning
        if self.add_mode == "NODE":
            bpy.ops.scene.blenderkit_download(
                "EXEC_DEFAULT",
                asset_index=self.asset_search_index,
                node_x=self.node_x,
                node_y=self.node_y,
                target_object=target_object,
                nodegroup_mode=self.add_mode,
                model_location=self.snapped_location,
                model_rotation=self.snapped_rotation,
            )
        else:  # MODIFIER mode
            bpy.ops.scene.blenderkit_download(
                "EXEC_DEFAULT",
                asset_index=self.asset_search_index,
                model_location=self.snapped_location,
                model_rotation=self.snapped_rotation,
                target_object=target_object,
                nodegroup_mode=self.add_mode,
            )
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)


classes = (
    BLENDERKIT_OT_hdr_thumbnail_tune,
    BLENDERKIT_OT_show_validation_popup,
    BLENDERKIT_OT_permissions_error_popup,
    BLENDERKIT_OT_set_default_directory,
    SetCategoryOperatorOrigin,
    SetCategoryOperator,
    SetCategoryOperatorInPopupCard,
    SetCategoryOperatorLastInPopupCard,
    ClearSearchKeywords,
    SetCommentReplyId,
    VIEW3D_PT_blenderkit_profile,
    VIEW3D_PT_blenderkit_unified,
    VIEW3D_PT_blenderkit_advanced_model_search,
    VIEW3D_PT_blenderkit_advanced_material_search,
    VIEW3D_PT_blenderkit_advanced_scene_search,
    VIEW3D_PT_blenderkit_advanced_HDR_search,
    VIEW3D_PT_blenderkit_advanced_brush_search,
    VIEW3D_PT_blenderkit_advanced_nodegroup_search,
    VIEW3D_PT_blenderkit_advanced_addon_search,
    VIEW3D_PT_blenderkit_advanced_author_search,
    VIEW3D_PT_blenderkit_advanced_printable_search,
    VIEW3D_PT_blenderkit_categories,
    VIEW3D_PT_blenderkit_import_settings,
    VIEW3D_PT_blenderkit_model_properties,
    VIEW3D_MT_blenderkit_model_properties,
    NODE_PT_blenderkit_material_properties,
    OpenBlenderKitDiscord,
    CopyEnvironmentInfo,
    ReportBug,
    OpenSystemDirectory,
    OpenAssetDirectory,
    OpenAddonDirectory,
    OpenGlobalDirectory,
    OpenClientLog,
    OpenTempDirectory,
    VIEW3D_PT_blenderkit_downloads,
    OBJECT_MT_blenderkit_asset_menu,
    OBJECT_MT_blenderkit_login_menu,
    AssetPopupCard,
    PopupDialog,
    UrlPopupDialog,
    ClosePopupButton,
    BlenderKitWelcomeOperator,
    MarkNotificationRead,
    UpvoteComment,
    SetPrivateComment,
    PostComment,
    ShowNotifications,
    LogoStatus,
    NotificationOpenTarget,
    MarkAllNotificationsRead,
    LoginPopupDialog,
    NodegroupDropDialog,
)


def header_search_draw_tools(self, context):
    if not bpy.context.area.spaces.active.show_region_tool_header:
        return
    if bpy.context.mode in ("SCULPT", "PAINT_TEXTURE"):
        return
    header_search_draw(self, context)


def header_search_draw_others(self, context):
    if (
        not bpy.context.area.spaces.active.show_region_tool_header
        or bpy.context.mode in ("SCULPT", "PAINT_TEXTURE")
    ):
        header_search_draw(self, context)


def header_draw(self, context):
    layout = self.layout

    self.draw_tool_settings(context)

    layout.separator_spacer()
    header_search_draw_tools(self, context)
    layout.separator_spacer()

    self.draw_mode_settings(context)


def object_context_draw(self, context):
    preferences = bpy.context.preferences.addons[__package__].preferences
    layout = self.layout
    pcoll = icons.icon_collections["main"]
    if not preferences.show_VIEW3D_MT_blenderkit_model_properties:
        return
    layout.menu(
        VIEW3D_MT_blenderkit_model_properties.bl_idname,
        icon_value=pcoll["logo"].icon_id,
    )


def register_ui_panels():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.VIEW3D_HT_tool_header.draw = header_draw
    bpy.types.VIEW3D_MT_editor_menus.append(header_search_draw_others)
    bpy.types.VIEW3D_MT_object_context_menu.append(object_context_draw)


def unregister_ui_panels():
    bpy.types.VIEW3D_MT_editor_menus.remove(header_search_draw_others)
    bpy.types.VIEW3D_MT_object_context_menu.remove(object_context_draw)
    for c in classes:
        bpy.utils.unregister_class(c)
