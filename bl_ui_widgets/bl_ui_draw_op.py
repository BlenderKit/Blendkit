import logging
import math
from typing import Optional

import bpy
import gpu
from bpy.types import Operator

from .. import ui_bgl
from .bl_ui_widget import region_redraw

bk_logger = logging.getLogger(__name__)


def _widget_outside_clip(widget, clip):
    """Return True when widget's screen rect is fully outside the clip rect.

    ``clip`` is a (top, bottom, left, right) tuple in widget (top-down) coords.
    """
    gt, gb, gl, gr = clip
    return (
        widget.y_screen + widget.height <= gt
        or widget.y_screen >= gb
        or widget.x_screen + widget.width <= gl
        or widget.x_screen >= gr
    )


def get_safely(obj, attr_name, default=None):
    """Get attribute from object while tolerating freed data."""
    try:
        return getattr(obj, attr_name, default)
    except ReferenceError:
        return default
    except Exception:
        return default


def _compute_grid_clip(op):
    """Return the visible grid area as (top, bottom, left, right) in widget coords.

    Returns None when the clip area cannot be determined (e.g. missing panel).
    Used by both the draw callback (GPU scissor) and the event handler to skip
    buffer-row widgets that are positioned outside the visible bar.
    """
    panel = get_safely(op, "panel", None)
    button_size = get_safely(op, "button_size", 0)
    if panel is None or button_size <= 0:
        return None
    hcount = get_safely(op, "hcount", 1)
    wcount = get_safely(op, "wcount", 1)
    margin = get_safely(op, "assetbar_margin", 0)
    top = panel.y_screen + margin
    left = panel.x_screen + margin
    return (top, top + hcount * button_size, left, left + wcount * button_size)


def restart_asset_bar():
    # ignore failures if already gone
    from ..asset_bar.asset_bar_op import BlenderKitAssetBarOperator

    try:
        bpy.utils.unregister_class(BlenderKitAssetBarOperator)
    except Exception:
        pass
    bpy.utils.register_class(BlenderKitAssetBarOperator)
    bpy.ops.view3d.blenderkit_asset_bar_widget("INVOKE_DEFAULT")


class BL_UI_OT_draw_operator(Operator):
    bl_idname = "object.bl_ui_ot_draw_operator"
    bl_label = "bl ui widgets operator"
    bl_description = "Operator for bl ui widgets"
    bl_options = {"REGISTER"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.draw_handle = None
        self.draw_event = None
        self._finished = False

        self.widgets = []
        self._timer_interval = 0.1

    def init_widgets(self, context, widgets):
        self.widgets = widgets
        for widget in self.widgets:
            widget.init(context)

    def on_invoke(self, context, event) -> Optional[bool]:
        pass

    def on_finish(self, context):
        self._finished = True

    def invoke(self, context, event):
        self.on_invoke(context, event)

        context.window_manager.modal_handler_add(self)

        # first set pointers to keep track if the area is still available
        self.active_window_pointer = context.window.as_pointer()
        self.active_area_pointer = context.area.as_pointer()
        self.active_region_pointer = context.region.as_pointer()

        args = (self, context)
        self.register_handlers(args, context, timer_interval=self._timer_interval)

        region_redraw(context)
        return {"RUNNING_MODAL"}

    def register_handlers(self, args, context, timer_interval=0.1):
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback_px, args, "WINDOW", "POST_PIXEL"
        )
        self.draw_event = context.window_manager.event_timer_add(
            timer_interval, window=context.window
        )

    def unregister_handlers(self, context):
        context.window_manager.event_timer_remove(self.draw_event)

        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, "WINDOW")

        self.draw_handle = None
        self.draw_event = None

    def handle_widget_events(self, event):
        grid_clip = _compute_grid_clip(self)
        # Iterate reversed so top/front widgets get priority on overlap.
        for widget in reversed(self.widgets):
            if (
                getattr(widget, "_is_grid_widget", False)
                and grid_clip is not None
                and _widget_outside_clip(widget, grid_clip)
            ):
                continue
            if widget.handle_event(event):
                return True
        return False

    def modal(self, context, event):
        if self._finished:
            return {"FINISHED"}

        if context.area:
            region_redraw(context)

        if self.handle_widget_events(event):
            return {"RUNNING_MODAL"}

        if event.type in {"ESC"}:
            self.finish()

        return {"PASS_THROUGH"}

    def finish(self):
        self.unregister_handlers(bpy.context)
        # it is possible that the area has been closed, so we check if it is still available
        region_redraw()
        self.on_finish(bpy.context)

    # Draw handler to paint onto the screen
    def draw_callback_px(self, op, context):
        draw_callback_px_separated(self, op, context)

    def cancel(self, context):
        """Cancel the modal operator and finish. This is called before unregistration on Blender quit. Has to be here, so BL_UI_Button, BL_UI_Drag_Panel, BL_UI_Image and other elements are removed with finish().
        We cannot call this during unregister because at that stage Operator is already removed, but BL_UI_Button is kept in memory causing memory leaks. Issue: #770
        """
        self.finish()


