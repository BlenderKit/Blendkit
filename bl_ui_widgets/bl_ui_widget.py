import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from .. import ui_bgl

from contextlib import contextmanager
from typing import Union


def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(max_value, value))


def set_font_size(font_id, size):
    if bpy.app.version < (4, 0, 0):
        blf.size(font_id, size, 72)
    else:
        blf.size(font_id, size)


def tint_color(color, tint_amount):
    if tint_amount == 0.0:
        return color
    r, g, b, a = color
    if tint_amount > 0.0:
        r += (1.0 - r) * tint_amount
        g += (1.0 - g) * tint_amount
        b += (1.0 - b) * tint_amount
    else:
        r *= 1.0 + tint_amount
        g *= 1.0 + tint_amount
        b *= 1.0 + tint_amount
    return (clamp(r), clamp(g), clamp(b), a)


def resolve_fill_color(preferred_color, fallback_color):
    color = preferred_color or fallback_color or (1.0, 1.0, 1.0, 1.0)
    r, g, b, a = color
    return (clamp(r), clamp(g), clamp(b), clamp(a))


_suppress_region_redraw = False


def region_redraw(ctx: bpy.types.Context = None):
    # Inside a batched_region_redraw() block, individual widget redraws are
    # suppressed; the caller issues a single redraw afterwards.
    if _suppress_region_redraw:
        return
    if ctx is not None:
        context = ctx
    else:
        context = bpy.context
    if context.region is not None:
        context.region.tag_redraw()


@contextmanager
def batched_region_redraw():
    """Suppress per-widget region_redraw() calls inside the block.

    Bulk layout passes (e.g. repositioning hundreds of asset buttons on every
    smooth-scroll frame) would otherwise tag a redraw once per widget. Wrap the
    pass in this context and issue a single region_redraw() afterwards.
    """
    global _suppress_region_redraw
    previous = _suppress_region_redraw
    _suppress_region_redraw = True
    try:
        yield
    finally:
        _suppress_region_redraw = previous


