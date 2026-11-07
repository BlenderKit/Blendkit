import math

from .. import ui_bgl
from ..bl_ui_widgets.bl_ui_button import BL_UI_Button
from ..bl_ui_widgets.bl_ui_label import BL_UI_Label
from ..bl_ui_widgets.bl_ui_widget import BL_UI_Widget


def mini_bar_layout(count, tile_size, width, height, mouse_x, mouse_y):
    margin = 8
    header = 28
    row_height = tile_size + 44
    columns = max(1, min(count, int((width - margin * 4) // tile_size)))
    rows = max(
        1,
        min(
            math.ceil(count / columns),
            int((height - header - margin * 4) // row_height),
        ),
    )
    panel_width = columns * tile_size + margin * 2
    panel_height = rows * row_height + header + margin * 2
    left = max(margin, min(mouse_x - tile_size / 2, width - panel_width - margin))
    top = max(
        margin, min(mouse_y - header - tile_size / 2, height - panel_height - margin)
    )
    return left, top, panel_width, panel_height, columns, rows


def fit_label(text, width, size):
    text = str(text).replace("\n", " ")
    if ui_bgl.get_text_size(1, text, size)[0] <= width:
        return text
    suffix_word = text.rsplit(" ", 1)[-1]
    if (
        suffix_word != text
        and ui_bgl.get_text_size(1, "..." + suffix_word, size)[0] <= width
    ):
        prefix = text[: -len(suffix_word)].rstrip()
        while prefix:
            shortened = prefix + "..." + suffix_word
            if ui_bgl.get_text_size(1, shortened, size)[0] <= width:
                return shortened
            prefix = prefix[:-1].rstrip()
        return "..." + suffix_word
    count = len(text)
    while count > 0:
        count -= 1
        prefix = (count + 1) // 2
        suffix = count // 2
        shortened = text[:prefix] + "..." + (text[-suffix:] if suffix else "")
        if ui_bgl.get_text_size(1, shortened, size)[0] <= width:
            return shortened
    return ""


class MiniAssetBar:
    def __init__(
        self,
        context,
        assets,
        title,
        tile_size,
        thumbnail_size,
        mouse_x,
        mouse_y,
        set_thumbnail,
        on_select,
        on_context=None,
    ):
        self.context = context
        self.assets = list(assets)
        self.title = title
        self.tile_size = tile_size
        self.thumbnail_size = thumbnail_size
        self.set_thumbnail = set_thumbnail
        self.on_select = on_select
        self.on_context = on_context
        self.offset = 0
        self.rect = mini_bar_layout(
            len(assets),
            tile_size,
            context.region.width,
            context.area.height,
            mouse_x,
            mouse_y,
        )
        self.widgets = []
        self.buttons = []
        self.build_widgets()

    def build_widgets(self):
        left, top, width, height, columns, rows = self.rect
        panel = BL_UI_Widget(left, top, width, height)
        panel.bg_color = (0.08, 0.08, 0.08, 0.98)
        panel.active = False
        title = BL_UI_Label(left + 8, top + 6, width - 16, 16)
        title.text_size = 13
        title.text = fit_label(self.title, width - 16, 13)
        self.widgets = [panel, title]
        self.buttons = []
        for slot, asset in enumerate(
            self.assets[self.offset : self.offset + columns * rows]
        ):
            x = left + 8 + (slot % columns) * self.tile_size
            y = top + 28 + (slot // columns) * (self.tile_size + 44)
            button = BL_UI_Button(x, y, self.tile_size, self.tile_size + 44)
            button.text = ""
            button.bg_color = (0.15, 0.15, 0.15, 1.0)
            button.hover_bg_color = (0.24, 0.24, 0.24, 1.0)
            button.asset_data = asset
            padding = (self.tile_size - self.thumbnail_size) / 2
            button.set_image_size((self.thumbnail_size, self.thumbnail_size))
            button.set_image_position((padding, padding))
            self.set_thumbnail(button, asset)
            button.set_mouse_down(self.select)
            button.set_mouse_enter(self.hover)
            if self.on_context:
                button.set_mouse_down_right(self.show_context)
            label = BL_UI_Label(x + 4, y + self.tile_size + 2, self.tile_size - 8, 14)
            label.text_size = 12
            label.text = fit_label(
                asset.get("displayName", asset.get("name", "")), self.tile_size - 8, 12
            )
            price = BL_UI_Label(x + 4, y + self.tile_size + 21, self.tile_size - 8, 14)
            price.text_size = 12
            price.text = fit_label(asset.get("mini_label", ""), self.tile_size - 8, 12)
            self.buttons.append(button)
            self.widgets.extend((button, label, price))
        for widget in self.widgets:
            widget.init(self.context)

    def hover(self, widget):
        self.widgets[1].text = fit_label(
            widget.asset_data.get("displayName", widget.asset_data.get("name", "")),
            self.rect[2] - 16,
            13,
        )

    def contains(self, mouse_x, mouse_y):
        left, top, width, height, columns, rows = self.rect
        return left <= mouse_x <= left + width and top <= mouse_y <= top + height

    def select(self, widget):
        self.on_select(widget.asset_data)

    def refresh_thumbnails(self):
        for button in self.buttons:
            self.set_thumbnail(button, button.asset_data)

    def show_context(self, widget):
        self.on_context(widget.asset_data)

    def handle_event(self, event):
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            columns, rows = self.rect[4:]
            delta = columns if event.type == "WHEELDOWNMOUSE" else -columns
            max_offset = max(
                0, math.ceil(len(self.assets) / columns) * columns - columns * rows
            )
            offset = max(0, min(self.offset + delta, max_offset))
            if offset != self.offset:
                self.offset = offset
                return "REBUILD"
        for button in self.buttons:
            if button.handle_event(event):
                break
        return "HANDLED"
