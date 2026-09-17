import os
import logging

import gpu

from .. import image_utils, ui_bgl
from .bl_ui_widget import BL_UI_Widget

bk_logger = logging.getLogger(__name__)


class BL_UI_Image(BL_UI_Widget):
    """A simple image widget.

    Used to display bigger thumbnail with additional info,
    while hover over a button.
    """

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.bg_color = (1.0, 1.0, 1.0, 1.0)

        self.__state = 0
        self.__image = None
        self.__image_size = (24, 24)
        self.__image_position = (4, 2)
        self.__image_padding: float = 0.0

    @property
    def image_padding(self):
        return self.__image_padding

    @image_padding.setter
    def image_padding(self, value: float):
        self.__image_padding = value

    def set_image_size(self, image_size):
        self.__image_size = image_size

    def set_image_position(self, image_position):
        self.__image_position = image_position

    def check_image_exists(self):
        # it's possible image was removed and doesn't exist.
        try:
            self.__image
            self.__image.filepath
        except Exception as e:
            self.__image = None
        return None

    def set_image(self, rel_filepath):
        # first try to access the image, for cases where it can get removed
        self.check_image_exists()
        try:
            if self.__image is None or self.__image.filepath != rel_filepath:
                imgname = f".{os.path.basename(rel_filepath)}"
                self.__image = image_utils.IMG(name=imgname, filepath=rel_filepath)
        except Exception as e:
            bk_logger.exception("BL_UI_BUTTON: exception in set_image(): %s", e)
            self.__image = None

    def set_image_colorspace(self, colorspace: str = ""):
        image_utils.set_colorspace(self.__image, colorspace)

    def get_image_path(self):
        self.check_image_exists()
        if self.__image is None:
            return None
        return self.__image.filepath

    def update(self, x, y):
        super().update(x, y)

    def draw(self):
        if not self._is_visible:
            return
        gpu.state.blend_set("ALPHA")

        if self.draw_image():
            return

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

    def draw_image(self):
        if self.__image is not None:
            y_screen_flip = self.get_area_height() - self.y_screen
            off_x, off_y = self.__image_position
            sx, sy = self.__image_size
            pad = self.image_padding
            img_x = self.x_screen + off_x + pad
            img_y = y_screen_flip - off_y - sy + pad
            img_w = sx - 2 * pad
            img_h = sy - 2 * pad

            if self.use_rounded_background:
                fill_color = self.bg_color or (1.0, 1.0, 1.0, 1.0)
                self.draw_background_rect(
                    img_x,
                    img_y,
                    img_w,
                    img_h,
                    fill_color,
                    force=True,
                    fill_color_override=fill_color,
                )

            corner_radius = (
                self.background_corner_radius
                if self.has_background_corner_radius_override()
                else None
            )

            ui_bgl.draw_image_runtime(
                img_x,
                img_y,
                img_w,
                img_h,
                self.__image,
                1.0,
                crop=(0, 0, 1, 1),
                batch=None,
                corner_radius=corner_radius,
                corner_segments=12,
            )
            return True

        return False

    def set_mouse_down(self, mouse_down_func):
        self.mouse_down_func = mouse_down_func

    def mouse_down(self, x, y):
        return False

    def mouse_move(self, x, y):
        return

    def mouse_up(self, x, y):
        return
