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
# type: ignore

bl_info = {
    "name": "Blendkit Online Asset Library",
    "author": "Vilem Duha, Petr Dlouhy, A. Gajdosik, Michal Hons",
    "version": (3, 21, 1, 260804),  # X.Y.Z.yymmdd
    "blender": (3, 0, 0),
    "location": "View3D > Properties > Blendkit",
    "description": "Boost your workflow with drag&drop assets from the community driven library.",
    "doc_url": "https://github.com/BlenderKit/blenderkit/wiki",
    "tracker_url": "https://github.com/BlenderKit/blenderkit/issues",
    "category": "3D View",
}
VERSION = (3, 21, 1, 260804)

import logging
import random
import sys
from importlib import reload
from os import path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception as e:
    print(f"stdout reconfigure failed: {e}.\n({type(sys.stdout)}):\n{vars(sys.stdout)}")
bk_logger = logging.getLogger(__name__)

# lib = path.join(path.dirname(__file__), 'lib')
# sys.path.insert(0, lib)
# from .lib import sentry_sdk
# sentry_sdk.init(
#     "https://d0c1619436104436999ef934ecba6393@o182975.ingest.sentry.io/6075237",
#
#     # Set traces_sample_rate to 1.0 to capture 100%
#     # of transactions for performance monitoring.
#     # We recommend adjusting this value in production.
#     traces_sample_rate=1.0
# )

if "bpy" in locals():
    global_vars = reload(global_vars)
    try:
        log = reload(log)
    except:
        from . import log

    log.configure_loggers()

    # alphabetically sorted all add-on modules since reload only happens from __init__.
    # modules with _bg are used for background computations in separate blender instance and that's why they don't need reload.
    addon_updater_ops = reload(addon_updater_ops)
    append_link = reload(append_link)
    timer = reload(timer)
    asset_bar_op = reload(asset_bar_op)
    asset_drag_op = reload(asset_drag_op)
    asset_inspector = reload(asset_inspector)
    autothumb = reload(autothumb)
    bg_blender = reload(bg_blender)
    bkit_oauth = reload(bkit_oauth)
    categories = reload(categories)
    colors = reload(colors)
    client_lib = reload(client_lib)
    client_tasks = reload(client_tasks)
    clipboard_x11 = reload(clipboard_x11)
    unlock_options = reload(unlock_options)
    disclaimer_op = reload(disclaimer_op)
    warning_dialog = reload(warning_dialog)
    download = reload(download)
    icons = reload(icons)
    image_utils = reload(image_utils)
    overrides = reload(overrides)
    if bpy.app.version >= (4, 2, 0):
        override_extension_draw = reload(override_extension_draw)
    paths = reload(paths)
    ratings_utils = reload(ratings_utils)
    ratings = reload(ratings)
    rating_nudge = reload(rating_nudge)
    comments_utils = reload(comments_utils)
    resolutions = reload(resolutions)
    search = reload(search)
    tasks_queue = reload(tasks_queue)
    ui = reload(ui)
    ui_bgl = reload(ui_bgl)
    ui_panels = reload(ui_panels)
    keymap_utils = reload(keymap_utils)
    upload = reload(upload)
    upload_bg = reload(upload_bg)
    utils = reload(utils)
    persistent_preferences = reload(persistent_preferences)
    reports = reload(reports)
    rereports = reload(reports)

    from .bk_proxor._blender import draw as bk_proxor_draw
    from .bk_proxor._blender import generate as bk_proxor_generate
    from .bk_proxor import prx_format as bk_proxor_prx_format

    bk_proxor_draw = reload(bk_proxor_draw)
    bk_proxor_generate = reload(bk_proxor_generate)
    bk_proxor_prx_format = reload(bk_proxor_prx_format)

    bl_ui_widget = reload(bl_ui_widget)
    bl_ui_label = reload(bl_ui_label)
    bl_ui_button = reload(bl_ui_button)
    bl_ui_image = reload(bl_ui_image)

    bl_ui_drag_panel = reload(bl_ui_drag_panel)
    bl_ui_draw_op = reload(bl_ui_draw_op)


else:
    import bpy

    from . import global_vars, log

    log.configure_loggers()

    from . import addon_updater_ops
    from . import timer
    from . import append_link
    from .asset_bar import asset_bar_op
    from .asset_bar import asset_drag_op
    from . import asset_inspector
    from . import autothumb
    from . import bg_blender
    from . import bkit_oauth
    from . import categories
    from . import colors
    from . import client_lib
    from . import client_tasks
    from . import client_thread
    from . import clipboard_x11
    from . import unlock_options
    from . import disclaimer_op
    from . import warning_dialog
    from . import download
    from . import icons
    from . import image_utils
    from . import overrides

    if bpy.app.version >= (4, 2, 0):
        from . import override_extension_draw
    from . import paths
    from . import ratings
    from . import ratings_utils
    from . import rating_nudge
    from . import comments_utils
    from . import resolutions
    from . import search
    from . import tasks_queue
    from . import ui
    from . import ui_bgl
    from . import ui_panels
    from . import keymap_utils
    from . import upload
    from . import upload_bg
    from . import utils
    from . import persistent_preferences
    from . import reports

    from .bl_ui_widgets import bl_ui_widget
    from .bl_ui_widgets import bl_ui_label
    from .bl_ui_widgets import bl_ui_button
    from .bl_ui_widgets import bl_ui_image

    from .bl_ui_widgets import bl_ui_draw_op
    from .bl_ui_widgets import bl_ui_drag_panel


from math import pi

import bpy.utils.previews
from bl_operators import userpref
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, PropertyGroup


@persistent
def scene_load(context):
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.assetbar_on = False
    ui_props.turn_off = False
    if global_vars.CLIENT_ACCESSIBLE:
        ui_props.logo_status = "logo"
    if (
        bpy.app.factory_startup is False
    ):  # factory_start is used in bg blender runs, but we want to run for tests in background mode
        preferences = bpy.context.preferences.addons[__package__].preferences
        preferences.login_attempt = False


conditions = (
    ("UNSPECIFIED", "Unspecified", ""),
    ("NEW", "New", "Shiny new item"),
    ("USED", "Used", "Casually used item"),
    ("OLD", "Old", "Old item"),
    ("DESOLATE", "Desolate", "Desolate item - dusty & rusty"),
)
model_styles = (
    ("REALISTIC", "Realistic", "Photo realistic model"),
    ("PAINTERLY", "Painterly", "Hand painted with visible strokes"),
    ("LOWPOLY", "Lowpoly", "Lowpoly art -don't mix up with polycount!"),
    ("ANIME", "Anime", "Anime style"),
    ("2D_VECTOR", "2D Vector", "2D vector"),
    ("3D_GRAPHICS", "3D Graphics", "3D graphics"),
    ("OTHER", "Other", "Other styles"),
)
search_model_styles = (
    ("REALISTIC", "Realistic", "Photo realistic model"),
    ("PAINTERLY", "Painterly", "Hand painted with visible strokes"),
    ("LOWPOLY", "Lowpoly", "Lowpoly art -don't mix up with polycount!"),
    ("ANIME", "Anime", "Anime style"),
    ("2D_VECTOR", "2D Vector", "2D vector"),
    ("3D_GRAPHICS", "3D Graphics", "3D graphics"),
    ("OTHER", "Other", "Other Style"),
    ("ANY", "Any", "Any Style"),
)
material_styles = (
    ("REALISTIC", "Realistic", "Photo realistic model"),
    ("NPR", "Non photorealistic", "Hand painted with visible strokes"),
    ("OTHER", "Other", "Other style"),
)
search_material_styles = (
    ("REALISTIC", "Realistic", "Photo realistic model"),
    ("NPR", "Non photorealistic", "Hand painted with visible strokes"),
    ("ANY", "Any", "Any"),
)
engines = (
    ("CYCLES", "Cycles", "Blender Cycles"),
    ("EEVEE", "Eevee", "Blender eevee renderer"),
    ("EEVEE_NEXT", "Eevee Next", "Blender eevee renderer (new)"),
    ("OCTANE", "Octane", "Octane render engine"),
    ("ARNOLD", "Arnold", "Arnold render engine"),
    ("V-RAY", "V-Ray", "V-Ray renderer"),
    ("UNREAL", "Unreal", "Unreal engine"),
    ("UNITY", "Unity", "Unity engine"),
    ("GODOT", "Godot", "Godot engine"),
    ("3D-PRINT", "3D printer", "object can be 3D printed"),
    ("OTHER", "Other", "any other engine"),
    ("NONE", "None", "no more engine block"),
)


pbr_types = (
    ("METALLIC", "Metallic-Roughness", "Metallic/Roughness PBR material type"),
    ("SPECULAR", "Specular  Glossy", ""),
)

mesh_poly_types = (
    ("QUAD", "quad", ""),
    ("QUAD_DOMINANT", "quad_dominant", ""),
    ("TRI_DOMINANT", "tri_dominant", ""),
    ("TRI", "tri", ""),
    ("NGON", "ngon_dominant", ""),
    ("OTHER", "other", ""),
)


EXTRA_PATH_OPTIONS = {}

if bpy.app.version >= (4, 5, 0):
    EXTRA_PATH_OPTIONS = {"options": {"PATH_SUPPORTS_BLEND_RELATIVE"}}


def update_down_up(self, context):
    """Perform a search if results are empty."""
    props = bpy.context.window_manager.blenderkitUI
    if search.get_search_results() is None and props.down_up == "SEARCH":
        search.search()


_asset_type_enum_items = []
_asset_type_enum_cache_key = None


def asset_type_callback(self, context):
    """
    Returns
    items for Enum property, depending on the down_up property - Blendkit is either in search or in upload mode.
    """
    global _asset_type_enum_items, _asset_type_enum_cache_key
    addon = bpy.context.preferences.addons.get(__package__)
    prefs = addon.preferences if addon is not None else None
    key = (
        self.down_up,
        getattr(prefs, "experimental_features", False),
        getattr(prefs, "author_tab", False),
    )
    if key == _asset_type_enum_cache_key and _asset_type_enum_items:
        return _asset_type_enum_items
    _asset_type_enum_cache_key = key
    pcoll = icons.icon_collections["main"]

    if self.down_up == "SEARCH":
        items = [
            ("MODEL", "Models", "Find models", "OBJECT_DATAMODE", 0),
            ("MATERIAL", "Materials", "Find materials", "MATERIAL", 1),
            ("SCENE", "Scenes", "Find scenes", "SCENE_DATA", 2),
            ("HDR", "HDRs", "Find HDRs", "WORLD", 3),
            ("BRUSH", "Brushes", "Find brushes", "BRUSH_DATA", 4),
            ("NODEGROUP", "Node Groups", "Find tools", "NODETREE", 5),
            (
                "PRINTABLE",
                "Printables",
                "Find 3D printable models",
                pcoll["asset_type_printable"].icon_id,
                6,
            ),
        ]

        # Only add addon option for Blender 4.2+

        if bpy.app.version >= (4, 2, 0):
            items.append(("ADDON", "Add-ons", "Find add-ons", "PLUGIN", 7))
        if prefs is not None:
            if prefs.experimental_features and prefs.author_tab:
                items.append(
                    (
                        "AUTHOR",
                        "Authors",
                        "Find authors",
                        pcoll["asset_type_author"].icon_id,
                        8,
                    ),
                )
    else:
        items = [
            ("MODEL", "Model", "Upload a model", "OBJECT_DATAMODE", 0),
            ("MATERIAL", "Material", "Upload a material", "MATERIAL", 1),
            ("SCENE", "Scene", "Upload a scene", "SCENE_DATA", 2),
            ("HDR", "HDR", "Upload a HDR", "WORLD", 3),
            ("BRUSH", "Brush", "Upload a brush", "BRUSH_DATA", 4),
            ("NODEGROUP", "Node Groups", "Upload a tool", "NODETREE", 5),
            (
                "PRINTABLE",
                "Printable",
                "Upload a 3D printable model",
                pcoll["asset_type_printable"].icon_id,
                6,
            ),
        ]

        # Only add addon option for Blender 4.2+

        if bpy.app.version >= (4, 2, 0):
            items.append(("ADDON", "Add-on", "Upload an addon", "PLUGIN", 7))

        # Author is search-only, no upload entry needed

    _asset_type_enum_items = items
    return _asset_type_enum_items


