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
import logging
import math
import os
import random
from typing import Any, Optional, Set, Tuple, Union

import bpy
import mathutils
from bpy.props import IntProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from .. import (
    bg_blender,
    client_lib,
    colors,
    download,
    global_vars,
    image_utils,
    paths,
    reports,
    search,
    ui,
    ui_bgl,
    ui_panels,
    utils,
    viewport_utils,
)
from ..bl_ui_widgets.bl_ui_button import BL_UI_Button
from ..bl_ui_widgets.bl_ui_drag_panel import BL_UI_Drag_Panel
from ..bl_ui_widgets.bl_ui_draw_op import BL_UI_OT_draw_operator
from ..bl_ui_widgets.bl_ui_image import BL_UI_Image

bk_logger = logging.getLogger(__name__)

# Addon root package name. We live in <addon>.asset_bar, but addon
# preferences are registered under the top-level addon package.
_ADDON_PACKAGE = __package__.rsplit(".", 1)[0]

handler_2d = None
handler_3d = None

# Cached proxor data for download progress drawing (raw Python dicts, no GPU).
# Keyed by assetBaseId → proxor dict or None if unavailable.
_download_proxor_cache: dict[str, Optional[dict]] = {}
_MISSING = object()  # sentinel for cache miss (distinct from cached None)


DEFAULT_DRAG_THRESHOLD = 30  # pixels
"""Pointer travel in pixels needed before we start rendering full drag hints."""


def is_draw_cb_available(self: bpy.types.Operator, context: bpy.types.Context) -> bool:
    """Check if drawing callbacks can be added safely.

    Be defensive: accessing attributes on a destroyed Operator raises ReferenceError.
    We avoid hasattr and use getattr in a try/except to prevent log spam.

    Args:
        self: The operator instance.
        context: Blender context.

    Returns:
        True if drawing callbacks can be added, False otherwise.
    """
    try:
        if self is None:
            return False
        if self.active_region_pointer is None:
            return False
    except ReferenceError:
        # The operator RNA is gone; skip drawing quietly
        bk_logger.exception("Operator RNA is gone; skipping drawing callback.")
        return False
    except Exception:
        return False

    if context.region.as_pointer() != self.active_region_pointer:
        return False

    return True


def draw_callback_dragging(
    self: bpy.types.Operator, context: bpy.types.Context
) -> None:
    """Draw drag & drop hints while dragging an asset.

    Args:
        self: The operator instance.
        context: Blender context.

    Returns:
        None
    """

    if not self.drag:
        return

    # Only draw 2D elements in the active region where the mouse is. Guard against destroyed operator.
    if not is_draw_cb_available(self, context):
        return

    try:
        ## optimized
        if hasattr(self, "_faux_img") and self._faux_img is not None:
            img = self._faux_img
        else:
            # load mini thumbnail of a file and store in the previews collection
            directory = paths.get_temp_dir(f"{self.asset_data['assetType']}_search")
            thumbnail_path = os.path.join(directory, self.asset_data["thumbnail_small"])
            img = self._faux_img = image_utils.IMG(
                name=self.iname, filepath=thumbnail_path
            )
    except Exception:
        bk_logger.exception("Error loading image while drawing:")
        return

    invalid_drop = False

    line_length = 35
    ui_props = bpy.context.window_manager.blenderkitUI

    line_color = colors.WHITE

    # Determine hint message and colors based on context
    main_message = ""
    main_color = (0.9, 0.9, 0.9, 1.0)  # Default white
    secondary_message = ""
    secondary_color = (0.7, 0.7, 0.7, 1.0)  # Default gray

    # Base text position
    text_x = self.mouse_x
    text_y_main = self.mouse_y - line_length - 20 - ui_props.thumb_size
    text_y_secondary = self.mouse_y - line_length - 40 - ui_props.thumb_size

    # Determine messages based on area type and asset type
    asset_type = self.asset_data["assetType"]
    asset_node_type = self.asset_data["dictParameters"].get("nodeType")
    if context.area.type == "VIEW_3D":
        if asset_type == "material":
            if asset_node_type == "shader":
                main_message = "Drop to replace active material"
            else:
                main_message = "Drop to assign material"

        elif asset_type in ["model", "printable"]:
            if self.shift_pressed and self.object_name:
                main_message = f"Drop to Set Parent to ({self.object_name})"
            else:
                collection_name = (
                    context.view_layer.active_layer_collection.collection.name
                )
                if self.object_name:
                    main_message = f"Drop into active collection '{collection_name}'"

                    secondary_message = "(Shift to parent)"
                else:
                    main_message = f"Drop into collection '{collection_name}'"

        elif asset_type == "nodegroup":
            if asset_node_type == "geometry":
                if self.object_name is not None:
                    # Hovering over an object
                    target_object = bpy.data.objects.get(self.object_name)
                    if target_object and target_object.type in ["MESH", "CURVE"]:
                        main_message = "Drop to add geometry nodegroup"
                        secondary_message = f"(Add as modifier to {self.object_name})"
                    else:
                        main_message = f"Unsupported object type: {target_object.type if target_object else 'Unknown'}"
                        main_color = (1.0, 0.5, 0.5, 1.0)  # Error red
                        secondary_message = (
                            "Geometry nodes work with Mesh/Curve objects"
                        )
                        secondary_color = (0.8, 0.6, 0.6, 1.0)  # Light red
                        invalid_drop = True
                else:
                    main_message = "Drop to add geometry nodegroup"
                    # if active object is mesh/curve, mention modifier option
                    active_object = bpy.context.active_object
                    if active_object and active_object.type in ["MESH", "CURVE"]:
                        secondary_message = f"(Add as modifier to {active_object.name})"
            else:
                asset_node_type_display = asset_node_type or "nodegroup"
                main_message = f"Drop to add {asset_node_type_display} nodegroup"

        elif asset_type == "addon":
            main_message = "Drop to install addon"

        # If hovering over a particle-system instance source, materials,
        # nodegroups and models won't land here — explain why.
        if getattr(self, "over_particle_instance", False) and asset_type in (
            "material",
            "nodegroup",
            "model",
            "printable",
        ):
            main_message = "Can't drop on particle instance"
            secondary_message = "Drop onto the source object in the Outliner instead"
            main_color = (1.0, 0.5, 0.5, 1.0)  # Error red
            secondary_color = (0.8, 0.6, 0.6, 1.0)  # Light red
            invalid_drop = True

    elif self.in_node_editor:
        if asset_type not in ["material", "nodegroup"]:
            if asset_type == "addon":
                main_message = "Drop to install addon"
            else:
                main_message = "Cancel Drag & Drop"
                invalid_drop = True
        elif asset_type == "material" and self.node_editor_type == "shader":
            main_message = "Drop to replace active material"
        elif asset_type == "material" and self.node_editor_type == "compositing":
            main_message = "Cancel Drag & Drop"
            secondary_message = "Unsupported asset type for node editor type"
            invalid_drop = True
        elif asset_type == "nodegroup":
            if self.is_nodegroup_compatible_with_editor(
                asset_node_type, self.node_editor_type
            ):
                if asset_node_type == "geometry":
                    # For geometry nodes, show dialog option
                    active_object = bpy.context.active_object
                    if active_object and active_object.type in ["MESH", "CURVE"]:
                        main_message = "Drop to show options"
                        secondary_message = (
                            f"(Add as modifier or node to {active_object.name})"
                        )
                    else:
                        main_message = "Drop to add node group"
                        secondary_message = "Select mesh/curve for modifier option"
                        secondary_color = (0.9, 0.9, 0.6, 1.0)  # Soft highlight
                else:
                    # For other nodegroup types, just add as node
                    main_message = "Drop to add node group"
            else:
                will_switch = asset_node_type in {"shader", "geometry", "compositing"}
                if asset_node_type == "shader":
                    main_message = "Drop to switch to shader editor"
                    secondary_message = "Editor switches automatically"
                elif asset_node_type == "geometry":
                    active_object = bpy.context.active_object
                    if active_object and active_object.type in ["MESH", "CURVE"]:
                        main_message = "Drop to switch & show options"
                        secondary_message = f"Geometry nodes for {active_object.name}"
                    else:
                        main_message = "Drop to switch to geometry nodes editor"
                        secondary_message = (
                            "Editor will switch; mesh optional for modifier"
                        )
                        secondary_color = (0.9, 0.9, 0.6, 1.0)
                elif asset_node_type == "compositing":
                    main_message = "Drop to switch to compositing"
                    secondary_message = "Editor switches automatically"
                else:
                    main_message = "Drop to switch editor type"
                if not will_switch:
                    invalid_drop = True

    elif context.area.type not in ["VIEW_3D", "OUTLINER"]:
        main_message = "Cancel Drag & Drop"
        invalid_drop = True

    # Outliner specific hints
    # TODO: drop obs into collections if they are hovered, not their parent collection
    if context.area.type == "OUTLINER" and self.hovered_outliner_element:
        main_message = ""
        if isinstance(self.hovered_outliner_element, bpy.types.Object):
            if asset_type == "nodegroup":
                if asset_node_type != "geometry":
                    main_message = "Cancel Drag & Drop"
                    invalid_drop = True
                else:
                    # Hovering over an object
                    target_object = bpy.data.objects.get(
                        self.hovered_outliner_element.name
                    )
                    if target_object and target_object.type in ["MESH", "CURVE"]:
                        main_message = "Assign as modifier"
                        secondary_message = f"(Geometry nodes for {target_object.name})"
                    else:
                        main_message = f"Unsupported object type: {target_object.type if target_object else 'Unknown'}"
                        invalid_drop = True

            elif asset_type == "material":
                main_message = "Drop to replace active material"

            elif self.shift_pressed:
                main_message = "Drop to Set Parent"
            else:
                collection_name = ""
                if self.hovered_outliner_element.users_collection:
                    collection_name = self.hovered_outliner_element.users_collection[
                        0
                    ].name
                main_message = (
                    f"Drop into collection '{collection_name}' (Shift to parent)"
                )
        elif isinstance(self.hovered_outliner_element, bpy.types.Collection):
            main_message = (
                f"Drop into collection '{self.hovered_outliner_element.name}'"
            )

    transparency = 1.0
    line_color = colors.WHITE
    if invalid_drop:
        line_color = colors.RED
        transparency = 0.35

    ui_bgl.draw_image_runtime(
        self.mouse_x + line_length,
        self.mouse_y - line_length - ui_props.thumb_size,
        ui_props.thumb_size,
        ui_props.thumb_size,
        img,
        transparency=transparency,
    )
    ui_bgl.draw_line2d(
        self.mouse_x,
        self.mouse_y,
        self.mouse_x + line_length,
        self.mouse_y - line_length,
        2,
        line_color,
    )

    if invalid_drop:
        # red border
        ui_bgl.draw_rect_outline(
            self.mouse_x + line_length,
            self.mouse_y - line_length - ui_props.thumb_size,
            ui_props.thumb_size,
            ui_props.thumb_size,
            line_color,
        )
        # simple red line over the thumbnail (bottom left to top right)
        ui_bgl.draw_line2d(
            self.mouse_x + line_length,
            self.mouse_y - line_length - ui_props.thumb_size,
            self.mouse_x + line_length + ui_props.thumb_size,
            self.mouse_y - line_length,
            2,
            line_color,
        )

    # Draw the text messages if we have any
    if main_message:
        ui_bgl.draw_text(main_message, text_x, text_y_main, 16, main_color)

    if secondary_message:
        ui_bgl.draw_text(
            secondary_message, text_x, text_y_secondary, 14, secondary_color
        )