class BL_UI_Widget:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.x_screen = x
        self.y_screen = y
        self.width = width
        self.height = height
        self._bg_color = (0.8, 0.8, 0.8, 1.0)
        self._tag = None
        self.context = None
        self.__inrect = False
        self._mouse_down = False
        self._mouse_down_right = False
        self._is_visible = True
        self._is_active = True  # if the widget needs to be disabled
        # decorative helpers (opt-in per widget)
        self._background_enabled = False
        self.use_rounded_background = False
        self.background_padding: tuple[int, int] = (0, 0)
        # Radius can be '50%' for pill shape, each corner individually
        self._background_corner_radius: Union[
            tuple[Union[str, float], ...],
            str,
            float,
        ] = (0.0,)
        self._background_corner_radius_custom = False
        self.background_border = False
        self.background_border_color = None
        self.background_border_tint = 0.2
        self.background_border_thickness = 1.0
        self.strikethrough = False
        self.strikethrough_thickness = 1.25

        if bpy.app.version < (4, 0, 0):
            self.shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
        else:
            self.shader = gpu.shader.from_builtin("UNIFORM_COLOR")

        # Background panel batch is built lazily, in local coordinates, and
        # cached by size. Position is applied at draw time (see update() /
        # _draw_panel_batch), so moving the widget does not rebuild the batch.
        self.batch_panel = None
        self._panel_batch_size = None

    @property
    def background_corner_radius(self):
        return self._background_corner_radius

    @background_corner_radius.setter
    def background_corner_radius(self, value):
        self._background_corner_radius = value
        self._background_corner_radius_custom = True

    @property
    def background(self):
        return self._background_enabled

    @background.setter
    def background(self, value):
        enabled = bool(value)
        self._background_enabled = enabled
        if not enabled:
            self.use_rounded_background = False
        elif enabled and not self.use_rounded_background:
            self.use_rounded_background = True

    def _set_background_corner_radius_default(self, value):
        self._background_corner_radius = value
        self._background_corner_radius_custom = False

    def has_background_corner_radius_override(self):
        return self._background_corner_radius_custom

    def resolve_background_fill(self, fallback_color, preferred_color=None):
        base_color = fallback_color if preferred_color is None else preferred_color
        return resolve_fill_color(
            base_color,
            fallback_color,
        )

    def resolve_background_border(self, fill_color):
        if not self.background_border:
            return None
        if self.background_border_color:
            return self.background_border_color
        return tint_color(fill_color, self.background_border_tint)

    def draw_background_rect(
        self,
        min_x,
        min_y,
        width,
        height,
        fallback_color,
        *,
        force=False,
        padding_override=None,
        corner_radius_override=None,
        fill_color_override=None,
    ):
        if (not self.use_rounded_background and not force) or width <= 0 or height <= 0:
            return
        if padding_override is None:
            pad_x = self.background_padding[0]
            pad_y = self.background_padding[1]
            pad_left = pad_right = pad_x
            pad_bottom = pad_top = pad_y
        else:
            if len(padding_override) == 4:
                pad_left, pad_right, pad_bottom, pad_top = padding_override
            elif len(padding_override) == 2:
                pad_left = pad_right = padding_override[0]
                pad_bottom = pad_top = padding_override[1]
            else:
                pad_left = pad_right = padding_override[0]
                pad_bottom = pad_top = padding_override[1]
        rect_x = min_x - pad_left
        rect_y = min_y - pad_bottom
        rect_width = width + pad_left + pad_right
        rect_height = height + pad_top + pad_bottom
        fill_color = self.resolve_background_fill(
            fallback_color,
            preferred_color=fill_color_override,
        )
        border_color = self.resolve_background_border(fill_color)
        corner_radius = (
            corner_radius_override
            if corner_radius_override is not None
            else self.background_corner_radius
        )
        ui_bgl.draw_rounded_rect_with_border(
            rect_x,
            rect_y,
            rect_width,
            rect_height,
            radius=corner_radius,
            fill_color=fill_color,
            border_color=border_color,
            border_thickness=self.background_border_thickness,
        )

    def draw_strikethrough(self, min_x, max_x, y, color, *, force=False):
        if (not self.strikethrough and not force) or max_x <= min_x:
            return
        ui_bgl.draw_line2d(
            min_x,
            y,
            max_x,
            y,
            self.strikethrough_thickness,
            color,
        )

    def set_location(self, x, y):
        # if self.x != x or self.y != y or self.x_screen != x or self.y_screen != y:
        #     region_redraw()
        self.x = x
        self.y = y
        self.x_screen = x
        self.y_screen = y
        self.update(x, y)

    @property
    def bg_color(self):
        return self._bg_color

    @bg_color.setter
    def bg_color(self, value):
        self._bg_color = value
        region_redraw()

    @property
    def background_color(self):
        return self._bg_color

    @background_color.setter
    def background_color(self, value):
        self.bg_color = value

    @property
    def visible(self):
        return self._is_visible

    @visible.setter
    def visible(self, value):
        if value != self._is_visible:
            region_redraw()
        self._is_visible = value

    @property
    def active(self):
        return self._is_active

    @active.setter
    def active(self, value):
        if value != self._is_active:
            region_redraw()
        self._is_active = value

    @property
    def tag(self):
        return self._tag

    @tag.setter
    def tag(self, value):
        self._tag = value

    def draw(self):
        if not self._is_visible:
            return

        gpu.state.blend_set("ALPHA")

        if self.use_rounded_background:
            area_height = self.get_area_height()
            rect_y = area_height - self.y_screen - self.height
            self.draw_background_rect(
                self.x_screen,
                rect_y,
                self.width,
                self.height,
                self._bg_color,
                force=True,
                fill_color_override=self._bg_color,
            )
            return

        self.shader.bind()
        self.shader.uniform_float("color", self._bg_color)

        self._draw_panel_batch()

    def init(self, context):
        self.context = context
        self.update(self.x, self.y)

    def update(self, x, y):
        self.x_screen = x
        self.y_screen = y
        self._ensure_panel_batch()
        region_redraw()

    def _ensure_panel_batch(self):
        """(Re)build the background batch only when the widget size changes.

        Vertices are in local space (origin at the widget's top-left, y growing
        downward); the screen position is applied at draw time via a translate.
        Moving the widget - e.g. every frame during smooth scroll - therefore
        no longer rebuilds the GPU batch, only an actual resize does.
        """
        size_key = (self.width, self.height)
        if self.batch_panel is not None and self._panel_batch_size == size_key:
            return
        indices = ((0, 1, 2), (0, 2, 3))
        # top-left, bottom-left, bottom-right, top-right (local, y down)
        vertices = (
            (0.0, 0.0),
            (0.0, -self.height),
            (self.width, -self.height),
            (self.width, 0.0),
        )
        self.batch_panel = batch_for_shader(
            self.shader, "TRIS", {"pos": vertices}, indices=indices
        )
        self._panel_batch_size = size_key

    def _draw_panel_batch(self):
        """Draw the cached background batch at the widget's current position."""
        if self.batch_panel is None:
            self._ensure_panel_batch()
        area_height = self.get_area_height()
        gpu.matrix.push()
        try:
            gpu.matrix.translate((self.x_screen, area_height - self.y_screen))
            self.batch_panel.draw(self.shader)
        finally:
            gpu.matrix.pop()

    def handle_event(self, event):
        """
        returns True if the event was handled by the widget
        # 'handled_pass', if the event was handled but the event should be passed to other widgets
        False if the event was not handled by the widget
        """

        if not self._is_visible:
            return False
        if not self._is_active:
            return False

        x, y = self._to_widget_region_coords(event)

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._mouse_down = True
                region_redraw()
                return self.mouse_down(x, y)
            else:
                self._mouse_down = False
                region_redraw()
                self.mouse_up(x, y)
                return False

        elif event.type == "RIGHTMOUSE":
            if event.value == "PRESS":
                self._mouse_down_right = True
                region_redraw()
                return self.mouse_down_right(x, y)
            else:
                self._mouse_down_right = False
                region_redraw()
                self.mouse_up(x, y)

        elif event.type == "MOUSEMOVE":
            self.mouse_move(x, y)
            inrect = self.is_in_rect(x, y)

            # we enter the rect
            if not self.__inrect and inrect:
                self.__inrect = True
                self.mouse_enter(event, x, y)
                # we tag redraw since the hover colors are picked in the draw function
                region_redraw()

            # we are leaving the rect
            elif self.__inrect and not inrect:
                self.__inrect = False
                self.mouse_exit(event, x, y)
                region_redraw()

            # return always false to enable mouse exit events on other buttons.(would sometimes not hide the tooltip)
            return False  # self.__inrect

        elif (
            event.value == "PRESS"
            and self.__inrect
            and (event.ascii != "" or event.type in self.get_input_keys())
        ):
            return self.text_input(event)

        return False

    def _to_widget_region_coords(self, event):
        region = None
        ctx = self.context
        if isinstance(ctx, dict):
            region = ctx.get("region")
        elif hasattr(ctx, "region"):
            region = getattr(ctx, "region")

        if (
            region is not None
            and hasattr(event, "mouse_x")
            and hasattr(event, "mouse_y")
        ):
            try:
                return event.mouse_x - region.x, event.mouse_y - region.y
            except AttributeError:
                pass

        return getattr(event, "mouse_region_x", 0), getattr(event, "mouse_region_y", 0)

    def get_input_keys(self):
        return []

    def get_area_height(self):
        return self.context.area.height

    def is_in_rect(self, x, y):
        area_height = self.get_area_height()

        widget_y = area_height - self.y_screen
        if (self.x_screen <= x <= (self.x_screen + self.width)) and (
            widget_y >= y >= (widget_y - self.height)
        ):
            # print('is in rect!?')
            # print('area height', area_height)
            # print ('x screen ',self.x_screen,'x ', x, 'width', self.width)
            # print ('widget y', widget_y,'y', y, 'height',self.height)
            return True

        return False

    def text_input(self, event):
        return False

    def mouse_down(self, x, y):
        return self.is_in_rect(x, y)

    def mouse_down_right(self, x, y):
        return self.is_in_rect(x, y)

    def mouse_up(self, x, y):
        pass

    def mouse_enter_func(self, widget):
        pass

    def mouse_exit_func(self, widget):
        pass

    def set_mouse_enter(self, mouse_enter_func):
        self.mouse_enter_func = mouse_enter_func

    def call_mouse_enter(self):
        if self.mouse_enter_func:
            self.mouse_enter_func(self)

    def mouse_enter(self, event, x, y):
        self.call_mouse_enter()

    def set_mouse_exit(self, mouse_exit_func):
        self.mouse_exit_func = mouse_exit_func

    def call_mouse_exit(self):
        if self.mouse_exit_func:
            self.mouse_exit_func(self)

    def mouse_exit(self, event, x, y):
        self.call_mouse_exit()

    def mouse_move(self, x, y):
        pass
