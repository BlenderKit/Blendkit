import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ..asset_bar import asset_bar_op
from ..asset_bar.mini_asset_bar import (
    MiniAssetBar,
    fit_label,
    mini_bar_layout,
    price_bubble_style,
)


class TestMiniPriceBubbles(unittest.TestCase):
    def test_discount_bubble_uses_strikethrough_and_wraps_without_smaller_text(self):
        owner = SimpleNamespace(tile_size=180, text_size=24)
        asset = {"isForSale": True, "userPrice": "34.85", "basePrice": "41.00"}
        with (
            patch(
                "%s.BL_UI_DuoLabel" % MiniAssetBar.__module__,
                side_effect=lambda *args: Mock(),
            ) as label,
            patch.object(
                asset_bar_op.ui_bgl,
                "get_text_size",
                side_effect=lambda font, text, size: (len(text) * 12, size),
            ),
        ):
            widgets = MiniAssetBar.price_widgets(owner, asset, 10, 20)
        self.assertEqual(len(widgets), 2)
        self.assertEqual(widgets[0].text_size, 24)
        self.assertEqual(widgets[1].text_size, 24)
        self.assertTrue(widgets[0].segment_backgrounds)
        self.assertEqual(
            widgets[0].segment_background_color_a, asset_bar_op.colors.PURPLE_PRICE
        )
        self.assertTrue(widgets[1].strikethrough_a)
        self.assertEqual(label.call_args_list[1].args[1], 51)

    def test_free_and_paid_use_regular_price_colors(self):
        self.assertEqual(
            price_bubble_style({"isFree": True}),
            (" Free ", "", asset_bar_op.colors.GREEN_PRICE),
        )
        self.assertEqual(
            price_bubble_style({"isForSale": True, "basePrice": "21.25"}),
            (" $21.25 ", "", asset_bar_op.colors.PURPLE_PRICE),
        )

    def test_discount_preserves_original_price(self):
        self.assertEqual(
            price_bubble_style(
                {"isForSale": True, "userPrice": "34.85", "basePrice": "41.00"}
            ),
            (" $34.85 ", " ($41.00) ", asset_bar_op.colors.PURPLE_PRICE),
        )

    def test_purchased_and_full_plan_styles(self):
        self.assertEqual(
            price_bubble_style({"isForSale": True, "canDownload": True})[0],
            " Purchased ",
        )
        self.assertEqual(
            price_bubble_style({"assetType": "addon"})[2],
            asset_bar_op.colors.ORANGE_FULL,
        )

    def test_wrapped_prices_have_extra_space_without_changing_thumbnails(self):
        single = mini_bar_layout(3, 180, 1200, 800, 500, 300, text_size=24)
        wrapped = mini_bar_layout(
            3, 180, 1200, 800, 500, 300, text_size=24, price_rows=2
        )
        self.assertEqual(single[2], wrapped[2])
        self.assertEqual(wrapped[3] - single[3], 31)