def run_drag_drop_update(self, context):
    if self.drag_init_button:
        ui_props = bpy.context.window_manager.blenderkitUI

        if ui_props.dragging:
            self.drag_init_button = False
            return

        bpy.ops.view3d.close_popup_button("INVOKE_DEFAULT")
        bpy.ops.view3d.asset_drag_drop(
            "INVOKE_DEFAULT",
            asset_search_index=ui_props.active_index + ui_props.scroll_offset,
        )

        self.drag_init_button = False


class BlenderKitThumbnailSettings(PropertyGroup):
    """Global, persisted thumbnail render settings.

    Single source of truth for thumbnail settings that are shared between asset
    types and remembered across sessions (saved through persistent_preferences).
    Each field is built from the factories in autothumb.py, so the definitions
    are not duplicated. Changing any field persists the preferences.
    """

    # common
    thumbnail_render_engine: autothumb.thumbnail_render_engine_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_resolution: autothumb.thumbnail_resolution_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_samples: autothumb.thumbnail_samples_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_denoising: autothumb.thumbnail_denoising_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_background_lightness: autothumb.thumbnail_background_lightness_prop(
        update=autothumb.save_thumbnail_settings
    )

    # model / printable
    thumbnail_angle: autothumb.thumbnail_angle_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_snap_to: autothumb.thumbnail_snap_to_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_material_color: autothumb.thumbnail_material_color_prop(
        update=autothumb.save_thumbnail_settings
    )

    # material
    thumbnail_generator_type: autothumb.thumbnail_generator_type_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_scale: autothumb.thumbnail_scale_prop(
        update=autothumb.save_thumbnail_settings
    )
    thumbnail_background: autothumb.thumbnail_background_prop(
        update=autothumb.save_thumbnail_settings
    )
    adaptive_subdivision: autothumb.adaptive_subdivision_prop(
        update=autothumb.save_thumbnail_settings
    )

    # render settings
    thumbnail_use_gpu: autothumb.thumbnail_use_gpu_prop(
        update=autothumb.save_thumbnail_settings
    )


class BlenderKitUIProps(PropertyGroup):
    down_up: EnumProperty(
        name="Download vs Upload",
        items=(
            ("SEARCH", "Search", "Activate searching", "VIEWZOOM", 0),
            ("UPLOAD", "Upload", "Activate uploading", "COPYDOWN", 1),
            # ('RATING', 'Rating', 'Activate rating', 'SOLO_ON', 2)
        ),
        description="Blendkit",
        default="SEARCH",
        update=update_down_up,
    )
    asset_type: EnumProperty(
        name=" ",
        items=asset_type_callback,
        description="",
        default=None,
        update=search.search_update,
    )
    # moved from per-asset search properties
    free_only: BoolProperty(
        name="Free first",
        description="Show free models first",
        default=False,
        update=search.search_update,
    )

    # moved from per-asset search properties
    own_only: BoolProperty(
        name="My Assets Only",
        description="Search only for your assets",
        default=False,
        update=search.search_update,
    )
    # user assets verification status
    own_verification_status: EnumProperty(
        name="My Assets Status",
        description="Search only for your assets with this verification status",
        items=(
            ("ALL", "All", "All"),
            ("UPLOADING", "Uploading", "Uploading"),
            ("UPLOADED", "Uploaded", "Uploaded"),
            ("VALIDATED", "Validated", "Validated"),
            ("ON_HOLD", "On Hold", "On Hold"),
            ("REJECTED", "Rejected", "Rejected"),
        ),
        default="ALL",
        update=search.search_update,
    )
    # moved from per-asset search properties
    search_bookmarks: BoolProperty(
        name="My Bookmarks",
        default=False,
        description="Filter my bookmarked assets only",
        update=search.search_update,
    )
    # moved from per-asset search properties
    quality_limit: IntProperty(
        name="Quality limit",
        description="Only show assets with a higher quality",
        default=0,
        min=0,
        max=10,
        update=search.search_update_delayed,
    )
    search_order_by: EnumProperty(
        name="Order",
        description="Search result order",
        items=(
            (
                "default",
                "Default",
                "By default, the sorting algorithm changes dynamically based on search filters.",
            ),
            ("-created", "Newest", "Sort results from newest to oldest."),
            ("created", "Oldest", "Sort results from oldest to newest."),
            (
                "-bookmarks",
                "▼ Bookmarks",
                "Sort results from most bookmarked to least.",
            ),
            (
                "bookmarks",
                "▲ Bookmarks",
                "Sort results from least bookmarked to most.",
            ),
            (
                "-score",
                "▼ Score",
                "Sort results from highest asset score to the lowest.",
            ),
            (
                "score",
                "▲ Score",
                "Sort results from lowest asset score to the highest.",
            ),
            (
                "-working_hours",
                "▼ Complexity",
                "Sort results from most complex to the least.",
            ),
            (
                "working_hours",
                "▲ Complexity",
                "Sort results from least complex to the most.",
            ),
            (
                "-quality",
                "▼ Quality",
                "Sort results from highest quality rating to the lowest.",
            ),
            (
                "quality",
                "▲ Quality",
                "Sort results from lowest quality rating to the highest.",
            ),
        ),
        default="default",
        update=search.search_update,
    )
    search_license: EnumProperty(
        name="License",
        items=(
            ("ANY", "Any", ""),
            ("royalty_free", "Royalty Free", "royalty free commercial license"),
            ("cc_zero", "Creative Commons Zero", "Creative Commons Zero"),
        ),
        description="License of the asset",
        default="ANY",
        update=search.search_update,
    )

    # BLENDER VERSION of ASSET
    search_blender_version: BoolProperty(
        name="Asset Blender Version",
        description="Limit the assets by version of Blender (minimum, maximum) in which they were created. "
        + "Use maximum version limit to exclude incompatible assets from newer Blender versions than yours. Or set the minimum version to exclude assets created in quite old Blender versions",
    )
    search_blender_version_min: StringProperty(
        name="Minimal version (including, higher than or equal)",
        default="0.0",
        description="Limit the assets by minimum version of Blender in which they were created, including also the specified version and excluding all older versions from the search results. "
        + "Only assets created in HIGHER THAN OR EQUAL (>= min) minimum version will be shown. Use semantic versioning format: X.Y.Z.\n\n"
        + "E.g.: exclude all Blender 2 assets by specifying 3, 3.0, or 3.0.0. Assets created in 3.0 or higher will be shown",
        update=search.search_update,
    )
    search_blender_version_max: StringProperty(
        name="Maximum version (excluding, lower than)",
        default="5.99",
        description="Limit the assets by maximum version of Blender in which they were created, excluding the specified version and all newer versions from the search results. "
        + "Only assets created in LOWER THAN (< max) maximum version will be shown. Use semantic versioning format: X.Y.Z.\n\n"
        + "E.g.: exclude all Blender 4 assets by specifying 4, 4.0, or 4.0.0. Assets created in 3.6 and lower will be shown",
        update=search.search_update,
    )

    # search lock
    search_lock: BoolProperty(
        name="Search Lock",
        description="Lock the search to restore ui state and not trigger search update",
        default=False,
    )

    logo_status: StringProperty(name="", default="logo_offline")
    asset_type_fold: BoolProperty(name="Expand asset types", default=False)
    # these aren't actually used ( by now, seems to better use globals in UI module:
    draw_tooltip: BoolProperty(name="Draw Tooltip", default=False)
    addon_update: BoolProperty(name="Should Update Addon", default=False)

    tooltip: StringProperty(
        name="Tooltip", description="asset preview info", default=""
    )

    ui_scale = 1

    thumb_size_def = 128
    margin_def = 0

    thumb_size: IntProperty(
        name="Thumbnail Size", default=thumb_size_def, min=48, max=256
    )

    margin: IntProperty(name="Margin", default=margin_def, min=-1, max=256)
    highlight_margin: IntProperty(
        name="Highlight Margin", default=int(margin_def / 2), min=-10, max=256
    )

    bar_height: IntProperty(
        name="Bar Height", default=thumb_size_def + 2 * margin_def, min=-1, max=2048
    )
    bar_x_offset: IntProperty(name="Bar X Offset", default=40, min=0, max=5000)
    bar_y_offset: IntProperty(name="Bar Y Offset", default=120, min=0, max=5000)

    bar_x: IntProperty(name="Bar X", default=100, min=0, max=5000)
    bar_y: IntProperty(name="Bar Y", default=100, min=50, max=5000)
    bar_end: IntProperty(name="Bar End", default=100, min=0, max=5000)
    bar_width: IntProperty(name="Bar Width", default=100, min=0, max=5000)

    wcount: IntProperty(name="Width Count", default=10, min=0, max=5000)
    hcount: IntProperty(name="Rows", default=5, min=0, max=5000)

    reports_y: IntProperty(name="Reports Y", default=5, min=0, max=5000)
    reports_x: IntProperty(name="Reports X", default=5, min=0, max=5000)

    assetbar_on: BoolProperty(name="Assetbar On", default=False)
    turn_off: BoolProperty(name="Turn Off", default=False)

    mouse_x: IntProperty(name="Mouse X", default=0)
    mouse_y: IntProperty(name="Mouse Y", default=0)

    active_index: IntProperty(name="Active Index", default=-3)
    scroll_offset: IntProperty(name="Scroll Offset", default=0)
    drawoffset: IntProperty(name="Draw Offset", default=0)

    dragging: BoolProperty(name="Dragging", default=False)
    drag_init: BoolProperty(name="Drag Initialisation", default=False)
    drag_init_button: BoolProperty(
        name="Drag Initialisation from button",
        default=False,
        description="Click or drag into scene for download.\nUse mouse wheel during drag to rotate the asset. Cancel the drag by pressing 'Esc'.",
        update=run_drag_drop_update,
    )
    draw_drag_image: BoolProperty(name="Draw Drag Image", default=False)
    draw_snapped_bounds: BoolProperty(name="Draw Snapped Bounds", default=False)

    snapped_location: FloatVectorProperty(name="Snapped Location", default=(0, 0, 0))
    snapped_bbox_min: FloatVectorProperty(name="Snapped Bbox Min", default=(0, 0, 0))
    snapped_bbox_max: FloatVectorProperty(name="Snapped Bbox Max", default=(0, 0, 0))
    snapped_normal: FloatVectorProperty(name="Snapped Normal", default=(0, 0, 0))

    snapped_rotation: FloatVectorProperty(
        name="Snapped Rotation", default=(0, 0, 0), subtype="QUATERNION"
    )

    has_hit: BoolProperty(name="has_hit", default=False)
    thumbnail_image = StringProperty(
        name="Thumbnail Image",
        description="",
        default=paths.get_addon_thumbnail_path("thumbnail_notready.jpg"),
    )

    #### rating UI props
    rating_ui_scale = ui_scale

    rating_button_on: BoolProperty(name="Rating Button On", default=True)
    rating_menu_on: BoolProperty(name="Rating Menu On", default=False)
    rating_on: BoolProperty(name="Rating on", default=True)

    rating_button_width: IntProperty(name="Rating Button Width", default=50 * ui_scale)
    rating_button_height: IntProperty(
        name="Rating Button Height", default=50 * ui_scale
    )

    rating_ui_width: IntProperty(name="Rating UI Width", default=rating_ui_scale * 600)
    rating_ui_height: IntProperty(
        name="Rating UI Height", default=rating_ui_scale * 256
    )

    quality_stars_x: IntProperty(name="Rating UI Stars X", default=rating_ui_scale * 90)
    quality_stars_y: IntProperty(
        name="Rating UI Stars Y", default=rating_ui_scale * 190
    )

    star_size: IntProperty(name="Star Size", default=rating_ui_scale * 50)

    workhours_bar_slider_size: IntProperty(
        name="Workhours Bar Slider Size", default=rating_ui_scale * 30
    )

    workhours_bar_x: IntProperty(
        name="Workhours Bar X", default=rating_ui_scale * (100 - 15)
    )
    workhours_bar_y: IntProperty(
        name="Workhours Bar Y", default=rating_ui_scale * (45 - 15)
    )

    workhours_bar_x_max: IntProperty(
        name="Workhours Bar X Max", default=rating_ui_scale * (480 - 15)
    )

    dragging_rating: BoolProperty(name="Dragging Rating", default=False)
    dragging_rating_quality: BoolProperty(name="Dragging Rating Quality", default=False)
    dragging_rating_work_hours: BoolProperty(
        name="Dragging Rating Work Hours", default=False
    )
    last_rating_time: FloatProperty(name="Last Rating Time", default=0.0)

    hdr_upload_image: PointerProperty(
        name="Upload HDR", type=bpy.types.Image, description="Pick an image to upload"
    )

    hdr_use_custom_thumbnail_tone: BoolProperty(
        name="Use Custom Thumbnail Tone",
        description="Use custom exposure and gamma for HDR thumbnail conversion",
        default=False,
    )

    hdr_thumbnail_exposure: FloatProperty(
        name="Thumbnail Exposure",
        description="Exposure offset used only for HDR thumbnail conversion",
        default=0.0,
        min=-5.0,
        max=5.0,
        soft_min=-2.0,
        soft_max=2.0,
    )

    hdr_thumbnail_gamma: FloatProperty(
        name="Thumbnail Gamma",
        description="Gamma used only for HDR thumbnail conversion",
        default=1.0,
        min=0.2,
        max=3.0,
        soft_min=0.7,
        soft_max=1.6,
    )

    nodegroup_upload: PointerProperty(
        name="Upload Tool",
        type=bpy.types.GeometryNodeTree,
        description="Pick the geometry node tool to upload",
    )

    new_comment: StringProperty(
        name="New comment", description="Write your comment", default=""
    )
    reply_id: IntProperty(
        name="Reply Id", description="Active comment id to reply to", default=0
    )

    # Add search_keywords property
    search_keywords: StringProperty(
        name="Search",
        description="Search Blendkit for these keywords",
        default="",
        update=search.search_update_delayed,
    )


