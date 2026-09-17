import os
import logging

import blf
import bpy
import gpu

from .. import image_utils, ui_bgl
from .bl_ui_widget import BL_UI_Widget, region_redraw

bk_logger = logging.getLogger(__name__)


class BL_UI_Button(BL_UI_Widget):
    """Image Button for assets in asset bar."""

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.background = True
        self.background_padding = (0, 0)
        self._text_color = (1.0, 1.0, 1.0, 1.0)
        self._hover_bg_color = (0.5, 0.5, 0.5, 1.0)
        self._select_bg_color = (0.7, 0.7, 0.7, 1.0)

        self._text = "Button"
        self._text_size = 16
        self._textpos = (x, y)

        self.__state = 0
        self.__image = None
        self.__image_size = (24, 24)
        self.__image_position = (4, 2)
        self.__image_padding = 0.0
        self.image_corner_radius = None

    @property
    def text_color(self):
        return self._text_color

    @text_color.setter
    def text_color(self, value):
        if value != self._text_color:
            region_redraw()
        self._text_color = value

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        if value != self._text:
            region_redraw()
        self._text = value

    @property
    def text_size(self):
        return self._text_size

    @text_size.setter
    def text_size(self, value):
        if value != self._text_size:
            region_redraw()
        self._text_size = value

    @property
    def hover_bg_color(self):
        return self._hover_bg_color

    @hover_bg_color.setter
    def hover_bg_color(self, value):
        if value != self._hover_bg_color:
            region_redraw()
        self._hover_bg_color = value

    @property
    def select_bg_color(self):
        return self._select_bg_color

    @select_bg_color.setter
    def select_bg_color(self, value):
        if value != self._select_bg_color:
            region_redraw()
        self._select_bg_color = value

    def set_image_size(self, image_size):
        self.__image_size = image_size

    def set_image_position(self, image_position):
        self.__image_position = image_position

    def check_image_exists(self):
        # it's possible image was removed and doesn't exist.
        try:
            self.__image
            self.__image.filepath
            # self.__image.pixels
        except Exception:
            self.__image = None

    def set_image_colorspace(self, colorspace: str = ""):
        image_utils.set_colorspace(self.__image, colorspace)

    def set_image(self, rel_filepath):
        if rel_filepath is None:
            self.__image = None
            return
        # first try to access the image, for cases where it can get removed
        self.check_image_exists()
        try:
            if self.__image is None or self.__image.filepath != rel_filepath:
                imgname = f".{os.path.basename(rel_filepath)}"
                self.__image = image_utils.IMG(name=imgname, filepath=rel_filepath)

        except Exception:
            bk_logger.exception("BL_UI_BUTTON set_image() error:")
            self.__image = None

    def get_image_path(self):
        self.check_image_exists()
        if self.__image is None:
            return None
        return self.__image.filepath

    @property
    def image_padding(self):
        return self.__image_padding

    @image_padding.setter
    def image_padding(self, padding: float):
        self.__image_padding = padding

    def get_image_padding(self):
        return self.__image_padding

    def update(self, x, y):
        super().update(x, y)
        self._textpos = [x, y]

    def draw(self):
        if not self._is_visible:
            return
        area_height = self.get_area_height()

        gpu.state.blend_set("ALPHA")
        fill_color = self._resolve_panel_color()

        if self.use_rounded_background:
            rect_y = area_height - self.y_screen - self.height
            self.draw_background_rect(
                self.x_screen,
                rect_y,
                self.width,
                self.height,
                fill_color,
                force=True,
                fill_color_override=fill_color,
            )
        else:
            self.shader.bind()
            self.shader.uniform_float("color", fill_color)
            self._draw_panel_batch()

        self.draw_image()

        # Draw text
        self.draw_text(area_height)

    def _resolve_panel_color(self):
        color = self._bg_color

        # pressed
        if self.__state == 1:
            color = self._select_bg_color

        # hover
        elif self.__state == 2:
            color = self._hover_bg_color

        return color

    def draw_text(self, area_height):
        font_id = 1
        if bpy.app.version < (3, 1, 0):
            # Blender 3.0 requires size:int https://docs.blender.org/api/3.0/blf.html#blf.size
            # but assetBar's search tab text is float - needs conversion in here
            blf.size(font_id, int(self._text_size), 72)
        elif bpy.app.version < (4, 0, 0):
            blf.size(font_id, self._text_size, 72)
        else:
            blf.size(font_id, self._text_size)

        size = blf.dimensions(font_id, self._text)

        # When an image is present, center text in the remaining space after the image
        image_offset = 0
        if self.__image is not None:
            image_offset = self.__image_position[0] + self.__image_size[0]

        textpos_y = area_height - self._textpos[1] - (self.height + size[1]) / 2.0
        blf.position(
            font_id,
            self._textpos[0]
            + image_offset
            + (self.width - image_offset - size[0]) / 2.0,
            textpos_y + 1,
            0,
        )

        r, g, b, a = self._text_color
        blf.color(font_id, r, g, b, a)

        blf.draw(font_id, self._text)

    def draw_image(self):
        if self.__image is not None:
            y_screen_flip = self.get_area_height() - self.y_screen
            off_x, off_y = self.__image_position
            sx, sy = self.__image_size
            pad = self.__image_padding
            ui_bgl.draw_image_runtime(
                self.x_screen + off_x + pad,
                y_screen_flip - off_y - sy + pad,
                sx - 2 * pad,
                sy - 2 * pad,
                self.__image,
                1.0,
                crop=(0, 0, 1, 1),
                batch=None,
                corner_radius=self.image_corner_radius,
            )
            return True
        return False

    def set_mouse_down(self, mouse_down_func):
        self.mouse_down_func = mouse_down_func

    def mouse_down(self, x, y):
        if self.is_in_rect(x, y):
            self.__state = 1
            try:
                self.mouse_down_func(self)
            except Exception:
                bk_logger.exception("BL_UI_BUTTON mouse_down() error:")
            return True
        return False

    def set_mouse_down_right(self, mouse_down_right_func):
        self.mouse_down_right_func = mouse_down_right_func

    def mouse_down_right(self, x, y):
        if self.is_in_rect(x, y):
            if hasattr(self, "mouse_down_right_func"):
                try:
                    self.mouse_down_right_func(self)
                except Exception:
                    bk_logger.exception("BL_UI_BUTTON mouse_down_right() error:")

            return True

        return False

    def mouse_move(self, x, y):
        if self.is_in_rect(x, y):
            if self.__state != 1:
                # hover state
                self.__state = 2
        else:
            self.__state = 0

    def mouse_up(self, x, y):
        if self.is_in_rect(x, y):
            self.__state = 2
        else:
            self.__state = 0