class TestMiniAssetBarLayout(unittest.TestCase):
    def test_main_bar_dimensions_and_text_size_are_forwarded(self):
        context = Mock()
        context.area.height = 800
        owner = SimpleNamespace(
            context=context,
            close_mini_asset_bar=Mock(),
            hide_tooltip=Mock(),
            badge_tooltip=Mock(),
            hover_mini_asset=Mock(),
            exit_mini_asset=Mock(),
            raise_tooltip=Mock(),
            button_size=180,
            thumb_size=172,
            free_button_text_size=24,
            mouse_x=400,
            mouse_y=500,
            widgets=[],
            other_button_size=32,
            panel=Mock(x_screen=0, y_screen=32, width=900, height=360),
        )
        with (
            patch.object(asset_bar_op, "MiniAssetBar") as mini,
            patch.object(asset_bar_op, "BL_UI_Widget"),
            patch.object(asset_bar_op, "region_redraw"),
        ):
            asset_bar_op.BlenderKitAssetBarOperator.open_mini_asset_bar(
                owner, [{"id": "variant"}], "Variants", Mock()
            )
        self.assertEqual(mini.call_args.args[3:5], (180, 172))
        self.assertEqual(mini.call_args.kwargs["text_size"], 24)
        self.assertIs(mini.call_args.kwargs["on_hover"], owner.hover_mini_asset)
        self.assertIs(mini.call_args.kwargs["on_hover_exit"], owner.exit_mini_asset)
        self.assertEqual(
            mini.call_args.kwargs["corner_radius"], asset_bar_op.ROUNDING_RADIUS
        )
        owner.badge_tooltip.hide.assert_called_once()
        owner.raise_tooltip.assert_called_once()

    def test_panel_and_thumbnail_corners_remain_rounded_after_rebuild(self):
        context = Mock()
        context.region.width = 1000
        context.area.height = 800
        with (
            patch.object(asset_bar_op.bpy, "context", context),
            patch.object(asset_bar_op.gpu.shader, "from_builtin"),
            patch.object(asset_bar_op.BL_UI_Widget, "_ensure_panel_batch"),
            patch.object(
                asset_bar_op.ui_bgl,
                "get_text_size",
                side_effect=lambda font, text, size: (len(text) * 6, size),
            ),
        ):
            mini = MiniAssetBar(
                context,
                [{"displayName": "Variant", "isFree": True}],
                "Variants",
                180,
                172,
                400,
                300,
                Mock(),
                Mock(),
                corner_radius=asset_bar_op.ROUNDING_RADIUS,
            )
            for _ in range(2):
                panel, button = mini.widgets[0], mini.buttons[0]
                self.assertTrue(panel.use_rounded_background)
                self.assertEqual(
                    panel.background_corner_radius, asset_bar_op.ROUNDING_RADIUS
                )
                self.assertTrue(button.use_rounded_background)
                self.assertEqual(button.image_corner_radius, 12.0)
                self.assertEqual(button.background_corner_radius, 12.0)
                mini.build_widgets()

    def test_header_inset_and_hovered_title_fit_rounded_panel(self):
        context = Mock()
        context.region.width = 1000
        context.area.height = 800
        name = "A very long variant name that needs truncation"
        with (
            patch.object(asset_bar_op.bpy, "context", context),
            patch.object(asset_bar_op.gpu.shader, "from_builtin"),
            patch.object(asset_bar_op.BL_UI_Widget, "_ensure_panel_batch"),
            patch.object(
                asset_bar_op.ui_bgl,
                "get_text_size",
                side_effect=lambda font, text, size: (len(text) * 6, size),
            ),
        ):
            mini = MiniAssetBar(
                context,
                [{"displayName": name}],
                name,
                180,
                172,
                400,
                300,
                Mock(),
                Mock(),
                corner_radius=asset_bar_op.ROUNDING_RADIUS,
            )
            title = mini.widgets[1]
            self.assertEqual(title.x - mini.rect[0], mini.corner_radius)
            self.assertEqual(title.width, mini.rect[2] - 2 * mini.corner_radius)
            self.assertLessEqual(len(title.text) * 6, title.width)
            mini.hover(mini.buttons[0])
            self.assertLessEqual(len(title.text) * 6, title.width)

    def test_preview_loader_uses_full_thumbnail_not_tile_thumbnail(self):
        image = Mock()
        image.get_image_path.return_value = None
        asset = {
            "assetType": "addon",
            "thumbnail": "large.jpg",
            "thumbnail_small": "small.jpg",
        }
        with (
            patch.object(asset_bar_op.paths, "get_temp_dir", return_value="/cache"),
            patch.dict(
                asset_bar_op.global_vars.DATA,
                {"images available": {"/cache/large.jpg": True}},
            ),
        ):
            asset_bar_op.set_thumb_check(image, asset, thumb_type="thumbnail")
        image.set_image.assert_called_once_with("/cache/large.jpg")

    def test_larger_text_increases_label_space_without_shrinking_thumbnails(self):
        normal = mini_bar_layout(3, 180, 1200, 800, 500, 300, text_size=12)
        enlarged = mini_bar_layout(3, 180, 1200, 800, 500, 300, text_size=24)
        self.assertEqual(normal[2], enlarged[2])
        self.assertEqual(enlarged[4:], (3, 1))
        self.assertGreater(enlarged[3], normal[3])

    def test_shortened_variant_title_keeps_complete_variant_suffix(self):
        with patch.object(
            asset_bar_op.ui_bgl,
            "get_text_size",
            side_effect=lambda font, text, size: (len(text) * 6, 12),
        ):
            label = fit_label("Mock VALIDATED Variant Add-on [Basic]", 92, 12)
        self.assertTrue(label.endswith("[Basic]"))
        self.assertLessEqual(len(label) * 6, 92)

    def test_matches_main_thumbnail_size_and_contains_cursor(self):
        left, top, width, height, columns, rows = mini_bar_layout(
            3, 100, 1200, 800, 500, 300
        )
        self.assertEqual((columns, rows), (3, 1))
        self.assertEqual(width, 316)
        self.assertTrue(left <= 500 <= left + width)
        self.assertTrue(top <= 300 <= top + height)

    def test_clamps_to_viewport_edges(self):
        for mouse_x, mouse_y in ((10, 10), (1190, 790)):
            left, top, width, height, columns, rows = mini_bar_layout(
                3, 100, 1200, 800, mouse_x, mouse_y
            )
            self.assertGreaterEqual(left, 8)
            self.assertGreaterEqual(top, 8)
            self.assertLessEqual(left + width, 1192)
            self.assertLessEqual(top + height, 792)

    def test_large_collection_uses_bounded_grid(self):
        left, top, width, height, columns, rows = mini_bar_layout(
            100, 100, 400, 500, 200, 200
        )
        self.assertEqual(columns, 3)
        self.assertLess(columns * rows, 100)
        self.assertLessEqual(height, 484)