def draw_callback_3d_dragging(
    self: bpy.types.Operator, context: bpy.types.Context
) -> None:
    """Draw snapped bbox while dragging."""
    if not utils.guard_from_crash():
        return

    # ignore unless we are dragging
    if not self.drag:
        return

    # Only draw 3D elements in VIEW_3D areas, not in outliner
    if context.area.type != "VIEW_3D":
        return

    # Check if operator is still valid before accessing its attributes
    if not is_draw_cb_available(self, context):
        return

    # Check if all required attributes are available
    required_attrs = [
        "has_hit",
        "snapped_location",
        "snapped_rotation",
        "snapped_bbox_min",
        "snapped_bbox_max",
        "asset_data",
    ]

    for attr in required_attrs:
        if not hasattr(self, attr):
            return

    # Only continue if we have a hit in a 3D view
    if not self.has_hit:
        return

    if self.asset_data["assetType"] in ["model", "printable"]:
        if self._proxor_handler is not None:
            # Update proxor transform to match snapped placement
            rot_euler = mathutils.Euler(self.snapped_rotation)
            loc = Vector(self.snapped_location)
            mat = mathutils.Matrix.Translation(loc) @ rot_euler.to_matrix().to_4x4()
            self._proxor_handler._matrix = mat
        else:
            draw_bbox(
                self.snapped_location,
                self.snapped_rotation,
                self.snapped_bbox_min,
                self.snapped_bbox_max,
            )


def _load_proxor_for_download(asset_base_id: str) -> Optional[dict]:
    """Load and cache proxor data for download progress drawing.

    Returns the raw ``data`` dict from the .prxc file, or ``None`` if
    unavailable.  Results are cached in ``_download_proxor_cache``; a
    cached ``None`` is invalidated if the ``.prxc`` file appears on
    disk later (common with on-demand fetch scheduled at drag start).
    """
    prxc_path = global_vars.DATA.get("prxc available", {}).get(asset_base_id)
    cached = _download_proxor_cache.get(asset_base_id, _MISSING)
    if cached is not _MISSING:
        if cached is not None:
            return cached
        # Previously unavailable — recheck in case the on-demand fetch
        # finished after the first miss.
        if not prxc_path or not os.path.exists(prxc_path):
            return None

    if not prxc_path or not os.path.exists(prxc_path):
        _download_proxor_cache[asset_base_id] = None
        return None

    try:
        from ..bk_proxor import prx_format as proxor_prx_format

        payload = proxor_prx_format.read_prx(prxc_path)
        proxor_data = payload.get("data")
        if not proxor_data:
            _download_proxor_cache[asset_base_id] = None
            return None

        _download_proxor_cache[asset_base_id] = proxor_data
        return proxor_data
    except Exception:
        bk_logger.debug(f"Failed to load proxor for download: {asset_base_id}")
        _download_proxor_cache[asset_base_id] = None
        return None


def draw_proxor_download(
    location: Vector,
    rotation: Vector,
    proxor_data: dict,
    progress: Optional[float] = None,
    color: Tuple[float, float, float, float] = colors.PURE_GREEN,
) -> None:
    """Draw full proxor (mesh, lines, points) during download."""
    ui_bgl.draw_proxor_download(location, rotation, proxor_data, progress, color)


def draw_bbox(
    location: Vector,
    rotation: Vector,
    bbox_min: Vector,
    bbox_max: Vector,
    progress: Optional[float] = None,
    color: Tuple[float, float, float, float] = colors.PURE_GREEN,
) -> None:
    """Draw a 3D wireframe bounding box."""
    ui_bgl.draw_bbox(location, rotation, bbox_min, bbox_max, progress, color)


def draw_callback_2d_progress(
    self: bpy.types.Operator, context: bpy.types.Context
) -> None:
    if not utils.guard_from_crash():
        return
    ui = bpy.context.window_manager.blenderkitUI

    x = ui.reports_x
    y = ui.reports_y
    index = 0
    for key, task in download.download_tasks.items():
        asset_data = task["asset_data"]
        if not task.get("downloaders"):
            draw_progress(
                x,
                y - index * 30,
                text=f"downloading {asset_data['name']}",
                percent=task["progress"],
            )
            index += 1

    for process in bg_blender.bg_processes:
        tcom = process[1]
        n = ""
        if tcom.name is not None:
            n = tcom.name + ": "
        draw_progress(x, y - index * 30, f"{n}{tcom.lasttext}", tcom.progress)
        index += 1
    for report in reports.reports:
        lines = report.draw(x, y - index * 30)
        index += lines if lines else 1
        report.fade()


def draw_callback_3d_progress(
    self: bpy.types.Operator, context: bpy.types.Context
) -> None:
    # 'star trek' mode is here

    if not utils.guard_from_crash():
        return
    for key, task in download.download_tasks.items():
        asset_data = task["asset_data"]
        if task.get("downloaders"):
            for d in task["downloaders"]:
                if asset_data["assetType"] in ["model", "printable"]:
                    asset_base_id = asset_data.get("assetBaseId", "")
                    proxor_data = (
                        _load_proxor_for_download(asset_base_id)
                        if utils.proxor_enabled()
                        else None
                    )
                    if proxor_data is not None:
                        draw_proxor_download(
                            d["location"],
                            d["rotation"],
                            proxor_data,
                            progress=task["progress"],
                        )
                    else:
                        draw_bbox(
                            d["location"],
                            d["rotation"],
                            asset_data["bbox_min"],
                            asset_data["bbox_max"],
                            progress=task["progress"],
                        )


def draw_progress(
    x: int,
    y: int,
    text: str = "",
    percent: float = 0.0,
    color: Tuple[float, float, float, float] = colors.GREEN,
):
    ui_bgl.draw_rect(x, y, percent, 5, color)
    ui_bgl.draw_text(text, x, y + 8, 16, color)


def mouse_raycast(
    region: bpy.types.Region, rv3d: bpy.types.RegionView3D, mx: int, my: int
) -> Tuple[
    bool,
    Vector,
    Vector,
    Vector,
    Optional[int],
    Optional[bpy.types.Object],
    Optional[mathutils.Matrix],
    Optional[bpy.types.Object],
]:
    coord = mx, my

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    if rv3d.view_perspective == "CAMERA" and rv3d.is_perspective == False:
        #  orthographic cameras don't work with region_2d_to_origin_3d
        view_position = rv3d.view_matrix.inverted().translation
        ray_origin = view3d_utils.region_2d_to_location_3d(
            region, rv3d, coord, depth_location=view_position
        )
    else:
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord, clamp=1.0)

    ray_target = ray_origin + (view_vector * 1000000000)

    vec = ray_target - ray_origin

    (
        has_hit,
        snapped_location,
        snapped_normal,
        face_index,
        obj,
        matrix,
        raw_first_obj,
    ) = deep_ray_cast(ray_origin, vec)

    # backface snapping inversion
    if view_vector.angle(snapped_normal) < math.pi / 2:
        snapped_normal = -snapped_normal

    random_offset = math.pi
    if has_hit:
        props = bpy.context.window_manager.blenderkit_models
        up = Vector((0, 0, 1))

        if props.perpendicular_snap:
            if snapped_normal.z > 1 - props.perpendicular_snap_threshold:
                snapped_normal = Vector((0, 0, 1))
            elif snapped_normal.z < -1 + props.perpendicular_snap_threshold:
                snapped_normal = Vector((0, 0, -1))
            elif abs(snapped_normal.z) < props.perpendicular_snap_threshold:
                snapped_normal.z = 0
                snapped_normal.normalize()

        snapped_rotation = snapped_normal.to_track_quat("Z", "Y").to_euler()

        if snapped_normal.angle(up) < math.radians(10.0):
            # near-flat, up-facing surface: match the scene floor behavior,
            # which applies a 180° flip so the model faces the same way.
            random_offset = props.offset_rotation_amount + math.pi
            if props.randomize_rotation:
                random_offset += (
                    random.random() - 0.5
                ) * props.randomize_rotation_amount
        else:
            random_offset = (
                props.offset_rotation_amount
            )  # we don't rotate this way on walls and ceilings.

    else:
        snapped_rotation = mathutils.Quaternion((0, 0, 0, 0)).to_euler()

    snapped_rotation.rotate_axis("Z", random_offset)

    return (
        has_hit,
        snapped_location,
        snapped_normal,
        snapped_rotation,
        face_index,
        obj,
        matrix,
        raw_first_obj,
    )