def draw_callback_px_separated(self, op, context):
    # separated only for purpose of profiling
    try:
        # hide during animation playback, to improve performance
        if context.screen.is_animation_playing:
            return
        area_pointer = (
            context.area.as_pointer() if getattr(context, "area", None) else None
        )

        # get area, check if RNA failed
        active_pointer = get_safely(self, "active_area_pointer", None)
        if area_pointer is None or area_pointer != active_pointer:
            return

        active_region_pointer = get_safely(self, "active_region_pointer", None)
        if active_region_pointer is not None:
            region_pointer = (
                context.region.as_pointer()
                if getattr(context, "region", None)
                else None
            )
            if region_pointer is None or region_pointer != active_region_pointer:
                return

        region = getattr(context, "region", None)

        # Grid clipping strategy:
        #  * Always cull widgets that are fully outside the visible bar.
        #  * When the GPU scissor API is available (Blender 3.6+), also
        #    clip partially-visible widgets so smooth-scroll animations
        #    don't spill rows outside the bar. On older Blender versions
        #    smooth scroll is disabled at the asset-bar level, so plain
        #    culling is sufficient.
        grid_clip = _compute_grid_clip(self)
        scissor_supported = hasattr(gpu.state, "scissor_test_set") and hasattr(
            gpu.state, "scissor_set"
        )
        grid_scissor = None
        if scissor_supported and grid_clip is not None and region is not None:
            gt, gb, gl, gr = grid_clip
            try:
                vp = gpu.state.viewport_get()
            except Exception:  # noqa: BLE001
                vp = None
            if vp is not None:
                rw = max(region.width, 1)
                rh = max(region.height, 1)
                sx = int(vp[0] + gl * vp[2] / rw)
                sy = int(vp[1] + (region.height - gb) * vp[3] / rh)
                sw = math.ceil((gr - gl) * vp[2] / rw)
                sh = math.ceil((gb - gt) * vp[3] / rh)
                if sw > 0 and sh > 0:
                    grid_scissor = (sx, sy, sw, sh)

        # Smooth-scroll sub-slot offset is applied as a single draw-time
        # translate to all grid widgets (GPU coords, +x right / +y up) instead
        # of repositioning each widget per frame. While it's non-zero, expand
        # the *cull* clip by one slot so buffer widgets sliding into view are
        # not culled; the GPU scissor stays at the exact bar bounds so partial
        # widgets are still clipped precisely.
        grid_offset = get_safely(self, "_grid_draw_offset", (0.0, 0.0))
        offset_dx, offset_dy = grid_offset
        has_grid_offset = offset_dx != 0.0 or offset_dy != 0.0
        cull_clip = grid_clip
        if has_grid_offset and grid_clip is not None:
            bs = get_safely(self, "button_size", 0) or 0
            gt, gb, gl, gr = grid_clip
            cull_clip = (gt - bs, gb + bs, gl - bs, gr + bs)

        with ui_bgl.overlay_matrix_guard(region):
            scissor_active = False
            for widget in self.widgets:
                is_grid = getattr(widget, "_is_grid_widget", False)
                if (
                    is_grid
                    and cull_clip is not None
                    and _widget_outside_clip(widget, cull_clip)
                ):
                    continue

                if is_grid and grid_scissor is not None:
                    if not scissor_active:
                        gpu.state.scissor_test_set(True)
                        gpu.state.scissor_set(*grid_scissor)
                        scissor_active = True
                elif scissor_active:
                    gpu.state.scissor_test_set(False)
                    scissor_active = False

                if is_grid and has_grid_offset:
                    gpu.matrix.push()
                    gpu.matrix.translate((offset_dx, offset_dy))
                    widget.draw()
                    gpu.matrix.pop()
                else:
                    widget.draw()

            if scissor_active:
                gpu.state.scissor_test_set(False)

    except Exception:
        bk_logger.exception("Error in draw_callback_px_separated: ")
