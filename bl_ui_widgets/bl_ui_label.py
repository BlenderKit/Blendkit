from typing import Tuple, Union

import blf
import bpy
from gpu_extras.batch import batch_for_shader

from .bl_ui_widget import BL_UI_Widget, region_redraw, set_font_size


class BL_UI_Label(BL_UI_Widget):
    """A simple text label widget."""

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self._set_background_corner_radius_default((4.0,))

        self._text_color = (1.0, 1.0, 1.0, 1.0)
        self._text = "Label"
        self._text_size = 16
        self._halign = "LEFT"
        self._valign = "TOP"
        # multiline
        self.multiline = False
        self.row_height = 20

        self.padding: Union[Tuple[float, float], float] = 0
        self.background = False

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

    def is_in_rect(self, x, y):
        return False

    def draw(self):
        if not self._is_visible or not self._text:
            return

        area_height = self.get_area_height()
        font_id = 1
        set_font_size(font_id, self._text_size)

        textpos_y = area_height - self.y_screen - self.height

        x = self.x_screen
        y = textpos_y
        block_width, block_height = blf.dimensions(font_id, self._text)
        if self._halign == "RIGHT":
            x -= block_width
        elif self._halign == "CENTER":
            x -= block_width // 2
        if self._halign != "LEFT" and self._valign == "CENTER":
            y -= block_height // 2

        lines = self._text.split("\n") if self.multiline else [self._text]
        entries = []
        cursor_y = y
        for index, line in enumerate(lines):
            if index > 0:
                cursor_y -= self.row_height
            width, height = blf.dimensions(font_id, line)
            if self.multiline and height == 0:
                height = self.row_height
            elif height == 0:
                height = self._text_size
            entries.append(
                {
                    "text": line,
                    "x": x,
                    "y": cursor_y,
                    "width": width,
                    "height": height,
                }
            )

        if not entries:
            return

        min_x = min(item["x"] for item in entries)
        max_x = max(item["x"] + item["width"] for item in entries)
        min_y = min(item["y"] for item in entries)
        max_y = max(item["y"] + item["height"] for item in entries)
        content_width = max(0.0, max_x - min_x)
        content_height = max(0.0, max_y - min_y)

        self.draw_background_rect(
            min_x,
            min_y,
            content_width,
            content_height,
            self._bg_color,
        )

        r, g, b, a = self._text_color
        for item in entries:
            if not item["text"]:
                continue
            blf.position(font_id, item["x"], item["y"], 0)
            blf.color(font_id, r, g, b, a)
            blf.draw(font_id, item["text"])

        if content_width > 0:
            strike_y = min_y + content_height * 0.5
            self.draw_strikethrough(
                min_x,
                max_x,
                strike_y,
                self._text_color,
            )