def floor_raycast(
    r: bpy.types.Region, rv3d: bpy.types.RegionView3D, mx: int, my: int
) -> Tuple[
    bool,
    Vector,
    Vector,
    Vector,
    Optional[int],
    Optional[bpy.types.Object],
    Optional[mathutils.Matrix],
]:
    coord = mx, my

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(r, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(r, rv3d, coord)
    ray_target = ray_origin + (view_vector * 1000)

    # various intersection plane normals are needed for corner cases that might actually happen quite often - in front and side view.
    # default plane normal is scene floor.
    plane_normal = (0, 0, 1)
    if math.isclose(view_vector.x, 0, abs_tol=1e-4) and math.isclose(
        view_vector.z, 0, abs_tol=1e-4
    ):
        plane_normal = (0, 1, 0)
    elif math.isclose(view_vector.z, 0, abs_tol=1e-4):
        plane_normal = (1, 0, 0)

    snapped_location = mathutils.geometry.intersect_line_plane(
        ray_origin, ray_target, (0, 0, 0), plane_normal, False
    )
    has_hit = False
    snapped_normal = Vector((0, 0, 1))
    snapped_rotation = Vector((0, 0, 0))
    face_index = None
    out_object = None
    matrix = None
    if snapped_location is not None:
        has_hit = True
        snapped_normal = Vector((0, 0, 1))
        face_index = None
        out_object = None
        matrix = None
        snapped_rotation = snapped_normal.to_track_quat("Z", "Y").to_euler()
        props = bpy.context.window_manager.blenderkit_models
        if props.randomize_rotation:
            random_offset = (
                props.offset_rotation_amount
                + math.pi
                + (random.random() - 0.5) * props.randomize_rotation_amount
            )
        else:
            random_offset = props.offset_rotation_amount + math.pi
        snapped_rotation.rotate_axis("Z", random_offset)

    return (
        has_hit,
        snapped_location,
        snapped_normal,
        snapped_rotation,
        face_index,
        out_object,
        matrix,
    )


def deep_ray_cast(ray_origin: Vector, vec: Vector) -> Tuple[
    bool,
    Vector,
    Vector,
    Optional[int],
    Optional[bpy.types.Object],
    Optional[mathutils.Matrix],
    Optional[bpy.types.Object],
]:
    # this allows to ignore some objects, like objects with bounding box draw style or particle objects
    obj = None
    # while object is None or object.draw
    depsgraph = bpy.context.view_layer.depsgraph
    (
        has_hit,
        snapped_location,
        snapped_normal,
        face_index,
        obj,
        matrix,
    ) = bpy.context.scene.ray_cast(depsgraph, ray_origin, vec)
    # The raw (unfiltered) first hit is returned so the caller can detect
    # hovering over a particle-system instance without a second scene ray_cast.
    raw_first_obj = obj
    empty_set = (
        False,
        Vector((0, 0, 0)),
        Vector((0, 0, 1)),
        None,
        None,
        None,
        raw_first_obj,
    )
    if not obj:
        return empty_set
    try_object = obj
    while try_object and (
        try_object.display_type == "BOUNDS"
        or object_in_particle_collection(try_object)
        or not try_object.visible_get(viewport=bpy.context.space_data)
    ):
        ray_origin = snapped_location + vec.normalized() * 0.0003
        (
            try_has_hit,
            try_snapped_location,
            try_snapped_normal,
            try_face_index,
            try_object,
            try_matrix,
        ) = bpy.context.scene.ray_cast(depsgraph, ray_origin, vec)
        if try_has_hit:
            # this way only good hits are returned, otherwise
            has_hit, snapped_location, snapped_normal, face_index, obj, matrix = (
                try_has_hit,
                try_snapped_location,
                try_snapped_normal,
                try_face_index,
                try_object,
                try_matrix,
            )
    if try_object is None:
        return empty_set
    if not (obj.display_type == "BOUNDS" or object_in_particle_collection(try_object)):
        return (
            has_hit,
            snapped_location,
            snapped_normal,
            face_index,
            obj,
            matrix,
            raw_first_obj,
        )
    return empty_set


def object_in_particle_collection(o: Optional[bpy.types.Object]) -> bool:
    """checks if an object is in a particle system as instance, to not snap to it and not to try to attach material."""
    if o is None:
        return False
    for p in bpy.data.particles:
        if p.render_type == "COLLECTION" and p.instance_collection:
            if o.name in p.instance_collection.objects:
                return True
        if p.render_type == "OBJECT":
            if p.instance_object == o:
                return True
    return False


def get_node_tree(context: bpy.types.Context) -> bpy.types.NodeTree:
    """Blender version invariant way to get the node tree from the current node editor."""
    if bpy.app.version < (5, 0, 0):
        if context.scene.use_nodes and context.scene.node_tree:
            node_tree = context.scene.node_tree
        else:
            # Enable compositor nodes if not already enabled
            context.scene.use_nodes = True
            node_tree = context.scene.node_tree
        return node_tree

    # blender 5.0+
    # FUTURE check if valid in 5.RC
    if not context.scene.compositing_node_group:
        bpy.ops.node.new_compositing_node_group()
        context.scene.compositing_node_group = bpy.data.node_groups[-1]

        return context.scene.compositing_node_group

    return context.scene.compositing_node_group


def _make_drag_status_fn(asset_type: str):
    """Build a status-bar draw function shown in Blender's status bar during drag-drop."""
    show_rotation = asset_type in ("model", "printable")

    def _draw(header, context):
        layout = header.layout
        layout.label(text="Blendkit Drag-Drop")

        layout.label(text="Place", icon="MOUSE_LMB")
        layout.label(text="Cancel", icon="MOUSE_RMB")

        if show_rotation:
            layout.label(text="Rotate 10°", icon="MOUSE_MMB")
            layout.label(text="1°", icon="EVENT_SHIFT")
            layout.label(text="Snap 90°", icon="EVENT_CTRL")

        layout.separator_spacer()

    return _draw


class AssetDragOperator(bpy.types.Operator):
    """Drag & drop assets into scene. Operator being drawn when dragging asset."""

    bl_idname = "view3d.asset_drag_drop"
    bl_label = "Blendkit asset drag drop"

    asset_search_index: IntProperty(name="Active Index", default=0)  # type: ignore

    object_name = None
    active_operator_id = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # predefine all attributes to avoid dynamic creation during draw calls
        self.asset_data = {}
        self.active_region_pointer = None

        self._handle_3d = None
        self._handlers_universal = {}

        self.hovered_outliner_element: Union[bpy.types.Object, bpy.types.Collection] = (
            None
        )
        self.active_window = None
        self.active_area = None
        self.active_region = None

        self.orig_active_object = None
        self.orig_selected_objects = None
        self.orig_active_collection = None

        self.downloader = None

        # Mouse tracking variables
        self.start_mouse_x = 0
        self.start_mouse_y = 0

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_screen_x = 0
        self.mouse_screen_y = 0

        # Initialize outliner tracking variables
        self.outliner_area = None
        self.outliner_region = None
        self.prev_area_type = None

        # Initialize node editor tracking
        self.in_node_editor = False
        self.node_editor_type = None

        self.shift_pressed = False

        # Initialize has_hit to False, and set other 3D properties
        # We'll only use these in 3D views, not in outliner
        self.has_hit = False
        self.snapped_location = (0, 0, 0)
        self.snapped_normal = (0, 0, 1)
        self.snapped_rotation = (0, 0, 0)
        self.face_index = 0
        self.matrix = None

        self.iname = ""
        self.drag = False
        self.steps = 0
        self.closed_assetbar = False

        # Set when the cursor is over an object that is excluded from drag
        # snapping because it is used as a particle-system instance. Used by
        # draw_callback_dragging to explain to the user why a material/model
        # can't be dropped on that object in the 3D view.
        self.over_particle_instance = False

        # Proxor draw handler for proxy mesh preview during drag
        self._proxor_handler = None
        # assetBaseId of a .prxc download kicked off at drag start but not
        # yet available on disk. Polled in modal() and swapped in when
        # the file lands in global_vars.DATA["prxc available"].
        self._proxor_pending: Optional[str] = None

    def handlers_remove(self) -> None:
        """Remove all draw handlers."""
        if self._proxor_handler is not None:
            self._proxor_handler.remove()
            self._proxor_handler = None
        self._proxor_pending = None
        # Remove specific handlers for VIEW_3D and Outliner
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")

        # Remove handlers for all other space types
        for space_type, handler in self._handlers_universal.items():
            if handler:
                getattr(bpy.types, space_type).draw_handler_remove(handler, "WINDOW")

    def _install_proxor_handler_from_path(
        self, asset_base_id: str, prxc_path: str
    ) -> None:
        """Build and install a :class:`ProxorLiteDrawHandler` from *prxc_path*.

        On any failure the handler is torn down and ``self._proxor_handler``
        is reset to ``None`` so the drag falls back to the green bbox.
        """
        try:
            from ..bk_proxor import prx_format as proxor_prx_format
            from ..bk_proxor._blender.draw import (
                ProxorLiteDrawHandler,
                default_draw_context,
            )

            payload = proxor_prx_format.read_prx(prxc_path)
            proxor_data = payload.get("data")
            if not proxor_data:
                return

            self._proxor_handler = ProxorLiteDrawHandler()
            self._proxor_handler.draw_ctx = default_draw_context(
                mesh_color_mode="CUSTOM",
                custom_color=colors.PURE_GREEN,
                mesh_shading_mode="FLAT",
                use_gradient=True,
                point_visibility=0.0,
                line_thickness=0.0,
            )
            self._proxor_handler.set_payload(proxor_data)
            self._proxor_handler.install()
            bk_logger.debug(f"Proxor preview loaded for {asset_base_id}")
        except Exception as e:
            bk_logger.warning(f"Failed to load proxor preview: {e}")
            # Ensure a partially-initialized handler is torn down
            # (e.g. install() raised after set_payload() cached batches).
            if self._proxor_handler is not None:
                try:
                    self._proxor_handler.remove()
                except Exception:
                    pass
            self._proxor_handler = None

    def _start_proxor_fetch(self, asset_base_id: str) -> None:
        """Fire a single on-demand ``.prxc`` download for *asset_base_id*.

        No-op if the asset has no ``.prxc`` URL. The download completes
        asynchronously; :meth:`_poll_proxor_pending` swaps the handler in
        once the file lands.
        """
        if not asset_base_id:
            return
        prxc_url = ""
        for f in self.asset_data.get("files", []) or []:
            if f.get("fileType") == "prxc" and f.get("downloadUrl"):
                prxc_url = f["downloadUrl"]
                break
        if not prxc_url:
            return
        try:
            asset_type = self.asset_data.get("assetType", "model")
            tempdir = paths.get_temp_dir(f"{asset_type}_search")
            file_path = os.path.join(tempdir, f"{asset_base_id}.prxc")
            scene_uuid = utils.get_scene_id()
            client_lib.asset_prxc_download(
                asset_base_id, prxc_url, file_path, scene_uuid
            )
            self._proxor_pending = asset_base_id
        except Exception as e:
            bk_logger.debug(f"prxc on-demand fetch not scheduled: {e}")
            self._proxor_pending = None

    def _poll_proxor_pending(self) -> None:
        """Swap to proxor mid-drag once the pending ``.prxc`` lands."""
        if self._proxor_pending is None or self._proxor_handler is not None:
            return
        asset_base_id = self._proxor_pending
        prxc_path = global_vars.DATA.get("prxc available", {}).get(asset_base_id)
        if prxc_path and os.path.exists(prxc_path):
            self._install_proxor_handler_from_path(asset_base_id, prxc_path)
            self._proxor_pending = None

    def is_nodegroup_compatible_with_editor(
        self, nodegroup_type: str, editor_type: Optional[str] = None
    ) -> bool:
        """Check if a nodegroup of a specific type is compatible with the given editor type."""
        # Direct matches, or invalid editor
        if not nodegroup_type or nodegroup_type == editor_type:
            return True
        # Otherwise, not compatible
        return False

    def handle_view3d_drop(self, context: bpy.types.Context) -> None:
        """Handle dropping assets in the 3D view."""
        scene = context.scene
        if self.asset_data["assetType"] in ["model", "printable"]:
            if not self.drag:
                self.snapped_location = scene.cursor.location
                self.snapped_rotation = (0, 0, 0)

            parent = ""
            target_collection = ""

            if self.object_name is not None and self.shift_pressed:
                parent = self.object_name

            # If parent is set, put asset in parent's collection. Otherwise, active collection.
            if parent:
                parent_obj = bpy.data.objects.get(parent)
                if parent_obj and parent_obj.users_collection:
                    target_collection = parent_obj.users_collection[0].name
            else:
                target_collection = (
                    context.view_layer.active_layer_collection.collection.name
                )

            if "particle_plants" in self.asset_data["tags"]:
                bpy.ops.object.blenderkit_particles_drop(
                    "INVOKE_DEFAULT",
                    asset_search_index=self.asset_search_index,
                    model_location=self.snapped_location,
                    model_rotation=self.snapped_rotation,
                    target_object=self.object_name or "",
                )
            else:
                # TODO: after we drop the support for B3.0, B3.1, we can update all the download operators called from the drag drop operator to use
                # context.temp_override(), so the download is triggered in the area/window where it was dropped
                bpy.ops.scene.blenderkit_download(
                    "EXEC_DEFAULT",
                    asset_index=self.asset_search_index,
                    model_location=self.snapped_location,
                    model_rotation=self.snapped_rotation,
                    parent=parent,
                    target_collection=target_collection,
                )

        if self.asset_data["assetType"] == "material":
            obj = None
            target_object = ""
            target_slot = ""
            if not self.drag:
                # click interaction
                obj = context.active_object
                if obj is None:
                    ui_panels.ui_message(
                        title="Nothing selected",
                        message="Select something to assign materials by clicking.",
                    )
                    return
                target_object = obj.name
                target_slot = obj.active_material_index
                self.snapped_location = obj.location
            elif self.object_name is not None and self.has_hit:
                # first, test if object can have material applied.
                obj = bpy.data.objects[self.object_name]
                # this enables to run Bring to scene automatically when dropping on a linked objects.
                if (
                    obj is not None
                    and not obj.is_library_indirect
                    and obj.type in utils.supported_material_drag
                ):
                    target_object = obj.name
                    # create final mesh to extract correct material slot
                    depsgraph = context.evaluated_depsgraph_get()
                    object_eval = obj.evaluated_get(depsgraph)

                    if obj.type == "MESH":
                        temp_mesh = object_eval.to_mesh()
                        _mapping = create_material_mapping(obj, temp_mesh)
                        target_slot = temp_mesh.polygons[self.face_index].material_index
                        object_eval.to_mesh_clear()
                    else:
                        self.snapped_location = obj.location
                        target_slot = obj.active_material_index
            if not obj:
                return
            if obj.is_library_indirect:
                ui_panels.ui_message(
                    title="This object is linked from outer file",
                    message="Please select the model,"
                    "go to the 'Selected Model' panel "
                    "in Blendkit and hit 'Bring to Scene' first.",
                )
                return
            if obj.type not in utils.supported_material_drag:
                if obj.type in utils.supported_material_click:
                    ui_panels.ui_message(
                        title="Unsupported object type",
                        message=f"Use click interaction for {obj.type.lower()} object.",
                    )
                    return

                ui_panels.ui_message(
                    title="Unsupported object type",
                    message=f"Can't assign materials to {obj.type.lower()} object.",
                )
                return

            if target_object != "":
                # position is for downloader:
                loc = self.snapped_location
                rotation = (0, 0, 0)

                utils.automap(
                    target_object,
                    target_slot=target_slot,
                    tex_size=self.asset_data.get("texture_size_meters", 1.0),
                )
                bpy.ops.scene.blenderkit_download(
                    "EXEC_DEFAULT",
                    asset_index=self.asset_search_index,
                    model_location=loc,
                    model_rotation=rotation,
                    target_object=target_object,
                    material_target_slot=target_slot,
                )

        if self.asset_data["assetType"] == "nodegroup":
            # Handle nodegroup drop in 3D view
            nodegroup_type = self.asset_data["dictParameters"].get("nodeType")

            # Only handle geometry nodegroups for now
            if nodegroup_type == "geometry":
                target_object_name = ""
                target_location = self.snapped_location
                target_rotation = self.snapped_rotation

                if not self.drag:
                    # Click interaction - use active object like materials do
                    active_object = context.active_object
                    if active_object and active_object.type in ["MESH", "CURVE"]:
                        target_object_name = active_object.name
                        target_location = active_object.location
                        target_rotation = (0, 0, 0)
                elif self.object_name is not None and self.has_hit:
                    # Drag interaction - use object under mouse
                    target_object = bpy.data.objects.get(self.object_name)
                    if target_object and target_object.type in ["MESH", "CURVE"]:
                        target_object_name = self.object_name

                # Show dialog for geometry nodegroups
                # modify default if not target_object_name is set
                if target_object_name:
                    bpy.ops.wm.blenderkit_nodegroup_drop_dialog(
                        "INVOKE_DEFAULT",
                        asset_search_index=self.asset_search_index,
                        target_object_name=target_object_name,
                        snapped_location=target_location,
                        snapped_rotation=target_rotation,
                    )
                else:
                    bpy.ops.wm.blenderkit_nodegroup_drop_dialog(
                        "INVOKE_DEFAULT",
                        asset_search_index=self.asset_search_index,
                        target_object_name=target_object_name,
                        add_mode="NODE",
                        snapped_location=target_location,
                        snapped_rotation=target_rotation,
                    )
            else:
                # For non-geometry nodegroups, use regular download
                bpy.ops.scene.blenderkit_download(
                    "EXEC_DEFAULT",
                    asset_index=self.asset_search_index,
                    model_location=self.snapped_location,
                    model_rotation=self.snapped_rotation,
                )

        if self.asset_data["assetType"] in ["material", "model"]:
            bpy.ops.view3d.blenderkit_download_gizmo_widget(
                "INVOKE_REGION_WIN",
                asset_base_id=self.asset_data["assetBaseId"],
            )

    def handle_outliner_drop(self, context: bpy.types.Context) -> None:
        """Handle dropping assets in the outliner."""
        asset_type = self.asset_data["assetType"]
        asset_node_type = self.asset_data.get("dictParameters", {}).get("nodeType")
        if asset_type in ["model", "printable"]:
            parent = ""
            target_collection = ""

            # Check what type of element we're dropping on
            _element_type = type(self.hovered_outliner_element).__name__

            # If dropping on a collection, set target_collection parameter
            if isinstance(self.hovered_outliner_element, bpy.types.Collection):
                target_collection = self.hovered_outliner_element.name
            # Otherwise if dropping on an object, place it in the same collection
            elif isinstance(self.hovered_outliner_element, bpy.types.Object):
                hovered_object = self.hovered_outliner_element
                if self.shift_pressed:
                    parent = hovered_object.name
                # even if we have parent, we also want the collection to be parented correctly
                if hovered_object.users_collection:
                    target_collection = hovered_object.users_collection[0].name
            else:
                # Unsupported element type - just continue with default values
                pass

            # Place the asset at the origin or at a default location
            self.snapped_location = (0, 0, 0)
            self.snapped_rotation = (0, 0, 0)

            # Download the asset with the target collection or parent
            bpy.ops.scene.blenderkit_download(
                "EXEC_DEFAULT",
                asset_index=self.asset_search_index,
                model_location=self.snapped_location,
                model_rotation=self.snapped_rotation,
                parent=parent,
                target_collection=target_collection,
            )

            # Restore original selection
            self.restore_original_selection()

        elif asset_type == "material":
            # If dropping a material on an object in the outliner
            target_object = self.hovered_outliner_element.name

            # Check if object supports materials, it can also be a collection
            if not (
                type(self.hovered_outliner_element) == bpy.types.Object
                and self.hovered_outliner_element.type in ["MESH", "CURVE"]
            ):
                reports.add_report(
                    "Can't assign materials to this outliner element.",
                    type="ERROR",
                )
                return

            # Use active material slot or create one
            target_slot = self.hovered_outliner_element.active_material_index

            # Position is for downloader
            loc = (0, 0, 0)
            rotation = (0, 0, 0)

            # Try to automap if it's a mesh
            if self.hovered_outliner_element.type == "MESH":
                utils.automap(
                    target_object,
                    target_slot=target_slot,
                    tex_size=self.asset_data.get("texture_size_meters", 1.0),
                )

            # Download the material
            bpy.ops.scene.blenderkit_download(
                "EXEC_DEFAULT",
                asset_index=self.asset_search_index,
                model_location=loc,
                model_rotation=rotation,
                target_object=target_object,
                material_target_slot=target_slot,
            )

            # Restore original selection
            self.restore_original_selection()

        elif asset_type == "nodegroup":
            if asset_node_type != "geometry":
                reports.add_report(
                    "Only geometry nodegroups can be dropped in the outliner.",
                    type="ERROR",
                )
                return
            target_object = self.hovered_outliner_element.name

            # Check if object supports materials, it can also be a collection
            if not (
                type(self.hovered_outliner_element) == bpy.types.Object
                and self.hovered_outliner_element.type in ["MESH", "CURVE"]
            ):
                reports.add_report(
                    "Can't assign geometry node group to this outliner element.",
                    type="ERROR",
                )
                return

            # call out wm operator
            bpy.ops.wm.blenderkit_nodegroup_drop_dialog(
                "INVOKE_DEFAULT",
                asset_search_index=self.asset_search_index,
                target_object_name=target_object,
                add_mode="MODIFIER",
            )

            # If we reach this point, the nodegroup is valid for dropping
            self.restore_original_selection()

        elif self.asset_data["assetType"] == "addon":
            # Handle addon drop in outliner - show management popup

            bpy.ops.scene.blenderkit_addon_choice(
                "INVOKE_DEFAULT", asset_data=json.dumps(self.asset_data)
            )
            # Restore original selection
            self.restore_original_selection()

    def make_node_editor_switch(
        self, nodegroup_type: str, node_editor_type: Optional[str] = None
    ) -> bool:
        """Make a node editor switch safely.

        Avoids raising if area or operator state is invalid. This prevents persistent
        draw exceptions when the operator RNA gets destroyed mid-drag.
        """
        try:
            node_types_to_node_editor_type = {
                "shader": "ShaderNodeTree",
                "geometry": "GeometryNodeTree",
                "compositing": "CompositorNodeTree",
            }
            node_editor_type = node_types_to_node_editor_type[nodegroup_type]
            if self.active_area:
                self.active_area.ui_type = node_editor_type
        except KeyError:
            # Be silent in production to avoid repeated errors during draw
            bk_logger.exception("make_node_editor_switch failed")
            return False

        return True

    def handle_node_editor_drop_material(self, context: bpy.types.Context) -> None:
        """Handle dropping materials in the node editor."""
        active_object = context.active_object

        if not active_object:
            # No active object, can't assign material
            reports.add_report("No active object to assign material to", type="ERROR")
            return

        if active_object.type not in utils.supported_material_drag:
            # Object type doesn't support materials
            reports.add_report(
                f"Can't assign materials to {active_object.type.lower()} object",
                type="ERROR",
            )
            return

        # Use active material slot or create one
        target_slot = active_object.active_material_index

        # Download the material
        bpy.ops.scene.blenderkit_download(
            "EXEC_DEFAULT",
            asset_index=self.asset_search_index,
            model_location=(0, 0, 0),
            model_rotation=(0, 0, 0),
            target_object=active_object.name,
            material_target_slot=target_slot,
        )
        return

    def handle_node_editor_drop(self, context: bpy.types.Context) -> None:
        """Handle dropping assets in the node editor."""
        # Check if asset type is compatible with the node editor
        if self.asset_data["assetType"] not in ["material", "nodegroup"]:
            reports.add_report(
                f"{self.asset_data['assetType'].capitalize()} assets cannot be used in node editors",
                type="ERROR",
            )
            return

        # Handle material drop in shader editor
        if (
            self.asset_data["assetType"] == "material"
            and self.node_editor_type == "shader"
        ):
            self.handle_node_editor_drop_material(context)
            return

        # Handle nodegroup drop
        if self.asset_data["assetType"] == "nodegroup":
            # Get the mouse position in the node editor
            nodegroup_type = self.asset_data["dictParameters"].get("nodeType")

            # Check if the nodegroup type is compatible with the current editor
            if not self.is_nodegroup_compatible_with_editor(
                nodegroup_type, self.node_editor_type
            ):
                has_switched = self.make_node_editor_switch(
                    nodegroup_type, self.node_editor_type
                )
                if not has_switched:
                    reports.add_report(
                        f"Nodegroup of type '{nodegroup_type}' cannot be used in {self.node_editor_type} editor",
                        type="ERROR",
                    )
                    return
            # Special handling for geometry nodegroups - show dialog if active object supports it
            if nodegroup_type == "geometry":
                active_object = context.active_object
                if active_object and active_object.type in ["MESH", "CURVE"]:
                    # Get node position for passing to dialog
                    node_pos = self.get_node_editor_cursor_position()

                    # Show dialog to choose how to add the geometry nodegroup
                    bpy.ops.wm.blenderkit_nodegroup_drop_dialog(
                        "INVOKE_DEFAULT",
                        asset_search_index=self.asset_search_index,
                        target_object_name=active_object.name,
                        snapped_location=(0, 0, 0),  # Not used for node editor
                        snapped_rotation=(0, 0, 0),  # Not used for node editor
                        node_x=node_pos[0],
                        node_y=node_pos[1],
                    )
                    return

                # No compatible object, just add as node
                reports.add_report(
                    "No compatible object selected, adding as node only",
                    type="INFO",
                )

                # Prepare geometry nodes editor (for when user chooses "As Node" or no object)
                if active_object and active_object.type in ["MESH", "CURVE"]:
                    # Check if there's a geometry nodes modifier
                    gn_mod = None
                    for mod in active_object.modifiers:
                        if mod.type == "NODES":
                            gn_mod = mod
                            if gn_mod.node_group:  # Only use it if it has a node group
                                break
                            # Otherwise keep looking for a better one

                    # If no geometry nodes modifier, add one
                    if not gn_mod:
                        # Create a new one
                        reports.add_report(
                            "No geometry nodes modifier found, adding one", type="INFO"
                        )
                        gn_mod = active_object.modifiers.new(
                            name="GeometryNodes", type="NODES"
                        )

                    if not gn_mod.node_group:
                        # Modifier exists but doesn't have a node group
                        # Create a new node group
                        node_group = bpy.data.node_groups.new(
                            "Geometry Nodes", "GeometryNodeTree"
                        )
                        # Add input and output nodes
                        input_node = node_group.nodes.new("NodeGroupInput")
                        output_node = node_group.nodes.new("NodeGroupOutput")
                        # Add a geometry socket to the group
                        node_group.interface.new_socket(
                            "Geometry",
                            description="Geometry",
                            in_out="OUTPUT",
                            socket_type="NodeSocketGeometry",
                        )
                        node_group.interface.new_socket(
                            "Geometry",
                            description="Geometry",
                            in_out="INPUT",
                            socket_type="NodeSocketGeometry",
                        )
                        # Position nodes
                        input_node.location = (-200, 0)
                        output_node.location = (200, 0)
                        # Link the nodes
                        node_group.links.new(
                            input_node.outputs["Geometry"],
                            output_node.inputs["Geometry"],
                        )
                        # Assign the node group to the modifier
                        gn_mod.node_group = node_group

                    # Make sure we have a node tree to work with
                    node_tree = gn_mod.node_group
                    if self.active_area:
                        self.active_area.spaces[0].node_tree = node_tree
                        self.active_area.tag_redraw()

            # Third case: need to switch to shader nodes for shader nodegroup
            elif nodegroup_type == "shader":
                # Try to find a material to edit
                active_object = context.active_object
                node_tree = None

                if not active_object:
                    reports.add_report("No active object", type="ERROR")
                    return

                if not active_object.active_material:
                    temp_material = bpy.data.materials.new("Temporary Material")
                    active_object.active_material = temp_material

                active_material = active_object.active_material
                # Use active material
                # TODO: material.use_nodes is expected to be removed in Blender 6.0
                if not active_material.use_nodes:
                    active_material.use_nodes = True
                node_tree = active_material.node_tree

                # Set the node tree AFTER changing the editor type
                if self.active_area:
                    self.active_area.spaces[0].node_tree = node_tree

            elif nodegroup_type == "compositing":
                # potential fix for blender5.0+
                node_tree = get_node_tree(context)

            # Finally doing the real stuff (only if we didn't show a dialog)
            # Get node position relative to the active node editor area
            node_pos = self.get_node_editor_cursor_position()

            # Download the nodegroup with correct positioning
            bpy.ops.scene.blenderkit_download(
                "EXEC_DEFAULT",
                asset_index=self.asset_search_index,
                node_x=node_pos[0],
                node_y=node_pos[1],
            )
            return

    def mouse_release(self, context: bpy.types.Context) -> None:
        """Main mouse release handler that delegates to specific handlers based on area type."""

        # first let's handle asset types that are independent of the area type
        if self.asset_data["assetType"] == "hdr":
            bpy.ops.scene.blenderkit_download(
                "INVOKE_DEFAULT",
                asset_index=self.asset_search_index,
                invoke_resolution=True,
                use_resolution_operator=True,
                max_resolution=self.asset_data.get("max_resolution", 0),
            )

        if self.asset_data["assetType"] == "scene":
            bpy.ops.scene.blenderkit_download(
                "INVOKE_DEFAULT",
                asset_index=self.asset_search_index,
                invoke_resolution=False,
                invoke_scene_settings=True,
            )

        if self.asset_data["assetType"] == "brush":
            bpy.ops.scene.blenderkit_download(
                asset_index=self.asset_search_index,
            )

        if self.asset_data["assetType"] == "addon":
            # Show addon management popup instead of direct installation

            bpy.ops.scene.blenderkit_addon_choice(
                "INVOKE_DEFAULT", asset_data=json.dumps(self.asset_data)
            )

        # In any other area than 3D view and outliner, we just cancel the drag&drop
        if self.prev_area_type not in ["VIEW_3D", "OUTLINER", "NODE_EDITOR"]:
            return

        # Handle Node Editor drop
        if self.in_node_editor:
            self.handle_node_editor_drop(context)
            return

        # Handle Outliner drop
        if self.hovered_outliner_element is not None:
            self.handle_outliner_drop(context)
            return

        # Handle 3D View drop
        self.handle_view3d_drop(context)

    def find_active_region(
        self,
        x: float,
        y: float,
    ) -> Union[
        Tuple[bpy.types.Window, bpy.types.Region, bpy.types.Area],
        Tuple[None, None, None],
    ]:
        """Find the window, region and area under the mouse cursor."""

        wins = bpy.context.window_manager.windows[:]
        # reverse the list, seemed to work well at least on windows.
        wins.reverse()
        context_win = bpy.context.window

        # let's prioritize the context window
        if context_win is not None:
            wins.remove(context_win)
            wins.insert(0, context_win)

        for window in wins:
            # first let's test if it's in this window, so we know we shall continue
            window_x = window.x * self.resolution_factor
            window_y = window.y * self.resolution_factor
            window_width = window.width * self.resolution_factor
            window_height = window.height * self.resolution_factor
            if (
                x < window_x
                or x > window_x + window_width
                or y < window_y
                or y > window_y + window_height
            ):
                continue
            for area in window.screen.areas:
                for region in area.regions:
                    region_x = window_x + region.x
                    region_y = window_y + region.y
                    if region.type != "WINDOW":
                        continue
                    if (
                        region_x <= x < region_x + region.width
                        and region_y <= y < region_y + region.height
                    ):
                        return window, area, region
        return None, None, None

    def find_outliner_element_under_mouse(
        self,
    ) -> Union[bpy.types.Object, bpy.types.Collection, None]:
        """Find and select the element under the mouse in the outliner.
        Returns the selected object, collection, or None."""
        if not self.active_area or self.active_area.type != "OUTLINER":
            return None

        context = bpy.context
        view_layer = context.view_layer
        selected_objects = context.selected_objects
        active_object = context.active_object

        orig_selected_objects = selected_objects.copy()
        orig_active_object = active_object
        orig_active_collection = view_layer.active_layer_collection

        selected_element = None
        if bpy.app.version > (3, 1, 9):
            # doesn't make sense for lower versions, we wouldn't get the selected_ids anyway.
            #  Simply drops into active_layer_collection in prehistoric Blender.
            with bpy.context.temp_override(
                window=self.active_window,
                area=self.active_area,
                region=self.active_region,
            ):
                bpy.ops.outliner.select_box(
                    xmin=self.mouse_x - 1,
                    xmax=self.mouse_x + 1,
                    ymin=self.mouse_y - 1,
                    ymax=self.mouse_y + 1,
                    wait_for_input=False,
                    mode="SET",
                )

                # Get the newly selected element using selected_ids
                if (
                    hasattr(bpy.context, "selected_ids")
                    and len(bpy.context.selected_ids) > 0
                ):
                    selected_element = bpy.context.selected_ids[0]

        if selected_element is None and hasattr(view_layer, "active_layer_collection"):
            alc = view_layer.active_layer_collection
            if alc is not None and hasattr(alc, "collection"):
                selected_element = alc.collection

        self.orig_selected_objects = orig_selected_objects
        self.orig_active_object = orig_active_object
        self.orig_active_collection = orig_active_collection

        return selected_element

    def restore_original_selection(self) -> None:
        """Restore the original object selection that was active before entering the outliner."""
        if self.orig_selected_objects:
            # Deselect all objects
            bpy.ops.object.select_all(action="DESELECT")
            # Restore original selection
            for obj in self.orig_selected_objects:
                if obj:  # Check if object still exists
                    obj.select_set(True)
            if self.orig_active_object:
                bpy.context.view_layer.objects.active = self.orig_active_object

            # Reset the stored selection to avoid restoring it multiple times
            self.orig_selected_objects = None
            self.orig_active_object = None

        # Restore original active collection
        if self.orig_active_collection:
            # Restore the original active layer collection
            if hasattr(bpy.context, "view_layer"):
                bpy.context.view_layer.active_layer_collection = (
                    self.orig_active_collection
                )
            self.orig_active_collection = None

        # Clear outliner selection
        if hasattr(bpy.context, "selected_ids") and self.prev_area_type == "OUTLINER":
            # This is a read-only property, so we can't directly clear it
            # Instead, we can deselect in the outliner

            # need to create a new context to deselect in the outliner
            if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                context = bpy.context
                override = {
                    "window": context.window,
                    "screen": context.screen,
                    "area": self.outliner_area,
                    "region": self.outliner_region,
                    "scene": context.scene,
                    "view_layer": context.view_layer,
                }
                # Only try to deselect if we have valid area and region
                if self.outliner_area and self.outliner_region:
                    bpy.ops.outliner.select_box(
                        override,
                        xmin=0,
                        xmax=1,
                        ymin=0,
                        ymax=1,
                        wait_for_input=False,
                        mode="SET",
                    )  # Use a very small selection box in the corner to deselect everything
            else:  # B3.2+ can use context.temp_override()
                with bpy.context.temp_override(
                    window=self.outliner_window,
                    area=self.outliner_area,
                    region=self.outliner_region,
                ):
                    bpy.ops.outliner.select_box(
                        xmin=0,
                        xmax=1,
                        ymin=0,
                        ymax=1,
                        wait_for_input=False,
                        mode="SET",
                    )  # Use a very small selection box in the corner to deselect everything

    def drag_raycast_3d_view(
        self, context, event, active_window, active_region, active_area
    ):
        """Get the active object under the mouse cursor during drag."""

        # Reset per-frame hover state
        self.over_particle_instance = False

        # precise placement in ortho views, and quad view
        region_data = viewport_utils.region_data_for_view(active_area, active_region)
        if region_data is None:
            for space in active_area.spaces:
                if space.type == "VIEW_3D":
                    region_data = getattr(space, "region_3d", None)
                    if region_data is not None:
                        break

        # Raw (unfiltered) first hit from mouse_raycast, reused below to detect
        # hovering over a particle-system instance without a second ray_cast.
        raw_first_obj = None
        # Need to temporarily override context for raycasting
        if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
            override = {
                "window": active_window,
                "screen": active_window.screen,
                "area": active_area,
                "region": active_region,
                "region_data": region_data,
                "scene": context.scene,
                "view_layer": context.view_layer,
            }
            (
                self.has_hit,
                self.snapped_location,
                self.snapped_normal,
                self.snapped_rotation,
                self.face_index,
                obj,
                self.matrix,
                raw_first_obj,
            ) = mouse_raycast(active_region, region_data, self.mouse_x, self.mouse_y)
            if obj is not None:
                self.object_name = obj.name
        else:  # B3.2+ can use context.temp_override()
            with bpy.context.temp_override(
                window=active_window, area=active_area, region=active_region
            ):
                (
                    self.has_hit,
                    self.snapped_location,
                    self.snapped_normal,
                    self.snapped_rotation,
                    self.face_index,
                    obj,
                    self.matrix,
                    raw_first_obj,
                ) = mouse_raycast(
                    active_region,
                    region_data,
                    self.mouse_x,
                    self.mouse_y,
                )
                if obj is not None:
                    self.object_name = obj.name

        # MODELS and NODEGROUPS can be dragged on scene floor
        if not self.has_hit and self.asset_data["assetType"] in [
            "model",
            "printable",
            "nodegroup",
        ]:
            # Need to temporarily override context for raycasting
            if bpy.app.version < (3, 2, 0):  # B3.0, B3.1 - custom context override
                override = {
                    "window": active_window,
                    "screen": active_window.screen,
                    "area": active_area,
                    "region": active_region,
                    "region_data": region_data,
                    "scene": context.scene,
                    "view_layer": context.view_layer,
                }
                (
                    self.has_hit,
                    self.snapped_location,
                    self.snapped_normal,
                    self.snapped_rotation,
                    self.face_index,
                    obj,
                    self.matrix,
                ) = floor_raycast(
                    active_region,
                    region_data,
                    self.mouse_x,
                    self.mouse_y,
                )
                if obj is not None:
                    self.object_name = obj.name
                else:
                    self.object_name = None
            else:  # B3.2+ can use context.temp_override()
                with bpy.context.temp_override(
                    window=active_window, area=active_area, region=active_region
                ):
                    (
                        self.has_hit,
                        self.snapped_location,
                        self.snapped_normal,
                        self.snapped_rotation,
                        self.face_index,
                        obj,
                        self.matrix,
                    ) = floor_raycast(
                        active_region,
                        region_data,
                        self.mouse_x,
                        self.mouse_y,
                    )
                    if obj is not None:
                        self.object_name = obj.name
                    else:
                        self.object_name = None

        # Detect if the cursor is over an object that was filtered out of drag
        # snapping because it's used as a particle-system instance. mouse_raycast
        # already returns the raw (unfiltered) first hit, so we reuse it here
        # instead of doing a second full scene ray_cast every drag frame.
        try:
            if raw_first_obj is not None and object_in_particle_collection(
                raw_first_obj
            ):
                self.over_particle_instance = True
        except Exception:
            # Informational only — never break drag on detection failure.
            pass

    def _handle_node_editor_type(
        self, current_area_type: Union[str, None], active_area: bpy.types.Area
    ) -> None:
        """Track if we're in a node editor and what type."""
        if current_area_type and current_area_type == "NODE_EDITOR":
            self.in_node_editor = True
            if active_area.spaces.active.tree_type == "ShaderNodeTree":
                self.node_editor_type = "shader"
            elif active_area.spaces.active.tree_type == "GeometryNodeTree":
                self.node_editor_type = "geometry"
            elif active_area.spaces.active.tree_type == "CompositorNodeTree":
                self.node_editor_type = "compositing"
            elif active_area.spaces.active.tree_type == "TextureNodeTree":
                self.node_editor_type = "texture"
        else:
            self.in_node_editor = False
            self.node_editor_type = None

    def _cleanup_drag(self, ui_props, cls, *, reopen_assetbar: bool = False) -> None:
        """Shared teardown: remove handlers, restore cursor, reset drag state."""
        self.handlers_remove()
        bpy.context.window.cursor_modal_restore()
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception:
            pass
        ui_props.dragging = False
        if self.closed_assetbar:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
        if reopen_assetbar:
            bpy.ops.view3d.blenderkit_asset_bar_widget(
                "INVOKE_REGION_WIN", do_search=False
            )
        cls.active_operator_id = None

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> Set[str]:
        cls = type(self)
        ui_props = bpy.context.window_manager.blenderkitUI

        # Swap in the proxor handler if an on-demand fetch finished since
        # the last modal tick (cheap dict + path check, no I/O in common case).
        if self._proxor_pending is not None:
            self._poll_proxor_pending()

        self.mouse_screen_x = int(
            context.window.x * self.resolution_factor + event.mouse_x
        )
        self.mouse_screen_y = int(
            context.window.y * self.resolution_factor + event.mouse_y
        )

        # Find the active region under the mouse cursor using actual screen coordinates
        found_window, found_area, found_region = self.find_active_region(
            self.mouse_screen_x, self.mouse_screen_y
        )
        if (
            found_region is not None
            and found_area is not None
            and found_window is not None
        ):
            self.active_window, self.active_area, self.active_region = (
                found_window,
                found_area,
                found_region,
            )
        # --- CURSOR VISIBILITY FIX ---
        if self.active_region is None or self.active_area is None:
            # bpy.context.window.cursor_modal_set("STOP")
            bpy.context.window.cursor_modal_restore()
            return {"PASS_THROUGH"}

        if self.drag:
            bpy.context.window.cursor_modal_set("NONE")

        # Convert screen coords (bottom-left) to region-local coords
        # window.x/y and region.x/y are also in bottom-left coordinate system
        self.mouse_x = int(
            self.mouse_screen_x
            - self.active_window.x * self.resolution_factor
            - self.active_region.x
        )
        self.mouse_y = int(
            self.mouse_screen_y
            - self.active_window.y * self.resolution_factor
            - self.active_region.y
        )

        # redraw all windows to update cursor and other elements
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        current_area_type = self.active_area.type

        # Check if we're transitioning out of the outliner
        if self.prev_area_type == "OUTLINER" and current_area_type != "OUTLINER":
            self.restore_original_selection()

        self.shift_pressed = event.shift

        # Track if we're in a node editor
        self._handle_node_editor_type(current_area_type, self.active_area)

        # Update the previous area type for the next frame
        if current_area_type:
            self.prev_area_type = current_area_type

        if self.active_region and self.active_area:
            # Store the active region pointer for drawing 2D elements only in this region
            self.active_region_pointer = self.active_region.as_pointer()

            # Handle outliner interaction
            if current_area_type == "OUTLINER":
                self.hovered_outliner_element = self.find_outliner_element_under_mouse()
                self.outliner_window = self.active_window
                self.outliner_area = self.active_area
                self.outliner_region = self.active_region
            else:
                # Reset outliner tracking
                self.hovered_outliner_element = None
                self.outliner_window = None
                self.outliner_area = None
                self.outliner_region = None
        else:
            # If no active 3D region is found, use the context region
            self.active_region_pointer = context.region.as_pointer()

        # are we dragging already?
        delta_x = abs(self.start_mouse_x - self.mouse_screen_x)
        delta_y = abs(self.start_mouse_y - self.mouse_screen_y)
        if not self.drag and (
            delta_x > DEFAULT_DRAG_THRESHOLD or delta_y > DEFAULT_DRAG_THRESHOLD
        ):
            self.drag = True

        if self.drag and ui_props.assetbar_on and not self.closed_assetbar:
            # turn off asset bar here; reopen after placement when we actually dragged
            ui_props.turn_off = True
            self.closed_assetbar = True

        if event.type in {"RIGHTMOUSE", "ESC"}:
            # Restore original selection if we changed it
            self.restore_original_selection()

            self._cleanup_drag(ui_props, cls, reopen_assetbar=True)
            return {"CANCELLED"}

        self.steps += 1

        if (
            event.type == "ESC"
            or not ui.mouse_in_region(context.region, self.mouse_x, self.mouse_y)
        ) and (not self.drag or self.steps < 5):
            # this case is for canceling from inside popup card when there's an escape attempt to close the window
            return {"PASS_THROUGH"}

        sprops = bpy.context.window_manager.blenderkit_models
        if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
            direction = 1 if event.type == "WHEELUPMOUSE" else -1
            if event.ctrl:
                # Snap to nearest perpendicular (90°) then step by 90°
                snap = math.pi / 2
                current = sprops.offset_rotation_amount
                snapped = round(current / snap) * snap
                sprops.offset_rotation_amount = snapped + direction * snap
            elif event.shift:
                sprops.offset_rotation_amount += direction * math.radians(1)
            else:
                sprops.offset_rotation_amount += direction * math.radians(10)

        if event.type in {
            "MOUSEMOVE",
            "INBETWEEN_MOUSEMOVE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
        }:
            # sometimes active area or region can be None, so we need to check for that
            if self.active_area is None or self.active_region is None:
                return {"RUNNING_MODAL"}

            # reset values
            self.object_name = None
            self.has_hit = False

            # Only perform raycasting in 3D view areas
            if current_area_type == "VIEW_3D":
                # prefetch the drag active object info
                self.drag_raycast_3d_view(
                    context,
                    event,
                    self.active_window,
                    self.active_region,
                    self.active_area,
                )

            if self.asset_data["assetType"] in ["model", "printable"]:
                self.snapped_bbox_min = Vector(self.asset_data["bbox_min"])
                self.snapped_bbox_max = Vector(self.asset_data["bbox_max"])
            elif current_area_type != "VIEW_3D":
                # In outliner, don't do raycasting, but keep has_hit to avoid errors
                self.has_hit = False

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self.mouse_release(context)
            self._cleanup_drag(ui_props, cls)
            return {"FINISHED"}

        # pass event to assetbar so it can close itself
        if ui_props.assetbar_on and ui_props.turn_off:
            return {"PASS_THROUGH"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        # Before registering callbacks, check for canceling situations: login and localdir popups, sculpt popup/switch
        sr = search.get_search_results()
        ui_props = bpy.context.window_manager.blenderkitUI
        if ui_props.dragging:
            return {"CANCELLED"}
        cls = type(self)
        if cls.active_operator_id is not None and cls.active_operator_id != id(self):
            return {"CANCELLED"}
        # Acquire drag lock immediately so concurrent invoke paths cannot race while this invoke initializes.
        ui_props.dragging = True
        cls.active_operator_id = id(self)
        self.closed_assetbar = False
        # Use the asset_search_index parameter passed to the operator, not the global ui_props.active_index
        # This is critical for multi-window support where active_index is shared across windows
        self.asset_data = dict(sr[self.asset_search_index])

        # Try to load proxor preview for model/printable assets
        if utils.proxor_enabled() and self.asset_data.get("assetType") in (
            "model",
            "printable",
        ):
            asset_base_id = self.asset_data.get("assetBaseId", "")
            prxc_path = global_vars.DATA.get("prxc available", {}).get(asset_base_id)
            if prxc_path and os.path.exists(prxc_path):
                self._install_proxor_handler_from_path(asset_base_id, prxc_path)
            else:
                # No cached file: kick off a single on-demand .prxc fetch.
                # Drag continues with the green bbox; handler is swapped in
                # from modal() once the file lands on disk.
                self._start_proxor_fetch(asset_base_id)

        # Initialize drag-start coordinates immediately in invoke.
        # resolution factor is essential on Mac OS. don't touch it if you don't know what you are doing.
        self.resolution_factor = (
            bpy.context.preferences.system.pixel_size
            / bpy.context.preferences.view.ui_scale
        )
        self.mouse_screen_x = int(
            context.window.x * self.resolution_factor + event.mouse_x
        )
        self.mouse_screen_y = int(
            context.window.y * self.resolution_factor + event.mouse_y
        )
        self.start_mouse_x = self.mouse_screen_x
        self.start_mouse_y = self.mouse_screen_y
        # Author assets should not be dragged, cancel immediately
        if self.asset_data.get("assetType") == "author":
            return {"CANCELLED"}
        # add-ons
        if self.asset_data.get("assetType") == "addon" and not self.asset_data.get(
            "canDownload"
        ):
            message = "This addon is not purchased yet."
            link_text = "Purchase add-on online"
            url = paths.get_unlock_asset_url(
                self.asset_data["id"], "addon_purchase_drag"
            )
            bpy.ops.wm.blenderkit_url_dialog(
                "INVOKE_REGION_WIN", url=url, message=message, link_text=link_text
            )
            ui_props.dragging = False
            cls.active_operator_id = None
            return {"CANCELLED"}

        if not self.asset_data.get("canDownload"):

            message = "This asset is included in Full Plan.\nSupport asset creators & open-source by subscribing."
            link_text = "Unlock All Assets"
            url = paths.get_unlock_asset_url(self.asset_data["id"], "asset_unlock_drag")
            bpy.ops.wm.blenderkit_url_dialog(
                "INVOKE_REGION_WIN", url=url, message=message, link_text=link_text
            )
            ui_props.dragging = False
            cls.active_operator_id = None
            return {"CANCELLED"}

        prefs = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences

        dir_behaviour = prefs.directory_behaviour

        if dir_behaviour == "LOCAL" and bpy.data.filepath == "":
            message = "Save the project to download in local directory mode."
            link_text = "See documentation"
            url = "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-Preferences#use-directories"
            bpy.ops.wm.blenderkit_url_dialog(
                "INVOKE_REGION_WIN", url=url, message=message, link_text=link_text
            )
            ui_props.dragging = False
            cls.active_operator_id = None
            return {"CANCELLED"}

        if self.asset_data.get("assetType") == "brush" and not (
            context.sculpt_object or context.image_paint_object
        ):
            # either switch to sculpt mode and layout automatically or show a popup message
            if context.active_object and context.active_object.type == "MESH":
                bpy.ops.object.mode_set(mode="SCULPT")
                self.mouse_release(context)  # does the main job with assets

                if bpy.data.workspaces.get("Sculpting") is not None:
                    bpy.context.window.workspace = bpy.data.workspaces["Sculpting"]
                reports.add_report(
                    "Automatically switched to sculpt mode to use brushes."
                )
            else:
                message = "Select a mesh and switch to sculpt or image paint modes to use the brushes."
                bpy.ops.wm.blenderkit_popup_dialog(
                    "INVOKE_REGION_WIN", message=message, width=500
                )
            ui_props.dragging = False
            cls.active_operator_id = None
            return {"CANCELLED"}

        # the arguments we pass the the callback
        args = (self, context)

        # Register callback for VIEW_3D spaces
        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_3d_dragging, args, "WINDOW", "POST_VIEW"
        )

        # Register callbacks for all other space types
        # List of space types we want to support
        space_types = [
            "SpaceTextEditor",
            "SpaceConsole",
            "SpaceInfo",
            "SpacePreferences",
            "SpaceFileBrowser",
            "SpaceNLA",
            "SpaceDopeSheetEditor",
            "SpaceGraphEditor",
            "SpaceNodeEditor",
            "SpaceProperties",
            "SpaceSequenceEditor",
            "SpaceImageEditor",
            "SpaceView3D",
            "SpaceOutliner",
        ]

        # Initialize a dictionary to store handlers
        self._handlers_universal = {}

        # Register a handler for each space type
        for space_type in space_types:
            try:
                space_class = getattr(bpy.types, space_type)
                handler = space_class.draw_handler_add(
                    draw_callback_dragging, args, "WINDOW", "POST_PIXEL"
                )
                # we should store the handler to be able to remove it later
                # but if RNA Struct fails we are not longer able to remove it, so we log an error and store None
                self._handlers_universal[space_type] = handler
            except (AttributeError, TypeError) as e:
                bk_logger.error("Could not register handler for %s: %s", space_type, e)
                self._handlers_universal[space_type] = None

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_screen_x = self.start_mouse_x
        self.mouse_screen_y = self.start_mouse_y
        # Store the initial active region pointer
        self.active_region_pointer = context.region.as_pointer()

        self.prev_area_type = context.area.type  # Track previous area type

        self.iname = f".{self.asset_data['thumbnail_small']}"
        self.iname = (self.iname[:63]) if len(self.iname) > 63 else self.iname

        bpy.context.window.cursor_modal_restore()
        ui_props = bpy.context.window_manager.blenderkitUI
        self.drag = False
        self.steps = 0
        try:
            bpy.context.workspace.status_text_set(
                _make_drag_status_fn(self.asset_data.get("assetType", ""))
            )
        except Exception as e:
            bk_logger.debug("Could not set drag-drop status text: %s", e)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def get_node_editor_cursor_position(
        self,
    ) -> Tuple[float, float]:
        """Get the cursor position in the node editor space."""

        # Get view2d from region
        ui_scale = bpy.context.preferences.system.ui_scale

        # Convert region coordinates to view coordinates using view2d
        x, y = self.active_region.view2d.region_to_view(
            float(self.mouse_x), float(self.mouse_y)
        )

        # Scale by UI scale - this ensures proper positioning
        x = x / ui_scale
        y = y / ui_scale
        return (x, y)


class DownloadGizmoOperator(BL_UI_OT_draw_operator):
    bl_idname = "view3d.blenderkit_download_gizmo_widget"
    bl_label = "Blendkit download gizmo"
    bl_description = (
        "Blendkit download gizmo - draws download and enables to cancel it."
    )
    bl_options = {"REGISTER"}
    instances = []

    asset_base_id: StringProperty(name="asset base id", default="")  # type: ignore

    def cancel_press(self, widget: Any) -> None:
        self.finish()
        cancel_download = False

        if self.downloader is None:
            # prevent unbound
            return

        for key, t in download.download_tasks.items():
            if key == self.task_key:
                for d in t.get("downloaders", []):
                    if d["location"] == self.downloader["location"]:
                        download.download_tasks[key]["downloaders"].remove(d)
                        if len(download.download_tasks[key]["downloaders"]) == 0:
                            cancel_download = True
                        break
        if cancel_download:
            bpy.ops.scene.blenderkit_download_kill(task_id=self.task_key)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # get downloader
        self.task = None
        for key, t in download.download_tasks.items():
            if t["asset_data"]["assetBaseId"] == self.asset_base_id:
                self.task = t
                self.task_key = key
                break

        if self.task is None:
            self._finished = True
            return

        self.asset_data = self.task["asset_data"]

        if self.task.get("downloaders"):
            self.downloader = self.task["downloaders"][-1]
        else:
            self.downloader = None

        ui_scale = bpy.context.preferences.view.ui_scale

        text_size = int(10 * ui_scale)
        margin = int(5 * ui_scale)

        self.bg_color = (0.05, 0.05, 0.05, 0.3)
        self.hover_bg_color = (0.05, 0.05, 0.05, 0.5)

        self.text_color = (0.9, 0.9, 0.9, 1)

        ui_props = bpy.context.window_manager.blenderkitUI

        pix_size = ui_bgl.get_text_size(
            font_id=1,
            text=self.task["text"],
            text_size=text_size,
            dpi=int(bpy.context.preferences.system.dpi / ui_scale),
        )
        self.height = pix_size[1] + 2 * margin
        self.button_size = int(ui_props.thumb_size)
        self.width = pix_size[0] + 2 * margin  # adding image and cancel button to width

        if bpy.context.space_data is not None and self.downloader is not None:
            loc = view3d_utils.location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.space_data.region_3d,
                self.downloader["location"],
            )
            if loc is None:
                loc = Vector((0, 0))
        else:
            loc = Vector((0, 0))

        self.panel = BL_UI_Drag_Panel(
            loc.x, bpy.context.region.height - loc.y, self.width, self.height
        )
        self.panel.bg_color = (0.2, 0.2, 0.2, 0.02)

        self.image = BL_UI_Image(
            0, -self.button_size, self.button_size, self.button_size
        )

        self.label = BL_UI_Button(0, 0, pix_size[0] + 2 * margin, self.height)
        self.label.text = self.task["text"]
        self.label.text_size = text_size
        self.label.text_color = self.text_color

        self.label.bg_color = self.bg_color
        self.label.hover_bg_color = self.hover_bg_color

        self.button_close = BL_UI_Button(
            self.button_size * 0.75,
            -self.button_size * 1.25,
            self.button_size / 2,
            self.button_size / 2,
        )
        self.button_close.bg_color = self.bg_color
        self.button_close.hover_bg_color = self.hover_bg_color
        self.button_close.text = ""
        self.button_close.set_mouse_down(self.cancel_press)
        self._timer_interval = 0.04

    def on_invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        # Add new widgets here (TODO: perhaps a better, more automated solution?)
        self.context = context
        self.instances.append(self)

        # no task, no downloader...
        if self._finished:
            return False

        widgets_panel = [self.label, self.image, self.button_close]
        widgets = [self.panel]

        widgets += widgets_panel

        # assign image to the cancel button
        img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
        img_size = self.button_size
        button_size = int(self.button_size / 2)

        self.button_close.set_image(img_fp)
        self.button_close.set_image_size((button_size, button_size))
        self.button_close.set_image_position((0, 0))

        directory = paths.get_temp_dir(f"{self.asset_data['assetType']}_search")
        thumbnail_path = os.path.join(directory, self.asset_data["thumbnail_small"])

        self.image.set_image(thumbnail_path)
        self.image.set_image_size((img_size, img_size))
        self.image.set_image_position((0, 0))

        self.init_widgets(context, widgets)
        self.panel.add_widgets(widgets_panel)
        return True

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}

        if self.task is None or self.task_key not in download.download_tasks:
            self.finish()
            return {"PASS_THROUGH"}

        if not context.area:
            # end if area disappears
            self.finish()
            return {"PASS_THROUGH"}

        # if event.type == "MOUSEMOVE":
        if bpy.context.space_data is not None and self.downloader is not None:
            loc = view3d_utils.location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.space_data.region_3d,
                self.downloader["location"],
            )
            if loc is None:
                loc = Vector((0, 0))
        else:
            loc = Vector((0, 0))

        self.panel.set_location(loc.x, context.region.height - loc.y)
        self.label.text = self.task["text"]
        if self.handle_widget_events(event):
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def on_finish(self, context):
        self._finished = True

    @classmethod
    def unregister(cls):
        bk_logger.debug("unregistering class %s", cls)
        instances_copy = cls.instances.copy()
        for instance in instances_copy:
            try:
                bk_logger.debug("- class instance %s", instance)
            except ReferenceError:
                bk_logger.debug("- class instance <deleted>")
            try:
                instance.unregister_handlers(instance.context)
            except Exception as e:
                bk_logger.debug("-- error unregister_handlers(): %s", e)
            try:
                instance.on_finish(instance.context)
            except Exception as e:
                bk_logger.debug("-- error calling on_finish(): %s", e)
            if bpy.context.region is not None:
                bpy.context.region.tag_redraw()

            cls.instances.remove(instance)