class TestMiniAssetBarEvents(unittest.TestCase):
    def test_hover_switch_and_exit_route_to_shared_tooltip(self):
        mini = SimpleNamespace(
            widgets=[Mock(), Mock(width=360)],
            rect=(0, 0, 400, 200, 1, 1),
            text_size=12,
            on_hover=Mock(),
            on_hover_exit=Mock(),
            hovered_button=None,
        )
        first = SimpleNamespace(
            asset_data={"id": "first", "displayName": "First"},
            x_screen=900,
            y_screen=500,
            height=120,
        )
        second = SimpleNamespace(
            asset_data={"id": "second", "displayName": "Second"},
            x_screen=0,
            y_screen=100,
            height=120,
        )
        with patch.object(asset_bar_op.ui_bgl, "get_text_size", return_value=(20, 12)):
            MiniAssetBar.hover(mini, first)
            mini.on_hover.assert_called_with(first)
            MiniAssetBar.hover(mini, second)
            mini.on_hover.assert_called_with(second)
        MiniAssetBar.exit_hover(mini, first)
        mini.on_hover_exit.assert_not_called()
        MiniAssetBar.exit_hover(mini, second)
        mini.on_hover_exit.assert_called_once_with(second)
        self.assertIsNone(mini.hovered_button)

    def test_wheel_scroll_stays_within_collection(self):
        mini = SimpleNamespace(
            rect=(0, 0, 316, 332, 3, 2), offset=0, assets=list(range(20)), buttons=[]
        )
        down = SimpleNamespace(type="WHEELDOWNMOUSE")
        for index in range(10):
            MiniAssetBar.handle_event(mini, down)
        self.assertEqual(mini.offset, 15)
        self.assertEqual(
            MiniAssetBar.handle_event(mini, SimpleNamespace(type="WHEELUPMOUSE")),
            "REBUILD",
        )
        self.assertEqual(mini.offset, 12)

    def test_timer_refreshes_mini_thumbnails_without_closing(self):
        owner = self.owner()
        with patch.object(asset_bar_op, "region_redraw"):
            self.assertTrue(
                asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                    owner, SimpleNamespace(type="TIMER")
                )
            )
        owner.mini_asset_bar.refresh_thumbnails.assert_called_once()
        owner.close_mini_asset_bar.assert_not_called()

    def test_timer_updates_hovered_variant_image(self):
        owner = self.owner()
        owner.tooltip_image = Mock()
        asset = {"id": "variant"}
        owner.mini_asset_bar.hovered_button = SimpleNamespace(asset_data=asset)
        with (
            patch.object(asset_bar_op, "region_redraw"),
            patch.object(asset_bar_op, "set_thumb_check") as set_thumb,
        ):
            asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                owner, SimpleNamespace(type="TIMER")
            )
        set_thumb.assert_called_once_with(
            owner.tooltip_image, asset, thumb_type="thumbnail"
        )

    def test_parent_thumbnail_download_does_not_replace_mini_tooltip(self):
        owner = SimpleNamespace(
            mini_asset_bar=SimpleNamespace(hovered_button=object()),
            tooltip_image=Mock(),
        )
        with patch.object(asset_bar_op, "set_thumb_check") as set_thumb:
            asset_bar_op.BlenderKitAssetBarOperator.update_tooltip_image(
                owner, "parent"
            )
        set_thumb.assert_not_called()

    def test_shared_tooltip_is_drawn_above_mini_widgets(self):
        bar, panel, image, mini = object(), object(), object(), object()
        owner = SimpleNamespace(
            widgets=[bar, panel, image, mini],
            tooltip_panel=panel,
            tooltip_widgets=[image],
        )
        asset_bar_op.BlenderKitAssetBarOperator.raise_tooltip(owner)
        self.assertEqual(owner.widgets, [bar, mini, panel, image])

    def test_scrolling_rebuild_hides_stale_tooltip_and_raises_it(self):
        old, new, tooltip = object(), object(), object()
        owner = self.owner()
        owner.widgets = [old, tooltip]
        owner.hide_tooltip = Mock()
        owner.raise_tooltip = Mock()
        owner.mini_asset_bar.widgets = [old]
        owner.mini_asset_bar.handle_event.return_value = "REBUILD"
        owner.mini_asset_bar.build_widgets.side_effect = lambda: setattr(
            owner.mini_asset_bar, "widgets", [new]
        )
        with patch.object(asset_bar_op, "region_redraw"):
            asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                owner, SimpleNamespace(type="WHEELDOWNMOUSE")
            )
        self.assertEqual(owner.widgets, [tooltip, new])
        self.assertFalse(owner.draw_tooltip)
        owner.hide_tooltip.assert_called_once()
        owner.raise_tooltip.assert_called_once()

    def test_mini_hover_uses_full_tooltip_without_changing_parent_selection(self):
        operator_class = asset_bar_op.BlenderKitAssetBarOperator
        ui = SimpleNamespace(active_index=12)
        context = SimpleNamespace(window_manager=SimpleNamespace(blenderkitUI=ui))
        area = SimpleNamespace(regions=[])
        region = SimpleNamespace(width=1000, height=800)
        operator = SimpleNamespace(
            active_index=12,
            show_tooltip=Mock(),
            hide_tooltip=Mock(),
            tooltip_image=Mock(),
            tooltip_image_help=Mock(),
            asset_name=Mock(),
            authors_name=Mock(),
            gravatar_image=Mock(),
            quality_label=Mock(),
            quality_star=Mock(),
            multi_price_label=Mock(),
            author_about_me=Mock(),
            version_warning=Mock(),
            tooltip_panel=Mock(width=400, height=480),
            update_comments_for_validators=Mock(),
            _current_area_region=Mock(return_value=(area, region)),
            _reset_tooltip_dimensions=Mock(),
            _build_context_snapshot=Mock(return_value=SimpleNamespace(region=region)),
            update_tooltip_size=Mock(),
            update_tooltip_layout=Mock(),
            tooltip_width=400,
            tooltip_height=480,
            warning_color=(1, 0, 0, 1),
            caution_color=(1, 1, 0, 1),
        )
        operator.show_asset_tooltip = lambda widget, data: (
            operator_class.show_asset_tooltip(operator, widget, data)
        )
        asset = {
            "id": "pro",
            "assetBaseId": "pro-base",
            "assetType": "addon",
            "structure": "variant",
            "displayName": "Pro edition",
            "author": {"id": "1"},
            "ratingsCount": {"quality": 3},
            "ratingsAverage": {"quality": 8},
            "isForSale": True,
            "canDownload": False,
            "isFree": False,
            "basePrice": "10",
        }
        widget = SimpleNamespace(
            asset_data=asset, x_screen=100, y_screen=100, height=100
        )
        author = SimpleNamespace(firstName="Jane", lastName="Doe", gravatarImg="avatar")
        with (
            patch.object(asset_bar_op.bpy, "context", context),
            patch.dict(asset_bar_op.global_vars.BKIT_AUTHORS, {1: author}, clear=True),
            patch.object(asset_bar_op, "set_thumb_check") as thumbnail,
            patch.object(asset_bar_op.utils, "get_search_props", return_value=Mock()),
            patch.object(
                asset_bar_op.utils, "profile_is_validator", return_value=False
            ),
            patch.object(
                asset_bar_op.utils,
                "asset_from_newer_blender_version",
                return_value=(False, None),
            ),
            patch.object(
                asset_bar_op.utils,
                "get_addon_blender_compatibility",
                return_value=(True, None, None),
            ),
            patch.object(
                asset_bar_op.utils,
                "get_addon_os_compatibility",
                return_value=(True, []),
            ),
        ):
            operator_class.hover_mini_asset(operator, widget)
        operator.show_tooltip.assert_called_once()
        thumbnail.assert_called_once_with(
            operator.tooltip_image, asset, thumb_type="thumbnail"
        )
        self.assertEqual(operator.asset_name.text, "Pro edition")
        self.assertEqual(operator.authors_name.text, "by Jane Doe")
        self.assertEqual(operator.quality_label.text, "8/10")
        self.assertEqual(operator.multi_price_label.text_b, " $10 ")
        self.assertTrue(operator.multi_price_label.visible)
        self.assertEqual(operator.gravatar_image.set_image.call_args.args, ("avatar",))
        self.assertEqual(operator.active_index, 12)
        self.assertEqual(ui.active_index, 12)

    def test_parent_click_always_opens_mini_bar_not_install_dialog(self):
        owner = SimpleNamespace(scroll_offset=0, show_variant_picker=Mock())
        widget = SimpleNamespace(button_index=0)
        parent = {"assetType": "addon", "structure": "variant_parent"}
        context = Mock()
        context.window_manager.blenderkitUI.dragging = False
        with (
            patch.object(asset_bar_op.bpy, "context", context),
            patch.object(asset_bar_op.bpy, "ops") as ops,
            patch.object(
                asset_bar_op.search, "get_search_results", return_value=[parent]
            ),
            patch.object(asset_bar_op.ui_panels, "last_time_overlay_panel_active", 0),
        ):
            for selection in (None, "free", "pro"):
                parent["selectedVariantId"] = selection
                asset_bar_op.BlenderKitAssetBarOperator.drag_drop_asset(owner, widget)
        self.assertEqual(owner.show_variant_picker.call_count, 3)
        self.assertEqual(owner.show_variant_picker.call_args.args[0].asset_index, 0)
        ops.view3d.asset_drag_drop.assert_not_called()
        ops.scene.blenderkit_addon_choice.assert_not_called()

    def test_close_removes_overlay_widgets_but_preserves_main_bar(self):
        main = object()
        overlay = object()
        dim = object()
        owner = SimpleNamespace(
            widgets=[main, dim, overlay],
            mini_asset_bar=SimpleNamespace(widgets=[overlay]),
            _mini_asset_bar_dim=dim,
            hide_tooltip=Mock(),
        )
        with patch.object(asset_bar_op, "region_redraw"):
            asset_bar_op.BlenderKitAssetBarOperator.close_mini_asset_bar(owner)
        self.assertEqual(owner.widgets, [main])
        self.assertIsNone(owner.mini_asset_bar)
        self.assertIsNone(owner._mini_asset_bar_dim)
        owner.hide_tooltip.assert_called_once()

    def owner(self, inside=True):
        mini = Mock()
        mini.hovered_button = None
        mini.context.area.height = 800
        mini.contains.return_value = inside
        mini.handle_event.return_value = "HANDLED"
        return SimpleNamespace(
            mini_asset_bar=mini,
            close_mini_asset_bar=Mock(),
            _event_coords_in_active_region=Mock(return_value=(500, 300)),
        )

    def test_inside_click_is_consumed_by_mini_bar(self):
        owner = self.owner()
        event = SimpleNamespace(type="LEFTMOUSE", value="PRESS")
        with patch.object(asset_bar_op, "region_redraw"):
            self.assertTrue(
                asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                    owner, event
                )
            )
        owner.mini_asset_bar.handle_event.assert_called_once_with(event)
        owner.close_mini_asset_bar.assert_not_called()

    def test_leaving_or_clicking_outside_closes_without_click_through(self):
        for event_type in ("MOUSEMOVE", "LEFTMOUSE", "RIGHTMOUSE"):
            owner = self.owner(inside=False)
            event = SimpleNamespace(type=event_type, value="PRESS")
            self.assertTrue(
                asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                    owner, event
                )
            )
            owner.close_mini_asset_bar.assert_called_once()
            owner.mini_asset_bar.handle_event.assert_not_called()

    def test_escape_closes_mini_bar_only(self):
        owner = self.owner()
        self.assertTrue(
            asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                owner, SimpleNamespace(type="ESC", value="PRESS")
            )
        )
        owner.close_mini_asset_bar.assert_called_once()

    def test_no_mini_bar_leaves_main_bar_events_unchanged(self):
        owner = SimpleNamespace(mini_asset_bar=None)
        self.assertFalse(
            asset_bar_op.BlenderKitAssetBarOperator.handle_mini_asset_bar_event(
                owner, SimpleNamespace(type="LEFTMOUSE")
            )
        )