class BL_UI_DuoLabel(BL_UI_Widget):
    """A label with two text fields, A and B."""

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self._set_background_corner_radius_default((4.0,))

        self._text_a_color = (1.0, 1.0, 1.0, 1.0)
        self._text_a = "Label"

        self._text_b_color = (1.0, 1.0, 1.0, 1.0)
        self._text_b = ""

        self._text_size = 16
        self._halign = "LEFT"
        self._valign = "TOP"
        # multiline
        self.multiline = False
        self.row_height = 20
        self.strikethrough_a = False
        self.strikethrough_b = False
        self.segment_backgrounds = False
        self.segment_background_padding = None
        self.segment_background_color_a = None
        self.segment_background_color_b = None
        self.segment_background_gap = 0.0
        self.segment_spacing = 4.0
        self.segment_background_extra_top = 0.0
        self.segment_background_extra_bottom = 1.5

    @property
    def text_a_color(self):
        return self._text_a_color

    @text_a_color.setter
    def text_a_color(self, value):
        if value != self._text_a_color:
            bpy.context.region.tag_redraw()
        self._text_a_color = value

    @property
    def text_a(self):
        return self._text_a

    @text_a.setter
    def text_a(self, value):
        if value != self._text_a:
            bpy.context.region.tag_redraw()
        self._text_a = value

    @property
    def text_b_color(self):
        return self._text_b_color

    @text_b_color.setter
    def text_b_color(self, value):
        if value != self._text_b_color:
            bpy.context.region.tag_redraw()
        self._text_b_color = value

    @property
    def text_b(self):
        return self._text_b

    @text_b.setter
    def text_b(self, value):
        if value != self._text_b:
            bpy.context.region.tag_redraw()
        self._text_b = value

    @property
    def text_size(self):
        return self._text_size

    @text_size.setter
    def text_size(self, value):
        if value != self._text_size:
            bpy.context.region.tag_redraw()
        self._text_size = value

    def is_in_rect(self, x, y):
        return False

    def draw(self):
        if not self._is_visible:
            return

        area_height = self.get_area_height()

        font_id = 1
        set_font_size(font_id, self._text_size)

        textpos_y = area_height - self.y_screen - self.height

        cursor_x = self.x_screen
        spacing = max(0.0, float(self.segment_spacing))
        blocks = [
            (
                self._text_a,
                self._text_a_color,
                self.strikethrough_a,
                self.segment_background_color_a,
            ),
            (
                self._text_b,
                self._text_b_color,
                self.strikethrough_b,
                self.segment_background_color_b,
            ),
        ]
        segments = []
        for text, color, strike_flag, background_color in blocks:
            if not text:
                continue

            set_font_size(font_id, self._text_size)
            width, height = blf.dimensions(font_id, text)
            scaled_size = self._text_size
            scaled = False
            if self.width > 0:
                if self._halign == "LEFT":
                    available_width = max(1, self.x_screen + self.width - cursor_x)
                else:
                    available_width = self.width
                if width > available_width and width > 0:
                    scale = available_width / width
                    scaled_size = max(8, int(self._text_size * scale))
                    if scaled_size < self._text_size:
                        set_font_size(font_id, scaled_size)
                        width, height = blf.dimensions(font_id, text)
                        scaled = True

            x = cursor_x if self._halign == "LEFT" else self.x_screen
            y = textpos_y
            if self._halign != "LEFT":
                if self._halign == "RIGHT":
                    x -= width
                elif self._halign == "CENTER":
                    x -= width // 2
            if self._valign == "CENTER":
                y -= height // 2

            if not self.multiline:
                lines = [
                    {
                        "text": text,
                        "x": x,
                        "y": y,
                        "width": width,
                        "height": height or self._text_size,
                        "font_size": scaled_size,
                    }
                ]
            else:
                lines = []
                current_y = y
                split_lines = text.split("\n")
                for index, line in enumerate(split_lines):
                    if index > 0:
                        current_y -= self.row_height
                    line_width, line_height = blf.dimensions(font_id, line)
                    if line_height == 0:
                        line_height = self.row_height
                    lines.append(
                        {
                            "text": line,
                            "x": x,
                            "y": current_y,
                            "width": line_width,
                            "height": line_height,
                            "font_size": scaled_size,
                        }
                    )
                width = max((line["width"] for line in lines), default=width)
                height = max(len(lines) * self.row_height, height)

            if lines:
                seg_min_x = min(line["x"] for line in lines)
                seg_max_x = max(line["x"] + line["width"] for line in lines)
                seg_min_y = min(line["y"] for line in lines)
                seg_max_y = max(line["y"] + line["height"] for line in lines)
                bounds = {
                    "min_x": seg_min_x,
                    "max_x": seg_max_x,
                    "min_y": seg_min_y,
                    "max_y": seg_max_y,
                }
            else:
                bounds = None

            segments.append(
                {
                    "lines": lines,
                    "color": color,
                    "strikethrough": strike_flag,
                    "bounds": bounds,
                    "background_color": background_color,
                }
            )

            if self._halign == "LEFT" and bounds:
                cursor_x = bounds["max_x"] + spacing

            if scaled:
                set_font_size(font_id, self._text_size)

        if not segments:
            return

        all_lines = [line for segment in segments for line in segment["lines"]]
        if not all_lines:
            return

        min_x = min(line["x"] for line in all_lines)
        max_x = max(line["x"] + line["width"] for line in all_lines)
        min_y = min(line["y"] for line in all_lines)
        max_y = max(line["y"] + line["height"] for line in all_lines)
        content_width = max(0.0, max_x - min_x)
        content_height = max(0.0, max_y - min_y)

        if self.segment_backgrounds:
            pad_source = (
                self.segment_background_padding
                if self.segment_background_padding is not None
                else self.background_padding
            )
            if isinstance(pad_source, (list, tuple)):
                base_pad_x = float(pad_source[0])
                base_pad_y = (
                    float(pad_source[1])
                    if len(pad_source) > 1
                    else float(pad_source[0])
                )
            else:
                base_pad_x = base_pad_y = float(pad_source)

            bounded_segments = [seg for seg in segments if seg.get("bounds")]
            total_bounded = len(bounded_segments)
            desired_gap = max(0.0, float(self.segment_background_gap))
            spacing = max(0.0, float(self.segment_spacing))
            interior_pad = max(0.0, (spacing - desired_gap) * 0.5)
            extra_top = max(0.0, float(self.segment_background_extra_top))
            extra_bottom = max(0.0, float(self.segment_background_extra_bottom))

            def coerce_corner_radii(value):
                if isinstance(value, (tuple, list)):
                    values = list(value)
                else:
                    values = [value]
                if not values:
                    values = [0.0]
                if len(values) == 1:
                    values = values * 4
                elif len(values) == 2:
                    values = [values[0], values[1], values[1], values[0]]
                elif len(values) < 4:
                    values = values + [values[-1]] * (4 - len(values))
                return tuple(values[:4])

            base_corner_radii = coerce_corner_radii(self.background_corner_radius)

            for idx, segment in enumerate(bounded_segments):
                bounds = segment.get("bounds")
                if not bounds:
                    continue
                seg_width = max(0.0, bounds["max_x"] - bounds["min_x"])
                seg_height = max(0.0, bounds["max_y"] - bounds["min_y"])
                if seg_width <= 0 or seg_height <= 0:
                    continue

                pad_left = base_pad_x if idx == 0 else interior_pad
                pad_right = base_pad_x if idx == total_bounded - 1 else interior_pad

                if total_bounded > 1:
                    left_edge = idx == 0
                    right_edge = idx == total_bounded - 1
                    corner_override = (
                        base_corner_radii[0] if left_edge else 0.0,
                        base_corner_radii[1] if right_edge else 0.0,
                        base_corner_radii[2] if right_edge else 0.0,
                        base_corner_radii[3] if left_edge else 0.0,
                    )
                else:
                    corner_override = None

                padding_override = (
                    pad_left,
                    pad_right,
                    base_pad_y + extra_bottom,
                    base_pad_y + extra_top,
                )
                self.draw_background_rect(
                    bounds["min_x"],
                    bounds["min_y"],
                    seg_width,
                    seg_height,
                    segment.get("background_color") or segment["color"],
                    force=True,
                    padding_override=padding_override,
                    corner_radius_override=corner_override,
                )

        background_drawn = False
        if not self.segment_backgrounds:
            base_color = segments[0]["color"] if segments else self._text_a_color
            self.draw_background_rect(
                min_x,
                min_y,
                content_width,
                content_height,
                base_color,
            )
            background_drawn = True

        for segment in segments:
            r, g, b, a = segment["color"]
            for line in segment["lines"]:
                if not line["text"]:
                    continue
                set_font_size(font_id, line.get("font_size", self._text_size))
                blf.position(font_id, line["x"], line["y"], 0)
                blf.color(font_id, r, g, b, a)
                blf.draw(font_id, line["text"])
        set_font_size(font_id, self._text_size)

        for segment in segments:
            if not segment.get("strikethrough"):
                continue
            bounds = segment.get("bounds")
            if not bounds:
                continue
            segment_min_x = bounds["min_x"]
            segment_max_x = bounds["max_x"]
            if segment_max_x <= segment_min_x:
                continue
            strike_y = bounds["min_y"] + (bounds["max_y"] - bounds["min_y"]) * 0.5
            self.draw_strikethrough(
                segment_min_x,
                segment_max_x,
                strike_y,
                segment["color"],
                force=True,
            )

        if content_width > 0 and background_drawn:
            strike_color = segments[0]["color"]
            strike_y = min_y + content_height * 0.5
            self.draw_strikethrough(
                min_x,
                max_x,
                strike_y,
                strike_color,
            )