def analyze_gn_tree(tree, materials):
    """Recursively analyze GN tree and its node groups for Set Material nodes"""
    current_mapping = {}

    bk_logger.info("\nAnalyzing GN tree: %s", tree.name)
    for node in tree.nodes:
        bk_logger.info("Checking node: %s, type: %s", node.name, node.type)
        if node.type == "SET_MATERIAL":
            # Find material index in evaluated mesh
            mat = node.inputs["Material"].default_value
            bk_logger.info(
                "Found Set Material node with material: %s", mat.name if mat else "None"
            )

            if mat:
                for mat_idx, temp_mat in enumerate(materials):
                    if compare_material_names(temp_mat, mat):
                        bk_logger.info("Matched material to index %d", mat_idx)
                        current_mapping[mat_idx] = {
                            "type": "GN",
                            "node_name": node.name,
                            "tree_name": tree.name,
                        }
            else:
                # If no material is set, we can use this node for a new material
                # Find first available index that isn't mapped
                used_indices = set(current_mapping.keys())
                for i in range(len(materials)):
                    if i not in used_indices:
                        bk_logger.info("Using empty Set Material node for index %d", i)
                        current_mapping[i] = {
                            "type": "GN",
                            "node_name": node.name,
                            "tree_name": tree.name,
                        }
                        break

        # Check node groups recursively
        elif node.type == "GROUP" and node.node_tree:
            nested_mapping = analyze_gn_tree(node.node_tree, materials)
            current_mapping.update(nested_mapping)

    return current_mapping


