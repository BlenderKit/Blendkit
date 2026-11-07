import math

from .. import colors, ui_bgl
from ..bl_ui_widgets.bl_ui_button import BL_UI_Button
from ..bl_ui_widgets.bl_ui_label import BL_UI_DuoLabel, BL_UI_Label
from ..bl_ui_widgets.bl_ui_widget import BL_UI_Widget


def mini_bar_layout(
    count, tile_size, width, height, mouse_x, mouse_y, text_size=12, price_rows=1
):
    margin = 8
    header = max(28, text_size + 16)
    row_height = tile_size + (1 + price_rows) * text_size + 20 + (price_rows - 1) * 7
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


def price_bubble_style(asset):
    if asset.get("isPrivate"):
        return " Private ", "", colors.GRAY
    if asset.get("isFree"):
        return " Free ", "", colors.GREEN_PRICE
    if asset.get("isForSale"):
        if asset.get("canDownload"):
            return " Purchased ", "", colors.PURPLE_PRICE
        price = asset.get("userPrice")
        original = asset.get("basePrice")
        if price is not None and original is not None and str(price) != str(original):
            return f" ${price} ", f" (${original}) ", colors.PURPLE_PRICE
        price = price if price is not None else original
        return (
            (f" ${price} " if price is not None else " Paid "),
            "",
            colors.PURPLE_PRICE,
        )
    if asset.get("assetType") == "addon":
        return " Full Plan ", "", colors.ORANGE_FULL
    return asset.get("mini_label", ""), "", colors.GRAY


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
        text_size=12,
    ):
        self.context = context
        self.assets = list(assets)
        self.title = title
        self.tile_size = tile_size
        self.thumbnail_size = thumbnail_size
        self.text_size = text_size
        self.header_height = max(28, text_size + 16)
        self.price_rows = 1
        for asset in self.assets:
            current, original, background = price_bubble_style(asset)
            if (
                original
                and ui_bgl.get_text_size(1, current + original, text_size)[0] + 4
                > tile_size - 8
            ):
                self.price_rows = 2
        self.label_height = (
            (1 + self.price_rows) * text_size + 20 + (self.price_rows - 1) * 7
        )
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
            text_size,
            self.price_rows,
        )
        self.widgets = []
        self.buttons = []
        self.build_widgets()

    def build_widgets(self):
        left, top, width, height, columns, rows = self.rect
        panel = BL_UI_Widget(left, top, width, height)
        panel.bg_color = (0.08, 0.08, 0.08, 0.98)
        panel.active = False
        title = BL_UI_Label(left + 8, top + 6, width - 16, self.text_size + 2)
        title.text_size = self.text_size
        title.text = fit_label(self.title, width - 16, self.text_size)
        self.widgets = [panel, title]
        self.buttons = []
        for slot, asset in enumerate(
            self.assets[self.offset : self.offset + columns * rows]
        ):
            x = left + 8 + (slot % columns) * self.tile_size
            y = (
                top
                + self.header_height
                + (slot // columns) * (self.tile_size + self.label_height)
            )
            button = BL_UI_Button(
                x, y, self.tile_size, self.tile_size + self.label_height
            )
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
            label = BL_UI_Label(
                x + 4, y + self.tile_size + 2, self.tile_size - 8, self.text_size + 2
            )
            label.text_size = self.text_size
            label.text = fit_label(
                asset.get("displayName", asset.get("name", "")),
                self.tile_size - 8,
                self.text_size,
            )
            self.buttons.append(button)
            self.widgets.extend((button, label))
            self.widgets.extend(
                self.price_widgets(
                    asset, x + 4, y + self.tile_size + self.text_size + 9
                )
            )
        for widget in self.widgets:
            widget.init(self.context)

    def price_widgets(self, asset, x, y):
        current, original, background = price_bubble_style(asset)
        width = self.tile_size - 8
        wrap = (
            original
            and ui_bgl.get_text_size(1, current + original, self.text_size)[0] + 4
            > width
        )
        price = BL_UI_DuoLabel(x, y, width, self.text_size + 2)
        price.text_size = self.text_size
        price.text_a = fit_label(current, width, self.text_size)
        price.text_b = "" if wrap else original
        price.text_a_color = colors.WHITE
        price.text_b_color = colors.TEXT_DIM
        price.use_rounded_background = True
        price.background_corner_radius = "50%"
        price.segment_backgrounds = True
        price.segment_background_color_a = background
        price.segment_background_color_b = background
        price.strikethrough_b = bool(original) and not wrap
        widgets = [price]
        if wrap:
            previous = BL_UI_DuoLabel(
                x, y + self.text_size + 7, width, self.text_size + 2
            )
            previous.text_size = self.text_size
            previous.text_a = fit_label(original, width, self.text_size)
            previous.text_b = ""
            previous.text_a_color = colors.TEXT_DIM
            previous.use_rounded_background = True
            previous.background_corner_radius = "50%"
            previous.segment_backgrounds = True
            previous.segment_background_color_a = background
            previous.strikethrough_a = True
            widgets.append(previous)
        return widgets

    def hover(self, widget):
        self.widgets[1].text = fit_label(
            widget.asset_data.get("displayName", widget.asset_data.get("name", "")),
            self.rect[2] - 16,
            self.text_size,
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
