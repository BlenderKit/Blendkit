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
import math
import os
import re
import time
from collections import Counter
from functools import partial
from types import SimpleNamespace
from typing import Any, Dict, Optional, Union

import bpy
import gpu
import blf
from bpy.props import BoolProperty, StringProperty

from .. import (
    colors,
    comments_utils,
    global_vars,
    paths,
    ratings_utils,
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
from ..bl_ui_widgets.bl_ui_label import BL_UI_Label, BL_UI_DuoLabel
from ..bl_ui_widgets.bl_ui_resize_handle import BL_UI_Resize_Handle
from ..bl_ui_widgets.bl_ui_widget import (
    BL_UI_Widget,
    batched_region_redraw,
    region_redraw,
    set_font_size,
)


bk_logger = logging.getLogger(__name__)

# Addon root package name. We live in <addon>.asset_bar, but addon
# preferences are registered under the top-level addon package, so we
# strip the last component to look them up correctly.
_ADDON_PACKAGE = __package__.rsplit(".", 1)[0]

# Maximum label length for manufacturer chips (e.g. "Ford motor company")
MAX_MANUFACTURER_LABEL_LEN = 17
# Maximum label length for generic active filter chips (term + value)
MAX_FILTER_LABEL_LEN = 24

THUMBNAIL_TYPES = [
    "THUMBNAIL",
    "PHOTO",
    "WIREFRAME",
]

active_area_pointer = 0

ROUNDING_RADIUS = 20


def _format_comment_timestamp(submit_date):
    """Format an ISO comment date as [DD.MM.YYYY-HH:MM]. Returns "" if unknown."""
    if not submit_date or submit_date == "just now":
        return ""
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(submit_date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    return dt.strftime("%d.%m.%Y-%H:%M")


def _wrap_text_to_width(text, width_px, text_size):
    """Split text into lines that fit within width_px pixels at text_size."""
    if text == "":
        return [""]
    font_id = 1
    set_font_size(font_id, text_size)

    def fits(candidate):
        return blf.dimensions(font_id, candidate)[0] <= width_px

    lines = []
    current = ""
    for word in text.split(" "):
        candidate = word if current == "" else f"{current} {word}"
        if fits(candidate) or current == "":
            # break a single word that is too long on its own
            while current == "" and not fits(word) and len(word) > 1:
                cut = len(word)
                while cut > 1 and not fits(word[:cut]):
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
                candidate = word
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


ASSETBAR_MAX_VISIBLE_ASSETS = 200
ASSETBAR_RESIZE_CURSOR = "MOVE_Y"
ASSETBAR_RESIZE_CLICK_THRESHOLD_PX = 5

TOOLTIP_SIZE_PX = 512

# How many assets ahead of the current scroll position to trigger fetching the next page.
# Higher values start the fetch earlier, reducing visible pauses when scrolling fast.
SEARCH_PREFETCH_LOOKAHEAD = 20

# Default trackpad scroll sensitivity (pixels of finger travel per asset slot).
# Used as a fallback when addon preferences are unavailable.
SCROLL_TRACKPAD_SENSITIVITY_DEFAULT = 120.0

# --- Smooth-scroll animation tunables -----------------------------------------
# The scroll position is `scroll_offset` (integer slot count) + `scroll_phase`
# (signed pixel offset along the active scroll axis). Trackpad input feeds the
# phase continuously; once |phase| >= one slot-step the integer offset advances
# and the phase is reduced by that step. After the user stops feeding events
# we coast on the recorded velocity (friction decay) and finally snap the
# phase to zero (which is automatically row-aligned because integer commits
# always advance by a full row in multi-row mode).
SCROLL_FRICTION = 7.0  # exponential decay rate for inertia (1/s)
SCROLL_MIN_VELOCITY = 25.0  # px/s; below this we hand off from inertia to snap
SCROLL_SNAP_RATE = 16.0  # exponential rate for snap-to-zero (1/s)
SCROLL_SETTLE_PX = 0.5  # px; below this the animation stops entirely
SCROLL_INPUT_GAP = 0.05  # s; idle gap before inertia takes over
SCROLL_DT_CAP = 0.1  # s; max frame dt (avoid jumps after lag spikes)
SCROLL_VELOCITY_SAMPLE = 0.06  # s; window over which trackpad velocity is averaged

# Smooth scroll relies on per-frame partial-row offsets that need the
# GPU scissor API (gpu.state.scissor_test_set / scissor_set) to clip
# top/bottom rows during the animation so they don't spill outside the
# asset bar. That API is reliably available from Blender 3.6+; on older
# versions we fall back to immediate integer-row scrolling.
SMOOTH_SCROLL_SUPPORTED = bpy.app.version >= (3, 6, 0) and hasattr(
    gpu.state, "scissor_test_set"
)
# Per wheel-notch velocity boost, expressed as a multiple of one slot per
# second. With v0 = step_px * SCROLL_WHEEL_NOTCH_VELOCITY and exponential
# friction decay at SCROLL_FRICTION, each notch glides ~one slot before
# inertia hands off to magnetic snap. Multiple rapid notches accumulate
# (clamped to SCROLL_WHEEL_MAX_NOTCH_STACK slots-worth of velocity) so a
# fast spin coasts proportionally further.
SCROLL_WHEEL_NOTCH_VELOCITY = 7.0  # = SCROLL_FRICTION; gives ~1 slot per notch
SCROLL_WHEEL_MAX_NOTCH_STACK = 6  # cap on stacked notch velocity (in slots)
# Direction-bias for the magnetic snap: when traveling forward we still snap
# forward to the next slot as long as we already crossed >= (1 - bias) of one
# slot, i.e. we bias the half-way decision boundary toward the travel
# direction. 0.0 = pure nearest-slot, 0.5 = always continue forward unless
# almost no progress, sane range ~0.2-0.35.
SCROLL_SNAP_DIRECTION_BIAS = 0.30

# Scroll buffer rows/cols rendered outside the visible bar so that fast
# inertial swipes have pre-positioned thumbnails to slide in. Bigger values
# preload more pages around the visible area at the cost of extra widget
# instances. Asset-button pool size is sized to fit these buffers (see
# `setup_widgets`).
SCROLL_BUFFER_ROWS = 3  # multi-row mode: extra rows above + below visible grid
SCROLL_BUFFER_COLS = 6  # single-row mode: extra cols on each side

# Scroll position indicator dimensions (in unscaled px; multiplied by UI scale).
SCROLL_INDICATOR_THICKNESS_PX = 3  # track / thumb thickness
SCROLL_INDICATOR_MIN_THUMB_PX = 8  # min thumb length so it stays visible

# Wheel event types we treat as scroll input. Direction is mapped per-event:
#   WHEELUPMOUSE / WHEELLEFTMOUSE   -> back    (negative step)
#   WHEELDOWNMOUSE / WHEELRIGHTMOUSE -> forward (positive step)
# Both vertical and horizontal wheel events drive the same logical axis,
# so the user can scroll the bar with whatever wheel their hardware emits.
_WHEEL_EVENT_TYPES = {
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELLEFTMOUSE",
    "WHEELRIGHTMOUSE",
}
_WHEEL_FORWARD = {"WHEELDOWNMOUSE", "WHEELRIGHTMOUSE"}


def get_area_height(self):
    ctx = getattr(self, "context", None)

    if isinstance(ctx, dict):
        ctx_dict = ctx
    elif isinstance(ctx, SimpleNamespace):
        ctx_dict = {
            "window": getattr(ctx, "window", None),
            "area": getattr(ctx, "area", None),
            "region": getattr(ctx, "region", None),
        }
    else:
        if ctx is None:
            ctx = bpy.context
        ctx_dict = {
            "window": getattr(ctx, "window", None),
            "area": getattr(ctx, "area", None),
            "region": getattr(ctx, "region", None),
        }

    self.context = ctx_dict

    region = ctx_dict.get("region")
    if region is not None:
        return region.height

    area = ctx_dict.get("area")
    if area is not None:
        return area.height

    return 100


BL_UI_Widget.get_area_height = get_area_height  # type: ignore[method-assign]


def modal_inside(self, context, event):
    ui_props = bpy.context.window_manager.blenderkitUI

    # Initialize mouse coordinates early so shortcut handling in the first modal
    # events does not fail on fresh operators (Blender 3.0 lacks these attrs).
    if not hasattr(self, "mouse_x") or not hasattr(self, "mouse_y"):
        self.mouse_x, self.mouse_y = self._event_coords_in_active_region(event)

    if ui_props.turn_off:
        ui_props.turn_off = False
        self.finish()

    if self._finished:
        return {"FINISHED"}

    if self.context:
        context = self.context

    # HANDLE PHOTO THUMBNAIL SWITCH
    if hasattr(self, "needs_tooltip_update") and self.needs_tooltip_update:
        self.needs_tooltip_update = False
        sr = search.get_search_results()
        if sr and self.active_index < len(sr):
            asset_data = sr[self.active_index]
            if asset_data["assetType"].lower() in {"printable", "model", "scene"}:
                if self.show_thumbnail_variant == "PHOTO":
                    photo_img = ui.get_full_photo_thumbnail(asset_data)
                    if photo_img:
                        self.tooltip_image.set_image(photo_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                elif self.show_thumbnail_variant == "THUMBNAIL":
                    wire_img = ui.get_full_wire_thumbnail(asset_data)
                    if wire_img:
                        self.tooltip_image.set_image(wire_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                else:
                    set_thumb_check(
                        self.tooltip_image, asset_data, thumb_type="thumbnail"
                    )

    if not context.area:
        self.finish()
        w, a, r = utils.get_largest_area(area_type="VIEW_3D")
        if a is not None:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
        return {"FINISHED"}

    is_quad_view = self._is_quad_view(context)
    if getattr(self, "_quad_view_state", None) != is_quad_view:
        self._quad_view_state = is_quad_view
        self.active_area_pointer = None  # force refresh of area/region pointers
        self.active_region_pointer = None
        self.finish()
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)
        return {"FINISHED"}

    # Update active viewport based on cursor location so the asset bar follows the
    # region the user is interacting with.
    self.update_active_view_from_cursor(context, event)

    sr = search.get_search_results()
    if sr is not None:
        # this check runs more search, useful especially for first search. Could be moved to a better place where the check
        # doesn't run that often.
        current_max_rows = self.get_requested_assetbar_rows()
        if (
            len(sr) - ui_props.scroll_offset
            < (ui_props.wcount * current_max_rows) + SEARCH_PREFETCH_LOOKAHEAD
        ):
            self.search_more()

    # Toggle overlay stats/text with animation playback
    is_playing = getattr(bpy.context.screen, "is_animation_playing", False)
    if is_playing != getattr(self, "_animation_playing", False):
        self._animation_playing = is_playing
        self._set_overlays(context, show=is_playing)

    time_diff = time.time() - self.update_timer_start
    if time_diff > self.update_timer_limit:
        self.update_timer_start = time.time()
        self.update_buttons()

        # progress bar
        for asset_button in self.asset_buttons:
            if not asset_button.visible:
                continue
            if sr is not None and len(sr) > asset_button.asset_index:
                asset_data = sr[asset_button.asset_index]
                if asset_data.get("placeholder"):
                    continue
                self.update_progress_bar(asset_button, asset_data)

    # Check for tab shortcut keys directly in the modal function
    if (
        event.ctrl
        and event.value == "PRESS"
        and self.panel.is_in_rect(self.mouse_x, self.mouse_y)
    ):
        if event.type == "T" and not event.shift:
            bk_logger.info("Ctrl+T pressed - add new tab")
            if hasattr(self, "new_tab_button"):  # Only if we can add more tabs
                self.add_new_tab(None)
            return {"RUNNING_MODAL"}
        elif event.type == "W" and not event.shift:
            bk_logger.info("Ctrl+W pressed - close tab")
            if len(global_vars.TABS["tabs"]) > 1:  # Don't close last tab
                self.remove_tab(self.close_tab_buttons[global_vars.TABS["active_tab"]])
            return {"RUNNING_MODAL"}
        elif event.type == "TAB":
            bk_logger.info("Ctrl+Tab pressed - switch tab")
            tabs = global_vars.TABS["tabs"]
            current = global_vars.TABS["active_tab"]
            if event.shift:
                # Go to previous tab
                new_index = (current - 1) % len(tabs)
            else:
                # Go to next tab
                new_index = (current + 1) % len(tabs)
            self.switch_to_history_step(new_index, tabs[new_index]["history_index"])
            return {"RUNNING_MODAL"}
        elif event.type in {
            "ONE",
            "TWO",
            "THREE",
            "FOUR",
            "FIVE",
            "SIX",
            "SEVEN",
            "EIGHT",
            "NINE",
        }:
            # Convert numkey to index (0-based)
            tab_idx = {
                "ONE": 0,
                "TWO": 1,
                "THREE": 2,
                "FOUR": 3,
                "FIVE": 4,
                "SIX": 5,
                "SEVEN": 6,
                "EIGHT": 7,
                "NINE": 8,
            }[event.type]

            if tab_idx < len(global_vars.TABS["tabs"]):
                bk_logger.info(
                    "Ctrl+%d pressed - go to tab %d", tab_idx + 1, tab_idx + 1
                )
                self.switch_to_history_step(
                    tab_idx, global_vars.TABS["tabs"][tab_idx]["history_index"]
                )
            return {"RUNNING_MODAL"}

    # Handle Alt+Left/Right for history navigation
    elif (
        event.alt
        and event.value == "PRESS"
        and self.panel.is_in_rect(self.mouse_x, self.mouse_y)
    ):
        if event.type == "LEFT_ARROW":
            bk_logger.info("Alt+Left pressed - history back")
            active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
            if active_tab["history_index"] > 0:
                self.history_back(None)  # None instead of widget
            return {"RUNNING_MODAL"}
        elif event.type == "RIGHT_ARROW":
            bk_logger.info("Alt+Right pressed - history forward")
            active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
            if active_tab["history_index"] < len(active_tab["history"]) - 1:
                self.history_forward(None)  # None instead of widget
            return {"RUNNING_MODAL"}

    # ANY EVENT ACTIVATED = DON'T LET EVENTS THROUGH
    # While asset drag operator is active, do not consume pointer events here.
    # Otherwise the assetbar can starve the drag operator from MOUSEMOVE events,
    # especially with multiple windows/monitors.
    if ui_props.dragging:
        return {"PASS_THROUGH"}

    if self.handle_widget_events(event):
        return {"RUNNING_MODAL"}

    if event.type in {"ESC"} and event.value == "PRESS":
        # just escape dragging when dragging, not appending.
        if not ui_props.dragging:
            self.finish()

            # return {"FINISHED"} # we can jump out immediately

    self.mouse_x, self.mouse_y = self._event_coords_in_active_region(event)

    # Smooth-scroll animation tick. Runs every TIMER while inertia or snap
    # is in flight; cheap no-op once settled.
    if self._scroll_animating and event.type == "TIMER":
        self._smooth_scroll_tick(time.time())

    # SCROLL INPUT
    # All scroll-like input (vertical wheel, horizontal/tilt wheel, trackpad pan)
    # is routed through a single handler. Axis of motion is determined purely
    # by layout mode:
    #   - multi-row  (hcount > 1)  -> vertical input drives scrolling
    #   - single-row (hcount == 1) -> horizontal input drives scrolling
    # We always grab these events when the cursor is over the asset bar,
    # regardless of source, so the bar feels responsive to every input device.
    # Wheel and trackpad events never arrive in the same event so there is no
    # double-step risk.
    if self._handle_scroll_event(context, event):
        return {"RUNNING_MODAL"}

    if self.check_ui_resized(context):
        # Force a clean rebuild when the viewport size changes.
        if not getattr(self, "_restart_pending", False):
            self._restart_pending = True
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.assetbar_on = False
            ui_props.turn_off = True
            self.restart_asset_bar()
        return {"FINISHED"}

    if self.check_new_search_results(context) or self.check_region_changed(context):
        self._refresh_layout(context)
        # also update tooltip visibility
        # if there's less results and active button is not visible, hide tooltip
        # happened only when e.g. running new search from web browser (copying assetbaseid to clipboard)
        # fixes issue #1766
        if self.active_index >= len(search.get_search_results()):
            self.hide_tooltip()
        self.scroll_update(
            always=True
        )  # one extra update for scroll for correct redraw, updates all buttons

    # this was here to check if sculpt stroke is running, but obviously that didn't help,
    #  since the RELEASE event is caught by operator and thus there is no way to detect a stroke has ended...
    if bpy.context.mode in ("SCULPT", "PAINT_TEXTURE"):
        if (
            event.type == "MOUSEMOVE"
        ):  # ASSUME THAT SCULPT OPERATOR ACTUALLY STEALS THESE EVENTS,
            # SO WHEN THERE ARE SOME WE CAN APPEND BRUSH...
            bpy.context.window_manager["appendable"] = True
        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                bpy.context.window_manager["appendable"] = False
    return {"PASS_THROUGH"}


def asset_bar_modal(self, context, event):
    return modal_inside(self, context, event)


def asset_bar_invoke(self, context, event):
    # sprinkling of black magic
    result = self.on_invoke(context, event)
    if not result:
        return {"CANCELLED"}
    if not context.window:
        return {"CANCELLED"}
    if not context.area:
        return {"CANCELLED"}

    args = (self, context)

    self.register_handlers(args, context)

    self.update_timer_limit = 0.5
    self.update_timer_start = time.time()
    # Fast timer so the scroll animation can tick smoothly even when the
    # user is not producing any other events (post-release momentum, wheel
    # decay, etc.). Heavy per-tick work is still gated by `update_timer_limit`.
    self._timer = context.window_manager.event_timer_add(1 / 60, window=context.window)

    context.window_manager.modal_handler_add(self)
    global active_area_pointer
    self.active_window_pointer = context.window.as_pointer()
    self.active_area_pointer = context.area.as_pointer()
    active_area_pointer = self.active_area_pointer
    self.active_region_pointer = context.region.as_pointer()
    self.operator_area_pointer = self.active_area_pointer
    self.operator_region_pointer = self.active_region_pointer
    self._active_area_ref = context.area
    self._active_region_ref = context.region

    return {"RUNNING_MODAL"}


asset_bar_operator = None


def get_author_tooltip_data(asset_data):
    """Build tooltip_data for an author-type search result."""
    author_id = int(asset_data.get("id", asset_data.get("author", {}).get("id", 0)))
    author = global_vars.BKIT_AUTHORS.get(author_id)

    display_name = asset_data.get("displayName", "")
    about_me = ""
    if author:
        about_me = getattr(author, "aboutMe", "") or ""
    # Fallback: get aboutMe directly from the author sub-object in the result
    if not about_me:
        about_me = asset_data.get("author", {}).get("aboutMe", "") or ""

    # Asset count from ratingsSum
    ratings_sum = asset_data.get("ratingsSum", {})
    asset_count = ratings_sum.get("assetCount", 0)

    asset_data["tooltip_data"] = {
        "aname": display_name,
        "author_text": "",
        "quality": "-",
        "about_me": about_me,
        "asset_count": asset_count,
        "is_author": True,
        "user_price_text": "",
        "base_price_text": "",
        "user_price_color": colors.WHITE,
        "base_price_color": colors.WHITE,
        "user_price_bg_color": colors.GRAY,
        "base_price_bg_color": colors.GRAY,
    }


def get_tooltip_data(asset_data):
    tooltip_data = asset_data.get("tooltip_data")
    if tooltip_data is not None:
        return

    if asset_data.get("assetType") == "author":
        return get_author_tooltip_data(asset_data)

    author_text = ""
    if global_vars.BKIT_AUTHORS:
        author_id = int(asset_data["author"]["id"])
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author:
            if len(author.firstName) > 0 or len(author.lastName) > 0:
                author_text = f"by {author.firstName} {author.lastName}"
        else:
            bk_logger.warning("get_tooltip_data() AUTHOR NOT FOUND: %s", author_id)

    aname = asset_data["displayName"]
    if len(aname) == 0:
        # this shouldn't happen, but obviously did on server in addons section.
        aname = ""
    else:
        aname = aname[0].upper() + aname[1:]
    if len(aname) > 36:
        aname = f"{aname[:33]}..."

    rc = asset_data.get("ratingsCount")
    show_rating_threshold = 0
    rcount = 0
    quality = "-"
    if rc:
        rcount = min(rc.get("quality", 0), rc.get("workingHours", 0))
    if rcount > show_rating_threshold:
        quality = str(round(asset_data["ratingsAverage"].get("quality")))

    # Add pricing information
    base_price_text = ""
    user_price_text = ""

    user_price_color = colors.WHITE
    base_price_color = colors.WHITE

    user_price_bg_color = colors.GRAY
    base_price_bg_color = colors.GRAY

    # Check if asset is free or paid (works for all asset types)
    is_free = asset_data.get("isFree", True)
    can_download = asset_data.get("canDownload", True)

    if asset_data.get("assetType") == "addon":
        # Get pricing info from extensions cache.
        # Pricing info is shown only for add-ons.
        base_price_text = asset_data.get("basePrice")
        user_price_text = asset_data.get("userPrice")
        is_for_sale = asset_data.get("isForSale")

        # for debug show both prices always
        if utils.profile_is_validator():
            if (
                user_price_text
                and base_price_text
                and str(user_price_text) != str(base_price_text)
            ):
                # Sale: show discounted price + strikethrough original
                user_price_text = f" ${user_price_text} "
                user_price_color = colors.WHITE
                user_price_bg_color = colors.PURPLE_PRICE

                base_price_text = f" ${base_price_text} "
                base_price_color = colors.TEXT_DIM
                base_price_bg_color = colors.PURPLE_PRICE
            elif base_price_text:
                # No sale or only base price available
                base_price_text = f" ${base_price_text} "
                base_price_color = colors.WHITE
                base_price_bg_color = colors.PURPLE_PRICE

                user_price_text = ""
            elif user_price_text:
                user_price_text = f" ${user_price_text} "
                user_price_color = colors.WHITE
                user_price_bg_color = colors.PURPLE_PRICE

                base_price_text = ""
            else:
                user_price_text = ""
                base_price_text = ""
        else:
            if is_for_sale and not can_download and user_price_text and base_price_text:
                user_price_text = f" ${user_price_text} "
                user_price_bg_color = colors.PURPLE_PRICE
                user_price_color = colors.WHITE

                base_price_text = f" (${base_price_text}) "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.TEXT_DIM

            elif is_for_sale and not can_download and base_price_text:
                base_price_text = f" ${base_price_text} "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.WHITE

                user_price_text = ""

            elif not is_free and not is_for_sale:
                base_price_text = " Full Plan "
                base_price_bg_color = colors.ORANGE_FULL
                base_price_color = colors.WHITE

                user_price_text = ""

            elif is_for_sale and can_download:
                # purchased, so we dont show price anymore
                base_price_text = f" Purchased "
                base_price_bg_color = colors.PURPLE_PRICE
                base_price_color = colors.WHITE

                user_price_text = ""

    tooltip_data = {
        "aname": aname,
        "author_text": author_text,
        "quality": quality,
        # --- colors for price texts and backgrounds
        "user_price_text": user_price_text,
        "base_price_text": base_price_text,
        "user_price_color": user_price_color,
        "base_price_color": base_price_color,
        "user_price_bg_color": user_price_bg_color,
        "base_price_bg_color": base_price_bg_color,
    }
    asset_data["tooltip_data"] = tooltip_data


def set_thumb_check(
    element: Union[BL_UI_Button, BL_UI_Image],
    asset: Dict[str, Any],
    thumb_type: str = "thumbnail_small",
) -> bool:
    """Set image in case it is loaded in search results. Checks global_vars.DATA["images available"].
    - if image download failed, it will be set to 'thumbnail_not_available.jpg'
    - if image doesn't exist, it will be set to 'thumbnail_notready.jpg'

    Returns:
        True if the slot is showing its real/intended thumbnail (loaded, gravatar,
        or definitively "not available"). False when the slot is still showing the
        transient "loading" placeholder - callers should suppress overlay badges
        in that case to avoid drawing stale badges over not-yet-loaded items.
    """
    # Placeholder entries from prefetch get the "not ready" thumbnail
    if asset.get("placeholder"):
        tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        if element.get_image_path() != tpath:
            element.set_image(tpath)
            element.set_image_colorspace("")
        return False

    # Author assets have no server thumbnails, use gravatar from BKIT_AUTHORS
    if asset.get("assetType") == "author":
        author_id = int(asset.get("id", asset.get("author", {}).get("id", 0)))
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author and author.gravatarImg:
            if element.get_image_path() != author.gravatarImg:
                element.set_image(author.gravatarImg)
                element.set_image_colorspace("")
            return True
        tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        if element.get_image_path() != tpath:
            element.set_image(tpath)
            element.set_image_colorspace("")
        return False

    directory = paths.get_temp_dir("%s_search" % asset["assetType"])
    tpath = os.path.join(directory, asset[thumb_type])

    if element.get_image_path() == tpath:
        return True  # already showing the real thumbnail

    image_ready = global_vars.DATA["images available"].get(tpath)
    loaded = True
    if image_ready is None:
        tpath = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        loaded = False
    if image_ready is False or asset[thumb_type] == "":
        # "not available" is a terminal state - treat as loaded so the
        # badges (e.g. locked icon) can be shown over the fallback image.
        tpath = paths.get_addon_thumbnail_path("thumbnail_not_available.jpg")
        loaded = True

    if element.get_image_path() == tpath:
        return loaded
    element.set_image(tpath)
    element.set_image_colorspace("")
    return loaded


class BlenderKitAssetBarOperator(BL_UI_OT_draw_operator):
    """Blendkit Asset Bar Operator."""

    bl_idname = "view3d.blenderkit_asset_bar_widget"
    bl_label = "Blendkit asset bar refresh"
    bl_description = "Blendkit asset bar refresh"
    bl_options = {"REGISTER"}
    instances: list["BlenderKitAssetBarOperator"] = []
    _requested_rows_override: Optional[int]

    do_search: BoolProperty(  # type: ignore[valid-type]
        name="Run Search", description="", default=True, options={"SKIP_SAVE"}
    )
    keep_running: BoolProperty(  # type: ignore[valid-type]
        name="Keep Running", description="", default=True, options={"SKIP_SAVE"}
    )

    category: StringProperty(  # type: ignore[valid-type]
        name="Category",
        description="search only subtree of this category",
        default="",
        options={"SKIP_SAVE"},
    )

    tooltip: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    show_thumbnail_variant: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Show Thumbnail Variant",
        description="Toggle between normal, photo and wireframe thumbnail - use [ or ] to cycle through thumbnails. Currently used only for printables, models, and scenes.",
        default="THUMBNAIL",
        items=[
            ("THUMBNAIL", "Thumbnail", "Normal thumbnail"),
            ("PHOTO", "Photo", "Photo thumbnail"),
            ("WIREFRAME", "Wireframe", "Wireframe thumbnail"),
        ],
        options={"SKIP_SAVE"},
    )

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _resolve_window(self, context):
        return getattr(context, "window", None) or bpy.context.window

    def _validated_area(self, area):
        if area is None:
            return None
        try:
            area.as_pointer()
        except ReferenceError:
            return None
        return area

    def _validated_region(self, region):
        if region is None:
            return None
        try:
            region.as_pointer()
        except ReferenceError:
            return None
        return region

    def _safe_space_data(self, area):
        if area is None:
            return None
        try:
            return area.spaces.active
        except ReferenceError:
            return None

    def _build_context_snapshot(self, context, area=None, region=None):
        area = self._validated_area(area) or self._validated_area(
            getattr(context, "area", None)
        )
        region = self._validated_region(region) or self._validated_region(
            getattr(context, "region", None)
        )
        return SimpleNamespace(
            window=self._resolve_window(context),
            area=area,
            region=region,
            space_data=self._safe_space_data(area),
        )

    def _unwrap_area_region(self, ctx):
        if isinstance(ctx, dict):
            return ctx.get("area"), ctx.get("region")
        return getattr(ctx, "area", None), getattr(ctx, "region", None)

    def _current_area_region(self):
        """Return the currently active area and region with sensible fallbacks."""
        area = self._validated_area(getattr(self, "_active_area_ref", None))
        region = self._validated_region(getattr(self, "_active_region_ref", None))

        ctx_area, ctx_region = self._unwrap_area_region(getattr(self, "context", None))
        if area is None:
            area = self._validated_area(ctx_area)
        if region is None:
            region = self._validated_region(ctx_region)

        if area is None:
            area = self._validated_area(getattr(bpy.context, "area", None))
        if region is None:
            region = self._validated_region(getattr(bpy.context, "region", None))

        return area, region

    def _current_layout_context(self):
        area, region = self._current_area_region()
        return self._build_context_snapshot(bpy.context, area, region)

    def _get_row_limit(self) -> int:
        wcount = getattr(self, "wcount", 0)
        if wcount > 0:
            return math.ceil(ASSETBAR_MAX_VISIBLE_ASSETS / wcount)
        return ASSETBAR_MAX_VISIBLE_ASSETS

    def _get_height_limited_rows(self, context=None) -> int:
        context = (
            context
            or getattr(self, "_override_context", None)
            or self._current_layout_context()
        )
        region = getattr(context, "region", None)
        if region is None or getattr(self, "button_size", 0) <= 0:
            return self._get_row_limit()
        available_height = (
            region.height
            - self.bar_y
            - 2 * self.assetbar_margin
            - self.other_button_size
        )
        max_rows_by_height = math.floor(available_height / self.button_size)
        return max(1, min(self._get_row_limit(), max_rows_by_height))

    def clamp_assetbar_rows(self, rows: int, context=None) -> int:
        return max(1, min(rows, self._get_height_limited_rows(context)))

    def get_expanded_assetbar_rows(self) -> int:
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        return self.clamp_assetbar_rows(
            max(2, int(user_preferences.maximized_assetbar_rows))
        )

    def get_requested_assetbar_rows(self) -> int:
        override_rows = getattr(self, "_requested_rows_override", None)
        if override_rows is not None:
            return self.clamp_assetbar_rows(int(override_rows))
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        if not user_preferences.assetbar_expanded:
            return 1
        return self.get_expanded_assetbar_rows()

    def _resolve_layout_rows(self, user_preferences):
        """Resolve ``(expanded, max_rows)`` for the asset bar layout.

        Honors a live resize-drag preview: while the user drags the bottom
        handle, ``_requested_rows_override`` holds the previewed (already
        clamped) row count, so feed that into the layout instead of the saved
        preference and the bar reflows live. ``apply_assetbar_rows`` writes the
        preference and clears the override when the drag ends.
        """
        rows_override = getattr(self, "_requested_rows_override", None)
        if rows_override is not None:
            return rows_override > 1, max(2, int(rows_override))
        return (
            bool(user_preferences.assetbar_expanded),
            int(user_preferences.maximized_assetbar_rows),
        )

    def get_assetbar_rows_from_drag(
        self, start_rows: int, start_mouse_y: int, current_mouse_y: int
    ) -> int:
        """Translate vertical mouse drag distance into a target row count."""
        if getattr(self, "button_size", 0) <= 0:
            return self.clamp_assetbar_rows(start_rows)
        row_delta = int(
            round((start_mouse_y - current_mouse_y) / max(float(self.button_size), 1.0))
        )
        return self.clamp_assetbar_rows(start_rows + row_delta)

    def update_expand_button_icon(self):
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        self.button_expand.text = "▲" if user_preferences.assetbar_expanded else "▼"

    def _cursor_window(self):
        context_window = getattr(bpy.context, "window", None)
        if context_window is not None:
            return context_window
        try:
            return self.window
        except ReferenceError:
            return None

    def set_resize_hover_cursor(self):
        if self._resize_dragging:
            return
        window = self._cursor_window()
        if window is None:
            return
        window.cursor_set(ASSETBAR_RESIZE_CURSOR)

    def set_resize_drag_cursor(self):
        window = self._cursor_window()
        if window is None:
            return
        window.cursor_modal_set(ASSETBAR_RESIZE_CURSOR)
        self._resize_cursor_modal_active = True

    def restore_resize_cursor(self, *, hovering=False):
        window = self._cursor_window()
        if window is None:
            return
        if self._resize_cursor_modal_active:
            window.cursor_modal_restore()
            self._resize_cursor_modal_active = False
        cursor_name = (
            ASSETBAR_RESIZE_CURSOR
            if hovering and not self._resize_dragging
            else "DEFAULT"
        )
        window.cursor_set(cursor_name)

    def _get_resize_rows_from_mouse_y(self, mouse_y: int) -> int:
        return self.get_assetbar_rows_from_drag(
            self._resize_drag_start_rows, self._resize_drag_start_y, mouse_y
        )

    def on_resize_handle_enter(self, handle):
        if self._resize_dragging:
            return
        self.set_resize_hover_cursor()

    def on_resize_handle_exit(self, handle):
        if self._resize_dragging:
            return
        self.restore_resize_cursor()

    def on_resize_drag_begin(self, handle, start_y: int):
        self._resize_drag_start_rows = self.get_requested_assetbar_rows()
        self._resize_drag_start_y = start_y
        self.begin_resize_drag()
        self.set_resize_drag_cursor()

    def on_resize_drag_update(self, handle, y: int):
        self.preview_assetbar_rows(self._get_resize_rows_from_mouse_y(y))

    def on_resize_drag_end(self, handle, y: int, *, hovering: bool):
        self.apply_assetbar_rows(self._get_resize_rows_from_mouse_y(y))
        self.end_resize_drag(hovering=hovering)

    def on_resize_handle_click(self, handle):
        self.toggle_assetbar_rows()
        self.restore_resize_cursor(hovering=True)

    def begin_resize_drag(self):
        self._resize_dragging = True
        self.hide_tooltip()

    def end_resize_drag(self, *, hovering: bool):
        self._resize_dragging = False
        self.restore_resize_cursor(hovering=hovering)

    def preview_assetbar_rows(self, rows: int):
        rows = self.clamp_assetbar_rows(rows)
        if rows == self.get_requested_assetbar_rows():
            return
        self._requested_rows_override = rows
        self._refresh_layout(self._current_layout_context())
        self._redraw_tracked_regions()

    def apply_assetbar_rows(self, rows: int):
        rows = self.clamp_assetbar_rows(rows)
        self._requested_rows_override = None
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        if rows > 1 and user_preferences.maximized_assetbar_rows != rows:
            user_preferences.maximized_assetbar_rows = rows
        if rows <= 1 and user_preferences.maximized_assetbar_rows < 2:
            user_preferences.maximized_assetbar_rows = 2
        user_preferences.assetbar_expanded = rows > 1
        self._refresh_layout(self._current_layout_context())
        self.update_expand_button_icon()
        self._redraw_tracked_regions()

    def toggle_assetbar_rows(self):
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        if user_preferences.assetbar_expanded:
            self.apply_assetbar_rows(1)
            return
        self.apply_assetbar_rows(self.get_expanded_assetbar_rows())

    def _reset_resize_state(self):
        self._requested_rows_override = None
        self._resize_dragging = False
        self._resize_cursor_modal_active = False
        self._resize_drag_start_rows = 1
        self._resize_drag_start_y = 0

    def _event_window_coords(self, event):
        if not hasattr(event, "mouse_x") or not hasattr(event, "mouse_y"):
            return None, None
        return getattr(event, "mouse_x", None), getattr(event, "mouse_y", None)

    def _apply_widget_context(self, override_ctx):
        """Apply the given override context to all widgets in the asset bar.

        All widgets get the new context,
        except for the main panel and tooltip panel (and their children).
        """
        self._override_context = override_ctx
        if not hasattr(self, "widgets"):
            return
        panel = getattr(self, "panel", None)
        panel_children = (
            set(panel.widgets) if isinstance(panel, BL_UI_Drag_Panel) else set()
        )
        tooltip_panel = getattr(self, "tooltip_panel", None)
        tooltip_children = (
            set(self.tooltip_widgets) if hasattr(self, "tooltip_widgets") else set()
        )

        for widget in self.widgets:
            widget.context = override_ctx
            if (
                widget is panel
                or widget in panel_children
                or widget is tooltip_panel
                or widget in tooltip_children
            ):
                continue
            widget.update(widget.x, widget.y)

        if isinstance(panel, BL_UI_Drag_Panel):
            panel.update(panel.x, panel.y)
            panel.layout_widgets()

        if isinstance(tooltip_panel, BL_UI_Drag_Panel):
            tooltip_panel.update(tooltip_panel.x, tooltip_panel.y)
            tooltip_panel.layout_widgets()

    def _find_area_region_from_event(self, context, event):
        x, y = self._event_window_coords(event)
        if x is None or y is None:
            return None, None

        screen = getattr(self._resolve_window(context), "screen", None)
        if screen is None:
            return None, None

        for area in screen.areas:
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            if not (
                area.x <= x < area.x + area.width and area.y <= y < area.y + area.height
            ):
                continue

            target_region = None
            fallback_region = None
            for region in viewport_utils.iter_view3d_window_regions(area):
                if fallback_region is None:
                    fallback_region = region
                if (
                    region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height
                ):
                    target_region = region
                    break

            return area, target_region or fallback_region

        return None, None

    def _cursor_inside_active_area(self, event):
        # return False
        area = self._validated_area(getattr(self, "_active_area_ref", None))
        if area is None:
            return False

        x, y = self._event_window_coords(event)
        if x is None or y is None:
            return False

        if not (
            area.x <= x < area.x + area.width and area.y <= y < area.y + area.height
        ):
            return False

        region = self._validated_region(getattr(self, "_active_region_ref", None))
        if region is None:
            return True

        return (
            region.x <= x < region.x + region.width
            and region.y <= y < region.y + region.height
        )

    def _view_changed(
        self,
        area_pointer,
        region_pointer,
        previous_area_pointer,
        previous_region_pointer,
    ):
        return (
            previous_area_pointer != area_pointer
            or previous_region_pointer != region_pointer
        )

    def _store_active_view(self, context, area, region, area_pointer, region_pointer):
        self.active_area_pointer = area_pointer
        self.active_region_pointer = region_pointer
        global active_area_pointer
        active_area_pointer = area_pointer
        self._active_area_ref = area
        self._active_region_ref = region
        self.context = context

    def _refresh_layout(self, override_ctx):
        self.update_assetbar_sizes(override_ctx)
        self.update_tooltip_size(override_ctx)
        try:
            self.update_assetbar_layout(override_ctx)
            self.update_tooltip_layout(override_ctx)
            if hasattr(self, "tooltip_panel"):
                self.tooltip_panel.layout_widgets()
        except Exception as e:
            bk_logger.log(
                1, "Error updating asset bar layout, some objects may be missing. %s", e
            )

    def _safe_tag_redraw(self, region):
        if region is None:
            return
        try:
            region.tag_redraw()
        except ReferenceError:
            pass

    def _tag_regions_for_redraw(self, current_region, previous_region_ref):
        self._safe_tag_redraw(current_region)
        if previous_region_ref and previous_region_ref is not current_region:
            self._safe_tag_redraw(previous_region_ref)

    def _switch_active_view(self, context, area, region, *, force=True):
        """Switch the active area/region the asset bar is attached to.

        If `force` is True, the switch is applied even if the area/region
        pointers match the previously stored ones.
        """
        area = self._validated_area(area)
        region = self._validated_region(region)
        if area is None or region is None:
            return

        self.area = area
        self.region = region

        area_pointer = area.as_pointer()
        region_pointer = region.as_pointer()
        previous_area_pointer = getattr(self, "active_area_pointer", None)
        previous_region_pointer = getattr(self, "active_region_pointer", None)
        previous_region_ref = getattr(self, "_active_region_ref", None)

        self._store_active_view(context, area, region, area_pointer, region_pointer)

        override_ctx = self._build_context_snapshot(context, area, region)
        self._apply_widget_context(override_ctx)

        if force or self._view_changed(
            area_pointer,
            region_pointer,
            previous_area_pointer,
            previous_region_pointer,
        ):
            # Rebuild sizes/layout whenever we truly jump to a different area (or
            # the caller explicitly requests it) so the bar respects the new
            # region dimensions/UI scale. Plain cursor moves within the same view
            # keep the old layout for performance.
            self._refresh_layout(override_ctx)

        # Explicitly request redraws so the handler updates in the new region and
        # the previous one releases its stale widgets.
        self._tag_regions_for_redraw(region, previous_region_ref)

    def _redraw_tracked_regions(self):
        """Request redraw on any region the operator stored explicitly."""
        _, stored_region = self._unwrap_area_region(getattr(self, "context", None))
        regions = {
            self._validated_region(getattr(self, "_active_region_ref", None)),
            self._validated_region(
                getattr(getattr(self, "_override_context", None), "region", None)
            ),
            self._validated_region(stored_region),
        }

        for region in regions:
            self._safe_tag_redraw(region)

    def update_active_view_from_cursor(self, context, event):
        """Update the active area/region based on the current cursor location.

        This makes the asset bar follow the user's cursor as they move between
        different 3D viewports.
        """
        if event.type not in {"TIMER", "MOUSEMOVE"}:
            return

        user_prefs = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        follow_cursor = getattr(user_prefs, "assetbar_follows_cursor", True)

        if not follow_cursor and not self._is_quad_view(context):
            return

        area, region = self._find_area_region_from_event(context, event)
        if area is None or region is None:
            return

        # In quad view, only the perspective pane should host the asset bar. Keep the
        # legacy "follow any quad" behavior here for potential reuse:
        # if self._is_quad_view(context) and self._cursor_inside_active_area(event):
        #     return
        if self._is_quad_view(context) and not self._is_perspective_region(region):
            return

        # When follow is disabled, allow switching only within the same area; in quad
        # view this lets the bar appear in the hovered quad without jumping across
        # different 3D view areas.
        if not follow_cursor:
            active_area = self._validated_area(getattr(self, "_active_area_ref", None))
            if (
                active_area is not None
                and area.as_pointer() != active_area.as_pointer()
            ):
                return

        if self._cursor_inside_active_area(event):
            return

        self._switch_active_view(context, area, region)

    def _event_coords_in_active_region(self, event):
        region = self._validated_region(getattr(self, "_active_region_ref", None))
        if region is not None:
            x, y = self._event_window_coords(event)
            if x is not None and y is not None:
                return x - region.x, y - region.y

        return getattr(event, "mouse_region_x", 0), getattr(event, "mouse_region_y", 0)

    @classmethod
    def description(cls, context, properties):
        """Get the description for the asset bar operator."""
        return properties.tooltip

    def new_text(self, text, x, y, width=100, height=15, text_size=None, halign="LEFT"):
        """Create a new text label widget."""
        label = BL_UI_Label(x, y, width, height)
        label.text = text
        if text_size is None:
            text_size = 14
        label.text_size = text_size
        label.text_color = self.text_color
        label._halign = halign
        return label

    def new_duo_text(
        self,
        text_a,
        x,
        y,
        text_b="",
        width=100,
        height=15,
        text_size=None,
        halign="LEFT",
    ):
        """Create a new text label widget."""
        label = BL_UI_DuoLabel(x, y, width, height)
        label.use_rounded_background = True
        label.background_corner_radius = "50%"
        label.background_padding = (4, 4)
        label.text_a = text_a
        label.text_b = text_b
        if text_size is None:
            text_size = 14
        label.text_size = text_size
        label.text_a_color = self.text_color
        label.text_b_color = self.text_color

        label._halign = halign
        return label

    # region tooltip
    def init_tooltip(self):
        """Initialize the tooltip panel and its widgets."""
        self.tooltip_widgets = []
        self._tooltip_available_height = None
        if not hasattr(self, "tooltip_size"):
            self.tooltip_size = int(self.tooltip_base_size_pixels)
        self.tooltip_scale = getattr(self, "tooltip_scale", 1.0)

        # Fallbacks in case update_tooltip_size was not called yet
        self.tooltip_width = getattr(self, "tooltip_width", self.tooltip_size)
        image_height = getattr(self, "tooltip_image_height", self.tooltip_size)
        info_height = getattr(
            self,
            "tooltip_info_height",
            max(
                int(image_height * self.bottom_panel_fraction),
                self.asset_name_text_size * 3,
            ),
        )
        self.tooltip_image_height = image_height
        self.tooltip_info_height = info_height
        self.tooltip_height = self.tooltip_image_height + self.tooltip_info_height
        self.labels_start = self.tooltip_image_height

        # total_size = tooltip# + 2 * self.margin
        self.tooltip_panel = BL_UI_Drag_Panel(
            0, 0, self.tooltip_width, self.tooltip_height
        )
        self.tooltip_panel.bg_color = (0.0, 0.0, 0.0, 0.5)
        self.tooltip_panel.use_rounded_background = True
        self.tooltip_panel.background_corner_radius = ROUNDING_RADIUS
        self.tooltip_panel.visible = False

        tooltip_image = BL_UI_Image(0, 0, 1, 1)
        img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        tooltip_image.set_image(img_path)
        tooltip_image.set_image_size((self.tooltip_width, self.tooltip_image_height))
        tooltip_image.set_image_position((0, 0))
        tooltip_image.set_image_colorspace("")
        tooltip_image.background = False
        tooltip_image.bg_color = (0.0, 0.0, 0.0, 0.0)
        tooltip_image.use_rounded_background = True
        tooltip_image.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.tooltip_image = tooltip_image
        self.tooltip_widgets.append(tooltip_image)

        tooltip_image_help = self.new_text(
            "Left click to append. Right click for menu.",
            self.tooltip_margin,
            self.tooltip_image_height - self.tooltip_margin - self.author_text_size,
            height=self.author_text_size,
            text_size=self.author_text_size,
        )
        tooltip_image_help.text_color = (1.0, 0.6, 0.6, 0.9)
        tooltip_image_help.visible = False
        self.tooltip_image_help = tooltip_image_help
        self.tooltip_widgets.append(self.tooltip_image_help)

        dark_panel = BL_UI_Widget(
            0,
            self.labels_start,
            self.tooltip_width,
            self.tooltip_info_height,
        )
        dark_panel.bg_color = (0.0, 0.0, 0.0, 0.7)
        dark_panel.use_rounded_background = True
        dark_panel.background_corner_radius = (0, 0, ROUNDING_RADIUS, ROUNDING_RADIUS)
        self.tooltip_dark_panel = dark_panel
        self.tooltip_widgets.append(dark_panel)

        name_label = self.new_text(
            "",
            self.tooltip_margin,
            self.labels_start + self.tooltip_margin,
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        self.asset_name = name_label
        self.tooltip_widgets.append(name_label)

        self.gravatar_size = max(
            int(self.tooltip_info_height - 2 * self.tooltip_margin),
            self.asset_name_text_size,
        )

        authors_name = self.new_text(
            "author",
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.author_text_size - self.tooltip_margin,
            self.labels_start,
            height=self.author_text_size,
            text_size=self.author_text_size,
            halign="RIGHT",
        )
        self.authors_name = authors_name
        self.tooltip_widgets.append(authors_name)

        gravatar_image = BL_UI_Image(
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.gravatar_size - self.tooltip_margin,
            1,
            1,
        )
        img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
        gravatar_image.set_image(img_path)
        gravatar_image.set_image_size(
            (
                self.gravatar_size,
                self.gravatar_size,
            )
        )
        gravatar_image.set_image_position((0, 0))
        gravatar_image.set_image_colorspace("")
        gravatar_image.background_corner_radius = (
            0,
            0,
            ROUNDING_RADIUS / 2,
            0,
        )
        self.gravatar_image = gravatar_image
        self.tooltip_widgets.append(gravatar_image)

        quality_star = BL_UI_Image(
            self.tooltip_margin,
            self.tooltip_height - self.tooltip_margin - self.asset_name_text_size,
            1,
            1,
        )
        img_path = paths.get_addon_thumbnail_path("star_grey.png")
        quality_star.set_image(img_path)
        quality_star.set_image_size(
            (self.asset_name_text_size, self.asset_name_text_size)
        )
        quality_star.set_image_position((0, 0))
        self.quality_star = quality_star
        self.tooltip_widgets.append(quality_star)

        quality_label = self.new_text(
            "",
            2 * self.tooltip_margin + self.asset_name_text_size,
            self.tooltip_height - int(self.asset_name_text_size + self.tooltip_margin),
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        self.tooltip_widgets.append(quality_label)
        self.quality_label = quality_label

        # Add user/base price label for addons
        multi_price_label = self.new_duo_text(
            "",
            self.tooltip_margin,
            self.tooltip_height
            - int(self.asset_name_text_size + 2 * self.tooltip_margin),
            height=self.asset_name_text_size,
            text_size=self.asset_name_text_size,
        )
        multi_price_label.use_rounded_background = True
        multi_price_label.background_corner_radius = "50%"
        multi_price_label.text_a_color = colors.WHITE
        multi_price_label.text_b_color = colors.TEXT_DIM
        self.multi_price_label = multi_price_label
        self.tooltip_widgets.append(self.multi_price_label)

        # Author about-me label (multiline, used only for author-type results)
        author_about_me = self.new_text(
            "",
            self.tooltip_margin,
            self.labels_start
            + self.tooltip_margin
            + self.asset_name_text_size
            + self.tooltip_margin,
            height=self.author_text_size,
            text_size=self.author_text_size,
        )
        author_about_me.multiline = True
        author_about_me.visible = False
        self.author_about_me = author_about_me
        self.tooltip_widgets.append(author_about_me)

        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        offset = 0
        if (
            user_preferences.asset_popup_counter
            < user_preferences.asset_popup_counter_max
        ) or utils.profile_is_validator():
            # this is shown only to users who don't know yet about the popup card.
            label = self.new_text(
                "Right click for menu.",
                self.tooltip_margin,
                self.tooltip_height + self.tooltip_margin,
                height=self.author_text_size,
                text_size=self.author_text_size,
            )
            self.tooltip_widgets.append(label)
            self.comments = label
            offset += 1
            if utils.profile_is_validator():
                label.multiline = True
                label.text = "No comments yet."
        # version warning
        version_warning = self.new_text(
            "",
            self.tooltip_margin,
            self.tooltip_height
            + self.tooltip_margin
            + int(self.author_text_size * offset),
            height=self.author_text_size,
            text_size=self.author_text_size,
        )
        version_warning.text_color = self.warning_color
        self.tooltip_widgets.append(version_warning)
        self.version_warning = version_warning

    def hide_tooltip(self):
        """Hide the tooltip panel and its widgets."""
        # Idempotent redraw: doing the redraw on every row-crossing during
        # scroll used to cause periodic stutter. We still always sync the
        # widget visibility flags so the tooltip children can't linger
        # visible (e.g. at startup before the panel was ever shown) while
        # the panel itself is hidden.
        was_visible = getattr(self.tooltip_panel, "visible", False)
        self.tooltip_panel.visible = False
        for w in self.tooltip_widgets:
            w.visible = False
        if was_visible:
            self._redraw_tracked_regions()

    def show_tooltip(self):
        """Show the tooltip panel and its widgets."""
        self.tooltip_panel.visible = True
        self.tooltip_panel.active = False
        for w in self.tooltip_widgets:
            w.visible = True
        self._redraw_tracked_regions()

    def _reset_tooltip_dimensions(self):
        """Restore tooltip scale and panel size before recomputing layout.

        Prevents a previously downscaled tooltip from keeping a shrunken size
        on subsequent openings (e.g. after tight vertical space).
        """

        ui_scale = ui_bgl.get_ui_scale()
        self.tooltip_scale = ui_scale
        self._tooltip_available_height = None

        base_size = int(self.tooltip_base_size_pixels * ui_scale)
        base_height = int(base_size * (1 + self.bottom_panel_fraction))

        self.tooltip_size = base_size
        self.tooltip_height = base_height

        if hasattr(self, "tooltip_panel"):
            self.tooltip_panel.width = base_size
            self.tooltip_panel.height = base_height

    def update_tooltip_size(self, context):
        """Calculate all important sizes for the tooltip"""
        region = context.region
        ui_props = bpy.context.window_manager.blenderkitUI

        ui_scale = ui_bgl.get_ui_scale()
        desired_size = int(self.tooltip_base_size_pixels * ui_scale)
        desired_full_height = int(desired_size * (1 + self.bottom_panel_fraction))

        available_height = getattr(self, "_tooltip_available_height", None)
        if available_height is None:
            tooltip_panel = getattr(self, "tooltip_panel", None)
            anchor_y = None
            if tooltip_panel is not None:
                anchor_y = getattr(tooltip_panel, "y_screen", None)
            if anchor_y is None:
                anchor_y = self.bar_y + self.bar_height
            anchor_y = max(-region.height, min(region.height, anchor_y))
            if anchor_y < 0:
                available_height = anchor_y + region.height
            else:
                available_height = region.height - anchor_y

        available_height = max(64, int(available_height))
        if desired_full_height > available_height:
            scale_factor = available_height / max(desired_full_height, 1)
        else:
            scale_factor = 1.0

        final_size = max(32, int(desired_size * scale_factor))
        self.tooltip_scale = final_size / self.tooltip_base_size_pixels
        self.tooltip_size = final_size
        self.asset_name_text_size = int(
            0.039 * self.tooltip_base_size_pixels * self.tooltip_scale
        )
        self.author_text_size = int(self.asset_name_text_size * 0.8)
        self.tooltip_margin = int(
            0.017 * self.tooltip_base_size_pixels * self.tooltip_scale
        )

        # Check if the active asset is an author for tooltip sizing
        self._is_author_tooltip = False
        active_idx = getattr(self, "active_index", -1)
        sr = search.get_search_results()
        if sr and 0 <= active_idx < len(sr):
            self._is_author_tooltip = sr[active_idx].get("assetType") == "author"

        if ui_props.asset_type == "HDR":
            self.tooltip_width = self.tooltip_size * 2
            self.tooltip_image_height = self.tooltip_size
        else:
            self.tooltip_width = self.tooltip_size
            self.tooltip_image_height = self.tooltip_size

        if self._is_author_tooltip:
            # Author tooltip: sized to actual content (name + about lines)
            # Count how many about_me lines we'll actually show
            about_line_count = 0
            active_idx = getattr(self, "active_index", -1)
            if sr and 0 <= active_idx < len(sr):
                ad = sr[active_idx]
                td = ad.get("tooltip_data")
                if td:
                    about_me = td.get("about_me", "")
                    if about_me:
                        chars_per_line = max(
                            20, int(self.tooltip_size / (self.author_text_size * 0.65))
                        )
                        wrapped = 0
                        for paragraph in about_me.split("\n"):
                            words = paragraph.split()
                            cur = ""
                            for word in words:
                                if cur and len(cur) + 1 + len(word) > chars_per_line:
                                    wrapped += 1
                                    cur = word
                                else:
                                    cur = f"{cur} {word}" if cur else word
                            if cur:
                                wrapped += 1
                        about_line_count += min(wrapped, 8)
            self.tooltip_info_height = (
                4 * self.tooltip_margin
                + self.asset_name_text_size
                + max(1, about_line_count) * int(self.author_text_size * 1.4)
            )
        else:
            self.tooltip_info_height = max(
                int(self.tooltip_image_height * self.bottom_panel_fraction),
                self.asset_name_text_size * 3,
            )
        self.labels_start = self.tooltip_image_height
        self.comments_text_size = max(
            15,
            int(0.034 * self.tooltip_base_size_pixels * self.tooltip_scale),
            int(self.author_text_size),
        )

        self.tooltip_height = self.tooltip_image_height + self.tooltip_info_height
        self.gravatar_size = max(
            int(self.tooltip_info_height - 2 * self.tooltip_margin),
            self.asset_name_text_size,
        )

        self._tooltip_available_height = None

    def update_tooltip_layout(self, context):
        """Update the layout of the tooltip"""
        # update Tooltip size /scale for HDR or if area too small

        self.tooltip_panel.width = self.tooltip_width
        self.tooltip_panel.height = self.tooltip_height

        self.tooltip_image_help.set_location(
            self.tooltip_margin,
            self.tooltip_image_height - self.tooltip_margin - self.author_text_size,
        )
        self.tooltip_image_help.text_size = self.author_text_size
        self.tooltip_image.width = self.tooltip_width
        self.tooltip_image.height = self.tooltip_image_height

        self.labels_start = self.tooltip_image_height

        self.tooltip_image.set_image_size(
            (self.tooltip_width, self.tooltip_image_height)
        )
        self.tooltip_image.set_location(0, 0)

        self.gravatar_image.set_location(
            self.tooltip_width - self.gravatar_size - self.tooltip_margin,
            self.tooltip_height - self.gravatar_size - self.tooltip_margin,
        )
        self.gravatar_image.set_image_size(
            (
                self.gravatar_size,
                self.gravatar_size,
            )
        )

        if self._is_author_tooltip:
            # Asset count right-aligned on the same row as the author name
            self.authors_name.set_location(
                self.tooltip_width - self.tooltip_margin,
                self.labels_start + self.tooltip_margin,
            )
            self.authors_name.text_size = self.asset_name_text_size
            self.authors_name.height = self.asset_name_text_size
        else:
            self.authors_name.set_location(
                self.tooltip_width - self.gravatar_size - (self.tooltip_margin * 2),
                self.tooltip_height - self.author_text_size - self.tooltip_margin,
            )
            self.authors_name.text_size = self.author_text_size
            self.authors_name.height = self.author_text_size

        self.asset_name.set_location(
            self.tooltip_margin,
            self.labels_start + self.tooltip_margin,
        )
        self.asset_name.text_size = self.asset_name_text_size
        self.asset_name.height = self.asset_name_text_size

        self.tooltip_dark_panel.set_location(
            0,
            self.labels_start,
        )
        self.tooltip_dark_panel.height = self.tooltip_info_height
        self.tooltip_dark_panel.width = self.tooltip_width

        self.quality_label.set_location(
            2 * self.tooltip_margin + self.asset_name_text_size,
            self.tooltip_height - int(self.asset_name_text_size + self.tooltip_margin),
        )
        self.quality_label.text_size = self.asset_name_text_size
        self.quality_label.height = self.asset_name_text_size

        self.quality_star.set_location(
            self.tooltip_margin,
            self.tooltip_height - self.tooltip_margin - self.asset_name_text_size,
        )
        self.quality_star.set_image_size(
            (self.asset_name_text_size, self.asset_name_text_size)
        )

        # right after the asset name
        self.multi_price_label.set_location(
            self.tooltip_margin,
            self.labels_start + (self.tooltip_margin * 3) + self.asset_name.height,
        )
        self.multi_price_label.width = self.tooltip_width - 2 * self.tooltip_margin
        self.multi_price_label.height = self.asset_name_text_size
        self.multi_price_label.text_size = self.asset_name_text_size

        # Author about-me label: positioned directly below asset name
        if hasattr(self, "author_about_me"):
            about_y = (
                self.labels_start
                + self.tooltip_margin
                + self.asset_name_text_size
                + self.tooltip_margin
            )
            self.author_about_me.set_location(
                self.tooltip_margin,
                about_y,
            )
            self.author_about_me.text_size = self.author_text_size
            self.author_about_me.height = self.author_text_size
            self.author_about_me.width = self.tooltip_width - 2 * self.tooltip_margin

        if hasattr(self, "comments"):
            self.comments.set_location(
                self.tooltip_margin,
                self.tooltip_height + self.tooltip_margin,
            )
            self.comments.text_size = self.comments_text_size

    def update_tooltip_image(self, asset_id):
        """Update tooltip image when it finishes downloading and the downloaded image matches the active one."""
        search_results = search.get_search_results()
        if search_results is None:
            return

        if self.active_index == -1:  # prev search got no results
            return

        if self.active_index >= len(search_results):
            return

        asset_data = search_results[self.active_index]
        if asset_data.get("assetBaseId") == asset_id:
            set_thumb_check(self.tooltip_image, asset_data, thumb_type="thumbnail")

    def update_comments_for_validators(self, asset_data):
        """Update the comments section in the tooltip for validator profiles."""
        if not utils.profile_is_validator():
            return

        # The comments label widget is only created during tooltip setup when
        # the validator/popup-counter condition was true at that moment. If
        # the profile only became a validator after the asset bar was already
        # built, the widget won't exist — silently skip in that case.
        if not hasattr(self, "comments"):
            return

        if asset_data.get("assetType") == "author":
            self.comments.text = ""
            return

        # Lazily request comments only on hover (deduped + cached) so we
        # don't fire one HTTP request per search result, which would blow
        # past the backend's 100 req/min rate limit on validator accounts.
        asset_base_id = asset_data["assetBaseId"]
        comments = comments_utils.request_comments_if_needed(asset_base_id)
        comment_text = "No comments yet."
        if comments is None:
            comment_text = "Loading comments..."
        elif comments:
            wrap_width = max(100, int(self.tooltip_width - 2 * self.tooltip_margin))
            text_size = getattr(self, "comments_text_size", self.author_text_size)
            lines_out = []
            # iterate comments from last to first
            for comment in reversed(comments):
                timestamp = _format_comment_timestamp(comment.get("submitDate"))
                header = comment["userName"]
                if timestamp:
                    header = f"{header} [{timestamp}]"
                lines_out.append(f"{header}:")
                # strip urls and stuff, then wrap to the tooltip width
                for line in comment["comment"].split("\n"):
                    urls, text = utils.has_url(line)
                    if urls:
                        text = f"{text}{urls[0][0]}"
                    lines_out.extend(_wrap_text_to_width(text, wrap_width, text_size))
                lines_out.append("")
            comment_text = "\n".join(lines_out)

        self.comments.text = comment_text

    # endregion tooltip

    # region panel

    def asset_button_init(self, asset_x, asset_y, button_idx):
        """Initialize an asset button at the given position with the given index."""
        button_bg_color = (0.2, 0.2, 0.2, 0.1)
        button_hover_color = (0.8, 0.8, 0.8, 0.2)
        fully_transparent_color = (0.2, 0.2, 0.2, 0.0)
        new_button = BL_UI_Button(asset_x, asset_y, self.button_size, self.button_size)

        new_button.bg_color = button_bg_color
        new_button.hover_bg_color = button_hover_color
        new_button.text = ""  # asset_data['name']

        new_button.set_image_size((self.thumb_size, self.thumb_size))
        new_button.set_image_position((self.button_margin, self.button_margin))
        new_button.button_index = button_idx
        new_button.search_index = button_idx
        new_button.set_mouse_down(self.drag_drop_asset)
        new_button.set_mouse_down_right(self.asset_menu)
        new_button.set_mouse_enter(self.enter_button)
        new_button.set_mouse_exit(self.exit_button)
        new_button.text_input = self.handle_key_input

        # add validation icon to button
        validation_icon = BL_UI_Image(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            0,
            0,
        )

        validation_icon.set_image_size((self.icon_size, self.icon_size))
        validation_icon.set_image_position((0, 0))
        self.validation_icons.append(validation_icon)
        new_button.validation_icon = validation_icon

        bookmark_button = BL_UI_Button(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y + self.button_margin + self.validation_icon_margin,
            self.icon_size,
            self.icon_size,
        )
        bookmark_button.set_image_size((self.icon_size, self.icon_size))
        bookmark_button.set_image_position((0, 0))
        bookmark_button.button_index = button_idx
        bookmark_button.search_index = button_idx
        bookmark_button.text = ""
        bookmark_button.set_mouse_down(self.bookmark_asset)

        img_fp = paths.get_addon_thumbnail_path("bookmark_empty.png")
        bookmark_button.set_image(img_fp)
        bookmark_button.bg_color = fully_transparent_color
        bookmark_button.hover_bg_color = self.button_bg_color
        bookmark_button.select_bg_color = fully_transparent_color
        bookmark_button.visible = False
        new_button.bookmark_button = bookmark_button
        self.bookmark_buttons.append(bookmark_button)

        # Author type icon (top-left corner)
        author_button = BL_UI_Button(
            asset_x + self.button_margin + self.validation_icon_margin,
            asset_y + self.button_margin + self.validation_icon_margin,
            self.icon_size,
            self.icon_size,
        )
        author_button.set_image_size((self.icon_size, self.icon_size))
        author_button.set_image_position((0, 0))
        img_fp = paths.get_addon_thumbnail_path("asset_type_author.png")
        author_button.set_image(img_fp)
        author_button.bg_color = fully_transparent_color
        author_button.hover_bg_color = self.button_bg_color
        author_button.select_bg_color = fully_transparent_color
        author_button.visible = False
        author_button.button_index = button_idx
        author_button.search_index = button_idx
        author_button.text = ""
        author_button.set_mouse_down(self.show_author_profile)
        new_button.author_button = author_button
        self.author_buttons.append(author_button)

        progress_bar = BL_UI_Widget(
            asset_x, asset_y + self.button_size - 6, self.button_size, 6
        )
        progress_bar.bg_color = (0.0, 1.0, 0.0, 0.3)
        new_button.progress_bar = progress_bar
        self.progress_bars.append(progress_bar)

        # Tinted overlay reused for two purposes:
        # - validator: red "old upload" alert
        # - everyone:  dark-red dim for Blender-incompatible addons
        red_alert = BL_UI_Widget(
            asset_x - self.validation_icon_margin,
            asset_y - self.validation_icon_margin,
            self.button_size + 2 * self.validation_icon_margin,
            self.button_size + 2 * self.validation_icon_margin,
        )
        red_alert.bg_color = (1.0, 0.0, 0.0, 0.0)
        red_alert.visible = False
        red_alert.active = False
        red_alert._is_grid_widget = True
        new_button.red_alert = red_alert
        self.red_alerts.append(red_alert)

        # Tag all grid sub-widgets so the draw callback can apply scissor clipping
        new_button._is_grid_widget = True
        validation_icon._is_grid_widget = True
        bookmark_button._is_grid_widget = True
        author_button._is_grid_widget = True
        progress_bar._is_grid_widget = True

        return new_button

    def init_ui(self):
        """Initialize the asset bar UI and its widgets."""
        self.button_bg_color = (0.2, 0.2, 0.2, 1.0)
        self.button_hover_color = (0.8, 0.8, 0.8, 1.0)
        self.button_selected_color = (0.5, 0.5, 0.5, 1.0)
        self.button_selected_color_dim = (0.3, 0.3, 0.3, 1.0)

        self.buttons = []
        self.asset_buttons = []
        self.validation_icons = []
        self.bookmark_buttons = []
        self.author_buttons = []
        self.progress_bars = []
        self.red_alerts = []
        self.widgets_panel = []
        self.tab_buttons = []
        self.close_tab_buttons = []
        self.active_filter_buttons = []
        self.manufacturer_buttons = []

        # Create panel with extended height
        self.panel = BL_UI_Drag_Panel(
            0,
            0,
            self.bar_width,
            self.bar_height,  # Use total height including tabs
        )
        self.panel.drag_enabled = False
        self.panel.bg_color = (0.0, 0.0, 0.0, 0.9)

        # Create tab area background
        self.tab_area_bg = BL_UI_Widget(
            0,  # x position will be set in update_assetbar_layout
            -self.other_button_size,  # Position at top where tabs are
            self.bar_width,  # Same width as asset bar
            self.other_button_size,  # Same height as tab buttons
        )
        # dark blue
        self.tab_area_bg.bg_color = colors.TOP_BAR_BLUE
        self.tab_area_bg.use_rounded_background = True
        self.tab_area_bg.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )

        # Add widgets to panel - add tab background first so it's behind everything
        self.widgets_panel.append(self.tab_area_bg)

        # Scroll position indicator. Two thin widgets: a darker track behind
        # a brighter thumb whose length / position reflect visible_slots /
        # total_slots and current scroll position. Orientation switches with
        # mode (horizontal in single-row, vertical in multi-row). Added to
        # `widgets_panel` AFTER asset buttons in `setup_widgets` so they
        # render on top of thumbnails (otherwise they'd be occluded).
        scroll_track_height = max(
            2, int(round(SCROLL_INDICATOR_THICKNESS_PX * ui_bgl.get_ui_scale()))
        )
        self.scroll_indicator_track = BL_UI_Widget(
            0, 0, self.bar_width, scroll_track_height
        )
        self.scroll_indicator_track.bg_color = (0.0, 0.0, 0.0, 0.35)
        self.scroll_indicator_track.visible = False
        self.scroll_indicator_thumb = BL_UI_Widget(0, 0, 1, scroll_track_height)
        self.scroll_indicator_thumb.bg_color = (1.0, 1.0, 1.0, 0.7)
        self.scroll_indicator_thumb.visible = False
        # NOTE: deliberately NOT appended to `self.widgets_panel` here -
        # `setup_widgets` adds them last so they draw on top of thumbnails.

        # we init max possible buttons.
        # Add buffer rows/cols around the visible grid for scroll animation.
        # Multi-row mode uses extra rows; single-row mode uses extra columns.
        # Pool size has to cover the worst case of either mode.
        # The draggable resize handle lets the row count grow up to the
        # visible-asset cap (``_get_row_limit()``), independent of the saved
        # ``maximized_assetbar_rows`` (= ``self.max_wcount``); size the pool for
        # that worst case so dragging taller never runs out of buttons.
        button_idx = 0
        pool_cols = self._get_row_limit() + 2 * SCROLL_BUFFER_COLS
        pool_rows = self.max_hcount + 2 * SCROLL_BUFFER_ROWS
        for x in range(0, pool_cols):
            for y in range(0, pool_rows):
                # asset_x = self.assetbar_margin + a * (self.button_size)
                # asset_y = self.assetbar_margin + b * (self.button_size)
                # button_idx = x + y * self.max_wcount
                asset_idx = button_idx + self.scroll_offset
                # if asset_idx < len(sr):
                new_button = self.asset_button_init(0, 0, button_idx)
                new_button.asset_index = asset_idx
                self.asset_buttons.append(new_button)
                button_idx += 1

        # add close button
        self.button_close = BL_UI_Button(
            self.bar_width - self.other_button_size,
            -self.other_button_size,
            self.other_button_size,
            self.other_button_size,
        )
        self.button_close.bg_color = self.button_bg_color
        self.button_close.hover_bg_color = self.button_hover_color
        self.button_close.use_rounded_background = True
        self.button_close.background_corner_radius = (
            0,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.button_close.text = "×"
        self.button_close.text_size = self.other_button_size * 0.8
        self.button_close.set_image_position((0, 0))
        self.button_close.set_image_size(
            (self.other_button_size, self.other_button_size)
        )
        self.button_close.set_mouse_down(self.cancel_press)

        self.widgets_panel.append(self.button_close)

        # Drag-to-resize handle: a thin strip along the bottom edge. It spans
        # the bar width minus the expand-button corner so the two never fight
        # over a click. Positioned just below the bar content (panel-relative
        # y = bar_height), matching the expand button's coordinate convention.
        self.resize_edge_height = max(6, self.other_button_size // 4)
        self.resize_handle = BL_UI_Resize_Handle(
            0,
            self.bar_height,
            self.bar_width - self.other_button_size,
            self.resize_edge_height,
        )
        self.resize_handle.threshold_px = ASSETBAR_RESIZE_CLICK_THRESHOLD_PX
        self.resize_handle.bg_color = (1.0, 1.0, 1.0, 0.5)
        self.resize_handle.on_drag_begin = self.on_resize_drag_begin
        self.resize_handle.on_drag_update = self.on_resize_drag_update
        self.resize_handle.on_drag_end = self.on_resize_drag_end
        self.resize_handle.on_click = self.on_resize_handle_click
        self.resize_handle.set_mouse_enter(self.on_resize_handle_enter)
        self.resize_handle.set_mouse_exit(self.on_resize_handle_exit)
        self.resize_handle.visible = False

        self.button_expand = BL_UI_Button(
            self.bar_width - self.other_button_size,
            self.bar_height,
            self.other_button_size,
            self.other_button_size,
        )
        self.button_expand.bg_color = self.button_bg_color
        self.button_expand.hover_bg_color = self.button_hover_color
        self.button_expand.text = ""
        self.button_expand.text_size = self.other_button_size * 0.8
        self.button_expand.use_rounded_background = True
        self.button_expand.background_corner_radius = (
            0,
            0,
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
        )
        self.button_expand.set_image_position((0, 0))
        self.button_expand.set_image_size(
            (self.other_button_size, self.other_button_size)
        )
        self.button_expand.set_mouse_down(self.toggle_expand)
        self.widgets_panel.append(self.button_expand)

        self.scroll_width = 30
        self.button_scroll_down = BL_UI_Button(
            -self.scroll_width, 0, self.scroll_width, self.bar_height
        )
        self.button_scroll_down.bg_color = self.button_bg_color
        self.button_scroll_down.hover_bg_color = self.button_hover_color
        self.button_scroll_down.use_rounded_background = True
        self.button_scroll_down.background_corner_radius = (
            ROUNDING_RADIUS,
            0,
            0,
            ROUNDING_RADIUS,
        )
        self.button_scroll_down.text = ""
        self.button_scroll_down.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_down.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

        self.button_scroll_down.set_mouse_down(self.scroll_down)

        self.widgets_panel.append(self.button_scroll_down)

        self.button_scroll_up = BL_UI_Button(
            self.bar_width, 0, self.scroll_width, self.bar_height
        )
        self.button_scroll_up.bg_color = self.button_bg_color
        self.button_scroll_up.hover_bg_color = self.button_hover_color
        self.button_scroll_up.use_rounded_background = True
        self.button_scroll_up.background_corner_radius = (
            0,
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
        )
        self.button_scroll_up.text = ""
        self.button_scroll_up.set_image_size((self.scroll_width, self.button_size))
        self.button_scroll_up.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

        self.button_scroll_up.set_mouse_down(self.scroll_up)

        self.widgets_panel.append(self.button_scroll_up)

        # Add tab navigation elements
        button_size = self.other_button_size
        margin = int(button_size * 0.05)
        space = int(button_size * 0.4)
        tab_icon_size = int(button_size * 0.7)  # Size for the asset type icon
        tab_width = (
            button_size * 4 + tab_icon_size
        )  # Widen the tabs to accommodate type icon

        # Back/Forward history buttons
        self.history_back_button = BL_UI_Button(
            margin, -button_size, button_size, button_size
        )
        self.history_back_button.bg_color = self.button_bg_color
        self.history_back_button.hover_bg_color = self.button_hover_color
        self.history_back_button.use_rounded_background = True
        self.history_back_button.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.history_back_button.text = ""
        icon_size = int(button_size * 0.6)
        margin_lr = int((button_size - icon_size) / 2)
        self.history_back_button.set_image(
            paths.get_addon_thumbnail_path("history_back.png")
        )
        self.history_back_button.set_image_size((icon_size, icon_size))
        self.history_back_button.set_image_position((margin_lr, margin_lr))

        self.history_forward_button = BL_UI_Button(
            margin * 2 + button_size,
            -button_size,
            button_size,
            button_size,
        )
        self.history_forward_button.bg_color = self.button_bg_color
        self.history_forward_button.hover_bg_color = self.button_hover_color
        self.history_forward_button.use_rounded_background = True
        self.history_forward_button.background_corner_radius = (
            ROUNDING_RADIUS,
            ROUNDING_RADIUS,
            0,
            0,
        )
        self.history_forward_button.text = ""
        self.history_forward_button.set_image(
            paths.get_addon_thumbnail_path("history_forward.png")
        )
        self.history_forward_button.set_image_size((icon_size, icon_size))
        self.history_forward_button.set_image_position((margin_lr, margin_lr))

        # Tab buttons
        tabs = global_vars.TABS["tabs"]
        tab_x_start = margin * 4 + button_size * 3  # Starting x position of first tab

        tabs_end_x = 0

        for i, tab in enumerate(tabs):
            is_active = i == global_vars.TABS["active_tab"]

            # Calculate positions
            tab_x = tab_x_start + i * (
                tab_width + button_size + margin + space
            )  # Space for tab and close button

            # Tab button
            tab_button = BL_UI_Button(
                tab_x,  # Position with spacing for close buttons
                -button_size,
                tab_width,  # Width of tab
                button_size,
            )

            tab_button.hover_bg_color = self.button_hover_color
            tab_button.text = tab["name"]
            tab_button.text_size = button_size * 0.5
            tab_button.text_color = self.text_color
            tab_button.bg_color = self.button_bg_color
            tab_button.use_rounded_background = True
            tab_button.background_padding = (margin, 0)  # extra margin
            tab_button.background_corner_radius = (
                ROUNDING_RADIUS,
                0,
                0,
                0,
            )
            if is_active:
                tab_button.bg_color = self.button_selected_color

            tab_button.tab_index = i  # Store tab index
            tab_button.set_mouse_down(self.switch_tab)  # Add click handler
            self.tab_buttons.append(tab_button)

            # Set asset type icon as tab button image
            tab_button.set_image_size((tab_icon_size, tab_icon_size))
            tab_button.set_image_position(
                (margin * 2, (button_size - tab_icon_size) / 2)
            )  # Center vertically

            # Only create close button if there's more than one tab
            close_x = tab_x + tab_width + margin  # Position right after tab
            close_tab = BL_UI_Button(
                close_x,
                -button_size,
                button_size,
                button_size,
            )
            close_tab.bg_color = self.button_bg_color
            # slightly red
            close_tab.hover_bg_color = (0.8, 0.0, 0.0, 0.2)
            close_tab.text = "×"  # Set text after creation
            close_tab.text_size = button_size * 0.8
            close_tab.text_color = self.text_color
            close_tab.use_rounded_background = True
            close_tab.background_corner_radius = (0, ROUNDING_RADIUS, 0, 0)
            if is_active:
                close_tab.bg_color = self.button_selected_color_dim

            close_tab.tab_index = i  # Store tab index
            # if there's only one tab, the button closes asset bar instead of closing tab
            if len(tabs) > 1:
                close_tab.set_mouse_down(self.remove_tab)  # Add click handler
            else:
                close_tab.set_mouse_down(self.cancel_press)

            self.close_tab_buttons.append(close_tab)

            tabs_end_x = close_x + button_size

        # New tab button - position after all tabs and close buttons
        if len(tabs) > 0:
            new_tab_x = (
                space + tabs_end_x + margin * 2
            )  # After last tab and its close button
        else:
            new_tab_x = tab_x_start  # If no tabs, start at the beginning

        # if too close to the right side, let's not create this button
        if new_tab_x + button_size < self.bar_width:
            self.new_tab_button = BL_UI_Button(
                new_tab_x,
                -button_size,
                button_size,
                button_size,
            )
            # Change from default button color to slightly green
            self.new_tab_button.bg_color = (0.2, 0.5, 0.2, 1.0)  # Green tint
            # Slightly lighter green on hover
            self.new_tab_button.hover_bg_color = (0.3, 0.7, 0.3, 0.5)
            self.new_tab_button.text = "+"
            self.new_tab_button.text_size = button_size * 0.8
            self.new_tab_button.text_color = self.text_color
            self.new_tab_button.use_rounded_background = True
            self.new_tab_button.background_corner_radius = ROUNDING_RADIUS
            self.new_tab_button.set_mouse_down(self.add_new_tab)
            self.widgets_panel.append(self.new_tab_button)

        # Then add all other widgets
        self.widgets_panel.extend(
            [
                self.history_back_button,
                self.history_forward_button,
            ]
        )
        self.widgets_panel.extend(self.tab_buttons)
        self.widgets_panel.extend(self.close_tab_buttons)

        # Back/Forward history buttons
        self.history_back_button.set_mouse_down(self.history_back)
        self.history_forward_button.set_mouse_down(self.history_forward)

        # Set initial visibility based on history
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        self.history_back_button.visible = active_tab["history_index"] > 0
        self.history_forward_button.visible = (
            active_tab["history_index"] < len(active_tab["history"]) - 1
        )

        # Manufacturer filter buttons (stay hidden until populated)
        # Active filter chips (generic, per tab)
        for _ in range(self.max_active_filter_chips):
            chip_button = BL_UI_Button(0, 0, 100, self.filter_button_height)
            chip_button.bg_color = (0.18, 0.18, 0.18, 0.9)
            chip_button.hover_bg_color = (0.22, 0.22, 0.22, 1.0)
            chip_button.text = ""
            chip_button.text_size = self.filter_button_text_size
            chip_button.text_color = self.text_color
            chip_button.visible = False
            chip_button.use_rounded_background = True
            chip_button.background_corner_radius = "50%"
            chip_button.background_border = True
            chip_button.background_border_color = colors.ACTIVE_BLUE
            chip_button.background_border_thickness = 2
            chip_button.set_mouse_down(self.remove_active_filter_chip)
            chip_button.active_filter = None
            self.active_filter_buttons.append(chip_button)

        self.widgets_panel.extend(self.active_filter_buttons)

        # Manufacturer filter buttons (stay hidden until populated)
        for _ in range(self.max_manufacturer_filters):
            filter_button = BL_UI_Button(0, 0, 80, self.filter_button_height)
            # start with a neutral gray; exact shade is updated when buttons are positioned
            base_gray = 50 / 255
            filter_button.bg_color = (base_gray, base_gray, base_gray, 0.85)
            filter_button.hover_bg_color = (
                base_gray + 0.1,
                base_gray + 0.1,
                base_gray + 0.1,
                1.0,
            )
            filter_button.text = ""
            filter_button.text_size = self.filter_button_text_size
            filter_button.text_color = self.text_color
            filter_button.visible = False
            filter_button.use_rounded_background = True
            filter_button.background_corner_radius = "50%"
            filter_button.set_mouse_down(
                partial(self.apply_term_filter, term="manufacturer")
            )
            filter_button.manufacturer_name = ""
            self.manufacturer_buttons.append(filter_button)

        # Clear manufacturer filter bubble (red cross)
        self.widgets_panel.extend(self.manufacturer_buttons)

    # endregion panel

    def show_notifications(self, widget):
        """Show notifications on the asset bar."""
        bpy.ops.wm.show_notifications()
        if comments_utils.check_notifications_read():
            widget.visible = False

    # region checks

    def check_new_search_results(self, context):
        """checks if results were replaced.
        this can happen from search, but also by switching results.
        We should rather trigger that update from search. maybe let's add a uuid to the results?
        """
        # Get search results from history
        sr = search.get_search_results()
        current_id = id(sr) if sr is not None else None

        if not hasattr(self, "search_results_count"):
            self.search_results_count = len(sr) if sr else 0
            self.last_asset_type = sr[0]["assetType"] if sr else ""
            self._last_search_results_id = current_id
            return True

        if current_id != getattr(self, "_last_search_results_id", None):
            self._last_search_results_id = current_id
            self.search_results_count = len(sr) if sr else 0
            if sr:
                self.last_asset_type = sr[0]["assetType"]
            return True

        if sr is not None and len(sr) != self.search_results_count:
            self.search_results_count = len(sr)
            return True
        return False

    def get_region_size(self, context):
        """Get the size of the region."""
        # just check the size of region..

        region = context.region
        area = context.area
        ui_width = 0
        tools_width = 0
        for r in area.regions:
            if r.type == "UI":
                ui_width = r.width
            if r.type == "TOOLS":
                tools_width = r.width
        total_width = region.width - tools_width - ui_width
        return total_width, region.height

    def check_region_changed(self, context):
        """Check if the region has changed."""
        region_width, region_height = self.get_region_size(context)

        if not hasattr(self, "total_width"):
            self.total_width = region_width
            self.region_height = region_height

        changed = (
            region_height != self.region_height or region_width != self.total_width
        )

        if changed:
            self.region_height = region_height
            self.total_width = region_width
            return True
        return False

    def check_ui_resized(self, context):
        """Check if the UI has been resized."""
        scaling = ui_bgl.get_ui_scale()

        if not hasattr(self, "_ui_scale_state"):
            self._ui_scale_state = scaling

        scale_changed = scaling != self._ui_scale_state

        if scale_changed:
            self._ui_scale_state = scaling
            return True
        return False

    # endregion checks

    # region updates

    def update_assetbar_sizes(self, context):
        """Calculate all important sizes for the asset bar.

        Pure geometry math is delegated to :mod:`.layout`; this method
        only collects inputs (which require ``bpy`` reads), runs the
        widget-side-effect steps that contribute height contributions
        (filter chips, manufacturer chips), then applies the resulting
        :class:`~.layout.LayoutSpec` onto ``self`` for backwards-compat
        attribute access (``self.bar_x``, ``self.button_size``, ...).

        Idempotency cache: the layout is recomputed only when the input
        signature changes. Repeat calls with identical inputs are O(1).
        """
        from . import layout as _layout_mod

        region = context.region
        area = context.area

        ui_props = bpy.context.window_manager.blenderkitUI
        user_preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
        scale = ui_bgl.get_ui_scale()

        ui_width, tools_width = _layout_mod.collect_side_panel_widths(
            area, bpy.context.preferences.system.use_region_overlap
        )

        history_step = search.get_active_history_step()
        search_results = history_step.get("search_results")
        sr_count = len(search_results) if search_results is not None else None
        sr_id = id(search_results) if search_results is not None else 0

        layout_expanded, layout_max_rows = self._resolve_layout_rows(user_preferences)

        # Build a stage-1 ("prelim") inputs object: everything we know
        # without having to call into widget-mutating helpers. This is
        # also the cache key - manufacturer height is recomputed each
        # time it would matter, and active filter height comes from a
        # widget-side-effect helper we still have to run.
        prelim_inputs = _layout_mod.LayoutInputs(
            region_width=int(region.width),
            region_height=int(region.height),
            window_width=int(context.window.width),
            ui_region_width=ui_width,
            tools_region_width=tools_width,
            ui_scale=scale,
            bar_x_offset=float(ui_props.bar_x_offset),
            bar_y_offset=float(ui_props.bar_y_offset),
            thumb_size_pref=int(user_preferences.thumb_size),
            assetbar_expanded=layout_expanded,
            maximized_assetbar_rows=layout_max_rows,
            search_results_count=sr_count,
            search_results_id=sr_id,
            active_filter_height=0,  # filled in below
            manufacturer_section_height=0,  # filled in below
        )

        # Position filter chips (widget side effect) so we can read
        # ``self.active_filter_height``. This is cheap when the chip
        # set hasn't changed, but it always runs because chips can be
        # restyled (e.g. active filter set changed) without the prelim
        # inputs changing.
        self.position_active_filter_buttons()
        active_filter_height = int(self.active_filter_height or 0)

        # Now we know the active filter height; rebuild prelim_inputs
        # with that field populated so the cache key reflects all
        # geometry-affecting state we currently know.
        prelim_inputs = _layout_mod.LayoutInputs(
            region_width=prelim_inputs.region_width,
            region_height=prelim_inputs.region_height,
            window_width=prelim_inputs.window_width,
            ui_region_width=prelim_inputs.ui_region_width,
            tools_region_width=prelim_inputs.tools_region_width,
            ui_scale=prelim_inputs.ui_scale,
            bar_x_offset=prelim_inputs.bar_x_offset,
            bar_y_offset=prelim_inputs.bar_y_offset,
            thumb_size_pref=prelim_inputs.thumb_size_pref,
            assetbar_expanded=prelim_inputs.assetbar_expanded,
            maximized_assetbar_rows=prelim_inputs.maximized_assetbar_rows,
            search_results_count=prelim_inputs.search_results_count,
            search_results_id=prelim_inputs.search_results_id,
            active_filter_height=active_filter_height,
            manufacturer_section_height=0,
        )

        # Idempotency fast path: identical inputs => skip the heavy work.
        # The cache key stores the prelim form (manufacturer=0) so the
        # comparison is well-defined regardless of whether the previous
        # run had manufacturer chips.
        cached_key = getattr(self, "_layout_cache_key", None)
        if cached_key == prelim_inputs and getattr(self, "_layout", None) is not None:
            # Re-apply spec onto self in case external code clobbered
            # any mirrored attribute since the last call.
            self._layout.apply_to(self)
            return

        # Build preliminary spec so manufacturer recomputation has the
        # geometry it needs (button_size, bar_width).
        # Remember geometry before the rebuild: only a button_size/wcount change
        # invalidates the smooth-scroll phase (phase is pixels relative to slot
        # size). A rebuild caused merely by search_results_count changing
        # (placeholders padded, a page arriving) keeps the same grid, so the
        # phase is still valid and must NOT be reset - otherwise scrolling jerks
        # back every time thumbnails populate. Scrolling and population are
        # independent.
        _prev_button_size = getattr(self, "button_size", None)
        _prev_wcount = getattr(self, "wcount", None)
        prelim_spec = _layout_mod.build_layout_spec(prelim_inputs)
        prelim_spec.apply_to(self)

        # Update manufacturer data using the preliminary geometry. This
        # populates ``self.manufacturer_section_height`` as a side effect.
        self._update_manufacturer_data(search_results)
        manufacturer_section_height = int(self.manufacturer_section_height or 0)

        # Final spec with the now-known manufacturer height.
        if manufacturer_section_height != 0:
            final_inputs = _layout_mod.LayoutInputs(
                region_width=prelim_inputs.region_width,
                region_height=prelim_inputs.region_height,
                window_width=prelim_inputs.window_width,
                ui_region_width=prelim_inputs.ui_region_width,
                tools_region_width=prelim_inputs.tools_region_width,
                ui_scale=prelim_inputs.ui_scale,
                bar_x_offset=prelim_inputs.bar_x_offset,
                bar_y_offset=prelim_inputs.bar_y_offset,
                thumb_size_pref=prelim_inputs.thumb_size_pref,
                assetbar_expanded=prelim_inputs.assetbar_expanded,
                maximized_assetbar_rows=prelim_inputs.maximized_assetbar_rows,
                search_results_count=prelim_inputs.search_results_count,
                search_results_id=prelim_inputs.search_results_id,
                active_filter_height=prelim_inputs.active_filter_height,
                manufacturer_section_height=manufacturer_section_height,
            )
            final_spec = _layout_mod.build_layout_spec(final_inputs)
        else:
            final_spec = prelim_spec
        final_spec.apply_to(self)

        # Cache the spec and its key so repeat calls are free.
        self._layout = final_spec
        self._layout_cache_key = prelim_inputs

        # Layout actually rebuilt -> any in-flight smooth-scroll phase is
        # stale ONLY if button_size / wcount changed (the pixel value of
        # "phase" no longer matches the intended slot fraction). When the grid
        # geometry is unchanged - e.g. the rebuild was triggered only by a
        # search_results_count change as placeholders/pages stream in - the
        # phase stays valid and we keep animating so population never snaps the
        # scroll back. The integer offset is preserved either way.
        if _prev_button_size != self.button_size or _prev_wcount != self.wcount:
            self.scroll_phase = 0.0
            self._scroll_velocity = 0.0
            self._scroll_animating = False
            self._scroll_travel_dir = 0

        # Reports panel coordinates depend on bar geometry and current
        # operator mode. Kept out of the pure spec because they touch
        # ``ui_props`` (Blender state).
        if ui_props.down_up == "UPLOAD":
            self.reports_y = region.height - self.bar_y - 600
            ui_props.reports_y = region.height - self.bar_y - 600
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x
        else:
            self.reports_y = region.height - self.bar_y - self.bar_height - 50
            ui_props.reports_y = int(region.height - self.bar_y - self.bar_height - 50)
            self.reports_x = self.bar_x
            ui_props.reports_x = self.bar_x

    def update_ui_size(self, context):
        """Calculate all important sizes for the asset bar and tooltip"""
        self._refresh_layout(context)

    def update_assetbar_layout(self, context):
        """Update the layout of the asset bar"""
        self.scroll_update(
            always=True,
            update_visible_buttons=False,
        )

        self.position_and_hide_buttons()
        self.update_buttons()

        self.button_close.set_location(
            self.bar_width - self.other_button_size, -self.other_button_size
        )
        self.button_expand.set_location(
            self.bar_width - self.other_button_size,
            self.bar_height,
        )
        history_step = search.get_active_history_step()
        search_results = history_step.get("search_results") or []
        edge_visible = len(search_results) > self.wcount
        self.button_expand.visible = edge_visible
        self.resize_handle.width = self.bar_width - self.other_button_size
        self.resize_handle.height = self.resize_edge_height
        self.resize_handle.visible = edge_visible
        self.resize_handle.set_location(0, self.bar_height)
        self.button_scroll_up.set_location(self.bar_width, 0)
        self.panel.width = self.bar_width
        self.panel.height = self.bar_height

        # Update tab area background position
        self.tab_area_bg.width = self.bar_width

        self.panel.set_location(self.bar_x, self.bar_y)

        self.position_manufacturer_buttons()

    def update_layout(self, context, event):
        """update UI sizes after their recalculation"""
        self.update_assetbar_layout(context)
        self.update_tooltip_layout(context)

    def _is_quad_view(self, context):
        """Return True when the current 3D view runs in quad-view layout."""
        space_data = getattr(context, "space_data", None)
        if not space_data or getattr(space_data, "type", "") != "VIEW_3D":
            return False
        quadviews = getattr(space_data, "region_quadviews", None)
        if quadviews is None:
            return False
        try:
            return len(quadviews) > 0
        except TypeError:
            return bool(quadviews)

    def _is_perspective_region(self, region):
        """Return True if the given region is a perspective (or camera) view."""
        r3d = getattr(region, "data", None) or getattr(region, "regiondata", None)
        if r3d is None:
            return False
        return getattr(r3d, "view_perspective", "") in {"PERSP", "CAMERA"}

    def set_element_images(self):
        """set ui elements images, has to be done after init of UI."""
        # img_fp = paths.get_addon_thumbnail_path("vs_rejected.png")
        # self.button_close.set_image(img_fp)
        self.button_scroll_down.set_image(
            paths.get_addon_thumbnail_path("arrow_left.png")
        )
        self.button_scroll_up.set_image(
            paths.get_addon_thumbnail_path("arrow_right.png")
        )
        # if not comments_utils.check_notifications_read():
        #     img_fp = paths.get_addon_thumbnail_path('bell.png')
        #     self.button_notifications.set_image(img_fp)

        # Update tab icons
        self.update_tab_icons()

        self.update_expand_button_icon()

    def update_tab_icons(self):
        """Update tab icons based on the active history step's asset type"""
        tabs = global_vars.TABS["tabs"]
        for i, tab_button in enumerate(self.tab_buttons):
            if i >= len(tabs):
                continue

            tab = tabs[i]
            history_index = tab["history_index"]

            if history_index >= 0 and history_index < len(tab["history"]):
                history_step = tab["history"][history_index]
                ui_state = history_step.get("ui_state", {})
                ui_props = ui_state.get("ui_props", {})
                asset_type = ui_props.get("asset_type", "").lower()

                # Set the icon based on asset type
                if asset_type:
                    icon_path = paths.get_addon_thumbnail_path(
                        f"asset_type_{asset_type}.png"
                    )
                    if not paths.icon_path_exists(icon_path):
                        icon_path = paths.get_addon_thumbnail_path(
                            "asset_type_model.png"
                        )

                    tab_button.set_image(icon_path)
                    tab_button.set_image_colorspace("")

    # region active filters

    def position_active_filter_buttons(self):
        self.active_filter_height = 0
        if not self.active_filter_buttons:
            return

        active_filters = search.get_active_filters()

        raw_available = self.bar_width - 2 * self.assetbar_margin

        if not active_filters or raw_available <= 0:
            for button in self.active_filter_buttons:
                button.visible = False
                button.active_filter = None
            return

        max_x = self.bar_width - self.assetbar_margin
        current_left_offset = (
            self.bar_x + self.assetbar_margin + self.free_button_margin
        )

        current_row = 0

        # Keep chips below the toolbar but above the asset bar when space is tight
        base_y = -(
            self.other_button_size
            + self.filter_button_height
            + (self.free_button_margin * 2)
        )

        for idx in range(self.max_active_filter_chips):
            button = self.active_filter_buttons[idx]
            if idx >= len(active_filters):
                button.visible = False
                break

            flt = active_filters[idx]

            term = flt.get("term", "")
            value = flt.get("value", "")
            label_source = flt.get("label") or value
            label = f"{label_source} ×"
            width = (
                ui_bgl.get_text_size(
                    font_id=1,
                    text=label,
                    text_size=self.free_button_text_size,
                )[0]
                + self.free_button_margin * 4
            )

            # Pre-calculate icon space for author chips
            if term == "author_id":
                icon_size = int(self.filter_button_height * 0.7)
                icon_pad = int((self.filter_button_height - icon_size) / 2)
                icon_space = icon_size + icon_pad * 2
                width += icon_space

                img_fp = paths.get_addon_thumbnail_path("asset_type_author.png")
                button.set_image(img_fp)
                button.set_image_size((icon_size, icon_size))
                button.set_image_position((icon_pad, icon_pad))
            else:
                button.set_image(None)
                button.set_image_size((0, 0))

            if current_left_offset + width > max_x:
                current_row += 1
                current_left_offset = (
                    self.bar_x + self.assetbar_margin + self.free_button_margin
                )

            button.set_location(
                current_left_offset,
                (
                    base_y
                    - (
                        current_row
                        * (self.filter_button_height + self.free_button_margin)
                    )
                ),  # offset up from bar
            )

            button.width = width
            button.height = self.filter_button_height
            button.text = label
            button.text_size = self.free_button_text_size
            button.visible = True
            button.active_filter = {"term": term, "value": value}

            current_left_offset += width + (self.free_button_margin * 2)

        self.active_filter_height = (current_row + 1) * (
            self.filter_button_height + self.free_button_margin
        )

    # endregion active filters

    # region manufacturer
    def _extract_manufacturer_name(self, asset_data):
        manufacturer = asset_data.get("dictParameters", {}).get("manufacturer")
        if not manufacturer:
            return ""
        return self._sanitize_manufacturer_name(str(manufacturer)) or ""

    def _sanitize_manufacturer_name(self, name: str) -> Optional[str]:
        cleaned = name.strip()
        if not cleaned:
            return None

        lowered = cleaned.lower()
        is_url = lowered.startswith(("http://", "https://", "www.")) or "://" in lowered
        if is_url:
            return None

        tokens = re.split(r"[\s,\\/|_-]+", lowered)
        invalid_tokens = {"me", "unknown", "self", "none", "n/a", "na", "null", "nil"}
        if any(t in invalid_tokens for t in tokens if t):
            return None

        # also use regex to disqualify names without any letters, or with only special characters
        if not re.search(r"[a-zA-Z]", cleaned):
            return None

        return cleaned

    def _format_manufacturer_label(self, name: str) -> str:
        if len(name) <= MAX_MANUFACTURER_LABEL_LEN:
            return name
        return name[: MAX_MANUFACTURER_LABEL_LEN - 3].rstrip() + "..."

    def _refresh_manufacturer_names(self, search_results):
        if not search_results:
            self.manufacturer_names = []
            self.manufacturer_counts = Counter()
            return

        # Case-insensitive grouping: count by lowercase key, display first-seen casing
        counts_lower: Counter = Counter()
        display_names: dict = {}
        for asset_data in search_results:
            name = self._extract_manufacturer_name(asset_data)
            if name:
                key = name.lower()
                counts_lower[key] += 1
                if key not in display_names:
                    display_names[key] = name

        most_common = counts_lower.most_common(self.max_manufacturer_filters)
        self.manufacturer_names = [display_names[key] for key, _ in most_common]
        self.manufacturer_counts = Counter(
            {display_names[k]: v for k, v in counts_lower.items()}
        )

    def _update_manufacturer_data(self, search_results: Optional[list[dict]] = None):
        if not utils.experimental_enabled():
            self.manufacturer_names = []
            self.manufacturer_counts = Counter()
            self.manufacturer_section_height = 0
            for btn in self.manufacturer_buttons:
                btn.visible = False
            return

        self._refresh_manufacturer_names(search_results)
        self.position_manufacturer_buttons()

    def _calculate_manufacturer_gray(self, count, min_count, max_count):
        """Map manufacturer usage count to a gray value between 50 and 120."""
        min_gray = 50 / 255
        max_gray = 120 / 255

        if max_count <= min_count:
            return min_gray

        factor = (count - min_count) / (max_count - min_count)
        gray = min_gray + factor * (max_gray - min_gray)
        return min(max_gray, max(min_gray, gray))

    def position_manufacturer_buttons(self):
        """Position manufacturer buttons in the asset bar.

        The number of manufacturer buttons is determined
        by the number of unique manufacturers in the search results,
        up to a maximum defined by self.max_manufacturer_filters.
        The buttons are sized based on the length of the manufacturer name"""
        self.manufacturer_section_height = 0

        names = self.manufacturer_names[: self.max_manufacturer_filters]
        content_width = max(0, self.bar_width - 2 * self.assetbar_margin)

        if not utils.experimental_enabled() or not names or content_width <= 0:
            for button in self.manufacturer_buttons:
                button.visible = False
            return

        max_x = self.bar_width - self.assetbar_margin

        # if needed expand this to multiple rows calculation,
        # but not now, let's just hide buttons that don't fit in one row
        self.manufacturer_section_height = self.filter_button_height + (
            self.free_button_margin * 2
        )

        if not self.manufacturer_buttons:
            return

        counts = self.manufacturer_counts

        # Vertically center the chips in the dark manufacturer strip at the
        # bottom of the bar. Strip occupies [base_bar_height, bar_height]
        # within the panel; centering a chip of height filter_button_height
        # in a strip of height (filter_button_height + 2*free_button_margin)
        # leaves free_button_margin of padding above and below.
        chip_y = self.bar_y + self.base_bar_height + self.free_button_margin
        displayed_counts = [counts.get(name, 0) for name in self.manufacturer_names]

        min_count = min(displayed_counts) if displayed_counts else 1
        max_count = max(displayed_counts) if displayed_counts else 1

        current_left_offset = (
            self.bar_x + self.assetbar_margin + self.free_button_margin
        )
        for idx, button in enumerate(self.manufacturer_buttons):
            if idx >= len(names):
                button.visible = False
                continue
            name = self.manufacturer_names[idx]
            label = self._format_manufacturer_label(name)

            # shift to the right so we leave space for the clear bubble
            # button.x += clear_slot
            width = (
                ui_bgl.get_text_size(
                    font_id=1,
                    text=label.upper(),
                    text_size=self.free_button_text_size,
                )[0]
                + self.free_button_margin * 4
            )

            if self.free_button_margin + width > max_x:
                button.visible = False
                continue

            button.set_location(
                current_left_offset,
                chip_y,
            )
            button.width = width
            button.height = self.filter_button_height
            button.text = label.upper()
            button.text_size = self.free_button_text_size
            button.visible = True
            button.manufacturer_name = name
            count = counts.get(name, min_count)
            gray = self._calculate_manufacturer_gray(count, min_count, max_count)
            hover_gray = min(gray + 0.1, 1.0)
            button.bg_color = (gray, gray, gray, 0.85)
            button.hover_bg_color = (hover_gray, hover_gray, hover_gray, 1.0)

            current_left_offset += width + (self.free_button_margin * 2)

    # endregion manufacturer

    def _position_single_button(self, button, asset_x, asset_y, asset_idx, sr_len):
        """Position a single asset button and its sub-widgets."""
        button.set_location(asset_x, asset_y)
        button.validation_icon.set_location(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
        )
        button.bookmark_button.set_location(
            asset_x
            + self.button_size
            - self.icon_size
            - self.button_margin
            - self.validation_icon_margin,
            asset_y + self.button_margin + self.validation_icon_margin,
        )
        button.progress_bar.set_location(asset_x, asset_y + self.button_size - 6)
        button.author_button.set_location(
            asset_x + self.button_margin + self.validation_icon_margin,
            asset_y + self.button_margin + self.validation_icon_margin,
        )

        if 0 <= asset_idx < sr_len:
            # If this button was just assigned to a new asset index (scrolling),
            # hide overlay badges immediately to avoid "ghost" badges from the
            # previous asset. update_buttons() will restore them when ready.
            if getattr(button, "asset_index", -1) != asset_idx:
                button.asset_index = asset_idx
                button.validation_icon.visible = False
                button.bookmark_button.visible = False
                button.author_button.visible = False
                button.progress_bar.visible = False
                button.red_alert.visible = False
            button.visible = True
        else:
            button.visible = False
            button.validation_icon.visible = False
            button.bookmark_button.visible = False
            button.author_button.visible = False
            button.progress_bar.visible = False
        button.red_alert.set_location(
            asset_x - self.validation_icon_margin,
            asset_y - self.validation_icon_margin,
        )

    def _update_scroll_indicator(self):
        """Position and size the scroll position indicator.

        In single-row mode the indicator runs horizontally along the bottom
        edge of the asset bar. In multi-row mode it runs vertically along
        the right edge, since scrolling there moves whole rows. Hidden
        whenever the entire result set fits without scrolling. Reads
        ``scroll_offset + scroll_phase / button_size`` so the thumb glides
        smoothly during animation.
        """
        track = self.scroll_indicator_track
        thumb = self.scroll_indicator_thumb

        history_step = search.get_active_history_step()
        sro = history_step.get("search_results_orig") if history_step else None
        sr = search.get_search_results() or []
        total = sro.get("count") if isinstance(sro, dict) else None
        if not isinstance(total, int) or total <= 0:
            total = len(sr)

        if self.button_size <= 0 or total <= 0 or self.wcount <= 0:
            track.visible = False
            thumb.visible = False
            return

        thickness = max(
            2, int(round(SCROLL_INDICATOR_THICKNESS_PX * ui_bgl.get_ui_scale()))
        )
        margin = self.assetbar_margin
        bar_inner_width = max(1, self.bar_width - 2 * margin)
        bar_inner_height = max(1, self.base_bar_height - 2 * margin)

        # Convert phase (pixels) into the same unit as `scroll_offset`.
        phase_slots = (self.scroll_phase or 0.0) / float(self.button_size)
        if self.hcount > 1:
            # Vertical: scrolling moves whole rows. Work in row units.
            total_units = int(math.ceil(total / float(self.wcount)))
            visible_units = self.hcount
            progress = self.scroll_offset / float(self.wcount) + phase_slots
            track_length = bar_inner_height
        else:
            # Horizontal: scrolling moves item-by-item.
            total_units = total
            visible_units = self.wcount
            progress = self.scroll_offset + phase_slots * self.wcount
            track_length = bar_inner_width

        if total_units <= visible_units:
            track.visible = False
            thumb.visible = False
            return

        progress = max(0.0, min(float(total_units - visible_units), progress))

        thumb_length = max(
            SCROLL_INDICATOR_MIN_THUMB_PX,
            int(round(track_length * visible_units / total_units)),
        )
        thumb_offset = int(
            round(
                (track_length - thumb_length)
                * (progress / float(total_units - visible_units))
            )
        )

        if self.hcount > 1:
            # Vertical: pinned to right edge, inside the bar.
            track_x = self.bar_width - thickness - 1
            track_y = margin
            track.width = thickness
            track.height = bar_inner_height
            track.set_location(track_x, track_y)
            thumb.width = thickness
            thumb.height = thumb_length
            thumb.set_location(track_x, track_y + thumb_offset)
        else:
            # Horizontal: pinned to bottom edge of thumbnail strip.
            track_y = self.base_bar_height - thickness - 1
            track.width = bar_inner_width
            track.height = thickness
            track.set_location(margin, track_y)
            thumb.width = thumb_length
            thumb.height = thickness
            thumb.set_location(margin + thumb_offset, track_y)

        # `set_location` writes the same coords to `x` (panel-local) and
        # `x_screen` (absolute). Bake the panel offset into `x_screen` so
        # the indicator draws at the correct absolute position whether or
        # not `panel.layout_widgets()` runs between updates. Without this
        # the indicator sits at panel-local coords in screen space at rest
        # and only happens to land in the right spot during smooth-scroll
        # animation (which re-bakes via `_smooth_scroll_redraw`).
        panel = getattr(self, "panel", None)
        if panel is not None:
            px = panel.x_screen
            py = panel.y_screen
            track.update(px + track.x, py + track.y)
            thumb.update(px + thumb.x, py + thumb.y)

        track.visible = True
        thumb.visible = True

    def position_and_hide_buttons(self):
        """Position asset buttons in the asset bar and hide unused buttons.

        Includes one buffer row above and below (multi-row) or two buffer
        columns on each side (single-row) so that scroll animation has
        content to slide in from off-screen.  The draw callback clips
        everything to the visible bar area with a GPU scissor rect.
        """
        sr = search.get_search_results()
        if sr is None:
            sr = []

        sr_len = len(sr)
        i = 0

        # Grid range including buffer rows/cols on each side for scroll animation.
        if self.hcount > 1:
            y_start = -SCROLL_BUFFER_ROWS
            y_end = self.hcount + SCROLL_BUFFER_ROWS
            x_start, x_end = 0, self.wcount
        else:
            y_start, y_end = 0, 1
            x_start = -SCROLL_BUFFER_COLS
            x_end = self.wcount + SCROLL_BUFFER_COLS

        # Buttons are positioned at their integer grid slots. The sub-slot
        # smooth-scroll offset (scroll_phase) is NOT baked into positions here;
        # it is applied as a single draw-time translate in the asset-bar draw
        # callback (see _update_grid_draw_offset). That way a smooth-scroll
        # animation frame no longer repositions every grid widget.
        #
        # Reposition the grid (incl. buffer rows/cols) and hide the rest. Each
        # set_location() inside would normally tag a redraw; coalesce them into
        # a single redraw for the whole pass.
        with batched_region_redraw():
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    if i >= len(self.asset_buttons):
                        break
                    asset_x = self.assetbar_margin + x * self.button_size
                    asset_y = self.assetbar_margin + y * self.button_size
                    logical_idx = x + y * self.wcount

                    button = self.asset_buttons[i]
                    button.button_index = logical_idx
                    button._grid_positioned = True
                    self._position_single_button(
                        button,
                        asset_x,
                        asset_y,
                        logical_idx + self.scroll_offset,
                        sr_len,
                    )
                    i += 1
                else:
                    continue
                break

            for a in range(i, len(self.asset_buttons)):
                button = self.asset_buttons[a]
                # Already hidden by a previous pass - skip the redundant work
                # (this loop runs every smooth-scroll frame over ~300 buttons).
                # getattr default covers the first pass, before _grid_positioned
                # has ever been assigned on freshly-created buffer buttons.
                if (
                    not getattr(button, "_grid_positioned", False)
                    and not button.visible
                ):
                    continue
                button._grid_positioned = False
                button.visible = False
                button.validation_icon.visible = False
                button.bookmark_button.visible = False
                button.author_button.visible = False
                button.progress_bar.visible = False
                button.red_alert.visible = False
        region_redraw()

        self.position_active_filter_buttons()

        self.button_scroll_down.height = self.bar_height
        self.button_scroll_down.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )
        self.button_scroll_up.height = self.bar_height
        self.button_scroll_up.set_image_position(
            (0, int((self.bar_height - self.button_size) / 2))
        )

    # region setup

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._quad_view_state = None
        self._restart_pending = False
        self._reset_resize_state()
        self.scroll_offset = 0
        self._tooltip_available_height = None

        # Smooth-scroll animation state. `scroll_phase` is a signed pixel
        # offset along the active scroll axis: `total_visual_position = (
        # scroll_offset + scroll_phase / button_size) * slot_size_px`.
        # While `_scroll_animating` is True the modal timer ticks the phase
        # toward rest (friction decay -> magnetic snap to zero).
        self.scroll_phase = 0.0
        # Sub-slot scroll offset applied as a single draw-time gpu.matrix
        # translate to all grid widgets (GPU coords: +x right, +y up), instead
        # of repositioning every widget per animation frame. Updated from
        # scroll_phase by _update_grid_draw_offset(); read by the draw callback.
        self._grid_draw_offset = (0.0, 0.0)
        self._scroll_velocity = 0.0
        self._scroll_last_input_time = 0.0
        self._scroll_last_tick_time = 0.0
        self._scroll_animating = False
        # True while the active source is the discrete mouse wheel (velocity
        # injected per-notch). The tick must integrate phase from velocity
        # even during active input, since wheel notches don't carry a
        # continuous pixel delta the way trackpad pans do.
        self._scroll_wheel_mode = False
        # Sticky travel direction (-1, 0, +1). Captures the dominant sign of
        # recent input/velocity so the snap stage can prefer continuing in
        # the same direction instead of always pulling phase toward 0.
        self._scroll_travel_dir = 0
        self._trackpad_axis_vertical = None

        self.base_bar_height = 0

        self._last_search_results_id = None

        self.max_active_filter_chips = 12
        self.active_filter_buttons = []
        self.active_filter_height = 0

        self.max_manufacturer_filters = 10
        self.manufacturer_buttons = []
        self.manufacturer_names = []
        self.manufacturer_counts = Counter()
        self.manufacturer_section_height = 0

    def on_init(self, context):
        """Initialize the asset bar operator."""
        self.tooltip_base_size_pixels = TOOLTIP_SIZE_PX
        self.tooltip_scale = 1.0
        self.bottom_panel_fraction = 0.18
        self.needs_tooltip_update = False
        self._reset_resize_state()
        self.update_ui_size(context)
        self._quad_view_state = self._is_quad_view(context)

        # todo move all this to update UI size
        ui_props = context.window_manager.blenderkitUI

        self.draw_tooltip = False
        # let's take saved scroll offset and use it to keep scroll between operator runs

        self.last_scroll_offset = -10  # set to -10 so it updates on first run
        self.scroll_offset = ui_props.scroll_offset

        self.text_color = (0.9, 0.9, 0.9, 1.0)
        self.info_color = (0.6, 0.6, 0.6, 1.0)
        self.caution_color = (0.7, 0.7, 0.5, 1.0)
        self.warning_color = (0.9, 0.3, 0.3, 1.0)

        self.init_ui()
        self.init_tooltip()
        self.hide_tooltip()

    def setup_widgets(self, context, event):
        """Set up all widgets for the asset bar and tooltip."""
        widgets_panel = []
        widgets_panel.extend(self.widgets_panel)
        widgets_panel.extend(self.buttons)

        widgets_panel.extend(self.asset_buttons)
        widgets_panel.extend(self.red_alerts)
        # we try to put bookmark_buttons before others, because they're on top
        widgets_panel.extend(self.bookmark_buttons)
        widgets_panel.extend(self.validation_icons)
        widgets_panel.extend(self.author_buttons)
        widgets_panel.extend(self.progress_bars)
        # Scroll indicator goes last so it draws on top of every thumbnail
        # and overlay; otherwise it would be occluded by the asset buttons.
        widgets_panel.append(self.scroll_indicator_track)
        widgets_panel.append(self.scroll_indicator_thumb)
        # Resize handle is registered last so reverse-order dispatch gives it
        # priority over the asset buttons along the bottom edge.
        widgets_panel.append(self.resize_handle)

        widgets = [self.panel]

        widgets += widgets_panel
        widgets.append(self.tooltip_panel)
        widgets += self.tooltip_widgets

        self.init_widgets(context, widgets)

        self.panel.add_widgets(widgets_panel)
        self.tooltip_panel.add_widgets(self.tooltip_widgets)

        stored_area, stored_region = self._unwrap_area_region(
            getattr(self, "context", None)
        )
        override_ctx = self._build_context_snapshot(
            context,
            stored_area or context.area,
            stored_region or context.region,
        )
        self._apply_widget_context(override_ctx)

    # endregion setup

    # region events

    def on_invoke(self, context, event):
        """Invoke the asset bar operator."""
        # Microsoft Store builds of Blender are sandboxed and break a number of
        # Blendkit features (client launch, background Blender, writing into
        # blenderkit_data). Show an in-viewport warning instead of the asset
        # bar on first launch; the warning's "Proceed anyway" button persists
        # the acceptance flag and re-invokes the asset bar.
        from .. import warning_dialog

        if warning_dialog.should_block_for_ms_store():
            warning_dialog.show_ms_store_warning()
            return False

        self.instances.append(self)
        if not context.area:
            return False

        ui_props = context.window_manager.blenderkitUI
        needs_initial_search = not search.get_search_results()
        if needs_initial_search:
            search.get_active_history_step()["is_searching"] = True

        self.on_init(context)
        self.context = context

        # start search if there isn't a search result yet
        if needs_initial_search:
            search.search()

        if ui_props.assetbar_on:
            # keep_running=True means "reuse" the existing instance instead of toggling it off
            if not self.keep_running:
                ui_props.turn_off = True
                # if there was an error, reset the flag so next invocation can start cleanly
                ui_props.assetbar_on = False
            return False

        # Clear stale shutdown flag from previous sessions (e.g. undo or addon reload)
        ui_props.turn_off = False
        ui_props.assetbar_on = True
        global asset_bar_operator

        asset_bar_operator = self

        self.active_index = -1

        self.check_new_search_results(context)
        self.setup_widgets(context, event)
        self.set_element_images()
        self.position_and_hide_buttons()
        self.hide_tooltip()

        self.panel.set_location(self.bar_x, self.bar_y)

        self.scroll_update(always=True)

        self.window = context.window
        self.area = context.area
        self.scene = bpy.context.scene

        self._save_and_hide_overlays(context)

        return True

    def _save_and_hide_overlays(self, context):
        """Save and disable viewport overlay stats/text while the asset bar is open."""
        self._saved_overlays = {}
        screen = getattr(context.window, "screen", None) if context.window else None
        if screen is None:
            return
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                try:
                    ptr = space.as_pointer()
                    self._saved_overlays[ptr] = {
                        "show_stats": space.overlay.show_stats,
                        "show_text": space.overlay.show_text,
                    }
                    space.overlay.show_stats = False
                    space.overlay.show_text = False
                except Exception:
                    pass
                break

    def _set_overlays(self, context, show: bool):
        """Set or restore viewport overlay stats/text.

        When *show* is True, values are restored from the saved state.
        When *show* is False, both flags are forced off (saved state unchanged).
        """
        saved = getattr(self, "_saved_overlays", {})
        screen = getattr(context.window, "screen", None) if context.window else None
        if screen is None:
            return
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                try:
                    ptr = space.as_pointer()
                    if show:
                        state = saved.get(ptr)
                        if state:
                            space.overlay.show_stats = state["show_stats"]
                            space.overlay.show_text = state["show_text"]
                    else:
                        space.overlay.show_stats = False
                        space.overlay.show_text = False
                except Exception:
                    pass
                break

    def _restore_overlays(self, context):
        """Restore viewport overlay stats/text to their saved state."""
        self._set_overlays(context, show=True)

    def on_finish(self, context):
        # redraw all areas, since otherwise it stays to hang for some more time.
        # bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d_tooltip, 'WINDOW')
        # to pass the operator to validation icons
        global asset_bar_operator
        asset_bar_operator = None
        self.restore_resize_cursor()
        self._reset_resize_state()

        context.window_manager.event_timer_remove(self._timer)

        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.assetbar_on = False
        ui_props.scroll_offset = self.scroll_offset

        self._restore_overlays(context)

        self._finished = True
        # to ensure the asset buttons are removed from screen
        self._redraw_tracked_regions()

    # handlers
    def enter_button(self, widget):
        """Handle mouse enter on an asset button."""
        if self._resize_dragging:
            return
        if not hasattr(widget, "button_index") or widget.button_index < 0:
            return  # click on left/right arrow button gave no attr button_index
            # we should detect on which button_index scroll/left/right happened to refresh shown thumbnail

        bpy.context.window.cursor_set("HAND")
        search_index = widget.button_index + self.scroll_offset
        if search_index < self.search_results_count:
            self.show_tooltip()
        if self.active_index != search_index:
            self.active_index = search_index
            sr = search.get_search_results()
            if search_index >= len(sr):
                return  # issue #1481 - index can be sometimes over the length of search results
            asset_data = sr[search_index]

            # Skip tooltip for placeholder entries (results not yet loaded)
            if asset_data.get("placeholder"):
                self.draw_tooltip = False
                self.hide_tooltip()
                return

            self.draw_tooltip = True
            # self.tooltip = asset_data['tooltip']
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = search_index  # + self.scroll_offset

            # Update tooltip size based on asset type
            thumbnail_found = False
            self.tooltip_image_help.visible = False
            if asset_data["assetType"].lower() in {
                "printable",
                "model",
                "scene",
            } and self.show_thumbnail_variant in {"PHOTO", "WIREFRAME"}:
                t_type = self.show_thumbnail_variant.lower()
                if t_type == "photo":
                    photo_img = ui.get_full_photo_thumbnail(asset_data)
                    if photo_img:
                        self.tooltip_image.set_image(photo_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                        thumbnail_found = True
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                        self.tooltip_image_help.text = "Photo thumbnail not ready yet."
                        self.tooltip_image_help.visible = True

                elif t_type == "wireframe":
                    wire_img = ui.get_full_wire_thumbnail(asset_data)
                    if wire_img:
                        self.tooltip_image.set_image(wire_img.filepath)
                        self.tooltip_image.set_image_colorspace("")
                        thumbnail_found = True
                    else:
                        self.tooltip_image.set_image(
                            paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                        )
                        self.tooltip_image_help.text = (
                            "Wireframe thumbnail not ready yet."
                        )
                        self.tooltip_image_help.visible = True

            if not thumbnail_found:
                set_thumb_check(self.tooltip_image, asset_data, thumb_type="thumbnail")

            get_tooltip_data(asset_data)
            is_author = asset_data.get("assetType") == "author"

            if is_author:
                # --- Author-specific tooltip content ---
                an = asset_data.get("displayName", "")
                max_name_length = 30
                if len(an) > max_name_length + 3:
                    an = an[:30] + "..."
                self.asset_name.text = an

                # Show asset count next to name using authors_name (right-aligned)
                asset_count = asset_data["tooltip_data"].get("asset_count", 0)
                if asset_count > 0:
                    self.authors_name.text = f"{asset_count} assets"
                    self.authors_name.text_color = (0.7, 0.7, 0.7, 0.8)
                    self.authors_name.visible = True
                else:
                    self.authors_name.visible = False

                # Show aboutMe in the dedicated multiline label with word wrapping
                about_me = asset_data["tooltip_data"].get("about_me", "")
                max_about_lines = 8
                # Estimate chars per line from tooltip width and font size
                chars_per_line = max(
                    20, int(self.tooltip_width / (self.author_text_size * 0.65))
                )
                lines = []
                if about_me:
                    # Word-wrap aboutMe text
                    all_wrapped = []
                    for paragraph in about_me.split("\n"):
                        words = paragraph.split()
                        current_line = ""
                        for word in words:
                            if (
                                current_line
                                and len(current_line) + 1 + len(word) > chars_per_line
                            ):
                                all_wrapped.append(current_line)
                                current_line = word
                            else:
                                current_line = (
                                    f"{current_line} {word}" if current_line else word
                                )
                        if current_line:
                            all_wrapped.append(current_line)
                    # Limit to max_about_lines, add ellipsis if truncated
                    if len(all_wrapped) > max_about_lines:
                        all_wrapped = all_wrapped[:max_about_lines]
                        last = all_wrapped[-1]
                        if len(last) + 3 > chars_per_line:
                            last = last[: chars_per_line - 3]
                        all_wrapped[-1] = last + "..."
                    lines.extend(all_wrapped)
                about_text = "\n".join(lines)
                self.author_about_me.text = about_text
                self.author_about_me.visible = True

                # Set tooltip image to gravatar
                author_id = int(
                    asset_data.get("id", asset_data.get("author", {}).get("id", 0))
                )
                author = global_vars.BKIT_AUTHORS.get(author_id)
                if author is not None and author.gravatarImg:
                    self.tooltip_image.set_image(author.gravatarImg)
                else:
                    img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                    self.tooltip_image.set_image(img_path)
                self.tooltip_image.set_image_colorspace("")

                # Show help text
                self.tooltip_image_help.text = "Click to search assets by this author"
                self.tooltip_image_help.visible = True

                # Hide widgets that don't apply to authors
                self.gravatar_image.visible = False
                self.quality_label.visible = False
                self.quality_star.visible = False
                self.multi_price_label.visible = False
                self.version_warning.text = ""
            else:
                # --- Regular asset tooltip content ---
                self.author_about_me.visible = False

                an = asset_data["displayName"]
                max_name_length = 30
                if len(an) > max_name_length + 3:
                    an = an[:30] + "..."

                search_props = utils.get_search_props()

                # if in top nodegroup category, show which type the nodegroup is
                if (
                    asset_data["assetType"] == "nodegroup"
                    and search_props.search_category == "nodegroup"
                ):
                    an = f"{an} - {asset_data['dictParameters']['nodeType']} nodes"

                self.asset_name.text = an
                self.authors_name.text = asset_data["tooltip_data"]["author_text"]
                self.authors_name.visible = True
                self.gravatar_image.visible = True

                # Hide ratings for addons
                is_addon = asset_data.get("assetType") == "addon"
                if not is_addon:
                    quality_text = asset_data["tooltip_data"]["quality"]
                    if utils.profile_is_validator():
                        quality_text += f" / {int(asset_data['score'])}"
                    self.quality_label.text = quality_text
                    self.quality_label.visible = True
                    self.quality_star.visible = True
                else:
                    self.quality_label.visible = False
                    self.quality_star.visible = False

                # Update price labels for addons
                user_price_text = asset_data["tooltip_data"].get("user_price_text", "")
                base_price_text = asset_data["tooltip_data"].get("base_price_text", "")

                user_price_text_color = asset_data["tooltip_data"].get(
                    "user_price_color", ""
                )
                base_price_text_color = asset_data["tooltip_data"].get(
                    "base_price_color", ""
                )

                user_price_background_color = asset_data["tooltip_data"].get(
                    "user_price_bg_color", ""
                )
                base_price_background_color = asset_data["tooltip_data"].get(
                    "base_price_bg_color", ""
                )

                self.multi_price_label.text_a = user_price_text
                self.multi_price_label.text_a_color = user_price_text_color
                self.multi_price_label.segment_background_color_a = (
                    user_price_background_color
                )

                self.multi_price_label.text_b = base_price_text
                self.multi_price_label.text_b_color = base_price_text_color
                self.multi_price_label.segment_background_color_b = (
                    base_price_background_color
                )

                self.multi_price_label.multiline = True

                if user_price_text and base_price_text:
                    self.multi_price_label.strikethrough_b = True
                    self.multi_price_label.visible = True
                    self.multi_price_label.segment_backgrounds = True
                elif user_price_text or base_price_text:
                    self.multi_price_label.visible = True
                    self.multi_price_label.strikethrough_b = False
                    self.multi_price_label.segment_backgrounds = True
                else:
                    self.multi_price_label.visible = False
                    self.multi_price_label.strikethrough_b = False
                    self.multi_price_label.segment_backgrounds = False

                # preview comments for validators
                self.update_comments_for_validators(asset_data)

                has_warning, difference = utils.asset_from_newer_blender_version(
                    asset_data
                )
                if has_warning:
                    if difference == "major_newer":
                        self.version_warning.text = f"Made in Blender {asset_data['sourceAppVersion']}! Use at your own risk."
                        self.version_warning.text_color = self.warning_color
                    elif difference == "minor":
                        self.version_warning.text = f"Made in Blender {asset_data['sourceAppVersion']}. Caution advised."
                        self.version_warning.text_color = self.caution_color
                else:
                    self.version_warning.text = ""

                # Addon-specific compatibility warning. This takes precedence
                # over the generic sourceAppVersion notice because it's based
                # on the addon's own declared supported range.
                if is_addon:
                    compat_ok, min_v, max_v = utils.get_addon_blender_compatibility(
                        asset_data
                    )
                    if not compat_ok:
                        if min_v and max_v:
                            rng = f"{min_v}\u2013{max_v}"
                        elif min_v:
                            rng = f"{min_v}+"
                        else:
                            rng = f"\u2264{max_v}"
                        cur = utils.get_blender_version()
                        self.version_warning.text = f"Incompatible: addon requires Blender {rng} (you have {cur})"
                        self.version_warning.text_color = self.warning_color

                author_id = int(asset_data["author"]["id"])
                author = global_vars.BKIT_AUTHORS.get(author_id)
                if author is None:
                    bk_logger.info(
                        "\n\n\nget_tooltip_data() AUTHOR NOT FOUND", author_id
                    )

                if author is not None and author.gravatarImg:
                    self.gravatar_image.set_image(author.gravatarImg)
                else:
                    img_path = paths.get_addon_thumbnail_path("thumbnail_notready.jpg")
                    self.gravatar_image.set_image(img_path)
                self.gravatar_image.set_image_colorspace("")

            area, region = self._current_area_region()

            properties_width = 0
            if area is not None:
                for r in getattr(area, "regions", []):
                    if r.type == "UI":
                        properties_width = r.width
                        break

            # reset tooltip sizing so each spawn starts from base values
            self._reset_tooltip_dimensions()

            fallback_region = getattr(bpy.context, "region", None)
            active_region = region or fallback_region
            region_width = getattr(active_region, "width", None)
            if region_width is None:
                region_width = self.tooltip_panel.width + properties_width
            region_height = getattr(active_region, "height", None)
            if region_height is None:
                region_height = self.tooltip_panel.height + widget.height

            tooltip_x = min(
                int(widget.x_screen),
                int(region_width - self.tooltip_panel.width - properties_width),
            )
            tooltip_x = max(0, tooltip_x)

            # Calculate space above and below the button to decide tooltip placement
            full_tooltip_height = self.tooltip_panel.height
            space_above = widget.y_screen
            space_below = region_height - (widget.y_screen + widget.height)
            place_above = (
                space_below < full_tooltip_height
                and space_below < full_tooltip_height * 0.7
                and space_below < space_above
            )

            if place_above:
                available_height = space_above
            else:
                available_height = space_below

            self._tooltip_available_height = max(64, int(available_height))

            # need to set image here because of context issues.
            img_path = paths.get_addon_thumbnail_path("star_grey.png")
            self.quality_star.set_image(img_path)

            tooltip_context = self._build_context_snapshot(
                bpy.context, area, active_region
            )
            self.update_tooltip_size(tooltip_context)
            self.update_tooltip_layout(tooltip_context)
            tooltip_width = self.tooltip_width
            max_x = max(0, int(region_width - tooltip_width - properties_width))
            tooltip_x = min(max(0, int(widget.x_screen)), max_x)

            if place_above:
                tooltip_y = int(widget.y_screen - self.tooltip_height)
            else:
                tooltip_y = int(widget.y_screen + widget.height)

            max_y = max(0, int(region_height - self.tooltip_height))
            tooltip_y = min(max(0, tooltip_y), max_y)

            self.tooltip_panel.set_location(tooltip_x, tooltip_y)
            self.tooltip_panel.layout_widgets()
            # show bookmark button - always on mouse enter (but not for authors)
            if widget.bookmark_button and not is_author:
                widget.bookmark_button.visible = True

    def exit_button(self, widget):
        """Handle mouse exit from an asset button."""
        if self._resize_dragging:
            return
        # this condition checks if there wasn't another button already entered, which can happen with small button gaps
        if self.active_index == widget.button_index + self.scroll_offset:
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.draw_tooltip = False
            self.draw_tooltip = False
            self.hide_tooltip()
            self.active_index = -1
            ui_props = bpy.context.window_manager.blenderkitUI
            ui_props.active_index = self.active_index
            bpy.context.window.cursor_set("DEFAULT")
        # hide bookmark button - only when Not bookmarked
        # make sure to transfer some data, to prevent missing attribute
        widget.bookmark_button.asset_index = widget.button_index
        widget.author_button.asset_index = widget.button_index
        self.update_bookmark_icon(widget.bookmark_button)

    def bookmark_asset(self, widget):
        """Bookmark the asset linked to this button."""
        # bookmark the asset linked to this button
        if not utils.user_logged_in():
            bpy.ops.wm.blenderkit_login_dialog(
                "INVOKE_DEFAULT",
                message="Please login to bookmark your favorite assets.",
                placement="bookmarks_prompt",
            )
            return

        sr = search.get_search_results()
        asset_data = sr[widget.asset_index]  # + self.scroll_offset]
        if asset_data.get("assetType") == "author":
            return

        bpy.ops.wm.blenderkit_bookmark_asset(asset_id=asset_data["id"])
        self.update_bookmark_icon(widget)

    def show_author_profile(self, widget):
        """Show the author profile linked to this button."""
        sr = search.get_search_results()
        asset_data = sr[widget.asset_index]  # + self.scroll_offset]
        author_id = asset_data["id"]
        int_id = int(author_id)
        author = global_vars.BKIT_AUTHORS.get(int_id)
        if author is None:
            bk_logger.warning("author is none")
            return
        # personal site >>
        # url = author.aboutMeUrl

        # Blendkit site profile >>
        url = paths.get_author_gallery_url(author_id, placement="asset_bar_author")
        if url is None:
            bk_logger.warning("url is none")
            return
        bpy.ops.wm.url_open(url=url)

    def drag_drop_asset(self, widget):
        """Start drag and drop operation for the asset linked to this button."""
        now = time.time()
        # avoid double click to download assets under panels, mainly category panel
        if now - ui_panels.last_time_overlay_panel_active < 0.5:
            return
        ui_props = bpy.context.window_manager.blenderkitUI
        if ui_props.dragging:
            return

        # Author assets: clicking/dragging triggers search-by-author instead.
        # Use ``button_index`` (kept in sync by position_and_hide_buttons),
        # NOT the stale ``search_index`` set once at button creation.
        search_index = widget.button_index + self.scroll_offset
        sr = search.get_search_results()
        if sr and 0 <= search_index < len(sr):
            asset_data = sr[search_index]
            if asset_data.get("placeholder"):
                return
            if asset_data.get("assetType") == "author":
                self.search_by_author(search_index)
                return

        # start drag drop
        bpy.ops.view3d.asset_drag_drop(
            "INVOKE_DEFAULT",
            asset_search_index=search_index,
        )

    def cancel_press(self, widget):
        """Handle cancel/close button press."""
        self.finish()

    def toggle_expand(self, widget):
        """Toggle the expanded state of the asset bar from the visible button."""
        self.toggle_assetbar_rows()

    def handle_key_input(self, event):
        """Handle keyboard shortcuts for asset bar operations."""
        # Check if enough time has passed since last popup/text input activity
        # to prevent shortcuts from triggering while typing in text fields
        now = time.time()
        if now - ui_panels.last_time_overlay_panel_active < 0.5:
            return False

        # Shortcut: Toggle between normal, photo and wireframe thumbnail
        if event.type in {"ONE"}:
            if self.show_thumbnail_variant != "THUMBNAIL":
                self.show_thumbnail_variant = "THUMBNAIL"
                self.needs_tooltip_update = True
        if event.type in {"TWO"}:
            if self.show_thumbnail_variant != "PHOTO":
                self.show_thumbnail_variant = "PHOTO"
                self.needs_tooltip_update = True
        if event.type in {"THREE"}:
            if self.show_thumbnail_variant != "WIREFRAME":
                self.show_thumbnail_variant = "WIREFRAME"
                self.needs_tooltip_update = True
        if (
            event.type in {"LEFT_BRACKET", "RIGHT_BRACKET"}
            and not event.shift
            and self.active_index > -1
        ):
            # iterate index and update tooltip
            c_idx = 0
            was_thumbnail_variant = self.show_thumbnail_variant
            if self.show_thumbnail_variant in THUMBNAIL_TYPES:
                c_idx = THUMBNAIL_TYPES.index(self.show_thumbnail_variant)

            if event.type == "LEFT_BRACKET":
                c_idx -= 1
            elif event.type == "RIGHT_BRACKET":
                c_idx += 1
            # clamp index - no rollover
            c_idx = min(max(c_idx, 0), len(THUMBNAIL_TYPES) - 1)

            if was_thumbnail_variant == THUMBNAIL_TYPES[c_idx]:
                return True
            # else update
            self.show_thumbnail_variant = THUMBNAIL_TYPES[c_idx]
            self.needs_tooltip_update = True
            return True

        # Check if active asset is an author (for guarding shortcuts below)
        _is_author_active = False
        if self.active_index > -1:
            _sr = search.get_search_results()
            if _sr and self.active_index < len(_sr):
                _is_author_active = _sr[self.active_index].get("assetType") == "author"

        # Shortcut: Search by author
        if event.type == "A":
            self.search_by_author(self.active_index)
            return True

        # Shortcut: Delete asset from hard-drive (not for authors)
        if event.type == "X" and self.active_index > -1 and not _is_author_active:
            # delete downloaded files for this asset
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bk_logger.info("deleting asset from local drive: %s", asset_data["name"])
            paths.delete_asset_debug(asset_data)
            asset_data["downloaded"] = 0
            return True

        # Shortcut: Open Author's personal Webpage
        if event.type == "W" and self.active_index > -1:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            author_id = int(asset_data["author"]["id"])
            author = global_vars.BKIT_AUTHORS.get(author_id)
            if author is None:
                bk_logger.warning("author is none")
                return True
            utils.p("author:", author)
            url = author.aboutMeUrl
            if url is None:
                bk_logger.warning("url is none")
                return True
            bpy.ops.wm.url_open(url=url)
            return True

        # Shortcut: Search Similar (not for authors)
        if event.type == "S" and self.active_index > -1 and not _is_author_active:
            self.search_similar(self.active_index)
            return True

        if event.type == "C" and self.active_index > -1 and not _is_author_active:
            self.search_in_category(self.active_index)
            return True

        if event.type == "B" and self.active_index > -1 and not _is_author_active:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.wm.blenderkit_bookmark_asset(asset_id=asset_data["id"])
            return True

        # Shortcut: Open Author's profile on BlenderKit
        if event.type == "P" and self.active_index > -1:
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            author_id = int(asset_data["author"]["id"])
            author = global_vars.BKIT_AUTHORS.get(author_id)
            if author is None:
                return True
            utils.p("author:", author)
            url = paths.get_author_gallery_url(author.id, placement="asset_bar_author")
            bpy.ops.wm.url_open(url=url)
            return True

        # FastRateMenu (not for authors)
        if (
            event.type == "R"
            and self.active_index > -1
            and not event.shift
            and not _is_author_active
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            if not utils.user_is_owner(asset_data=asset_data):
                bpy.ops.wm.blenderkit_menu_rating_upload(
                    asset_name=asset_data["name"],
                    asset_id=asset_data["id"],
                    asset_type=asset_data["assetType"],
                )
            return True

        if (
            event.type == "V"
            and event.shift
            and self.active_index > -1
            and not _is_author_active
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="validated"
            )
            return True

        if (
            event.type == "H"
            and event.shift
            and self.active_index > -1
            and not _is_author_active
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="on_hold"
            )
            return True

        if (
            event.type == "U"
            and event.shift
            and self.active_index > -1
            and not _is_author_active
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="uploaded"
            )
            return True

        if (
            event.type == "R"
            and event.shift
            and self.active_index > -1
            and not _is_author_active
            and utils.profile_is_validator()
        ):
            sr = search.get_search_results()
            asset_data = sr[self.active_index]
            bpy.ops.object.blenderkit_change_status(
                asset_id=asset_data["id"], state="rejected"
            )
            return True

        return False  # Let other shortcuts be handled

    def scroll_up(self, widget):
        """Scroll up in the asset bar."""
        step = self.wcount * self.hcount
        self._scroll_by_slots(step)
        self.enter_button(widget)

    def scroll_down(self, widget):
        """Scroll down in the asset bar."""
        step = -(self.wcount * self.hcount)
        self._scroll_by_slots(step)
        self.enter_button(widget)

    # endregion events

    # region actions

    def apply_term_filter(self, widget: BL_UI_Button, *, term: str):
        """Apply term filter based on the clicked bubble."""
        value = getattr(widget, f"{term}_name", "")
        if not value:
            self.clear_term_filter(widget, term=term)
            return

        label = getattr(widget, "text", value)
        # Mark data-driven filters so we can drop them when the asset type changes
        search.set_active_filter(term=term, value=value, label=label, origin="data")
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def clear_term_filter(self, widget: BL_UI_Button, *, term: str):
        """Remove term filter from the search keywords."""
        search.remove_active_filter(term=term)
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def _filter_out_term(self, term: str, keywords: str):
        """Remove term:* tokens using regex; return clean token list without extra +/spaces."""
        # strip term segments that may contain spaces until the next '+' or string end
        without_term = re.sub(
            rf"(?:^|\+)\s*{term}:[^+]+", "", keywords, flags=re.IGNORECASE
        )
        # normalize plus separators and drop empty pieces
        tokens = [part for part in without_term.replace(" ", "").split("+") if part]
        return tokens

    def remove_active_filter_chip(self, widget: BL_UI_Button):
        active_filter = getattr(widget, "active_filter", None)
        if not active_filter:
            return
        search.remove_active_filter(
            term=active_filter.get("term", ""), value=active_filter.get("value")
        )
        search.update_filters()
        search.create_history_step(search.get_active_tab())
        search.search()
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)

    def asset_menu(self, widget):
        """Open the asset menu for the asset linked to this button."""
        self.hide_tooltip()
        target_index = getattr(widget, "button_index", None)
        if target_index is None:
            target_index = getattr(widget, "asset_index", None)
        if target_index is not None:
            search_index = target_index + self.scroll_offset
            history_step = search.get_active_history_step()
            sr = history_step.get("search_results") or []
            if 0 <= search_index < len(sr):
                # No context menu for placeholder or author results
                if sr[search_index].get("placeholder"):
                    return
                if sr[search_index].get("assetType") == "author":
                    return
                self.active_index = search_index
                ui_props = bpy.context.window_manager.blenderkitUI
                ui_props.active_index = search_index
        bpy.ops.wm.blenderkit_asset_popup("INVOKE_DEFAULT")

    def search_more(self):
        """Search for more assets."""
        history_step = search.get_active_history_step()
        sro = history_step.get("search_results_orig")
        if sro is None:
            return
        if sro.get("next") is None:
            return
        search_props = utils.get_search_props()
        active_history_step = search.get_active_history_step()
        if active_history_step.get("is_searching"):
            return

        search.search(get_next=True)

        # Append placeholder entries so the user can keep scrolling while results load.
        sr = history_step.get("search_results")
        if sr is not None:
            total_count = sro.get("count", len(sr))
            placeholders_needed = min(total_count - len(sr), search.MAX_PAGE_SIZE)
            ui_props = bpy.context.window_manager.blenderkitUI
            asset_type = ui_props.asset_type.lower()
            for _ in range(placeholders_needed):
                sr.append(
                    {
                        "placeholder": True,
                        "assetType": asset_type,
                        "thumbnail_small": "",
                        "verificationStatus": "validated",
                    }
                )

    def update_bookmark_icon(self, bookmark_button: BL_UI_Button):
        """Update the bookmark icon for a given bookmark button."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_index = bookmark_button.asset_index  # type: ignore
        # sometimes happened here that the asset_index was out of range
        if asset_index >= len(sr):
            return
        asset_data = sr[asset_index]
        if asset_data.get("assetType") == "author":
            bookmark_button.visible = False
            return
        if asset_data.get("placeholder") or "id" not in asset_data:
            bookmark_button.visible = False
            return
        rating = ratings_utils.get_rating_local(asset_data["id"])
        if rating is not None and rating.bookmarks == 1:
            icon = "bookmark_full.png"
            visible = True
        else:
            icon = "bookmark_empty.png"
            if self.active_index == bookmark_button.asset_index:  # type: ignore
                visible = True
            else:
                visible = False
        bookmark_button.visible = visible
        img_fp = paths.get_addon_thumbnail_path(icon)
        bookmark_button.set_image(img_fp)

    def update_progress_bar(self, asset_button, asset_data):
        """Update the progress bar for  each button in asset bar.
        Enabled addons are shown in green, disabled but installed in blue."""

        pb = asset_button.progress_bar
        if pb is None:
            return

        if asset_data["downloaded"] > 0:
            pb.bg_color = colors.GREEN
            # For addons, always show full bar when installed, with color based on enabled status
            if asset_data.get("assetType") == "addon":
                w = self.button_size  # Full width for installed addons
                is_enabled = asset_data.get("enabled", False)
                if not is_enabled:
                    # Pale blue for installed but disabled addons
                    pb.bg_color = colors.BLUE
            w = int(self.button_size * asset_data["downloaded"] / 100.0)
            pb.width = w
            pb.update(pb.x_screen, pb.y_screen)
            pb.visible = True
        else:
            pb.visible = False
            return

        self._safe_tag_redraw(bpy.context.region)

    def update_validation_icon(self, asset_button, asset_data: dict):
        """Update the validation icon for each button in asset bar."""
        if asset_data.get("assetType") == "author":
            asset_button.validation_icon.visible = False
            return
        if utils.profile_is_validator():
            rating = global_vars.RATINGS.get(asset_data["id"])
            v_icon = ui.verification_icons[
                asset_data.get("verificationStatus", "validated")
            ]
            if v_icon is not None:
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            elif rating is None or rating.quality is None:
                v_icon = "star_grey.png"
                img_fp = paths.get_addon_thumbnail_path(v_icon)
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            else:
                asset_button.validation_icon.visible = False
        else:
            if asset_data.get("canDownload", True) == 0:
                img_fp = paths.get_addon_thumbnail_path("locked.png")
                asset_button.validation_icon.set_image(img_fp)
                asset_button.validation_icon.visible = True
            else:
                asset_button.validation_icon.visible = False

    def update_image(self, asset_id):
        """should be run after thumbs are retrieved so they can be updated"""
        sr = search.get_search_results()
        if not sr:
            return
        promoted = False
        for asset_button in self.asset_buttons:
            if 0 <= asset_button.asset_index < len(sr):
                asset_data = sr[asset_button.asset_index]
                if asset_data.get("placeholder"):
                    continue
                if asset_data.get("assetBaseId") == asset_id:
                    was_loaded = getattr(asset_button, "_thumb_loaded", False)
                    thumb_loaded = set_thumb_check(
                        asset_button, asset_data, thumb_type="thumbnail_small"
                    )
                    asset_button._thumb_loaded = thumb_loaded
                    # Slot just transitioned from "loading placeholder" to a
                    # real thumbnail - run the full button update so the
                    # overlay badges (validation/bookmark/progress/red_alert)
                    # that were suppressed in update_buttons() are now drawn
                    # against the correct thumbnail.
                    if thumb_loaded and not was_loaded:
                        promoted = True
        if promoted:
            self.update_buttons()

    def update_buttons(self):
        """Update asset buttons in the asset bar based on current search results and scroll offset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results")
        if not sr:
            return
        visible_results = []

        for asset_button in self.asset_buttons:
            # Only re-evaluate buttons that have a grid position.
            # Leftover (unused) buttons stay hidden.
            if not getattr(asset_button, "_grid_positioned", False):
                continue

            asset_button.asset_index = asset_button.button_index + self.scroll_offset
            if 0 <= asset_button.asset_index < len(sr):
                asset_button.visible = True

                asset_data = sr[asset_button.asset_index]
                if asset_data is None:
                    continue

                # Update bookmark and author-profile button indices.
                asset_button.bookmark_button.asset_index = asset_button.asset_index
                asset_button.author_button.asset_index = asset_button.asset_index

                thumb_loaded = set_thumb_check(
                    asset_button, asset_data, thumb_type="thumbnail_small"
                )
                # Track loaded state on the button so update_image() (called
                # when a thumbnail finishes downloading) can promote the slot
                # from "loading - no badges" to fully populated without
                # waiting for the next scroll/update_buttons pass.
                asset_button._thumb_loaded = thumb_loaded

                # Placeholder entries only need thumbnail rendering.
                if asset_data.get("placeholder"):
                    asset_button.bookmark_button.visible = False
                    asset_button.author_button.visible = False
                    asset_button.validation_icon.visible = False
                    asset_button.progress_bar.visible = False
                    asset_button.background_border = False
                    asset_button.background_border_color = None
                    asset_button.use_rounded_background = False
                    asset_button.background_corner_radius = 0.0
                    asset_button.image_corner_radius = None
                    asset_button.background_padding = [0.0, 0.0]
                    asset_button.image_padding = 0.0
                    asset_button.red_alert.visible = False
                    continue

                # Distinguish author cards with a blue border and author icon.
                if asset_data.get("assetType") == "author":
                    asset_button.background_border_thickness = 3.0
                    asset_button.author_button.visible = True
                    asset_button.background_corner_radius = 12.0
                    asset_button.image_corner_radius = 12.0
                    asset_button.background_padding = [-1.0, -1.0]
                    asset_button.background_border = True
                    asset_button.background_border_color = colors.ACTIVE_BLUE
                    asset_button.use_rounded_background = True
                    asset_button.image_padding = (
                        asset_button.background_border_thickness
                    )
                else:
                    asset_button.background_border = False
                    asset_button.background_border_color = None
                    asset_button.author_button.visible = False
                    asset_button.use_rounded_background = False
                    asset_button.background_corner_radius = 0.0
                    asset_button.image_corner_radius = None
                    asset_button.background_padding = [0.0, 0.0]
                    asset_button.image_padding = 0.0

                self.update_validation_icon(asset_button, asset_data)
                self.update_bookmark_icon(asset_button.bookmark_button)
                self.update_progress_bar(asset_button, asset_data)

                # red_alert overlay is reused for two cases (incompatible
                # addons take priority over the validator "old upload" alert):
                if asset_data.get(
                    "assetType"
                ) == "addon" and not utils.is_addon_blender_compatible(asset_data):
                    asset_button.red_alert.bg_color = (0.6, 0.05, 0.05, 0.55)
                    asset_button.red_alert.visible = True
                elif (
                    utils.profile_is_validator()
                    and asset_data["verificationStatus"] == "uploaded"
                ):
                    over_limit = utils.is_upload_old(asset_data.get("lastBlendUpload"))
                    if over_limit:
                        redness = min(over_limit * 0.05, 0.7)
                        asset_button.red_alert.bg_color = (1, 0, 0, redness)
                        asset_button.red_alert.visible = True
                    else:
                        asset_button.red_alert.visible = False
                else:
                    asset_button.red_alert.visible = False

                # When the thumbnail for this slot hasn't been downloaded
                # yet, the slot is showing the "Loading..." placeholder.
                # Suppress all overlay badges (validation icon, bookmark,
                # progress bar, red alert) so we don't draw stale or
                # next-asset badges over a not-yet-loaded thumbnail while
                # scrolling. The badges are restored by update_image() as
                # soon as the real thumbnail arrives.
                if not thumb_loaded:
                    asset_button.validation_icon.visible = False
                    asset_button.bookmark_button.visible = False
                    asset_button.progress_bar.visible = False
                    asset_button.red_alert.visible = False

                visible_results.append(asset_data)
            else:
                # Buffer button with out-of-range index – hide it
                asset_button.visible = False
                asset_button.validation_icon.visible = False
                asset_button.bookmark_button.visible = False
                asset_button.author_button.visible = False
                asset_button.progress_bar.visible = False
                asset_button.red_alert.visible = False

        # Refresh manufacturer chips to match currently visible assets.
        self._update_manufacturer_data(visible_results)

    def scroll_update(self, always=False, *, update_visible_buttons=True):
        """Update scroll position and visibility of scroll buttons."""
        self.hide_tooltip()
        # Outside the smooth-scroll loop any stale phase would leave buttons
        # visually offset from their integer position - reset it so external
        # callers (clicks, search refresh, edge clamps) start clean.
        if not self._scroll_animating and self.scroll_phase != 0.0:
            self.scroll_phase = 0.0
            self._scroll_velocity = 0.0
        # Keep the draw-time grid offset in sync with the (possibly reset)
        # phase so the grid never draws shifted while at rest.
        self._update_grid_draw_offset()
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results")
        sro = history_step.get("search_results_orig")
        # empty results
        if sr is None:
            self.button_scroll_down.visible = False
            self.button_scroll_up.visible = False
            return

        self.scroll_offset = min(self.scroll_offset, self._aligned_max_offset(len(sr)))
        self.scroll_offset = max(self.scroll_offset, 0)
        # only update if scroll offset actually changed, otherwise this is unnecessary

        if (
            sro["count"] > len(sr)
            and len(sr) - self.scroll_offset
            < (self.wcount * self.hcount) + SEARCH_PREFETCH_LOOKAHEAD
        ):
            self.search_more()

        if self.scroll_offset == 0:
            self.button_scroll_down.visible = False
        else:
            self.button_scroll_down.visible = True

        if self.scroll_offset >= self._aligned_max_offset(sro["count"]):
            self.button_scroll_up.visible = False
        else:
            self.button_scroll_up.visible = True

        self._update_scroll_indicator()

        # here we save some time by only updating the images if the scroll offset actually changed
        if self.last_scroll_offset == self.scroll_offset and not always:
            return
        self.last_scroll_offset = self.scroll_offset

        if not update_visible_buttons:
            return

        self.update_buttons()

    def _apply_edge_resistance(self, step: int) -> int:
        """Reduce scroll step when near the start or end of results.

        Instead of bouncing, we progressively reduce the step size so
        scrolling decelerates smoothly at the edges.
        """
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results")
        if sr is None:
            return step

        max_offset = self._aligned_max_offset(len(sr))

        if step < 0 and self.scroll_offset <= 0:
            # Already at the start, absorb the step entirely
            return 0
        if step > 0 and self.scroll_offset >= max_offset:
            # Already at the end, absorb the step entirely
            return 0

        # When approaching the edge, reduce the step
        if step < 0:
            # Scrolling toward start
            effective = self.scroll_offset + step
            if effective < 0:
                step = -self.scroll_offset  # clamp to exactly reach 0
        elif step > 0:
            # Scrolling toward end
            effective = self.scroll_offset + step
            if effective > max_offset:
                step = max_offset - self.scroll_offset  # clamp to exactly reach end

        return step

    def _scroll_by_slots(self, slot_step: int):
        """Discrete scroll commit. Cancels any in-flight smooth animation."""
        if slot_step == 0:
            return
        slot_step = self._apply_edge_resistance(slot_step)
        if slot_step == 0:
            return
        # A wheel commit overrides any active inertia or snap, so visuals do
        # not lag behind the integer position.
        self.scroll_phase = 0.0
        self._scroll_velocity = 0.0
        self._scroll_animating = False
        self._scroll_travel_dir = 0
        self.scroll_offset += slot_step
        self.scroll_update()

    # --- Smooth-scroll helpers ------------------------------------------------

    def _smooth_scroll_axis_step_px(self) -> float:
        """Pixel size of one slot along the active scroll axis."""
        return float(max(1, int(self.button_size)))

    def _smooth_scroll_unit_slots(self) -> int:
        """Slots advanced per integer scroll step (1 single-row, wcount multi-row)."""
        return self.wcount if self.hcount > 1 else 1

    def _aligned_max_offset(self, total: int) -> int:
        """Largest scroll_offset that still shows at least one asset, aligned
        to the natural scroll step.

        Aligning to the step (`wcount` for multi-row, `1` for single-row)
        ensures we never "shift" the layout by a fractional row at the end
        of the result set - trailing slots are simply left empty instead.
        """
        visible = self.wcount * self.hcount
        if total <= visible:
            return 0
        unit = max(1, self._smooth_scroll_unit_slots())
        # Round up so the last asset is guaranteed to be in view.
        return int(math.ceil((total - visible) / float(unit))) * unit

    def _smooth_scroll_max_offset(self) -> int:
        sr = search.get_search_results()
        if sr is None:
            return 0
        return self._aligned_max_offset(len(sr))

    def _smooth_scroll_commit_phase(self) -> bool:
        """Advance integer `scroll_offset` whenever |phase| crosses one slot step.

        Returns True if any integer commit happened (so callers can refresh
        button image bindings via `scroll_update`).
        """
        step_px = self._smooth_scroll_axis_step_px()
        unit = self._smooth_scroll_unit_slots()
        committed = False
        # Forward direction: positive phase eats slots forward.
        while self.scroll_phase >= step_px:
            self.scroll_phase -= step_px
            self.scroll_offset += unit
            committed = True
        while self.scroll_phase <= -step_px:
            self.scroll_phase += step_px
            self.scroll_offset -= unit
            committed = True
        return committed

    def _smooth_scroll_clamp(self):
        """Clamp `scroll_offset` to results bounds and zero phase at edges."""
        max_offset = self._smooth_scroll_max_offset()
        if self.scroll_offset < 0:
            self.scroll_offset = 0
        elif self.scroll_offset > max_offset:
            self.scroll_offset = max_offset
        if self.scroll_offset <= 0 and self.scroll_phase < 0:
            self.scroll_phase = 0.0
            self._scroll_velocity = 0.0
        if self.scroll_offset >= max_offset and self.scroll_phase > 0:
            self.scroll_phase = 0.0
            self._scroll_velocity = 0.0
        # Phase must always be a sub-slot fraction; any whole-slot residue
        # is a logic bug we'd rather visualize as a clean snap than a drift.
        step_px = self._smooth_scroll_axis_step_px()
        if abs(self.scroll_phase) >= step_px:
            self.scroll_phase = 0.0

    def _update_grid_draw_offset(self):
        """Translate the grid by the sub-slot scroll phase at draw time.

        Returns a GPU-space (dx, dy) offset (+x right, +y up). Buttons stay at
        their integer slot positions; the draw callback applies this translate
        to all grid widgets so they slide as one, with no per-widget work.
        Mirrors the old per-frame ``asset_x = base - phase`` baking:
        increasing ``scroll_phase`` moves multi-row grids up (+gpu_y) and
        single-row grids left (-gpu_x).
        """
        if self.hcount > 1:
            self._grid_draw_offset = (0.0, self.scroll_phase)
        else:
            self._grid_draw_offset = (-self.scroll_phase, 0.0)
        return self._grid_draw_offset

    def _smooth_scroll_redraw(self):
        """Apply the current scroll phase and request a redraw.

        The sub-slot slide is now a single draw-time translate (see the draw
        callback), so we no longer reposition every grid widget here - we just
        refresh the draw offset and the scroll indicator, then tag a redraw.
        """
        self._update_grid_draw_offset()
        # Refresh the indicator each animation frame so its thumb glides
        # smoothly with the sub-slot phase. (`scroll_update` handles the
        # non-animated paths.)
        self._update_scroll_indicator()
        try:
            region = bpy.context.region
        except Exception:
            region = None
        self._safe_tag_redraw(region)

    def _smooth_scroll_apply_input(self, axis_delta_px: float, now: float):
        """Feed a continuous (trackpad) pixel delta into the smooth scroller.

        Updates phase, integrates velocity from inter-event timing, commits
        any whole-slot crossings, clamps to edges, and redraws.
        """
        # If the layout's active scroll axis flipped since the last sample,
        # discard stale velocity so cross-axis input doesn't carry over.
        # (Axis flip itself is detected in `_handle_scroll_event`.)
        self.scroll_phase += axis_delta_px
        # Trackpad input drives phase directly; clear wheel mode so the tick
        # reverts to its post-release coast behaviour.
        self._scroll_wheel_mode = False

        last_input = self._scroll_last_input_time
        dt = now - last_input if last_input > 0.0 else 0.0
        if dt <= 0.0 or dt > 0.25:
            # Either first sample or long idle gap (start of a new swipe);
            # don't extrapolate a velocity from this single frame.
            instant_v = 0.0
        else:
            instant_v = axis_delta_px / max(dt, SCROLL_VELOCITY_SAMPLE)
        # Light smoothing so a single jittery sample doesn't dominate.
        blend = 0.6
        self._scroll_velocity = (
            1.0 - blend
        ) * self._scroll_velocity + blend * instant_v

        self._scroll_last_input_time = now
        if self._scroll_last_tick_time == 0.0:
            self._scroll_last_tick_time = now
        self._scroll_animating = True
        # Record dominant travel direction from this input. Sub-pixel jitter
        # near 0 is ignored so we don't keep flipping the bias.
        if axis_delta_px > 0.5:
            self._scroll_travel_dir = 1
        elif axis_delta_px < -0.5:
            self._scroll_travel_dir = -1

        committed = self._smooth_scroll_commit_phase()
        self._smooth_scroll_clamp()
        if committed:
            # Image rebinding etc. only when integer offset actually changed.
            self.scroll_update()
        self._smooth_scroll_redraw()

    def _smooth_scroll_tick(self, now: float):
        """Per-frame animation step. Called from modal TIMER while animating.

        Two-stage: friction-decayed inertia until velocity falls below
        `SCROLL_MIN_VELOCITY`, then magnetic snap of phase toward 0 (which
        is automatically row-aligned since integer commits move whole rows).
        """
        if not self._scroll_animating:
            return
        last = self._scroll_last_tick_time or now
        dt = now - last
        self._scroll_last_tick_time = now
        if dt <= 0.0:
            return
        if dt > SCROLL_DT_CAP:
            dt = SCROLL_DT_CAP

        time_since_input = now - self._scroll_last_input_time
        if time_since_input < SCROLL_INPUT_GAP and not self._scroll_wheel_mode:
            # User still feeding trackpad events; let
            # `_smooth_scroll_apply_input` drive phase. We just keep the
            # animation loop alive. Wheel mode is velocity-driven and must
            # integrate every tick even during active input.
            return

        if abs(self._scroll_velocity) > SCROLL_MIN_VELOCITY:
            # Inertia: exponential friction decay.
            decay = math.exp(-SCROLL_FRICTION * dt)
            avg_v = self._scroll_velocity * (1.0 + decay) * 0.5
            self.scroll_phase += avg_v * dt
            self._scroll_velocity *= decay
        else:
            # Magnetic snap. Target is the nearest slot boundary, but the
            # half-way decision boundary is shifted toward the travel
            # direction by `SCROLL_SNAP_DIRECTION_BIAS * step` so a partial
            # crossing in the direction we were already heading commits
            # forward instead of pulling back.
            self._scroll_velocity = 0.0
            step_px = self._smooth_scroll_axis_step_px()
            half = step_px * 0.5
            bias = SCROLL_SNAP_DIRECTION_BIAS * step_px
            direction = self._scroll_travel_dir
            if direction > 0:
                # Boundary lowered to (0.5 - bias_frac) of one slot.
                threshold = half - bias
                target = step_px if self.scroll_phase >= threshold else 0.0
            elif direction < 0:
                threshold = -(half - bias)
                target = -step_px if self.scroll_phase <= threshold else 0.0
            else:
                # No recorded direction: pure nearest-slot.
                if self.scroll_phase >= half:
                    target = step_px
                elif self.scroll_phase <= -half:
                    target = -step_px
                else:
                    target = 0.0

            distance = self.scroll_phase - target
            if abs(distance) <= SCROLL_SETTLE_PX:
                # Land cleanly. If target was a slot boundary the commit
                # below will reduce phase back to 0.
                self.scroll_phase = target
                committed_now = self._smooth_scroll_commit_phase()
                self._smooth_scroll_clamp()
                if committed_now:
                    self.scroll_update()
                self._smooth_scroll_redraw()
                self._scroll_animating = False
                self._scroll_last_tick_time = 0.0
                self._scroll_travel_dir = 0
                self._scroll_wheel_mode = False
                return
            ease = 1.0 - math.exp(-SCROLL_SNAP_RATE * dt)
            self.scroll_phase -= distance * ease

        committed = self._smooth_scroll_commit_phase()
        self._smooth_scroll_clamp()
        if committed:
            self.scroll_update()
        self._smooth_scroll_redraw()

    def _get_trackpad_sensitivity(self) -> float:
        """Pixels of finger travel required to advance one asset slot.

        Higher values produce slower scrolling. Read from addon preferences
        so users (notably on macOS) can tune trackpad speed.
        """
        try:
            prefs = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
            value = float(
                getattr(
                    prefs,
                    "trackpad_scroll_sensitivity",
                    SCROLL_TRACKPAD_SENSITIVITY_DEFAULT,
                )
            )
            if value < 1.0:
                value = 1.0
            return value
        except (KeyError, AttributeError):
            return SCROLL_TRACKPAD_SENSITIVITY_DEFAULT

    def _handle_scroll_event(self, context, event) -> bool:
        """Centralized scroll input handler.

        Consumes wheel and trackpad events whenever the cursor is over the
        asset bar panel, mapping them to discrete slot steps based on the
        current layout (single-row -> horizontal, multi-row -> vertical).

        Trackpad input feeds the smooth-scroll phase continuously and lets
        the timer-driven inertia + magnetic snap take over after release.
        Wheel input still commits one full step per tick (cancelling any
        in-flight animation).

        Returns True if the event was a scroll input that we should consume
        (RUNNING_MODAL); False to let the caller fall through to other
        handlers / pass the event through.
        """
        # Only react to scroll-class events.
        if event.type != "TRACKPADPAN" and event.type not in _WHEEL_EVENT_TYPES:
            return False

        # Only when the pointer is on the asset bar.
        if not self.panel.is_in_rect(self.mouse_x, self.mouse_y):
            return False

        # Layout-driven axis. We never mix the two axes so wheel and trackpad
        # cannot both step the bar at the same time.
        vertical = self.hcount > 1
        slot_per_step = self.wcount if vertical else 1

        # Reset accumulated state if the layout's scrolling axis changed
        # since the last event (leftover travel must not bleed across axes).
        if self._trackpad_axis_vertical != vertical:
            self._trackpad_axis_vertical = vertical
            self.scroll_phase = 0.0
            self._scroll_velocity = 0.0
            self._scroll_animating = False
            self._scroll_travel_dir = 0

        # On Blender versions without GPU scissor we can't clip partial rows,
        # so smooth-scroll rows would visibly spill outside the bar. Fall
        # back to immediate integer-row stepping for wheel events and just
        # ignore trackpad pan (which has no natural discrete equivalent).
        if not SMOOTH_SCROLL_SUPPORTED:
            if event.type == "TRACKPADPAN":
                # Accumulate trackpad delta into whole-slot steps without
                # animating phase. We still respect the user's sensitivity.
                dx = event.mouse_x - event.mouse_prev_x
                dy = event.mouse_y - event.mouse_prev_y
                axis_delta = float(dy) if abs(dy) >= abs(dx) else float(-dx)
                sensitivity = self._get_trackpad_sensitivity()
                self._legacy_trackpad_accum = (
                    getattr(self, "_legacy_trackpad_accum", 0.0) + axis_delta
                )
                steps_committed = 0
                while self._legacy_trackpad_accum >= sensitivity:
                    self._legacy_trackpad_accum -= sensitivity
                    steps_committed += 1
                while self._legacy_trackpad_accum <= -sensitivity:
                    self._legacy_trackpad_accum += sensitivity
                    steps_committed -= 1
                if steps_committed:
                    self.scroll_offset += steps_committed * slot_per_step
                    self.scroll_update()
                    if context.region is not None:
                        context.region.tag_redraw()
                return True

            steps = 1 if event.type in _WHEEL_FORWARD else -1
            self.scroll_offset += steps * slot_per_step
            self.scroll_update()
            if context.region is not None:
                context.region.tag_redraw()
            return True

        if event.type == "TRACKPADPAN":
            dx = event.mouse_x - event.mouse_prev_x
            dy = event.mouse_y - event.mouse_prev_y
            # Accept input from either axis - the user can side-swipe to
            # scroll a multi-row grid, or vertical-swipe a single-row bar.
            # Pick the dominant axis of this event so diagonal motion is
            # counted once, not summed.
            #
            # Natural-scroll convention (content follows the finger):
            #   swipe up   (dy > 0) -> forward
            #   swipe left (dx < 0) -> forward
            # Both axes map to the same logical "forward" regardless of
            # whether the layout is single-row or multi-row.
            if abs(dy) >= abs(dx):
                axis_delta = float(dy)
            else:
                axis_delta = float(-dx)

            # Map raw pixels into "scroll-axis pixels" via the user's
            # sensitivity preference: travelling `sensitivity` finger-pixels
            # equals one slot of bar movement (`button_size` pixels of phase).
            sensitivity = self._get_trackpad_sensitivity()
            step_px = self._smooth_scroll_axis_step_px()
            phase_delta = (axis_delta / sensitivity) * step_px

            self._smooth_scroll_apply_input(phase_delta, time.time())
        else:
            # Wheel event. Discrete notches don't carry a continuous pixel
            # delta, so feeding `step_px` straight into the smooth pipeline
            # would let `_smooth_scroll_commit_phase` consume the whole slot
            # in the same event and visually teleport. Instead we inject a
            # one-shot velocity: the timer integrates phase from 0 -> step_px
            # over multiple frames (inertia), then magnetic snap finishes the
            # row alignment. Multiple rapid notches stack velocity (capped),
            # so a fast spin coasts proportionally further.
            steps = 1 if event.type in _WHEEL_FORWARD else -1
            step_px = self._smooth_scroll_axis_step_px()
            notch_v = step_px * SCROLL_WHEEL_NOTCH_VELOCITY
            v_cap = step_px * SCROLL_WHEEL_NOTCH_VELOCITY * SCROLL_WHEEL_MAX_NOTCH_STACK
            now = time.time()
            # Reset stale velocity if it points the other way or we've been
            # idle long enough that the previous spin has settled.
            time_since_input = now - self._scroll_last_input_time
            if (
                steps * self._scroll_velocity < 0
                or time_since_input > SCROLL_INPUT_GAP * 4
            ):
                self._scroll_velocity = 0.0
            self._scroll_velocity += steps * notch_v
            # Clamp magnitude so a held wheel doesn't accelerate forever.
            if self._scroll_velocity > v_cap:
                self._scroll_velocity = v_cap
            elif self._scroll_velocity < -v_cap:
                self._scroll_velocity = -v_cap
            self._scroll_travel_dir = steps
            self._scroll_animating = True
            self._scroll_wheel_mode = True
            self._scroll_last_input_time = now
            if self._scroll_last_tick_time == 0.0:
                self._scroll_last_tick_time = now
            if context.region is not None:
                context.region.tag_redraw()
        return True

    def search_by_author(self, asset_index):
        """Search for assets by the author of the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        author_id = asset_data["author"]["id"]
        if author_id is None:
            return True

        # For author-type results, prefer displayName for the filter label
        author_name = ""
        if asset_data.get("assetType") == "author":
            author_name = asset_data.get("displayName", "")

        # For author-type cards, check if asset type picker is enabled
        if asset_data.get("assetType") == "author":
            preferences = bpy.context.preferences.addons[_ADDON_PACKAGE].preferences
            if (
                preferences.experimental_features
                and preferences.author_asset_type_picker
            ):
                # Extract per-type asset counts from author data (assetTypeCounts or ratingsCount)
                asset_type_counts = asset_data.get("assetTypeCounts", {})
                if not asset_type_counts:
                    asset_type_counts = asset_data.get("ratingsCount", {})
                search.AuthorAssetTypePopup._asset_type_counts = asset_type_counts or {}
                bpy.ops.view3d.blenderkit_author_asset_type_popup(
                    "INVOKE_DEFAULT",
                    author_id=str(author_id),
                    author_name=author_name,
                )
                return True
            # Picker not enabled — search by author in current tab
            search.search_by_author_id(author_id, author_name)
            self.update_ui_size(bpy.context)
            self.scroll_update(always=True)
            return True

        search.search_by_author_id(author_id, author_name)
        self.update_ui_size(bpy.context)
        self.scroll_update(always=True)
        return True

    def search_similar(self, asset_index):
        """Search for similar assets to the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        keywords = search.get_search_similar_keywords(asset_data)
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_keywords = keywords
        search.search()

    def search_in_category(self, asset_index):
        """Search for assets in the same category as the selected asset."""
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[asset_index]
        category = asset_data.get("category")
        if category is None:
            return True
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_category = category
        search.search()

    # endregion actions

    # region main operations

    @classmethod
    def unregister(cls):
        """Unregister the asset bar operator and clean up instances."""
        bk_logger.debug("unregistering class %s", cls)
        instances_copy = cls.instances.copy()
        for instance in instances_copy:
            try:
                bk_logger.debug("- instance %s", instance)
            except ReferenceError:
                bk_logger.debug("- instance <deleted>")
            try:
                instance.unregister_handlers(instance.context)
            except Exception as e:
                bk_logger.debug("-- error unregister_handlers(): %s", e)
            try:
                instance.on_finish(instance.context)
            except Exception as e:
                bk_logger.debug("-- error calling on_finish(): %s", e)
            cls.instances.remove(instance)

    def restart_asset_bar(self):
        """Restart the asset bar UI."""
        ui_props = bpy.context.window_manager.blenderkitUI
        self.finish()
        w, a, r = utils.get_largest_area(area_type="VIEW_3D")
        if a is not None:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)

    # endregion main operations

    # region tab management

    def add_new_tab(self, widget):
        """Add a new tab when the + button is clicked."""
        tabs = global_vars.TABS["tabs"]
        new_tab = {
            "name": f"Tab {len(tabs) + 1}",  # Default name with incremented number
            "history": [],  # Empty history list
            "history_index": -1,  # No history yet
            "active_filters": [],
        }
        tabs.append(new_tab)

        # Get current history step to copy its state and results
        current_history_step = search.get_active_history_step()

        # Create history step for the new tab, copying the current UI state
        new_history_step = search.create_history_step(new_tab)

        # Copy search results from current history step if they exist
        if current_history_step.get("search_results"):
            new_history_step["search_results"] = current_history_step["search_results"]
            new_history_step["search_results_orig"] = current_history_step[
                "search_results_orig"
            ]
            new_history_step["is_searching"] = False

            # Update search results count to trigger UI refresh
            self.search_results_count = len(new_history_step["search_results"])
            # Force scroll update to show results
            self.scroll_update(always=True)

        new_active_tab = len(tabs) - 1
        self.switch_to_history_step(new_active_tab, 0)

        # Write history step to tab
        # Restart asset bar to show new tab
        self.restart_asset_bar()

    def remove_tab(self, widget):
        """Remove a tab when its close button is clicked."""
        tabs = global_vars.TABS["tabs"]

        # Don't remove the last tab
        if len(tabs) <= 1:
            return

        tab_index = widget.tab_index

        # If removing active tab, switch to previous tab
        if global_vars.TABS["active_tab"] == tab_index:
            global_vars.TABS["active_tab"] = max(0, tab_index - 1)
        # If removing tab before active tab, adjust active tab index
        elif global_vars.TABS["active_tab"] > tab_index:
            global_vars.TABS["active_tab"] -= 1

        # Remove the tab
        tabs.pop(tab_index)

        # Restart asset bar to update UI
        self.restart_asset_bar()

    def update_history_buttons_rounding(self):
        """Update the rounding of history navigation buttons based on their visibility."""
        if self.history_back_button.visible and self.history_forward_button.visible:
            self.history_back_button.background_corner_radius = (
                ROUNDING_RADIUS,
                0,
                0,
                0,
            )
            self.history_forward_button.background_corner_radius = (
                0,
                ROUNDING_RADIUS,
                0,
                0,
            )
        else:
            self.history_back_button.background_corner_radius = (
                ROUNDING_RADIUS,
                ROUNDING_RADIUS,
                0,
                0,
            )
            self.history_forward_button.background_corner_radius = (
                ROUNDING_RADIUS,
                ROUNDING_RADIUS,
                0,
                0,
            )

    def switch_to_history_step(self, tab_index, history_index):
        """Switch to a specific tab and history step."""
        # Update UI properties without triggering update callbacks
        ui_props = bpy.context.window_manager.blenderkitUI
        # lock the search
        ui_props.search_lock = True

        if (
            tab_index == global_vars.TABS["active_tab"]
            and history_index == global_vars.TABS["tabs"][tab_index]["history_index"]
        ):
            return  # Already on this tab and history step
        # make original tab original background color
        self.tab_buttons[global_vars.TABS["active_tab"]].bg_color = self.button_bg_color
        # make also tab close button original background color
        self.close_tab_buttons[global_vars.TABS["active_tab"]].bg_color = (
            self.button_bg_color
        )

        global_vars.TABS["active_tab"] = tab_index
        global_vars.TABS["tabs"][tab_index]["history_index"] = history_index

        # Get active history step of the selected tab
        history_step = search.get_active_history_step()
        ui_state = history_step["ui_state"]

        # Update UI properties
        for prop_name, value in ui_state["ui_props"].items():
            if hasattr(ui_props, prop_name):
                setattr(ui_props, prop_name, value)

        # Update search type specific properties
        search_props = utils.get_search_props()
        for prop_name, value in ui_state["search_props"].items():
            if hasattr(search_props, prop_name):
                setattr(search_props, prop_name, value)

        # Restore active filter chips for this tab
        active_tab = global_vars.TABS["tabs"][tab_index]
        search.set_active_filters_for_tab(
            active_tab, ui_state.get("active_filters", [])
        )

        # update tab label
        # only if the button exists
        if len(self.tab_buttons) > tab_index:
            search.update_tab_name(global_vars.TABS["tabs"][tab_index])
        # Restore scroll position
        self.scroll_offset = history_step.get("scroll_offset", 0)

        # Update history button visibility
        self.history_back_button.visible = active_tab["history_index"] > 0
        self.history_forward_button.visible = (
            active_tab["history_index"] < len(active_tab["history"]) - 1
        )
        self.update_history_buttons_rounding()

        # Recalculate layout to reflect active filter chip changes on this history step
        self.update_ui_size(bpy.context)

        # set colors and rounding for tabs
        for tab_button in self.tab_buttons:
            c_tab_index = tab_button.tab_index
            if c_tab_index == tab_index:
                tab_button.bg_color = self.button_selected_color
                self.close_tab_buttons[tab_index].bg_color = (
                    self.button_selected_color_dim
                )

            else:
                tab_button.bg_color = self.button_bg_color
                self.close_tab_buttons[c_tab_index].bg_color = self.button_bg_color

        # update filters
        search.update_filters()
        # Update UI to show current tab's search results
        self.scroll_update(always=True)
        # Update tab icons to reflect the current asset type
        self.update_tab_icons()
        # unlock the search
        ui_props.search_lock = False

    def history_back(self, widget):
        """Navigate to previous history step."""
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        if active_tab["history_index"] > 0:
            self.switch_to_history_step(
                global_vars.TABS["active_tab"], active_tab["history_index"] - 1
            )

    def history_forward(self, widget):
        """Navigate to next history step."""
        active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
        if active_tab["history_index"] < len(active_tab["history"]) - 1:
            self.switch_to_history_step(
                global_vars.TABS["active_tab"], active_tab["history_index"] + 1
            )

    def switch_tab(self, widget):
        """Switch to the clicked tab and restore its UI state."""
        self.switch_to_history_step(
            widget.tab_index,
            global_vars.TABS["tabs"][widget.tab_index]["history_index"],
        )

    # endregion tab management


def handle_bkclientjs_get_asset(task: "search.client_tasks.Task"):
    """Handle incoming bkclientjs/get_asset task after the user asked for download in online gallery. How it goes:
    1. set search in the history
    2. set the results in the history step
    3. open the asset bar
    We handle the task in asset_bar_op because we need access to the asset_bar_operator without circular import from search.
    """
    bk_logger.info("handle_bkclientjs_get_asset: %s", task.result["asset_data"]["name"])

    # Get asset data from task result
    asset_data = task.result.get("asset_data")
    if not asset_data:
        bk_logger.error("No asset data found in task")
        return

    # Parse the asset data
    parsed_asset_data = search.parse_result(asset_data)
    if not parsed_asset_data:
        bk_logger.error("Failed to parse asset data")
        return

    search.append_history_step(
        search_keywords=f"asset_base_id:{asset_data['assetBaseId']}",
        search_results=[parsed_asset_data],
        asset_type=asset_data.get("assetType", "").upper(),
        search_results_orig={"results": [asset_data], "count": 1},
    )

    # If asset bar is not open, try to open it
    if asset_bar_operator is None:
        try:
            bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]
        except Exception as e:
            bk_logger.error("Failed to open asset bar: %s", e)
            return

    # Force redraw of the region if asset bar exists
    if asset_bar_operator and asset_bar_operator.area:
        search.load_preview(parsed_asset_data)
        asset_bar_operator.update_image(parsed_asset_data["assetBaseId"])
        asset_bar_operator.area.tag_redraw()


def refresh_comments_for_asset(asset_id):
    """Refresh the asset bar tooltip's comment text once comments arrive.

    Called from comments_utils.handle_get_comments_task() after a lazy
    fetch finishes. Only updates the UI when the currently hovered asset
    matches the one whose comments just downloaded.
    """
    if asset_bar_operator is None:
        return
    active_index = getattr(asset_bar_operator, "active_index", -1)
    if active_index < 0:
        return
    sr = search.get_search_results()
    if not sr or active_index >= len(sr):
        return
    asset_data = sr[active_index]
    if asset_data.get("assetBaseId") != asset_id:
        return
    asset_bar_operator.update_comments_for_validators(asset_data)
    if asset_bar_operator.area:
        asset_bar_operator.area.tag_redraw()


BlenderKitAssetBarOperator.modal = asset_bar_modal  # type: ignore[method-assign]
BlenderKitAssetBarOperator.invoke = asset_bar_invoke  # type: ignore[method-assign]


def register():
    bpy.utils.register_class(BlenderKitAssetBarOperator)


def unregister():
    bpy.utils.unregister_class(BlenderKitAssetBarOperator)