def search_procedural_update(self, context):
    if self.search_procedural in ("PROCEDURAL", "BOTH"):
        self.search_texture_resolution = False
    search.search_update_delayed(self, context)


class BlenderKitCommonSearchProps:
    # categories
    search_category: StringProperty(
        name="Category",
        description="Active subcategory for search",
        default="",
        update=search.search_update,
    )
    # STATES
    # Is searching is moved to history steps
    # is_searching: BoolProperty(
    #     name="Searching",
    #     description="search is currently running (internal)",
    #     default=False,
    # )
    is_downloading: BoolProperty(
        name="Downloading",
        description="download is currently running (internal)",
        default=False,
    )

    use_filters: BoolProperty(
        name="Filters are on", description="some filters are used", default=False
    )
    report: StringProperty(name="Report", description="errors and messages", default="")

    # TEXTURE RESOLUTION
    search_texture_resolution: BoolProperty(
        name="Texture Resolution",
        description="Limit texture resolutions",
        default=False,
        update=search.search_update,
    )
    search_texture_resolution_min: IntProperty(
        name="Min Texture Resolution",
        description="Minimum texture resolution",
        default=256,
        min=0,
        max=32768,
        update=search.search_update_delayed,
    )

    search_texture_resolution_max: IntProperty(
        name="Max Texture Resolution",
        description="Maximum texture resolution",
        default=4096,
        min=0,
        max=32768,
        update=search.search_update_delayed,
    )

    # file_size
    search_file_size: BoolProperty(
        name="File Size",
        description="Limit file sizes",
        default=False,
        update=search.search_update,
    )
    search_file_size_min: IntProperty(
        name="Min File Size",
        description="Minimum file size",
        default=0,
        min=0,
        max=2000,
        update=search.search_update_delayed,
    )

    search_file_size_max: IntProperty(
        name="Max File Size",
        description="Maximum file size",
        default=500,
        min=0,
        max=2000,
        update=search.search_update_delayed,
    )

    search_procedural: EnumProperty(
        items=(
            ("BOTH", "Both", ""),
            ("PROCEDURAL", "Procedural", ""),
            ("TEXTURE_BASED", "Texture based", ""),
        ),
        default="BOTH",
        description="Search only procedural/texture based assets",
        update=search_procedural_update,
    )

    search_verification_status: EnumProperty(
        name="Verification status",
        description="Search by verification status",
        items=(
            ("ALL", "All", "All"),
            ("UPLOADING", "Uploading", "Uploading"),
            ("UPLOADED", "Uploaded", "Uploaded"),
            ("READY", "Ready for V.", "Ready for validation (deprecated since 2.8)"),
            ("VALIDATED", "Validated", "Validated"),
            ("ON_HOLD", "On Hold", "On Hold"),
            ("REJECTED", "Rejected", "Rejected"),
            ("DELETED", "Deleted", "Deleted"),
        ),
        default="ALL",
        update=search.search_update_verification_status,
    )

    # moved to ui props, more convenient for user when for all assets on
    # free_only: BoolProperty(
    #     name="Free first",
    #     description="Show free models first",
    #     default=False,
    #     update=search.search_update,
    # )

    unrated_quality_only: BoolProperty(
        name="Unrated quality",
        description="Show only unrated models",
        default=False,
        update=search.search_update,
    )

    unrated_wh_only: BoolProperty(
        name="Unrated complexity",
        description="Show only unrated models",
        default=False,
        update=search.search_update,
    )


def update_free(self, context):
    if self.is_free == "FULL":
        self.is_free = "FREE"
        ui_panels.ui_message(
            title="All Blendkit materials are free",
            message="Any material uploaded to Blendkit is free."
            " However, it can still earn money for the author,"
            " based on our fair share system. "
            "Part of subscription is sent to authors based on usage by paying users.\n",
        )


class BlenderKitCommonUploadProps(object):
    # for p in common_upload_props:
    #     exec(f"{p['identifier']}: {p['type']}(name='{p['name']}',description='{p['description']}',default='{p['default']}')")

    id: StringProperty(
        name="Asset Version Id",
        description="Unique name of the asset version (hidden)",
        default="",
    )
    asset_base_id: StringProperty(
        name="Asset Base Id",
        description="Unique name of the asset (hidden)",
        default="",
    )
    proxor_path: StringProperty(
        name="Proxor Path",
        description="Path to the .prxc proxy mesh file for this asset (auto-populated on download)",
        default="",
        subtype="FILE_PATH",
    )
    name: StringProperty(
        name="Name",
        description="Provide name of your asset, choose a few descriptive English words that clearly identify and distinguish your asset. Good naming helps your asset to be found on the search engine. Follow these tips:\n\n"
        "Use Descriptive Terms:\nInclude specific details such as the brand, material, or distinct features of the asset.\n\n"
        "Avoid Generic or Vague Terms:\nNames like 'Sky 01' or 'Big Tree' are too general and not helpful for search optimization. Instead, use names that provide meaningful information about the asset.\n\n"
        "Highlight Key Attributes:\nIncorporate important attributes that are likely to be used in search queries, such as the model in vehicles or the designer in furniture.\n\n"
        "Bad names: Chair 01, Nice Car, Statue\n"
        "Good names: Knoll Steel Chair, Skoda Kodiaq, Statue of Liberty",
        default="",
        update=utils.name_update,
    )
    # this is to store name for purpose of checking if name has changed.
    name_old: StringProperty(
        name="Old Name",
        description="Brief description of the asset in english.",
        default="",
    )

    description: StringProperty(
        name="Description",
        description="Provide a clear and concise description of your asset in English. To enhance searchability and discoverability of your asset, follow these tips:\n\n"
        "Be Specific:\nUse precise terms that accurately reflect the asset. Include key characteristics such as material, color, function, or designer/brand.\n\n"
        "Use Recognizable Keywords:\nIncorporate well-known and relevant keywords that users are likely to search for. This includes brand names, designer names, common usage, and industry-specific terms.\n\n"
        "Avoid Jargon:\nUnless industry-specific terms are widely understood by your target audience, use simple language that is easy to understand.\n\n"
        "Highlight Unique Features:\nMention any distinctive features that set the asset apart from others, such as a unique design, special function, or notable collaboration.\n\n"
        "Keep it Brief:\nAim for a short description that captures the essence of the asset without unnecessary details. A concise description makes it easier for Elasticsearch to process and for users to scan",
        default="",
    )
    tags: StringProperty(
        name="Tags",
        description="Enter up to 10 tags, separated by commas. Tags may include alphanumeric characters and underscores only. For better discoverability, follow these tips:\n\n"
        "Choose Relevant Keywords:\nSelect tags that closely relate to the asset's features, usage, or industry terms. This increases the chances that your asset appears in relevant searches.\n\n"
        "Include Synonyms:\nAdd variations or synonyms to cover different ways users might search for similar items. Especially consider synonyms for terms used in the asset's name or description to broaden search relevancy.\n\n"
        "Prioritize Common Terms:\nUse commonly searched terms within your target audience. This helps connect your assets to the most likely queries.\n\n"
        "Enhance with Specificity: While common terms are essential, adding specific tags can help in uniquely identifying and categorizing the asset. This is particularly useful for users looking for particular features or attributes.",
        default="",
        update=utils.update_tags,
    )

    name_changed: BoolProperty(
        name="Name Changed",
        description="Name has changed, the asset has to be re-uploaded with all data",
        default=False,
    )

    pbr: BoolProperty(
        name="Pure PBR Compatible",
        description="Is compatible with PBR standard. This means only image textures are used with no"
        " procedurals and no color correction, only principled shader is used",
        default=False,
    )

    pbr_type: EnumProperty(
        name="PBR Type",
        items=pbr_types,
        description="PBR type",
        default="METALLIC",
    )
    license: EnumProperty(
        name="License",
        items=upload.licenses,
        default="royalty_free",
        description="License. Please read our help for choosing the right licenses",
    )

    # verification mainly to retrigger processing
    verification_status: EnumProperty(
        name="Verification status",
        description="Verification status of the asset, set by moderators",
        items=(
            ("UPLOADING", "Uploading", "uploading"),
            ("UPLOADED", "Uploaded", "uploaded"),
            ("VALIDATED", "Validated", "validated"),
            ("ON_HOLD", "On Hold", "on_hold"),
            ("REJECTED", "Rejected", "rejected"),
            ("DELETED", "Deleted", "deleted"),
        ),
        default="UPLOADING",
    )

    is_private: EnumProperty(
        name="Thumbnail Style",
        items=(("PRIVATE", "Private", ""), ("PUBLIC", "Public", "")),
        description="Public assets go into the validation process. \n"
        "Validated assets are visible to all users.\n"
        "Private assets are limited by your plan quota\n"
        "State",
        default="PUBLIC",
    )

    is_procedural: BoolProperty(
        name="Procedural",
        description="Asset is procedural - has no texture",
        default=True,
    )
    node_count: IntProperty(
        name="Node count", description="Total nodes in the asset", default=0
    )
    texture_count: IntProperty(
        name="Texture count", description="Total texture count in asset", default=0
    )
    total_megapixels: IntProperty(
        name="Megapixels", description="Total megapixels of texture", default=0
    )

    is_free: EnumProperty(
        name="Thumbnail Style",
        items=(
            ("FULL", "Full", "Your asset will be only available for subscribers"),
            (
                "FREE",
                "Free",
                "You consent you want to release this asset as free for everyone",
            ),
        ),
        description="Assets can be in Free or in Full plan. Also free assets generate credits",
        default="FULL",
    )

    uploading: BoolProperty(
        name="Uploading",
        description="True when background process is running",
        default=False,
        update=autothumb.update_upload_material_preview,
    )
    upload_state: StringProperty(
        name="State Of Upload", description="bg process reports for upload", default=""
    )

    has_thumbnail: BoolProperty(
        name="Has Thumbnail",
        description="True when thumbnail was checked and loaded",
        default=False,
    )

    thumbnail_generating_state: StringProperty(
        name="Thumbnail Generating State",
        description="bg process reports for thumbnail generation",
        default="Please add thumbnail (jpg or png, at least 1024x1024)",
    )

    report: StringProperty(
        name="Missing Upload Properties",
        description="used to write down what's missing",
        default="",
    )

    category: EnumProperty(
        name="Category",
        description="Select the main category for the uploaded asset. "
        "Choose the most accurate category to enhance visibility and download rates. "
        "Proper categorization ensures your asset reaches people actively searching for assets like yours",
        items=categories.get_category_enums,
        update=categories.update_category_enums,
    )
    subcategory: EnumProperty(
        name="Subcategory",
        description="Select a subcategory within the chosen main category",
        items=categories.get_subcategory_enums,
        update=categories.update_subcategory_enums,
    )
    subcategory1: EnumProperty(
        name="Sub-subcategory",
        description="Select a further subcategory within the chosen subcategory",
        items=categories.get_subcategory1_enums,
    )


class BlenderKitMaterialSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    search_style: EnumProperty(
        name="Style",
        items=search_material_styles,
        description="Style of material",
        default="ANY",
        update=search.search_update,
    )
    search_style_other: StringProperty(
        name="Style Other",
        description="Style not in the list",
        default="",
        update=search.search_update,
    )
    search_engine: EnumProperty(
        name="Engine",
        items=engines,
        default="NONE",
        description="Output engine",
        update=search.search_update,
    )
    search_engine_other: StringProperty(
        name="Engine",
        description="engine not specified by addon",
        default="",
        update=search.search_update,
    )
    import_method: EnumProperty(
        name="Import Method",
        items=(
            (
                "LINK",
                "Link",
                "Link Material - will be in external file and can't be directly edited",
            ),
            ("APPEND", "Append", "Append if you need to edit the material"),
        ),
        description="Appended materials are editable in your scene. Linked assets are saved in original files, "
        "aren't editable directly, but also don't increase your file size",
        default="APPEND",
    )


class BlenderKitMaterialUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    style: EnumProperty(
        name="Style",
        items=material_styles,
        description="Style of material",
        default="REALISTIC",
    )
    style_other: StringProperty(
        name="Style Other",
        description="Style not in the list",
        default="",
    )
    engine: EnumProperty(
        name="Engine",
        items=engines,
        default="CYCLES",
        description="Output engine",
    )
    engine_other: StringProperty(
        name="Engine Other",
        description="engine not specified by addon",
        default="",
    )

    shaders: StringProperty(
        name="Shaders Used",
        description="shaders used in asset, autofilled",
        default="",
    )

    is_free: EnumProperty(
        name="Thumbnail Style",
        items=(
            ("FULL", "Full", "Your asset will be only available for subscribers."),
            (
                "FREE",
                "Free",
                "You consent you want to release this asset as free for everyone.",
            ),
        ),
        description="Assets can be in Free or in Full plan. Also free assets generate credits. \n"
        "All Blendkit materials are free",
        default="FREE",
        update=update_free,
    )

    uv: BoolProperty(name="Needs UV", description="needs an UV set", default=False)
    # printable_3d : BoolProperty( name = "3d printable", description = "can be 3d printed", default = False)
    animated: BoolProperty(name="Animated", description="is animated", default=False)
    texture_resolution_min: IntProperty(
        name="Texture Resolution Min",
        description="texture resolution minimum",
        default=0,
    )
    texture_resolution_max: IntProperty(
        name="Texture Resolution Max",
        description="texture resolution maximum",
        default=0,
    )

    texture_size_meters: FloatProperty(
        name="Texture Size in Meters",
        description="Size of texture in real world units",
        default=1.0,
        min=0,
    )

    thumbnail_render_engine: autothumb.thumbnail_render_engine_prop()

    thumbnail_generator_type: autothumb.thumbnail_generator_type_prop()

    thumbnail_scale: autothumb.thumbnail_scale_prop()

    thumbnail_background: autothumb.thumbnail_background_prop()

    thumbnail_background_lightness: autothumb.thumbnail_background_lightness_prop(
        default=0.7,
        lo=0.00001,
        hi=1.0,
        description="Set to make your material stand out with enough contrast",
    )

    thumbnail_samples: autothumb.thumbnail_samples_prop()

    thumbnail_denoising: autothumb.thumbnail_denoising_prop()

    adaptive_subdivision: autothumb.adaptive_subdivision_prop()

    thumbnail_resolution: autothumb.thumbnail_resolution_prop()

    thumbnail: StringProperty(
        name="Thumbnail",
        description="Thumbnail path - 512x512 .jpg image, rendered with cycles.\n"
        "Only standard Blendkit previews will be accepted.\n"
        "Only exception are special effects like fire or similar",
        subtype="FILE_PATH",
        default="",
        update=autothumb.update_upload_material_preview,
        **EXTRA_PATH_OPTIONS,
    )

    is_generating_thumbnail: BoolProperty(
        name="Generating Thumbnail",
        description="True when background process is running",
        default=False,
        update=autothumb.update_upload_material_preview,
    )


class BlenderKitTextureUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    style: EnumProperty(
        name="Style",
        items=material_styles,
        description="Style of texture",
        default="REALISTIC",
    )
    style_other: StringProperty(
        name="Style Other",
        description="Style not in the list",
        default="",
    )

    pbr: BoolProperty(
        name="PBR Compatible",
        description="Is compatible with PBR standard",
        default=False,
    )

    # printable_3d : BoolProperty( name = "3d printable", description = "can be 3d printed", default = False)
    animated: BoolProperty(name="Animated", description="is animated", default=False)
    resolution: IntProperty(
        name="Texture Resolution", description="texture resolution", default=0
    )


class BlenderKitBrushSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    pass


class BlenderKitGeoToolSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    pass


class BlenderKitAddonSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    search_installed: BoolProperty(
        name="Installed Only",
        description="Show only addons that are already installed in Blender",
        default=False,
        update=lambda self, context: (
            search.search_update(self, context)
            if context.window_manager.blenderkitUI.asset_type == "ADDON"
            else None
        ),
    )
    search_compatible_only: BoolProperty(
        name="Compatible Only",
        description="Hide addons whose declared Blender version range does not include the running Blender version",
        default=False,
        update=lambda self, context: (
            search.search_update(self, context)
            if context.window_manager.blenderkitUI.asset_type == "ADDON"
            else None
        ),
    )


class BlenderKitAuthorSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    pass


class BlenderKitHDRUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    texture_resolution_max: IntProperty(
        name="Texture Resolution Max",
        description="texture resolution maximum",
        default=0,
    )
    evs_cap: IntProperty(name="EV cap", description="EVs dynamic range", default=0)
    true_hdr: BoolProperty(
        name="Real HDR", description="Image has High dynamic range.", default=False
    )


class BlenderKitBrushUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    thumbnail: StringProperty(
        name="Thumbnail",
        description="Thumbnail path - at least 1024x1024 .jpg or .png",
        subtype="FILE_PATH",
        default="",
        update=autothumb.update_upload_brush_preview,
        **EXTRA_PATH_OPTIONS,
    )

    mode: EnumProperty(
        name="Mode",
        items=(
            ("IMAGE", "Texture paint", "Texture brush"),
            ("SCULPT", "Sculpt", "Sculpt brush"),
            ("VERTEX", "Vertex paint", "Vertex paint brush"),
            ("WEIGHT", "Weight paint", "Weight paint brush"),
        ),
        description="Mode where the brush works",
        default="SCULPT",
    )


class BlenderKitNodeGroupUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    thumbnail: StringProperty(
        name="Thumbnail",
        description="Thumbnail path - minimum 1024x1024 square .jpg\n"
        "And make it beautiful!",
        subtype="FILE_PATH",
        default="",
        **EXTRA_PATH_OPTIONS,
        # update=autothumb.update_upload_model_preview,
    )
    # mode: EnumProperty(
    #     name="Mode",
    #     items=(
    #         ("IMAGE", "Texture paint", "Texture brush"),
    #         ("SCULPT", "Sculpt", "Sculpt brush"),
    #         ("VERTEX", "Vertex paint", "Vertex paint brush"),
    #         ("WEIGHT", "Weight paint", "Weight paint brush"),
    #     ),
    #     description="Mode where the brush works",
    #     default="SCULPT",
    # )