def compare_material_names(mat1, mat2):
    """Compare two materials by name, but if one is None, use 'None' instead of mat1.name"""
    if mat1 is None:
        return mat2 is None
    if mat2 is None:
        return False
    return mat1.name == mat2.name


def create_material_mapping(obj, temp_mesh):
    """Creates mapping between material indices and their sources (slots or GN nodes)"""
    mapping = {}

    bk_logger.info("\nCreating mapping for %s", obj.name)
    bk_logger.info("Material slots: %d", len(obj.material_slots))
    bk_logger.info("Has GN: %s", any(mod.type == "NODES" for mod in obj.modifiers))

    # 1. First map regular material slots
    for slot_idx, slot in enumerate(obj.material_slots):
        # Find matching material in evaluated mesh
        for mat_idx, mat in enumerate(temp_mesh.materials):
            if compare_material_names(mat, slot.material):
                mapping[mat_idx] = {"type": "SLOT", "index": slot_idx}
                break  # Stop after finding first match

    # 2. Check Geometry Nodes
    has_gn = False
    for modifier in obj.modifiers:
        if modifier.type == "NODES":
            has_gn = True
            gn_mapping = analyze_gn_tree(modifier.node_group, temp_mesh.materials)
            if gn_mapping:
                # Only add GN mappings for indices that aren't already mapped to slots
                for idx, map_data in gn_mapping.items():
                    if idx not in mapping:
                        mapping[idx] = map_data

    # 3. If no material slots and no GN, create a mapping for slot 0
    if len(obj.material_slots) == 0 and not has_gn:
        bk_logger.info("Creating default mapping to slot 0")
        mapping[0] = {"type": "SLOT", "index": 0}

    bk_logger.info("Final mapping: %s", mapping)

    # Store mapping as custom property (convert to serializable format)
    mapping_data = {str(k): v for k, v in mapping.items()}
    obj["material_mapping"] = mapping_data

    return mapping


classes = (
    AssetDragOperator,
    DownloadGizmoOperator,
)


def register():
    # register the classes
    global handler_2d, handler_3d

    for c in classes:
        bpy.utils.register_class(c)

    args = (None, bpy.context)

    handler_2d = bpy.types.SpaceView3D.draw_handler_add(
        draw_callback_2d_progress, args, "WINDOW", "POST_PIXEL"
    )
    handler_3d = bpy.types.SpaceView3D.draw_handler_add(
        draw_callback_3d_progress, args, "WINDOW", "POST_VIEW"
    )


def unregister():
    global handler_2d, handler_3d

    bpy.types.SpaceView3D.draw_handler_remove(handler_2d, "WINDOW")
    bpy.types.SpaceView3D.draw_handler_remove(handler_3d, "WINDOW")

    # unregister the classes
    for c in classes:
        bpy.utils.unregister_class(c)