# upload properties
class BlenderKitModelUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    style: EnumProperty(
        name="Style",
        items=model_styles,
        description="Style of asset",
        default="REALISTIC",
    )
    style_other: StringProperty(
        name="Style Other",
        description="Style not in the list",
        default="",
    )
    engine: EnumProperty(
        name="Engine",
        items=engines,
        default="CYCLES",
        description="Output engine",
    )

    production_level: EnumProperty(
        name="Production Level",
        items=(
            ("FINISHED", "Finished", "Render or animation ready asset"),
            (
                "TEMPLATE",
                "Template",
                "Asset intended to help in creation of something else",
            ),
        ),
        default="FINISHED",
        description="Production state of the asset. \n"
        "Templates should be tools to finish certain tasks, like a thumbnailer scene, \n "
        "finished mesh topology as start for modelling or others",
    )

    engine_other: StringProperty(
        name="Engine",
        description="engine not specified by addon",
        default="",
    )

    engine1: EnumProperty(
        name="2nd Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )
    engine2: EnumProperty(
        name="3rd Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )
    engine3: EnumProperty(
        name="4th Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )

    manufacturer: StringProperty(
        name="Manufacturer",
        description="Manufacturer, company making a design piece or product. Not you",
        default="",
    )

    designer: StringProperty(
        name="Designer",
        description="Author of the original design piece depicted. Usually not you",
        default="",
    )

    design_collection: StringProperty(
        name="Design Collection",
        description="Fill if this piece is part of a real world design collection",
        default="",
    )

    design_variant: StringProperty(
        name="Variant",
        description="Colour or material variant of the product",
        default="",
    )

    thumbnail: StringProperty(
        name="Thumbnail",
        description="Thumbnail path - 512x512 .jpg\n" "Rendered with cycles",
        subtype="FILE_PATH",
        default="",
        update=autothumb.update_upload_model_preview,
        **EXTRA_PATH_OPTIONS,
    )

    thumbnail_render_engine: autothumb.thumbnail_render_engine_prop()

    thumbnail_background_lightness: autothumb.thumbnail_background_lightness_prop(
        default=0.7,
        lo=0.01,
        hi=10.0,
        description="Set to make your Model stand out",
    )

    # for printable models
    thumbnail_material_color: autothumb.thumbnail_material_color_prop()

    thumbnail_angle: autothumb.thumbnail_angle_prop()

    thumbnail_snap_to: autothumb.thumbnail_snap_to_prop()

    thumbnail_resolution: autothumb.thumbnail_resolution_prop()

    thumbnail_samples: autothumb.thumbnail_samples_prop()

    thumbnail_denoising: autothumb.thumbnail_denoising_prop()

    use_design_year: BoolProperty(
        name="Use Design Year",
        description="When this thing came into world for the first time\n"
        " e.g. for dinosaur, you set -240 million years ;) ",
        default=False,
    )
    design_year: IntProperty(
        name="Design Year", description="when was this item designed", default=1960
    )

    condition: EnumProperty(
        name="Condition",
        items=conditions,
        default="UNSPECIFIED",
        description="Condition of the object",
    )

    sexualized_content: BoolProperty(
        name="Sexualized Content",
        description=(
            "Flag this asset if it includes explicit content, suggestive poses, or overemphasized secondary sexual characteristics. "
            "This helps users filter content according to their preferences, creating a safe and inclusive browsing experience for all.\n\n"
            "Flag not required:\n"
            "- naked base mesh model,\n"
            "- figure in underwear/swimwear in neutral position.\n\n"
            "Flag required:\n"
            "- figure in sexually suggestive pose,\n"
            "- figure with over overemphasized sexual characteristics,\n"
            "- objects related to sexual act."
        ),
        default=False,
    )  # In future we can subsets like sexualized, pornography or violence subset. And allow users choose what is part of NSFW.

    work_hours: FloatProperty(
        name="Work Hours",
        description="How long did it take you to finish the asset?",
        default=0.0,
        min=0.0,
        max=8760,
    )

    modifiers: StringProperty(
        name="Modifiers Used",
        description="if you need specific modifiers, autofilled",
        default="",
    )

    materials: StringProperty(
        name="Material Names",
        description="names of materials in the file, autofilled",
        default="",
    )
    shaders: StringProperty(
        name="Shaders Used",
        description="shaders used in asset, autofilled",
        default="",
    )

    dimensions: FloatVectorProperty(
        name="Dimensions",
        description="dimensions of the whole asset hierarchy",
        default=(0, 0, 0),
    )
    bbox_min: FloatVectorProperty(
        name="Bbox Min",
        description="dimensions of the whole asset hierarchy",
        default=(-0.25, -0.25, 0),
    )
    bbox_max: FloatVectorProperty(
        name="Bbox Max",
        description="dimensions of the whole asset hierarchy",
        default=(0.25, 0.25, 0.5),
    )

    texture_resolution_min: IntProperty(
        name="Texture Resolution Min",
        description="texture resolution min, autofilled",
        default=0,
    )
    texture_resolution_max: IntProperty(
        name="Texture Resolution Max",
        description="texture resolution max, autofilled",
        default=0,
    )

    pbr: BoolProperty(
        name="PBR Compatible",
        description="Is compatible with PBR standard",
        default=False,
    )

    uv: BoolProperty(name="Has UV", description="has an UV set", default=False)
    # printable_3d : BoolProperty( name = "3d printable", description = "can be 3d printed", default = False)
    animated: BoolProperty(name="Animated", description="is animated", default=False)
    face_count: IntProperty(
        name="Face count", description="face count, autofilled", default=0
    )
    face_count_render: IntProperty(
        name="Render Face Count", description="render face count, autofilled", default=0
    )

    object_count: IntProperty(
        name="Number of Objects",
        description="how many objects are in the asset, autofilled",
        default=0,
    )
    mesh_poly_type: EnumProperty(
        name="Dominant Poly Type",
        items=mesh_poly_types,
        default="OTHER",
        description="",
    )

    manifold: BoolProperty(
        name="Manifold", description="asset is manifold, autofilled", default=False
    )

    rig: BoolProperty(
        name="Rig", description="asset is rigged, autofilled", default=False
    )
    simulation: BoolProperty(
        name="Simulation",
        description="asset uses simulation, autofilled",
        default=False,
    )
    """
    filepath : StringProperty(
            name="Filepath",
            description="file path",
            default="",
            )
    """

    # THUMBNAIL STATES
    is_generating_thumbnail: BoolProperty(
        name="Generating Thumbnail",
        description="True when background process is running",
        default=False,
        update=autothumb.update_upload_model_preview,
    )

    is_generating_wire_thumbnail: BoolProperty(
        name="Generating Wire Thumbnail",
        description="True when background process is running",
        default=False,
        update=autothumb.update_wire_thumbnail_preview,
    )

    has_autotags: BoolProperty(
        name="Has Autotagging Done",
        description="True when autotagging done",
        default=False,
    )

    # Add this new property for printable assets
    photo_thumbnail: StringProperty(
        name="Photo Thumbnail",
        description="Photo of the 3D printed object (JPG or PNG, preferred size is 1024x1024 or higher)",
        subtype="FILE_PATH",
        default="",
        **EXTRA_PATH_OPTIONS,
    )
    photo_thumbnail_will_upload_on_website: BoolProperty(
        name="I will upload photo on website",
        description="True if the photo thumbnail will upload on the website\n please read upload tutorial for more information",
        default=False,
    )

    wire_thumbnail: StringProperty(
        name="Wireframe Thumbnail",
        description="Wireframe thumbnail (JPG or PNG, preferred size is 1024x1024 or higher)",
        subtype="FILE_PATH",
        default="",
        update=autothumb.update_wire_thumbnail_preview,
        **EXTRA_PATH_OPTIONS,
    )

    wire_thumbnail_generating_state: StringProperty(
        name="Wire Thumbnail Generating State",
        description="bg process reports for wireframe thumbnail generation",
        default="Please add wireframe thumbnail (jpg or png, at least 1024x1024)",
    )


class BlenderKitSceneUploadProps(PropertyGroup, BlenderKitCommonUploadProps):
    style: EnumProperty(
        name="Style",
        items=model_styles,
        description="Style of asset",
        default="REALISTIC",
    )
    style_other: StringProperty(
        name="Style Other",
        description="Style not in the list",
        default="",
    )
    engine: EnumProperty(
        name="Engine",
        items=engines,
        default="CYCLES",
        description="Output engine",
    )

    production_level: EnumProperty(
        name="Production Level",
        items=(
            ("FINISHED", "Finished", "Render or animation ready asset"),
            (
                "TEMPLATE",
                "Template",
                "Asset intended to help in creation of something else",
            ),
        ),
        default="FINISHED",
        description="Production state of the asset, \n also template should be actually finished, \n"
        "just the nature of it can be a template, like a thumbnailer scene, \n "
        "finished mesh topology as start for modelling or similar",
    )

    engine_other: StringProperty(
        name="Engine",
        description="engine not specified by addon",
        default="",
    )

    engine1: EnumProperty(
        name="2nd Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )
    engine2: EnumProperty(
        name="3rd Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )
    engine3: EnumProperty(
        name="4th Engine",
        items=engines,
        default="NONE",
        description="Output engine",
    )

    thumbnail: StringProperty(
        name="Thumbnail",
        description="Thumbnail path - 512x512 .jpg\n" "Rendered with cycles",
        subtype="FILE_PATH",
        default="",
        update=autothumb.update_upload_scene_preview,
        **EXTRA_PATH_OPTIONS,
    )

    use_design_year: BoolProperty(
        name="Use Design Year",
        description="When this thing came into world for the first time\n"
        " e.g. for dinosaur, you set -240 million years ;) ",
        default=False,
    )
    design_year: IntProperty(
        name="Design Year", description="when was this item designed", default=1960
    )

    condition: EnumProperty(
        name="Condition",
        items=conditions,
        default="UNSPECIFIED",
        description="Condition of the object",
    )

    sexualized_content: BoolProperty(
        name="Sexualized content",
        description="Scene contains sexualized content",
        default=False,
    )

    work_hours: FloatProperty(
        name="Work Hours",
        description="How long did it take you to finish the asset?",
        default=0.0,
        min=0.0,
        max=8760,
    )

    modifiers: StringProperty(
        name="Modifiers Used",
        description="if you need specific modifiers, autofilled",
        default="",
    )

    materials: StringProperty(
        name="Material Names",
        description="names of materials in the file, autofilled",
        default="",
    )
    shaders: StringProperty(
        name="Shaders Used",
        description="shaders used in asset, autofilled",
        default="",
    )

    dimensions: FloatVectorProperty(
        name="Dimensions",
        description="dimensions of the whole asset hierarchy",
        default=(0, 0, 0),
    )
    bbox_min: FloatVectorProperty(
        name="Dimensions",
        description="dimensions of the whole asset hierarchy",
        default=(-0.25, -0.25, 0),
    )
    bbox_max: FloatVectorProperty(
        name="Dimensions",
        description="dimensions of the whole asset hierarchy",
        default=(0.25, 0.25, 0.5),
    )

    texture_resolution_min: IntProperty(
        name="Texture Resolution Min",
        description="texture resolution min, autofilled",
        default=0,
    )
    texture_resolution_max: IntProperty(
        name="Texture Resolution Max",
        description="texture resolution max, autofilled",
        default=0,
    )

    pbr: BoolProperty(
        name="PBR Compatible",
        description="Is compatible with PBR standard",
        default=False,
    )

    uv: BoolProperty(name="Has UV", description="has an UV set", default=False)
    # printable_3d : BoolProperty( name = "3d printable", description = "can be 3d printed", default = False)
    animated: BoolProperty(name="Animated", description="is animated", default=False)
    face_count: IntProperty(
        name="Face Count", description="face count, autofilled", default=0
    )
    face_count_render: IntProperty(
        name="Render Face Count", description="render face count, autofilled", default=0
    )

    object_count: IntProperty(
        name="Number of Objects",
        description="how many objects are in the asset, autofilled",
        default=0,
    )
    mesh_poly_type: EnumProperty(
        name="Dominant Poly Type",
        items=mesh_poly_types,
        default="OTHER",
        description="",
    )

    rig: BoolProperty(
        name="Rig", description="asset is rigged, autofilled", default=False
    )
    simulation: BoolProperty(
        name="Simulation",
        description="asset uses simulation, autofilled",
        default=False,
    )

    # THUMBNAIL STATES
    is_generating_thumbnail: BoolProperty(
        name="Generating Thumbnail",
        description="True when background process is running",
        default=False,
        update=autothumb.update_upload_model_preview,
    )

    has_autotags: BoolProperty(
        name="Has Autotagging Done",
        description="True when autotagging done",
        default=False,
    )


class BlenderKitModelSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    search_style: EnumProperty(
        name="Style",
        items=search_model_styles,
        description="Keywords defining style (realistic, painted, polygonal, other)",
        default="ANY",
        update=search.search_update,
    )
    search_style_other: StringProperty(
        name="Style",
        description="Search style - other",
        default="",
        update=search.search_update,
    )
    search_engine: EnumProperty(
        items=engines,
        default="CYCLES",
        description="Output engine",
        update=search.search_update,
    )
    search_engine_other: StringProperty(
        name="Engine",
        description="Engine not specified by addon",
        default="",
        update=search.search_update,
    )
    search_condition: EnumProperty(
        name="Condition",
        items=conditions,
        default="UNSPECIFIED",
        description="Condition of the object",
        update=search.search_update,
    )
    search_design_year: BoolProperty(
        name="Designed in Year",
        description="When the object was approximately designed. \n"
        "Useful for search of historical or future objects",
        default=False,
        update=search.search_update,
    )

    search_design_year_min: IntProperty(
        name="Minimum Design Year",
        description="Minimum design year",
        default=1950,
        min=-100000000,
        max=1000000000,
        update=search.search_update_delayed,
    )

    search_design_year_max: IntProperty(
        name="Maximum Design Year",
        description="Maximum design year",
        default=2017,
        min=0,
        max=10000000,
        update=search.search_update_delayed,
    )

    # POLYCOUNT
    search_polycount: BoolProperty(
        name="Use Polycount",
        description="Limit polycount",
        default=False,
        update=search.search_update,
    )

    search_polycount_min: IntProperty(
        name="Min Polycount",
        description="Minimum poly count",
        default=0,
        min=0,
        max=100000000,
        update=search.search_update_delayed,
    )

    search_polycount_max: IntProperty(
        name="Max Polycount",
        description="Maximum poly count",
        default=100000000,
        min=0,
        max=100000000,
        update=search.search_update_delayed,
    )
    search_animated: BoolProperty(
        name="Animated",
        default=False,
        description="Search only animated assets",
        update=search.search_update,
    )

    search_geometry_nodes: BoolProperty(
        name="Geometry Nodes",
        default=False,
        description="Show only assets that use Geometry Nodes",
        update=search.search_update,
    )

    import_method: EnumProperty(
        name="Import Method",
        items=(
            ("LINK_COLLECTION", "Link", "Link Collection"),
            ("APPEND_OBJECTS", "Append", "Append as Objects"),
        ),
        description="Appended objects are editable in your scene. Linked assets are saved in original files, "
        "aren't editable but also don't increase your file size",
        default="APPEND_OBJECTS",
    )
    append_link: EnumProperty(
        name="How to Attach",
        items=(
            ("LINK", "Link", ""),
            ("APPEND", "Append", ""),
        ),
        description="choose if the assets will be linked or appended",
        default="LINK",
    )
    import_as: EnumProperty(
        name="Import as",
        items=(
            ("GROUP", "group", ""),
            ("INDIVIDUAL", "objects", ""),
        ),
        description="choose if the assets will be linked or appended",
        default="GROUP",
    )
    randomize_rotation: BoolProperty(
        name="Randomize Rotation",
        description="randomize rotation at placement",
        default=False,
    )
    randomize_rotation_amount: FloatProperty(
        name="Randomization Max Angle",
        description="maximum angle for random rotation",
        default=pi / 36,
        min=0,
        max=2 * pi,
        subtype="ANGLE",
    )
    offset_rotation_amount: FloatProperty(
        name="Offset Rotation",
        description="offset rotation, hidden prop",
        default=0,
        min=-360,
        max=360,
        subtype="ANGLE",
    )

    perpendicular_snap: BoolProperty(
        name="Perpendicular snap",
        description="Limit snapping that is close to perpendicular angles to be perpendicular",
        default=True,
    )

    perpendicular_snap_threshold: FloatProperty(
        name="Threshold",
        description="Limit perpendicular snap to be below these values",
        default=0.25,
        min=0,
        max=0.5,
    )


class BlenderKitHDRSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    true_hdr: BoolProperty(
        name="Real HDRs only",
        description="Search only for real HDRs, this means images that have a range higher than 0-1 in their pixels.",
        default=True,
        update=search.search_update,
    )


def our_keymap_draw(self, context):
    try:
        keymap_utils.draw_keymap(self, context)
    except Exception:
        bk_logger.exception("Failed to draw keymap in preferences")
        return


class BlenderKitSceneSearchProps(PropertyGroup, BlenderKitCommonSearchProps):
    search_style: EnumProperty(
        name="Style",
        items=search_model_styles,
        description="Restrict search for style",
        default="ANY",
        update=search.search_update,
    )
    search_style_other: StringProperty(
        name="Style",
        description="Search style - other",
        default="",
        update=search.search_update,
    )
    search_engine: EnumProperty(
        items=engines,
        default="CYCLES",
        description="Output engine",
        update=search.search_update,
    )
    search_engine_other: StringProperty(
        name="Engine",
        description="Engine not specified by addon",
        default="",
        update=search.search_update,
    )
    append_link: EnumProperty(
        name="Append or link",
        items=(
            ("LINK", "Link", ""),
            ("APPEND", "Append", ""),
        ),
        description="choose if the scene will be linked or appended",
        default="APPEND",
    )
    switch_after_append: BoolProperty(
        name="Switch to scene after download", default=True
    )


def fix_subdir(self, context):
    """Fixes project subdirectory settings if people input invalid path."""

    # pp = pathlib.PurePath(self.project_subdir)
    pp = self.project_subdir[:]
    pp = pp.replace("\\", "")
    pp = pp.replace("/", "")
    pp = pp.replace(":", "")
    pp = "//" + pp
    if self.project_subdir != pp:
        self.project_subdir = pp

        ui_panels.ui_message(
            title="Fixed to relative path",
            message="This path should be always relative.\n"
            " It's a directory Blendkit creates where your .blend is \n "
            "and uses it for storing assets.",
        )


def update_create_asset_library(self, context):
    """Save prefs and add or remove the Blendkit asset library entry accordingly.

    When enabled, ensures Blender's Asset Libraries list contains the Blendkit
    entry. When disabled, removes the Blendkit entry if it is present.
    """
    utils.save_prefs(self, context)
    if self.create_asset_library:
        paths.ensure_asset_library_path()
    else:
        paths.remove_asset_library_path()


def update_unpack(self, context):
    """Open UI message about unpacking compatibility. If unpack was updated from code (preferences_lock is True), then don't show the message."""
    if self.preferences_lock == True:
        return
    ui_panels.ui_message(
        title="Unpack compatibility",
        message=" - With unpack on, you can access your textures easier,"
        " and resolution swapping of assets is possible.\n\n"
        " - With unpack off, you can avoid some issues that "
        "are caused by other addons like e.g. Megascans. "
        "Switch unpack off if you encounter problems like stuck downloads",
    )


class BlenderKitAddonPreferences(AddonPreferences):
    bl_idname = __package__
    default_global_dict = paths.default_global_dict()

    preferences_lock: BoolProperty(
        name="Preferences Locked",
        description="When this is on, preferences will not be saved. Used for programmatic changes of preferences",
        default=False,
    )

    keep_preferences: BoolProperty(
        name="Keep preferences on disabling",
        description="When selected, the Blendkit add-on preferences will be saved into JSON file and persisted even when the add-on is disabled and then re-enabled.",
        default=False,
        update=persistent_preferences.property_keep_preferences_updated,
    )

    api_key: StringProperty(
        name="Blendkit API Key",
        description=(
            "Your unique API key authenticates downloads and requests inside the add-on. "
            "No manual setup is required, the API Key is auto-filled at login and cleared at logout. "
            "However, you can also paste the key from your profile settings on the Blendkit website."
        ),
        default="",
        subtype="PASSWORD",
        update=utils.api_key_property_updated,
    )

    api_key_refresh: StringProperty(
        name="Blendkit refresh API Key",
        description="API key used to refresh the token regularly",
        default="",
        subtype="PASSWORD",
    )

    api_key_timeout: IntProperty(
        name="api key timeout",
        description="time where the api key will need to be refreshed",
        default=0,
    )

    login_attempt: BoolProperty(
        name="Login/Signup attempt",
        description="When this is on, Blendkit is trying to connect and login",
        default=False,
    )

    show_on_start: BoolProperty(
        name="Show assetbar when starting Blender",
        description="Show assetbar when starting Blender",
        default=False,
        update=utils.save_prefs,
    )

    tips_on_start: BoolProperty(
        name="Show tips when starting Blender",
        description="Show tips when starting Blender",
        default=True,
        update=utils.save_prefs,
    )

    announcements_on_start: BoolProperty(
        name="Receive online announcements when starting Blender",
        description="Show crucial online announcements from the Blendkit service. These are official messages from the Blendkit team regarding maintenance, events, and other relevant information.",
        default=True,
        update=utils.save_prefs,
    )

    search_in_header: BoolProperty(
        name="Show Blendkit search in 3D view header",
        description="Show Blendkit search in 3D view header",
        default=True,
        update=utils.save_prefs,
    )

    sidebar_panels: BoolProperty(
        name="Hide sidebar panels",
        description="Hide Blendkit sidebar panels (search, upload, and selected model functionality). This prevents upload and it's also the only place for import settings. Reenable this to access these features.",
        default=False,
        update=utils.save_prefs,
    )

    header_menu_fold: BoolProperty(
        name="Header menu fold", default=False, update=ui_panels.update_header_menu_fold
    )

    show_VIEW3D_MT_blenderkit_model_properties: bpy.props.BoolProperty(
        name="Show Blendkit in Object Context Menu",
        description="Show Blendkit submenu in object context menu",
        default=True,
    )

    assetbar_follows_cursor: BoolProperty(
        name="Assetbar follows active viewport",
        description="Make the assetbar follow the cursor across the screen",
        default=False,
    )

    global_dir: StringProperty(
        name="Global Directory",
        description="Global storage for your assets, will use subdirectories for the contents. Client will place its files in subdirectory 'client'",
        subtype="DIR_PATH",
        default=default_global_dict,
        update=utils.save_prefs,
    )

    project_subdir: StringProperty(
        name="Project Subdirectory",
        description="Subdirectory for asset data storage in the project (provide relative path)",
        default="//assets",
        update=fix_subdir,
    )

    client_port: EnumProperty(
        name="Client port",
        description="Port to be used for startup and communication with Blendkit-Client. Changing the port will cancel all running downloads and searches",
        items=(
            ("62485", "62485", ""),
            ("65425", "65425", ""),
            ("55428", "55428", ""),
            ("49452", "49452", ""),
            ("35452", "35452", ""),
            ("25152", "25152", ""),
            ("5152", "5152", ""),
            ("1234", "1234", ""),
        ),
        default="62485",
        update=timer.save_prefs_cancel_all_tasks_and_restart_client,
    )

    client_polling: FloatProperty(
        name="Client Polling",
        description="Time interval in which add-on polls the Blendkit-Client for updates on running requests and tasks. The lower the more responsive the add-on is, but it requires more resources.",
        default=0.2,
        min=0.1,
        max=0.5,
        update=utils.save_prefs,
    )

    # USE OF CLIPBOARD SCAN
    use_clipboard_scan: BoolProperty(
        name="Use Clipboard Scan",
        description="Use the info from Blendkit website clipboard for visual search.\n"
        "On Linux/X11 this periodically reads the system clipboard, which can rarely\n"
        "stall if another application left the clipboard in a bad state - disable this\n"
        "option if you experience freezes",
        default=True,
        update=utils.save_prefs,
    )

    unpack_files: BoolProperty(
        name="Unpack Files",
        description="Unpack assets after download \n "
        "- With unpack on, you can access your textures easier,"
        " and resolution swapping of assets is possible.\n\n"
        " - With unpack off, you can avoid some issues that "
        "are caused by other addons like e.g. Megascans. "
        "Switch unpack off if you encounter problems like stuck downloads",
        default=False,
        update=update_unpack,
    )

    create_asset_library: BoolProperty(
        name="Register Local Blendkit Asset Library",
        description="Automatically add (and keep in sync) a 'Blendkit' entry in Blender's Asset Libraries pointing to the global directory.\n\n"
        "This allows you to easily access your downloaded assets in the Asset Browser, and also ensures that metadata like tags and descriptions are available for your assets across all your projects. "
        "When disabled, Blendkit will remove the 'Blendkit' entry from your Asset Libraries list (if present), and downloaded assets won't be unpacked in the background just to embed asset metadata "
        "(unless 'Unpack Files' is enabled). Disable this if you don't want Blendkit to manage your Asset Browser entries",
        default=False,
        update=update_create_asset_library,
    )

    # resolution download/import settings
    resolution: EnumProperty(
        name="Max resolution",
        description="Cap texture sizes in the file to this resolution",
        items=(
            # ('256', '256x256', ''),
            ("512", "512x512", ""),
            ("1024", "1024x1024", ""),
            ("2048", "2048x2048", ""),
            ("4096", "4096x4096", ""),
            ("8192", "8192x8192", ""),
            ("ORIGINAL", "ORIGINAL FILE", ""),
        ),
        default="2048",
    )

    material_import_automap: BoolProperty(
        name="Auto-Map",
        description="Reset object texture space and also add automatically a cube mapped UV to the object.\n"
        "This allows most materials to apply instantly to any mesh",
        default=True,
        update=utils.save_prefs,
    )

    # NETWORKING

    ip_version: EnumProperty(
        name="IP version",
        items=(
            (
                "BOTH",
                "Use both IPv4 and IPv6",
                "Add-on will use both IPv4 and IPv6 families of addresses for connections",
            ),
            (
                "IPv4",
                "Use only IPv4",
                "Add-on will use only IPv4 family of addresses for connections. This might fix connection issues on some systems connected to only IPv4 networks",
            ),
        ),
        description="Which address family add-on should use for connection",
        default="BOTH",
        update=timer.save_prefs_cancel_all_tasks_and_restart_client,
    )

    ssl_context: EnumProperty(
        name="SSL Verification",
        items=(
            (
                "ENABLED",
                "Enabled SSL Verification",
                "Activates SSL verification for outbound connections, ensuring secure communication between the Blendkit-client and the blendkit.com server",
            ),
            (
                "DISABLED",
                "Disabled SSL Verification - Insecure!",
                "Deactivates SSL verification, bypassing the validation of SSL certificates by Blendkit-client. This mode is insecure and recommended only for testing environments",
            ),
        ),
        description="Secure communication between Blendkit-client and blendkit.com server by SSL",
        default="ENABLED",
        update=timer.save_prefs_cancel_all_tasks_and_restart_client,
    )

    proxy_which: EnumProperty(
        name="Proxy",
        items=(
            (
                "SYSTEM",
                "SYSTEM: use system's networking settings",
                "The add-on will detect the proxy address from the operating system's networking settings "
                "with fallback to HTTPS_PROXY environment variable. "
                "Custom proxy settings in the add-on preferences will be ignored.",
            ),
            (
                "ENVIRONMENT",
                "ENVIRONMENT: use environment variable HTTPS_PROXY",
                "The add-on will detect the proxy address from the environment variable HTTPS_PROXY. "
                "Operating system's networking settings and custom proxy settings in the add-on preferences will be ignored.",
            ),
            (
                "NONE",
                "NONE: ignore all proxy settings",
                "The add-on will ignore operating system's networking settings, the environment variable HTTPS_PROXY, "
                "and custom proxy settings defined in the add-on preferences. "
                "No add-on HTTPS requests will go through any proxy server.",
            ),
            (
                "CUSTOM",
                "CUSTOM: use custom proxy settings",
                "The add-on will use specified custom proxy settings; system's and environment proxy settings will be ignored. "
                'Please set the address in the "Custom proxy address" field below. ',
            ),
        ),
        description="Configure proxy settings for all outgoing HTTPS requests",
        default="SYSTEM",
        update=timer.save_prefs_cancel_all_tasks_and_restart_client,
    )

    proxy_address: StringProperty(
        name="Custom proxy address",
        description="""Set custom HTTP proxy for HTTPS requests of add-on. This setting precedes any system wide proxy settings. If left empty custom proxy will not be set.

If you use simple HTTP proxy, set in format http://ip:port, or http://username:password@ip:port if your HTTP proxy requires authentication (make sure to escape special characters like #$%:^&*() etc. in username and password). You have to specify the address with http:// prefix.

HTTPS proxies are not supported! We wait for support in Python 3.11 and in aiohttp module. You can specify the HTTPS proxy with https:// prefix for hacking around and development purposes, but functionality cannot be guaranteed.
In this case you should also set path to your system CA bundle containing proxy's certificates in the field "Custom CA certificates path" below""",
        default="",
        update=timer.save_prefs_cancel_all_tasks_and_restart_client,
    )

    trusted_ca_certs: StringProperty(
        name="Custom CA certificates path",
        description=(
            "Specify a path to a custom bundle of trusted certificates in .PEM format.\n\n"
            "If you're on corporate/institutional networks, using a VPN, or behind intermediaries like proxies, firewalls, antiviruses that manipulate HTTPS traffic, "
            "the add-on might struggle to verify encrypted communication as signed by the Blendkit server leading to CERTIFICATE_VERIFY_FAILED error. "
            "This is because the traffic could be decrypted, possibly altered or logged, and then re-encrypted by the intermediary's certificate and not by Blendkit certificate. "
            "If you recognize and trust this intermediary, provide the path to its public certificates or their certificate authority here. "
            "This ensures the add-on communicates with a known, trusted entity, and not a potential threat.\n\n"
            "For those in corporate or educational institutions, it's advisable to consult your IT department about the relevant certificates. "
            "For personal VPNs, proxies, or other software, please consult its documentation"
        ),
        default="",
        subtype="FILE_PATH",
        update=timer.trusted_CA_certs_property_updated,
    )

    directory_behaviour: EnumProperty(
        name="Use Directories",
        items=(
            (
                "BOTH",
                "Global directory and Project's subdirectory",
                "Save downloaded asset files in both the global directory and the subdirectory of the current project. "
                "This option keeps your projects organized and preserves download data since assets are also cached in the global directory. "
                "However, it may consume more disk space due to potential duplication of assets in both locations.",
            ),
            (
                "GLOBAL",
                "Global directory",
                "Store downloaded files in the global directory only. "
                "This option saves disk space by keeping assets in a single location, "
                "but it makes it more difficult to move projects to another computer since assets won't be in the subdirectory of the current project.",
            ),
            (
                "LOCAL",
                "Project's subdirectory",
                "Save downloaded files in the subdirectory of the current project only."
                "This option makes projects compact, portable, and easy to transport as assets are stored inside. "
                "It usually saves disk space since no duplicate data is stored in the global directory. "
                "However, when reusing assets in a new project, they will be downloaded again and stored again in the new project's subdirectory.",
            ),
        ),
        description="Determines the locations used for storing downloaded asset data.",
        default="BOTH",
        update=utils.save_prefs,
    )

    thumbnail_settings: PointerProperty(
        type=BlenderKitThumbnailSettings,
        description="Global thumbnail render settings, remembered across sessions",
    )

    maximized_assetbar_rows: IntProperty(
        name="Assetbar Rows",
        description="Saved row count of the assetbar in the 3D view",
        default=4,
        min=2,
        max=asset_bar_op.ASSETBAR_MAX_VISIBLE_ASSETS,
        update=utils.save_prefs,
    )

    assetbar_expanded: BoolProperty(
        name="Assetbar Expanded",
        description="Remember whether the assetbar is expanded in the 3D view",
        default=False,
        update=utils.save_prefs,
    )

    trackpad_scroll_sensitivity: FloatProperty(
        name="Trackpad Scroll Sensitivity",
        description=(
            "Pixels of trackpad finger travel required to scroll one asset slot. "
            "Increase to make trackpad scrolling slower (recommended on macOS), "
            "decrease to make it faster"
        ),
        default=120.0,
        min=5.0,
        max=400.0,
        update=utils.save_prefs,
    )

    thumb_size: IntProperty(
        name="Assetbar Thumbnail Size",
        default=128,
        min=48,  # must newer be zero
        max=256,
        update=utils.save_prefs,
        description="Size of thumbnails of the assetbar in 3D view",
    )

    search_field_width: IntProperty(
        name="Search Field Width",
        default=0,
        min=0,
        max=100,
        update=utils.save_prefs,
        description="Width of the search field in the assetbar in 3D view. 0 means automatic width",
    )

    comments_order: EnumProperty(
        name="Comments Order",
        description="Order in which comments are shown in the asset detail popup",
        items=(
            ("default", "Default", "Keep the server order (based on ratings)"),
            ("oldest", "Oldest first", "Show oldest comments at the top"),
            ("newest", "Newest first", "Show newest comments at the top"),
        ),
        default="default",
        update=utils.save_prefs,
    )

    proxor_enabled: BoolProperty(
        name="Enable Proxor",
        description="Enable Proxor, proxy visualization of assets in the 3D view while placing. Loads with mini delay after the default green placeholder.",
        default=True,
        update=utils.save_prefs,
    )

    rating_nudge_enabled: BoolProperty(
        name="Ask me to rate downloaded assets",
        description="Occasionally open a rating popup for assets you downloaded that don't have enough ratings yet",
        default=True,
        update=utils.save_prefs,
    )

    experimental_features: BoolProperty(
        name="Enable experimental features",
        description="Enable experimental features of Blendkit, such as the Authors tab",
        default=False,
        update=utils.save_prefs,
    )

    accepted_ms_store_warning: BoolProperty(
        name="Accepted Microsoft Store Blender warning",
        description=(
            "Set after the user has acknowledged the in-viewport warning shown"
            " when running Blendkit on a Microsoft Store install of Blender."
            " Uncheck to see the warning again on the next asset bar launch"
            " (useful for debugging)."
        ),
        default=False,
        update=utils.save_prefs,
    )

    author_tab: BoolProperty(
        name="Show Authors tab",
        description="Show Authors tab in the assetbar. This tab allows you to see all assets of a specific author and is also used for showing your profile and assets",
        default=False,
        update=utils.save_prefs,
    )

    author_asset_type_picker: BoolProperty(
        name="Author asset type picker",
        description="Enable the Authors tab in the asset type picker. When disabled, clicking an author searches in the current tab",
        default=False,
        update=utils.save_prefs,
    )

    thread_communication: BoolProperty(
        name="Threaded Blendkit-Client communication",
        description=(
            "Move communication with the Blendkit-Client (report polling and"
            " selected fire-and-forget HTTP requests) onto a background thread."
            " This keeps Blender responsive when the local Client is slow to"
            " respond. Only takes effect while experimental features are enabled."
        ),
        default=False,
        update=utils.save_prefs,
    )

    categories_fix: BoolProperty(
        name="Enable category fixing mode",
        description="Enable category fixing mode",
        default=False,
        update=utils.save_prefs,
    )

    ### UPDATES
    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=True,
    )

    enable_prereleases: bpy.props.BoolProperty(
        name="Enable prereleases",
        description="If enabled, updater will also include prerelease versions and check for them on every start",
        default=False,
    )

    updater_interval_months: bpy.props.IntProperty(
        name="Months",
        description="Number of months between checking for updates",
        default=0,
        min=0,
    )

    updater_interval_days: bpy.props.IntProperty(
        name="Days",
        description="Number of days between checking for updates",
        default=10,
        min=0,
        max=31,
    )

    updater_interval_hours: bpy.props.IntProperty(
        name="Hours",
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23,
    )

    updater_interval_minutes: bpy.props.IntProperty(
        name="Minutes",
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59,
    )

    ### STATISTICS - so we can hide tooltips after a while and tailor UI more
    download_counter: IntProperty(
        name="Download Counter",
        description="Counts downloads of assets so it asks for registration only after reaching a limit",
        default=0,
        min=0,
        update=utils.save_prefs_without_save_userpref,
    )

    asset_popup_counter_max = 5  # how many times the popup hint will be shown
    asset_popup_counter: IntProperty(
        name="Asset Popup Card Counter",
        description="Counts Asset popup card counter. To enable hiding of the tooltip after some time",
        default=0,
        min=0,
        max=asset_popup_counter_max,
        update=utils.save_prefs_without_save_userpref,
    )
    welcome_operator_counter: IntProperty(
        name="Welcome Operator Counter",
        description="Counts how many times the Welcome Operator was shown on addon enable.",
        default=0,
        min=0,
        update=utils.save_prefs,
    )

    # NSFW FILTERS
    # prepared to be shared across all asset types, because materials can be violent, HDRi can terrifying etc.
    nsfw_filter: BoolProperty(
        name="Hide Adult/NSFW Content",
        description="Hide content intended for adults that may not be safe for work. This setting will be persisted between Blender sessions.\n\nBy disabling, you confirm that you are an adult.",
        default=True,
        update=search.search_update,
    )  # In future we can subsets like sexualized, pornography or violence subset. And allow users choose what is part of NSFW.

    temp_enabled_addons: StringProperty(
        name="Temporarily Enabled Addons",
        description="JSON string of temporarily enabled addon package IDs that should be disabled on next session",
        default="[]",
    )

    # EXPERIMENTAL AND DEBUG FEATURES CAN GO BELOW
    ignore_env_for_thumbnails: BoolProperty(
        name="Ignore ENVIRONMENT variables for thumbnails",
        description="If enabled, we will not modify the system environment variables for background thumbnail rendering.",
        default=False,
        # do not save prefs here, it's experimental
        options={"SKIP_SAVE"},
    )

    def draw(self, context):
        layout = self.layout
        login_box = layout.box()
        login_box.label(text="Login Options")
        if self.api_key.strip() == "":
            ui_panels.draw_login_buttons(login_box)
            login_box.label(
                text="Sign up to bookmark your favorite assets. Get 200 MiB of private storage in Free Plan."
            )
        else:
            login_box.operator("wm.blenderkit_logout", text="Logout", icon="URL")
        login_box.prop(self, "api_key", text="Your API Key")
        login_box.prop(self, "keep_preferences")
        community_row = login_box.row()
        community_row.prop(self, "experimental_features")
        community_row.operator("wm.blenderkit_join_discord", icon="URL")

        if utils.profile_is_validator():
            validator_box = layout.box()
            validator_box.label(text="Validator Settings")
            validator_box.prop(self, "categories_fix")

        # REPORT BUG BUTTON
        report_settings = layout.box()
        report_settings.label(text="Report a Bug")
        report_row = report_settings.row()
        report_row.operator(
            "wm.blenderkit_report_bug", text="Open Bug Report", icon="ERROR"
        )
        # report_row.label(text=f"Blendkit v{utils.get_addon_version()} · Blender {bpy.app.version_string}", icon="INFO")
        report_row.operator(
            "wm.blenderkit_copy_environment_info", text="Copy Info", icon="COPYDOWN"
        )

        # FILE PATHS
        locations_settings = layout.box()
        locations_settings.alignment = "EXPAND"
        locations_settings.label(text="File Paths and Data Handling")
        locations_settings.prop(self, "directory_behaviour")
        locations_settings.prop(self, "global_dir")
        if self.directory_behaviour in ("BOTH", "LOCAL"):
            locations_settings.prop(self, "project_subdir")
        locations_settings.prop(self, "unpack_files")
        locations_settings.prop(self, "create_asset_library")

        # GUI SETTINGS
        gui_settings = layout.box()
        gui_settings.alignment = "EXPAND"
        gui_settings.label(text="GUI settings")
        gui_settings.prop(self, "show_on_start")
        gui_settings.prop(self, "thumb_size")
        gui_settings.prop(self, "trackpad_scroll_sensitivity")
        gui_settings.prop(self, "search_field_width")
        gui_settings.prop(self, "search_in_header")
        gui_settings.prop(self, "sidebar_panels")
        gui_settings.prop(self, "show_VIEW3D_MT_blenderkit_model_properties")
        gui_settings.prop(self, "comments_order")
        gui_settings.prop(self, "tips_on_start")
        gui_settings.prop(self, "announcements_on_start")
        gui_settings.prop(self, "assetbar_follows_cursor")
        gui_settings.prop(self, "use_clipboard_scan")
        gui_settings.prop(self, "proxor_enabled")
        gui_settings.prop(self, "rating_nudge_enabled")

        # THUMBNAIL SETTINGS
        # These are machine-level preferences that should be set once, not
        # toggled in every thumbnail render dialog.
        thumbnail_settings = layout.box()
        thumbnail_settings.alignment = "EXPAND"
        thumbnail_settings.label(text="Thumbnail settings")
        thumbnail_settings.prop(self.thumbnail_settings, "thumbnail_use_gpu")
        if utils.elevated_experimental_enabled():
            thumbnail_settings.prop(self.thumbnail_settings, "thumbnail_render_engine")

        # NETWORKING SETTINGS
        network_settings = layout.box()
        network_settings.alignment = "EXPAND"
        network_settings.label(text="Networking settings")
        network_settings.prop(self, "client_port")
        network_settings.prop(self, "client_polling")
        network_settings.prop(self, "ip_version")
        network_settings.prop(self, "ssl_context")
        network_settings.prop(self, "proxy_which")
        if self.proxy_which == "CUSTOM":
            network_settings.prop(self, "proxy_address")
        network_settings.prop(self, "trusted_ca_certs")

        # UPDATER SETTINGS
        addon_updater_ops.update_settings_ui(self, context)

        # RUNTIME INFO
        directory_box = layout.box()
        directory_box.label(text="Directories and Paths")

        globdir_op = directory_box.operator(
            "wm.blenderkit_open_global_directory",
            text=f"Global directory: {self.global_dir}",
            icon="FILE_FOLDER",
        )
        globdir_op.directory = self.global_dir

        clientlog_path = client_lib.get_client_log_path()
        clientlog_op = directory_box.operator(
            "wm.blenderkit_open_client_log",
            text=f"Client log: {clientlog_path}",
            icon="FILE_FOLDER",
        )
        clientlog_op.directory = clientlog_path

        addondir = path.dirname(__file__)
        addondir_op = directory_box.operator(
            "wm.blenderkit_open_addon_directory",
            text=f"Installed at: {addondir}",
            icon="FILE_FOLDER",
        )
        addondir_op.directory = addondir

        tempdir = paths.get_temp_dir()
        tempdir_op = directory_box.operator(
            "wm.blenderkit_open_temp_directory",
            text=f"Temp directory: {tempdir}",
            icon="FILE_FOLDER",
        )
        tempdir_op.directory = tempdir

        # try to draw also custom keymaps
        our_keymap_draw(self, context)

        # EXPERIMENTAL SETTINGS
        # only if experimental features enabled
        if self.experimental_features:
            experimental_settings = layout.box()
            experimental_settings.alignment = "EXPAND"
            experimental_settings.label(text="Experimental settings")
            experimental_settings.prop(self, "author_tab")
            experimental_settings.prop(self, "author_asset_type_picker")
            experimental_settings.prop(self, "ignore_env_for_thumbnails")
            experimental_settings.prop(self, "thread_communication")
            experimental_settings.prop(self, "accepted_ms_store_warning")


# registration
classes = (
    BlenderKitUIProps,
    BlenderKitModelSearchProps,
    BlenderKitModelUploadProps,
    BlenderKitSceneSearchProps,
    BlenderKitSceneUploadProps,
    BlenderKitHDRSearchProps,
    BlenderKitHDRUploadProps,
    BlenderKitMaterialUploadProps,
    BlenderKitMaterialSearchProps,
    BlenderKitTextureUploadProps,
    BlenderKitBrushSearchProps,
    BlenderKitBrushUploadProps,
    BlenderKitGeoToolSearchProps,
    BlenderKitNodeGroupUploadProps,
    BlenderKitAddonSearchProps,
    BlenderKitAuthorSearchProps,
)


def register():
    reload(global_vars)
    global_vars.VERSION = VERSION
    # Must be registered before the preferences class, which references it via PointerProperty.
    bpy.utils.register_class(BlenderKitThumbnailSettings)
    bpy.utils.register_class(BlenderKitAddonPreferences)

    # Drop any downloads that might have been left running if the add-on was re-enabled mid-transfer.
    download.cancel_running_downloads("addon register")

    addon_updater_ops.register({"version": VERSION})
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.blenderkitUI = PointerProperty(type=BlenderKitUIProps)

    # bpy.types.WindowManager.blenderkit_ratings = PointerProperty(
    #     type =  ratings_utils.RatingPropsCollection)
    # MODELS
    bpy.types.WindowManager.blenderkit_models = PointerProperty(
        type=BlenderKitModelSearchProps
    )
    bpy.types.Object.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitModelUploadProps
    )

    # SCENES
    bpy.types.WindowManager.blenderkit_scene = PointerProperty(
        type=BlenderKitSceneSearchProps
    )
    bpy.types.Scene.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitSceneUploadProps
    )

    # HDRs
    bpy.types.WindowManager.blenderkit_HDR = PointerProperty(
        type=BlenderKitHDRSearchProps
    )
    bpy.types.Image.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitHDRUploadProps
    )

    # MATERIALS
    bpy.types.WindowManager.blenderkit_mat = PointerProperty(
        type=BlenderKitMaterialSearchProps
    )
    bpy.types.Material.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitMaterialUploadProps
    )

    # BRUSHES
    bpy.types.WindowManager.blenderkit_brush = PointerProperty(
        type=BlenderKitBrushSearchProps
    )
    bpy.types.Brush.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitBrushUploadProps
    )

    # NodeGroups
    bpy.types.WindowManager.blenderkit_nodegroup = PointerProperty(
        type=BlenderKitGeoToolSearchProps
    )
    bpy.types.NodeGroup.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitNodeGroupUploadProps
    )
    bpy.types.NodeTree.blenderkit = PointerProperty(  # for uploads, not now...
        type=BlenderKitNodeGroupUploadProps
    )
    bpy.types.WindowManager.blenderkit_addon = PointerProperty(
        type=BlenderKitAddonSearchProps
    )
    bpy.types.WindowManager.blenderkit_author = PointerProperty(
        type=BlenderKitAuthorSearchProps
    )
    if bpy.app.factory_startup is False:
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        global_vars.PREFS = utils.get_preferences_as_dict()
        paths.ensure_asset_library_path(user_preferences.global_dir)
        client_lib.reorder_ports(user_preferences.client_port)
        timer.update_trusted_CA_certs(user_preferences.trusted_ca_certs)

    search.register_search()
    asset_inspector.register_asset_inspector()
    download.register_download()
    upload.register_upload()
    ratings.register_ratings()
    autothumb.register_thumbnailer()
    ui.register_ui()
    icons.register_icons()
    ui_panels.register_ui_panels()
    bg_blender.register()
    overrides.register_overrides()
    bkit_oauth.register()
    tasks_queue.register()
    asset_bar_op.register()
    asset_drag_op.register()
    disclaimer_op.register()
    warning_dialog.register()
    timer.register_timers()

    bpy.app.handlers.load_post.append(scene_load)
    # detect if the user just enabled the addon in preferences, thus enable to run
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "PREFERENCES":
                # DISABLED because causes crashes in Blender 4.1
                # TODO: investigate
                # tasks_queue.add_task(
                #    (bpy.ops.wm.blenderkit_welcome, ("INVOKE_DEFAULT",)),
                #    fake_context=True,
                #    fake_context_area="PREFERENCES",
                #    wait=1,
                # )

                # save preferences after manually enabling the addon
                tasks_queue.add_task(
                    (bpy.ops.wm.save_userpref, ()),
                    fake_context=False,
                )
    # extension draw overrides, only in new versions and not in background mode
    if bpy.app.version >= (4, 2, 0) and bpy.app.background is False:
        override_extension_draw.register()
        override_extension_draw.ensure_repository(api_key=user_preferences.api_key)


def unregister():
    bk_logger.info("Unregistering Blendkit add-on")
    # Stop any in-flight downloads to avoid leaving stale UI state when disabling the add-on.
    download.cancel_running_downloads("addon unregister")
    timer.unregister_timers()
    ui_panels.unregister_ui_panels()
    ui.unregister_ui()
    icons.unregister_icons()
    search.unregister_search()
    asset_inspector.unregister_asset_inspector()
    download.unregister_download()
    upload.unregister_upload()
    ratings.unregister_ratings()
    autothumb.unregister_thumbnailer()
    bg_blender.unregister()
    overrides.unregister_overrides()
    bkit_oauth.unregister()
    tasks_queue.unregister()
    asset_bar_op.unregister()
    asset_drag_op.unregister()
    disclaimer_op.unregister()
    warning_dialog.unregister()

    if bpy.app.background is False:
        try:
            client_thread.stop()
        except Exception as e:
            bk_logger.error(e)
        try:
            client_lib.unsubscribe_addon()
            bk_logger.info("Reported Blender quit to Client.")
        except Exception as e:
            bk_logger.error(e)

    del bpy.types.WindowManager.blenderkitUI
    del bpy.types.WindowManager.blenderkit_models
    del bpy.types.WindowManager.blenderkit_scene
    del bpy.types.WindowManager.blenderkit_HDR
    del bpy.types.WindowManager.blenderkit_brush
    del bpy.types.WindowManager.blenderkit_mat
    del bpy.types.WindowManager.blenderkit_nodegroup
    del bpy.types.WindowManager.blenderkit_addon
    del bpy.types.WindowManager.blenderkit_author

    del bpy.types.Scene.blenderkit
    del bpy.types.Object.blenderkit
    del bpy.types.Image.blenderkit
    del bpy.types.Material.blenderkit
    del bpy.types.Brush.blenderkit

    for cls in classes:
        bpy.utils.unregister_class(cls)

    addon_updater_ops.unregister()

    bpy.utils.unregister_class(BlenderKitAddonPreferences)
    bpy.utils.unregister_class(BlenderKitThumbnailSettings)

    bpy.app.handlers.load_post.remove(scene_load)

    # extension draw overrides, only in new versions and not in background mode
    if bpy.app.version >= (4, 2, 0) and bpy.app.background is False:
        override_extension_draw.unregister()
