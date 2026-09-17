# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
# #
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# #
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
# #
# ##### END GPL LICENSE BLOCK #####

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bpy


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative imports
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import persistent_preferences
from .asset_bar import asset_bar_op


class _FakeWidget:
    """Hashable widget stand-in. SimpleNamespace defines __eq__ and is therefore
    unhashable, but _apply_widget_context does set-membership tests on widgets.
    """

    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y
        self.context = None
        self.update = Mock()


class TestAssetBarScrollUpdate(unittest.TestCase):
    def test_scroll_update_ignores_missing_search_results(self):
        dummy = SimpleNamespace(
            hide_tooltip=Mock(),
            button_scroll_down=SimpleNamespace(visible=True),
            button_scroll_up=SimpleNamespace(visible=True),
            _scroll_animating=False,
            scroll_phase=0.0,
            _update_grid_draw_offset=Mock(),
        )

        with patch.object(
            asset_bar_op.search,
            "get_active_history_step",
            return_value={"search_results": None, "search_results_orig": None},
        ):
            asset_bar_op.BlenderKitAssetBarOperator.scroll_update(dummy, always=True)

        dummy.hide_tooltip.assert_called_once_with()
        self.assertFalse(dummy.button_scroll_down.visible)
        self.assertFalse(dummy.button_scroll_up.visible)


class TestAssetBarPositioning(unittest.TestCase):
    def create_drag_panel(self, *, drag_enabled=False, is_drag=False):
        return SimpleNamespace(
            drag_enabled=drag_enabled,
            is_drag=is_drag,
            x_screen=0,
            y_screen=0,
            width=100,
            height=50,
            widgets=[],
            child_widget_focused=Mock(return_value=False),
            get_area_height=Mock(return_value=100),
            is_in_rect=Mock(return_value=True),
            update=Mock(),
            layout_widgets=Mock(),
        )

    def test_drag_panel_mouse_down_ignored_when_drag_disabled(self):
        panel = self.create_drag_panel(drag_enabled=False)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 10, 10)

        self.assertFalse(handled)
        self.assertFalse(panel.is_drag)

    def test_drag_panel_mouse_move_ignored_when_drag_disabled(self):
        panel = self.create_drag_panel(drag_enabled=False, is_drag=True)

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 10, 10)

        panel.update.assert_not_called()
        panel.layout_widgets.assert_not_called()

    def test_drag_panel_mouse_down_starts_drag_when_enabled(self):
        panel = self.create_drag_panel(drag_enabled=True)
        panel.is_in_rect = Mock(return_value=True)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 50, 130)

        self.assertTrue(handled)
        self.assertTrue(panel.is_drag)

    def test_drag_panel_mouse_down_ignored_outside_panel(self):
        panel = self.create_drag_panel(drag_enabled=True)
        panel.is_in_rect = Mock(return_value=False)

        handled = asset_bar_op.BL_UI_Drag_Panel.mouse_down(panel, 50, 130)

        self.assertFalse(handled)
        self.assertFalse(panel.is_drag)

    def test_drag_panel_mouse_move_drags_when_dragging(self):
        panel = self.create_drag_panel(drag_enabled=True, is_drag=True)

        asset_bar_op.BL_UI_Drag_Panel.mouse_move(panel, 60, 70)

        panel.update.assert_called_once()
        panel.layout_widgets.assert_called_once()

    def test_child_widget_focused_ignores_widget_not_under_cursor(self):
        panel = self.create_drag_panel()
        panel.widgets = [SimpleNamespace(is_in_rect=lambda x, y: False)]

        focused = asset_bar_op.BL_UI_Drag_Panel.child_widget_focused(panel, 40, 40)

        self.assertFalse(focused)


class TestAssetBarInvoke(unittest.TestCase):
    def test_initial_search_is_marked_before_layout_init(self):
        history_step = {}
        ui_props = SimpleNamespace(assetbar_on=False, turn_off=False)
        context = SimpleNamespace(
            area=SimpleNamespace(),
            window_manager=SimpleNamespace(blenderkitUI=ui_props),
            window=SimpleNamespace(),
        )
        dummy = SimpleNamespace(
            instances=[],
            keep_running=True,
            bar_x=10,
            bar_y=20,
            panel=SimpleNamespace(set_location=Mock()),
            on_init=Mock(),
            check_new_search_results=Mock(),
            setup_widgets=Mock(),
            set_element_images=Mock(),
            position_and_hide_buttons=Mock(),
            hide_tooltip=Mock(),
            scroll_update=Mock(),
            _save_and_hide_overlays=Mock(),
        )

        with (
            patch.object(asset_bar_op.search, "get_search_results", return_value=None),
            patch.object(
                asset_bar_op.search,
                "get_active_history_step",
                return_value=history_step,
            ),
            patch.object(asset_bar_op.search, "search") as mocked_search,
        ):
            result = asset_bar_op.BlenderKitAssetBarOperator.on_invoke(
                dummy, context, object()
            )

        self.assertTrue(result)
        self.assertTrue(history_step["is_searching"])
        mocked_search.assert_called_once_with()
        dummy.on_init.assert_called_once_with(context)


class TestAssetBarResizeHelpers(unittest.TestCase):
    def test_reset_resize_state_clears_resize_tracking(self):
        dummy = SimpleNamespace(
            _requested_rows_override=4,
            _resize_dragging=True,
            _resize_cursor_modal_active=True,
            _resize_drag_start_rows=7,
            _resize_drag_start_y=55,
        )

        asset_bar_op.BlenderKitAssetBarOperator._reset_resize_state(dummy)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertFalse(dummy._resize_dragging)
        self.assertFalse(dummy._resize_cursor_modal_active)
        self.assertEqual(dummy._resize_drag_start_rows, 1)
        self.assertEqual(dummy._resize_drag_start_y, 0)

    def test_set_resize_hover_cursor_updates_cursor_when_not_dragging(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_hover_cursor(dummy)

        window.cursor_set.assert_called_once_with(asset_bar_op.ASSETBAR_RESIZE_CURSOR)

    def test_set_resize_hover_cursor_ignores_dragging(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_dragging=True,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_hover_cursor(dummy)

        window.cursor_set.assert_not_called()

    def test_set_resize_drag_cursor_enables_modal_cursor(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.set_resize_drag_cursor(dummy)

        window.cursor_modal_set.assert_called_once_with(
            asset_bar_op.ASSETBAR_RESIZE_CURSOR
        )
        self.assertTrue(dummy._resize_cursor_modal_active)

    def test_restore_resize_cursor_restores_modal_cursor(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=True,
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.restore_resize_cursor(
            dummy, hovering=True
        )

        window.cursor_modal_restore.assert_called_once_with()
        window.cursor_set.assert_called_once_with(asset_bar_op.ASSETBAR_RESIZE_CURSOR)
        self.assertFalse(dummy._resize_cursor_modal_active)

    def test_update_expand_button_icon_uses_up_arrow_when_expanded(self):
        preferences = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(button_expand=SimpleNamespace(text=""))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.update_expand_button_icon(dummy)

        self.assertEqual(dummy.button_expand.text, "▲")

    def test_update_expand_button_icon_uses_down_arrow_when_collapsed(self):
        preferences = SimpleNamespace(assetbar_expanded=False)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(button_expand=SimpleNamespace(text=""))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.update_expand_button_icon(dummy)

        self.assertEqual(dummy.button_expand.text, "▼")

    def test_update_assetbar_layout_positions_toggle_button_and_enables_resize_edge(
        self,
    ):
        dummy = SimpleNamespace(
            scroll_update=Mock(),
            position_and_hide_buttons=Mock(),
            update_buttons=Mock(),
            button_close=SimpleNamespace(set_location=Mock()),
            other_button_size=40,
            bar_width=320,
            wcount=1,
            resize_edge_height=10,
            bar_height=180,
            button_expand=SimpleNamespace(set_location=Mock(), visible=False),
            button_scroll_up=SimpleNamespace(set_location=Mock()),
            resize_handle=SimpleNamespace(
                width=0,
                height=0,
                visible=False,
                set_location=Mock(),
            ),
            panel=SimpleNamespace(
                width=0,
                height=0,
                set_location=Mock(),
            ),
            tab_area_bg=SimpleNamespace(width=0),
            bar_x=12,
            bar_y=34,
            position_manufacturer_buttons=Mock(),
        )

        with patch.object(
            asset_bar_op.search,
            "get_active_history_step",
            return_value={"search_results": [{"id": 1}, {"id": 2}]},
        ):
            asset_bar_op.BlenderKitAssetBarOperator.update_assetbar_layout(
                dummy, context=object()
            )

        dummy.scroll_update.assert_called_once_with(
            always=True,
            update_visible_buttons=False,
        )
        dummy.button_expand.set_location.assert_called_once_with(280, 180)
        self.assertTrue(dummy.button_expand.visible)
        self.assertTrue(dummy.resize_handle.visible)
        self.assertEqual(dummy.resize_handle.width, 280)
        self.assertEqual(dummy.resize_handle.height, 10)
        dummy.resize_handle.set_location.assert_called_once_with(0, 180)

    def test_toggle_expand_delegates_to_toggle_assetbar_rows(self):
        dummy = SimpleNamespace(toggle_assetbar_rows=Mock())

        asset_bar_op.BlenderKitAssetBarOperator.toggle_expand(dummy, widget=object())

        dummy.toggle_assetbar_rows.assert_called_once_with()

    def test_begin_resize_drag_hides_tooltip_and_marks_dragging(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            hide_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.begin_resize_drag(dummy)

        self.assertTrue(dummy._resize_dragging)
        dummy.hide_tooltip.assert_called_once_with()

    def test_end_resize_drag_restores_cursor(self):
        dummy = SimpleNamespace(
            _resize_dragging=True,
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.end_resize_drag(dummy, hovering=False)

        self.assertFalse(dummy._resize_dragging)
        dummy.restore_resize_cursor.assert_called_once_with(hovering=False)

    def test_on_resize_drag_begin_captures_row_state_and_starts_drag(self):
        dummy = SimpleNamespace(
            _resize_drag_start_rows=1,
            _resize_drag_start_y=0,
            get_requested_assetbar_rows=Mock(return_value=4),
            begin_resize_drag=Mock(),
            set_resize_drag_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_drag_begin(
            dummy,
            handle=object(),
            start_y=140,
        )

        self.assertEqual(dummy._resize_drag_start_rows, 4)
        self.assertEqual(dummy._resize_drag_start_y, 140)
        dummy.begin_resize_drag.assert_called_once_with()
        dummy.set_resize_drag_cursor.assert_called_once_with()

    def test_on_resize_drag_update_previews_rows_from_drag(self):
        dummy = SimpleNamespace(
            _get_resize_rows_from_mouse_y=Mock(return_value=6),
            preview_assetbar_rows=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_drag_update(
            dummy,
            handle=object(),
            y=110,
        )

        dummy._get_resize_rows_from_mouse_y.assert_called_once_with(110)
        dummy.preview_assetbar_rows.assert_called_once_with(6)

    def test_on_resize_drag_end_applies_rows_and_restores_cursor_state(self):
        dummy = SimpleNamespace(
            _get_resize_rows_from_mouse_y=Mock(return_value=5),
            apply_assetbar_rows=Mock(),
            end_resize_drag=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_drag_end(
            dummy,
            handle=object(),
            y=100,
            hovering=True,
        )

        dummy._get_resize_rows_from_mouse_y.assert_called_once_with(100)
        dummy.apply_assetbar_rows.assert_called_once_with(5)
        dummy.end_resize_drag.assert_called_once_with(hovering=True)

    def test_on_resize_handle_click_toggles_rows(self):
        dummy = SimpleNamespace(
            toggle_assetbar_rows=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_handle_click(
            dummy,
            handle=object(),
        )

        dummy.toggle_assetbar_rows.assert_called_once_with()
        dummy.restore_resize_cursor.assert_called_once_with(hovering=True)

    def test_preview_assetbar_rows_refreshes_layout_for_changed_rows(self):
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=6),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 9)

        self.assertEqual(dummy._requested_rows_override, 6)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy._redraw_tracked_regions.assert_called_once_with()

    def test_preview_assetbar_rows_skips_refresh_for_same_rows(self):
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=4),
            get_requested_assetbar_rows=Mock(return_value=4),
            _current_layout_context=Mock(),
            _refresh_layout=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.preview_assetbar_rows(dummy, 4)

        self.assertIsNone(dummy._requested_rows_override)
        dummy._refresh_layout.assert_not_called()
        dummy._redraw_tracked_regions.assert_not_called()

    def test_apply_assetbar_rows_updates_preferences_and_refreshes_layout(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=2,
            assetbar_expanded=False,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=9,
            clamp_assetbar_rows=Mock(return_value=5),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 7)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertTrue(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_expand_button_icon.assert_called_once_with()
        dummy._redraw_tracked_regions.assert_called_once_with()

    def test_apply_assetbar_rows_keeps_expanded_rows_when_collapsing(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=5,
            assetbar_expanded=True,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=3,
            clamp_assetbar_rows=Mock(return_value=1),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 1)

        self.assertIsNone(dummy._requested_rows_override)
        self.assertEqual(preferences.maximized_assetbar_rows, 5)
        self.assertFalse(preferences.assetbar_expanded)
        dummy._refresh_layout.assert_called_once_with(context)
        dummy.update_expand_button_icon.assert_called_once_with()

    def test_apply_assetbar_rows_raises_collapsed_floor_to_two(self):
        # Collapsing while the saved expanded size is below two must bump the
        # remembered size up to two, so a later re-expand restores a usable bar
        # instead of a single row.
        preferences = SimpleNamespace(
            maximized_assetbar_rows=1,
            assetbar_expanded=True,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        context = object()
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(return_value=1),
            _current_layout_context=Mock(return_value=context),
            _refresh_layout=Mock(),
            update_expand_button_icon=Mock(),
            _redraw_tracked_regions=Mock(),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.apply_assetbar_rows(dummy, 1)

        self.assertEqual(preferences.maximized_assetbar_rows, 2)
        self.assertFalse(preferences.assetbar_expanded)

    def test_get_requested_assetbar_rows_returns_one_when_collapsed(self):
        preferences = SimpleNamespace(
            maximized_assetbar_rows=6,
            assetbar_expanded=False,
        )
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            clamp_assetbar_rows=Mock(side_effect=lambda rows: rows),
            get_expanded_assetbar_rows=Mock(return_value=6),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
                dummy
            )

        self.assertEqual(rows, 1)
        dummy.get_expanded_assetbar_rows.assert_not_called()

    def test_toggle_assetbar_rows_collapses_when_expanded(self):
        preferences = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            apply_assetbar_rows=Mock(),
            get_expanded_assetbar_rows=Mock(return_value=4),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.toggle_assetbar_rows(dummy)

        dummy.apply_assetbar_rows.assert_called_once_with(1)

    def test_toggle_assetbar_rows_expands_to_saved_rows_when_collapsed(self):
        preferences = SimpleNamespace(assetbar_expanded=False)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=preferences)}
                )
            )
        )
        dummy = SimpleNamespace(
            apply_assetbar_rows=Mock(),
            get_expanded_assetbar_rows=Mock(return_value=4),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            asset_bar_op.BlenderKitAssetBarOperator.toggle_assetbar_rows(dummy)

        dummy.apply_assetbar_rows.assert_called_once_with(4)

    def test_enter_button_ignores_tooltip_updates_while_resizing(self):
        widget = SimpleNamespace(button_index=0)
        dummy = SimpleNamespace(
            _resize_dragging=True,
            scroll_offset=0,
            search_results_count=10,
            active_index=-1,
            show_tooltip=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.enter_button(dummy, widget)

        self.assertEqual(dummy.active_index, -1)
        dummy.show_tooltip.assert_not_called()

    def test_exit_button_ignores_tooltip_cleanup_while_resizing(self):
        widget = SimpleNamespace(
            button_index=2,
            bookmark_button=SimpleNamespace(asset_index=None),
            author_button=SimpleNamespace(asset_index=None),
        )
        dummy = SimpleNamespace(
            _resize_dragging=True,
            scroll_offset=0,
            active_index=2,
            draw_tooltip=True,
            hide_tooltip=Mock(),
            update_bookmark_icon=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.exit_button(dummy, widget)

        self.assertTrue(dummy.draw_tooltip)
        self.assertEqual(dummy.active_index, 2)
        dummy.hide_tooltip.assert_not_called()

    def test_resolve_layout_rows_uses_override_preview(self):
        dummy = SimpleNamespace(_requested_rows_override=4)
        prefs = SimpleNamespace(assetbar_expanded=False, maximized_assetbar_rows=9)

        result = asset_bar_op.BlenderKitAssetBarOperator._resolve_layout_rows(
            dummy, prefs
        )

        self.assertEqual(result, (True, 4))

    def test_resolve_layout_rows_override_collapsed_floors_to_two(self):
        dummy = SimpleNamespace(_requested_rows_override=1)
        prefs = SimpleNamespace(assetbar_expanded=True, maximized_assetbar_rows=9)

        result = asset_bar_op.BlenderKitAssetBarOperator._resolve_layout_rows(
            dummy, prefs
        )

        self.assertEqual(result, (False, 2))

    def test_resolve_layout_rows_falls_back_to_preferences(self):
        dummy = SimpleNamespace(_requested_rows_override=None)
        prefs = SimpleNamespace(assetbar_expanded=True, maximized_assetbar_rows=5)

        result = asset_bar_op.BlenderKitAssetBarOperator._resolve_layout_rows(
            dummy, prefs
        )

        self.assertEqual(result, (True, 5))

    def test_clamp_assetbar_rows_bounds_to_height_limit(self):
        dummy = SimpleNamespace(_get_height_limited_rows=Mock(return_value=6))
        clamp = asset_bar_op.BlenderKitAssetBarOperator.clamp_assetbar_rows

        self.assertEqual(clamp(dummy, 10), 6)  # capped to the height limit
        self.assertEqual(clamp(dummy, 0), 1)  # never below one row
        self.assertEqual(clamp(dummy, 4), 4)  # passed through

    def test_get_expanded_assetbar_rows_clamps_saved_row_count(self):
        prefs = SimpleNamespace(maximized_assetbar_rows=5)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=prefs)}
                )
            )
        )
        dummy = SimpleNamespace(clamp_assetbar_rows=Mock(side_effect=lambda r: r))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_expanded_assetbar_rows(
                dummy
            )

        dummy.clamp_assetbar_rows.assert_called_once_with(5)
        self.assertEqual(rows, 5)

    def test_get_assetbar_rows_from_drag_converts_distance_to_rows(self):
        dummy = SimpleNamespace(
            button_size=50, clamp_assetbar_rows=Mock(side_effect=lambda r: r)
        )
        from_drag = asset_bar_op.BlenderKitAssetBarOperator.get_assetbar_rows_from_drag

        # drag the bottom edge down 100px (200 -> 100) at 50px/row => +2 rows
        self.assertEqual(from_drag(dummy, 3, 200, 100), 5)

    def test_get_assetbar_rows_from_drag_falls_back_without_button_size(self):
        dummy = SimpleNamespace(
            button_size=0, clamp_assetbar_rows=Mock(side_effect=lambda r: r)
        )
        from_drag = asset_bar_op.BlenderKitAssetBarOperator.get_assetbar_rows_from_drag

        self.assertEqual(from_drag(dummy, 3, 200, 100), 3)

    def test_get_resize_rows_from_mouse_y_uses_drag_start_state(self):
        dummy = SimpleNamespace(
            _resize_drag_start_rows=3,
            _resize_drag_start_y=200,
            get_assetbar_rows_from_drag=Mock(return_value=5),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator._get_resize_rows_from_mouse_y(
            dummy, 100
        )

        dummy.get_assetbar_rows_from_drag.assert_called_once_with(3, 200, 100)
        self.assertEqual(rows, 5)

    def test_get_requested_assetbar_rows_uses_live_override(self):
        dummy = SimpleNamespace(
            _requested_rows_override=4, clamp_assetbar_rows=Mock(return_value=4)
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
            dummy
        )

        dummy.clamp_assetbar_rows.assert_called_once_with(4)
        self.assertEqual(rows, 4)

    def test_get_requested_assetbar_rows_expands_when_expanded(self):
        prefs = SimpleNamespace(assetbar_expanded=True)
        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(
                preferences=SimpleNamespace(
                    addons={__package__: SimpleNamespace(preferences=prefs)}
                )
            )
        )
        dummy = SimpleNamespace(
            _requested_rows_override=None,
            get_expanded_assetbar_rows=Mock(return_value=6),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            rows = asset_bar_op.BlenderKitAssetBarOperator.get_requested_assetbar_rows(
                dummy
            )

        dummy.get_expanded_assetbar_rows.assert_called_once_with()
        self.assertEqual(rows, 6)

    def test_on_resize_handle_enter_sets_hover_cursor(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_handle_enter(dummy, None)

        dummy.set_resize_hover_cursor.assert_called_once_with()
        dummy.restore_resize_cursor.assert_not_called()

    def test_on_resize_handle_exit_restores_cursor(self):
        dummy = SimpleNamespace(
            _resize_dragging=False,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_handle_exit(dummy, None)

        dummy.restore_resize_cursor.assert_called_once_with()
        dummy.set_resize_hover_cursor.assert_not_called()

    def test_on_resize_handle_enter_ignored_while_dragging(self):
        dummy = SimpleNamespace(
            _resize_dragging=True,
            set_resize_hover_cursor=Mock(),
            restore_resize_cursor=Mock(),
        )

        asset_bar_op.BlenderKitAssetBarOperator.on_resize_handle_enter(dummy, None)

        dummy.set_resize_hover_cursor.assert_not_called()
        dummy.restore_resize_cursor.assert_not_called()

    def test_restore_resize_cursor_sets_default_when_not_hovering(self):
        window = Mock()
        dummy = SimpleNamespace(
            _resize_cursor_modal_active=False,
            _resize_dragging=False,
            _cursor_window=Mock(return_value=window),
        )

        asset_bar_op.BlenderKitAssetBarOperator.restore_resize_cursor(dummy)

        window.cursor_modal_restore.assert_not_called()
        window.cursor_set.assert_called_once_with("DEFAULT")

    def test_resize_cursor_helpers_noop_without_window(self):
        dummy = SimpleNamespace(
            _resize_dragging=False, _cursor_window=Mock(return_value=None)
        )
        op = asset_bar_op.BlenderKitAssetBarOperator

        # None window must short-circuit each cursor helper without raising.
        op.set_resize_hover_cursor(dummy)
        op.set_resize_drag_cursor(dummy)
        op.restore_resize_cursor(dummy)

        self.assertEqual(dummy._cursor_window.call_count, 3)

    def test_event_window_coords_returns_mouse_position(self):
        event = SimpleNamespace(mouse_x=12, mouse_y=34)

        coords = asset_bar_op.BlenderKitAssetBarOperator._event_window_coords(
            None, event
        )

        self.assertEqual(coords, (12, 34))

    def test_event_window_coords_none_without_mouse_attrs(self):
        coords = asset_bar_op.BlenderKitAssetBarOperator._event_window_coords(
            None, SimpleNamespace()
        )

        self.assertEqual(coords, (None, None))

    def test_get_height_limited_rows_caps_rows_by_region_height(self):
        context = SimpleNamespace(region=SimpleNamespace(height=500))
        dummy = SimpleNamespace(
            button_size=50,
            bar_y=20,
            assetbar_margin=10,
            other_button_size=30,
            _get_row_limit=Mock(return_value=20),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator._get_height_limited_rows(
            dummy, context
        )

        # available = 500 - 20 - 2*10 - 30 = 430; floor(430 / 50) = 8 rows fit,
        # which caps below the 20-row visible limit.
        self.assertEqual(rows, 8)

    def test_get_height_limited_rows_falls_back_to_row_limit_without_region(self):
        dummy = SimpleNamespace(
            button_size=50,
            _override_context=None,
            _get_row_limit=Mock(return_value=6),
            _current_layout_context=Mock(return_value=SimpleNamespace(region=None)),
        )

        rows = asset_bar_op.BlenderKitAssetBarOperator._get_height_limited_rows(dummy)

        dummy._current_layout_context.assert_called_once_with()
        self.assertEqual(rows, 6)

    def test_cursor_window_prefers_active_context_window(self):
        window = object()
        fake_bpy = SimpleNamespace(context=SimpleNamespace(window=window))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._cursor_window(
                SimpleNamespace()
            )

        self.assertIs(result, window)

    def test_cursor_window_falls_back_to_operator_window(self):
        window = object()
        fake_bpy = SimpleNamespace(context=SimpleNamespace(window=None))
        dummy = SimpleNamespace(window=window)

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._cursor_window(dummy)

        self.assertIs(result, window)

    def test_cursor_window_returns_none_when_operator_window_freed(self):
        fake_bpy = SimpleNamespace(context=SimpleNamespace(window=None))

        class FreedOperator:
            @property
            def window(self):
                raise ReferenceError("StructRNA of type Window has been removed")

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._cursor_window(
                FreedOperator()
            )

        self.assertIsNone(result)

    def test_current_layout_context_snapshots_active_area_region(self):
        area, region, snapshot = object(), object(), object()
        fake_bpy = SimpleNamespace(context=object())
        dummy = SimpleNamespace(
            _current_area_region=Mock(return_value=(area, region)),
            _build_context_snapshot=Mock(return_value=snapshot),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._current_layout_context(
                dummy
            )

        dummy._current_area_region.assert_called_once_with()
        dummy._build_context_snapshot.assert_called_once_with(
            fake_bpy.context, area, region
        )
        self.assertIs(result, snapshot)

    def test_resolve_window_prefers_context_window(self):
        window = object()

        result = asset_bar_op.BlenderKitAssetBarOperator._resolve_window(
            SimpleNamespace(), SimpleNamespace(window=window)
        )

        self.assertIs(result, window)

    def test_resolve_window_falls_back_to_active_bpy_window(self):
        window = object()
        fake_bpy = SimpleNamespace(context=SimpleNamespace(window=window))

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._resolve_window(
                SimpleNamespace(), SimpleNamespace(window=None)
            )

        self.assertIs(result, window)

    def test_validated_area_filters_none_and_freed_references(self):
        op = asset_bar_op.BlenderKitAssetBarOperator
        live = SimpleNamespace(as_pointer=lambda: 1)
        freed = SimpleNamespace(as_pointer=Mock(side_effect=ReferenceError))

        self.assertIsNone(op._validated_area(SimpleNamespace(), None))
        self.assertIs(op._validated_area(SimpleNamespace(), live), live)
        self.assertIsNone(op._validated_area(SimpleNamespace(), freed))

    def test_validated_region_filters_none_and_freed_references(self):
        op = asset_bar_op.BlenderKitAssetBarOperator
        live = SimpleNamespace(as_pointer=lambda: 1)
        freed = SimpleNamespace(as_pointer=Mock(side_effect=ReferenceError))

        self.assertIsNone(op._validated_region(SimpleNamespace(), None))
        self.assertIs(op._validated_region(SimpleNamespace(), live), live)
        self.assertIsNone(op._validated_region(SimpleNamespace(), freed))

    def test_safe_space_data_returns_active_space_or_none(self):
        op = asset_bar_op.BlenderKitAssetBarOperator
        space = object()
        area = SimpleNamespace(spaces=SimpleNamespace(active=space))

        class FreedArea:
            @property
            def spaces(self):
                raise ReferenceError

        self.assertIsNone(op._safe_space_data(SimpleNamespace(), None))
        self.assertIs(op._safe_space_data(SimpleNamespace(), area), space)
        self.assertIsNone(op._safe_space_data(SimpleNamespace(), FreedArea()))

    def test_build_context_snapshot_assembles_validated_pieces(self):
        window, area, region, space = object(), object(), object(), object()
        dummy = SimpleNamespace(
            _validated_area=Mock(return_value=area),
            _validated_region=Mock(return_value=region),
            _resolve_window=Mock(return_value=window),
            _safe_space_data=Mock(return_value=space),
        )

        snapshot = asset_bar_op.BlenderKitAssetBarOperator._build_context_snapshot(
            dummy, SimpleNamespace(area=None, region=None), area, region
        )

        self.assertEqual(
            (snapshot.window, snapshot.area, snapshot.region, snapshot.space_data),
            (window, area, region, space),
        )

    def test_unwrap_area_region_handles_dict_and_object(self):
        op = asset_bar_op.BlenderKitAssetBarOperator

        self.assertEqual(
            op._unwrap_area_region(SimpleNamespace(), {"area": 1, "region": 2}), (1, 2)
        )
        self.assertEqual(
            op._unwrap_area_region(
                SimpleNamespace(), SimpleNamespace(area=3, region=4)
            ),
            (3, 4),
        )

    def test_current_area_region_prefers_stored_refs(self):
        area, region = object(), object()
        dummy = SimpleNamespace(
            _active_area_ref=area,
            _active_region_ref=region,
            context=None,
            _validated_area=Mock(side_effect=lambda a: a),
            _validated_region=Mock(side_effect=lambda r: r),
            _unwrap_area_region=Mock(return_value=(None, None)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._current_area_region(dummy)

        self.assertEqual(result, (area, region))

    def test_current_area_region_falls_back_to_active_bpy(self):
        area, region = object(), object()
        fake_bpy = SimpleNamespace(context=SimpleNamespace(area=area, region=region))
        dummy = SimpleNamespace(
            _active_area_ref=None,
            _active_region_ref=None,
            context=None,
            _validated_area=Mock(side_effect=lambda a: a),
            _validated_region=Mock(side_effect=lambda r: r),
            _unwrap_area_region=Mock(return_value=(None, None)),
        )

        with patch.object(asset_bar_op, "bpy", fake_bpy):
            result = asset_bar_op.BlenderKitAssetBarOperator._current_area_region(dummy)

        self.assertEqual(result, (area, region))

    def test_apply_widget_context_updates_plain_widgets(self):
        override = object()
        w1 = _FakeWidget(1, 2)
        w2 = _FakeWidget(3, 4)
        dummy = SimpleNamespace(widgets=[w1, w2], panel=None, tooltip_panel=None)

        asset_bar_op.BlenderKitAssetBarOperator._apply_widget_context(dummy, override)

        self.assertIs(dummy._override_context, override)
        self.assertIs(w1.context, override)
        w1.update.assert_called_once_with(1, 2)
        w2.update.assert_called_once_with(3, 4)

    def test_apply_widget_context_returns_early_without_widgets(self):
        override = object()
        dummy = SimpleNamespace()

        asset_bar_op.BlenderKitAssetBarOperator._apply_widget_context(dummy, override)

        self.assertIs(dummy._override_context, override)

    def test_apply_widget_context_skips_panel_children_and_relayouts_panel(self):
        override = object()

        class FakePanel:
            def __init__(self):
                self.x = 0
                self.y = 0
                self.context = None
                self.update = Mock()
                self.layout_widgets = Mock()
                self.widgets = []

        panel = FakePanel()
        child = _FakeWidget(5, 6)
        panel.widgets = [child]
        plain = _FakeWidget(7, 8)
        dummy = SimpleNamespace(
            widgets=[panel, child, plain], panel=panel, tooltip_panel=None
        )

        with patch.object(asset_bar_op, "BL_UI_Drag_Panel", FakePanel):
            asset_bar_op.BlenderKitAssetBarOperator._apply_widget_context(
                dummy, override
            )

        child.update.assert_not_called()  # panel child must not be re-placed
        plain.update.assert_called_once_with(7, 8)
        panel.update.assert_called_once_with(0, 0)  # panel re-laid-out once
        panel.layout_widgets.assert_called_once_with()

    def test_find_area_region_returns_none_without_coords(self):
        dummy = SimpleNamespace(_event_window_coords=Mock(return_value=(None, None)))

        result = asset_bar_op.BlenderKitAssetBarOperator._find_area_region_from_event(
            dummy, object(), object()
        )

        self.assertEqual(result, (None, None))

    def test_find_area_region_returns_none_without_screen(self):
        dummy = SimpleNamespace(
            _event_window_coords=Mock(return_value=(10, 10)),
            _resolve_window=Mock(return_value=SimpleNamespace(screen=None)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._find_area_region_from_event(
            dummy, object(), object()
        )

        self.assertEqual(result, (None, None))

    def test_find_area_region_locates_region_under_cursor(self):
        region = SimpleNamespace(x=0, y=0, width=100, height=100)
        area = SimpleNamespace(type="VIEW_3D", x=0, y=0, width=200, height=200)
        screen = SimpleNamespace(areas=[area])
        dummy = SimpleNamespace(
            _event_window_coords=Mock(return_value=(50, 50)),
            _resolve_window=Mock(return_value=SimpleNamespace(screen=screen)),
        )

        with patch.object(
            asset_bar_op.viewport_utils,
            "iter_view3d_window_regions",
            return_value=[region],
        ):
            result = (
                asset_bar_op.BlenderKitAssetBarOperator._find_area_region_from_event(
                    dummy, object(), object()
                )
            )

        self.assertEqual(result, (area, region))

    def test_cursor_inside_active_area_true_within_region(self):
        area = SimpleNamespace(x=0, y=0, width=200, height=200)
        region = SimpleNamespace(x=0, y=0, width=100, height=100)
        dummy = SimpleNamespace(
            _active_area_ref=area,
            _active_region_ref=region,
            _validated_area=Mock(side_effect=lambda a: a),
            _validated_region=Mock(side_effect=lambda r: r),
            _event_window_coords=Mock(return_value=(50, 50)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._cursor_inside_active_area(
            dummy, object()
        )

        self.assertTrue(result)

    def test_cursor_inside_active_area_false_without_area(self):
        dummy = SimpleNamespace(
            _active_area_ref=None, _validated_area=Mock(return_value=None)
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._cursor_inside_active_area(
            dummy, object()
        )

        self.assertFalse(result)

    def test_view_changed_detects_area_or_region_difference(self):
        op = asset_bar_op.BlenderKitAssetBarOperator

        self.assertFalse(op._view_changed(SimpleNamespace(), 1, 2, 1, 2))
        self.assertTrue(op._view_changed(SimpleNamespace(), 9, 2, 1, 2))
        self.assertTrue(op._view_changed(SimpleNamespace(), 1, 9, 1, 2))

    def test_store_active_view_records_refs_and_pointers(self):
        ctx, area, region = object(), object(), object()
        dummy = SimpleNamespace()

        asset_bar_op.BlenderKitAssetBarOperator._store_active_view(
            dummy, ctx, area, region, 11, 22
        )

        self.assertEqual(dummy.active_area_pointer, 11)
        self.assertEqual(dummy.active_region_pointer, 22)
        self.assertIs(dummy._active_area_ref, area)
        self.assertIs(dummy._active_region_ref, region)
        self.assertIs(dummy.context, ctx)

    def test_refresh_layout_runs_all_updates(self):
        ctx = object()
        dummy = SimpleNamespace(
            update_assetbar_sizes=Mock(),
            update_tooltip_size=Mock(),
            update_assetbar_layout=Mock(),
            update_tooltip_layout=Mock(),
            tooltip_panel=SimpleNamespace(layout_widgets=Mock()),
        )

        asset_bar_op.BlenderKitAssetBarOperator._refresh_layout(dummy, ctx)

        dummy.update_assetbar_sizes.assert_called_once_with(ctx)
        dummy.update_assetbar_layout.assert_called_once_with(ctx)
        dummy.tooltip_panel.layout_widgets.assert_called_once_with()

    def test_refresh_layout_logs_layout_errors(self):
        ctx = object()
        dummy = SimpleNamespace(
            update_assetbar_sizes=Mock(),
            update_tooltip_size=Mock(),
            update_assetbar_layout=Mock(side_effect=RuntimeError("boom")),
            update_tooltip_layout=Mock(),
            tooltip_panel=SimpleNamespace(layout_widgets=Mock()),
        )

        with patch.object(asset_bar_op, "bk_logger") as logger:
            asset_bar_op.BlenderKitAssetBarOperator._refresh_layout(dummy, ctx)

        logger.log.assert_called_once()

    def test_apply_widget_context_relayouts_tooltip_panel(self):
        override = object()

        class FakePanel:
            def __init__(self):
                self.x = 0
                self.y = 0
                self.context = None
                self.update = Mock()
                self.layout_widgets = Mock()
                self.widgets = []

        tooltip = FakePanel()
        dummy = SimpleNamespace(widgets=[], panel=None, tooltip_panel=tooltip)

        with patch.object(asset_bar_op, "BL_UI_Drag_Panel", FakePanel):
            asset_bar_op.BlenderKitAssetBarOperator._apply_widget_context(
                dummy, override
            )

        tooltip.update.assert_called_once_with(0, 0)
        tooltip.layout_widgets.assert_called_once_with()

    def test_find_area_region_skips_non_view3d_area(self):
        area = SimpleNamespace(type="CONSOLE", x=0, y=0, width=200, height=200)
        screen = SimpleNamespace(areas=[area])
        dummy = SimpleNamespace(
            _event_window_coords=Mock(return_value=(50, 50)),
            _resolve_window=Mock(return_value=SimpleNamespace(screen=screen)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._find_area_region_from_event(
            dummy, object(), object()
        )

        self.assertEqual(result, (None, None))

    def test_find_area_region_skips_area_not_under_cursor(self):
        area = SimpleNamespace(type="VIEW_3D", x=0, y=0, width=200, height=200)
        screen = SimpleNamespace(areas=[area])
        dummy = SimpleNamespace(
            _event_window_coords=Mock(return_value=(999, 999)),
            _resolve_window=Mock(return_value=SimpleNamespace(screen=screen)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._find_area_region_from_event(
            dummy, object(), object()
        )

        self.assertEqual(result, (None, None))

    def test_cursor_inside_active_area_false_without_coords(self):
        area = SimpleNamespace(x=0, y=0, width=200, height=200)
        dummy = SimpleNamespace(
            _active_area_ref=area,
            _validated_area=Mock(side_effect=lambda a: a),
            _event_window_coords=Mock(return_value=(None, None)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._cursor_inside_active_area(
            dummy, object()
        )

        self.assertFalse(result)

    def test_cursor_inside_active_area_false_outside_area_bounds(self):
        area = SimpleNamespace(x=0, y=0, width=200, height=200)
        dummy = SimpleNamespace(
            _active_area_ref=area,
            _validated_area=Mock(side_effect=lambda a: a),
            _event_window_coords=Mock(return_value=(999, 999)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._cursor_inside_active_area(
            dummy, object()
        )

        self.assertFalse(result)

    def test_cursor_inside_active_area_true_without_region_ref(self):
        area = SimpleNamespace(x=0, y=0, width=200, height=200)
        dummy = SimpleNamespace(
            _active_area_ref=area,
            _active_region_ref=None,
            _validated_area=Mock(side_effect=lambda a: a),
            _validated_region=Mock(return_value=None),
            _event_window_coords=Mock(return_value=(50, 50)),
        )

        result = asset_bar_op.BlenderKitAssetBarOperator._cursor_inside_active_area(
            dummy, object()
        )

        self.assertTrue(result)


class TestPersistentPreferencesCompatibility(unittest.TestCase):
    def test_uses_json_assetbar_expanded_when_present(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=True,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=True),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"assetbar_expanded": False, "maximized_assetbar_rows": 4},
            user_preferences,
        )

        self.assertFalse(expanded)

    def test_uses_blender_property_when_json_key_is_missing(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=False,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=True),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"maximized_assetbar_rows": 4},
            user_preferences,
        )

        self.assertFalse(expanded)

    def test_falls_back_to_saved_row_count_when_property_was_not_persisted(self):
        user_preferences = SimpleNamespace(
            assetbar_expanded=True,
            maximized_assetbar_rows=4,
            is_property_set=Mock(return_value=False),
        )

        expanded = persistent_preferences.get_legacy_assetbar_expanded_preference(
            {"maximized_assetbar_rows": 1},
            user_preferences,
        )

        self.assertFalse(expanded)


class TestResizeHandle(unittest.TestCase):
    def make_handle(self, threshold=5):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = SimpleNamespace(
            dragging=False,
            press_active=False,
            start_y=0,
            threshold_px=threshold,
            _is_visible=True,
            _bg_color=(1.0, 1.0, 1.0, 0.5),
            shader=Mock(),
            is_in_rect=Mock(return_value=True),
            _draw_panel_batch=Mock(),
            on_drag_begin=Mock(),
            on_drag_update=Mock(),
            on_drag_end=Mock(),
            on_click=Mock(),
        )
        handle._call = lambda cb, *a, **k: cls._call(handle, cb, *a, **k)
        handle._threshold_reached = lambda y: cls._threshold_reached(handle, y)
        return handle

    def test_mouse_down_in_rect_arms_press(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()

        handled = cls.mouse_down(handle, 10, 100)

        self.assertTrue(handled)
        self.assertTrue(handle.press_active)
        self.assertEqual(handle.start_y, 100)

    def test_mouse_down_outside_rect_ignored(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()
        handle.is_in_rect = Mock(return_value=False)

        self.assertFalse(cls.mouse_down(handle, 10, 100))
        self.assertFalse(handle.press_active)

    def test_drag_begins_only_after_threshold_crossed(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle(threshold=5)
        cls.mouse_down(handle, 10, 100)

        cls.mouse_move(handle, 10, 103)  # within threshold
        handle.on_drag_begin.assert_not_called()
        self.assertFalse(handle.dragging)

        cls.mouse_move(handle, 10, 92)  # crosses threshold
        handle.on_drag_begin.assert_called_once_with(handle, 100)
        handle.on_drag_update.assert_called_with(handle, 92)
        self.assertTrue(handle.dragging)

    def test_drag_update_continues_after_started(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()
        cls.mouse_down(handle, 10, 100)
        cls.mouse_move(handle, 10, 90)
        cls.mouse_move(handle, 10, 80)

        self.assertEqual(handle.on_drag_update.call_count, 2)
        handle.on_drag_update.assert_called_with(handle, 80)

    def test_release_without_drag_is_click(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()
        cls.mouse_down(handle, 10, 100)

        cls.mouse_up(handle, 10, 100)

        handle.on_click.assert_called_once_with(handle)
        handle.on_drag_end.assert_not_called()
        self.assertFalse(handle.press_active)

    def test_release_after_drag_reports_hovering(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()
        cls.mouse_down(handle, 10, 100)
        cls.mouse_move(handle, 10, 90)

        cls.mouse_up(handle, 10, 90)

        handle.on_drag_end.assert_called_once_with(handle, 90, hovering=True)
        handle.on_click.assert_not_called()
        self.assertFalse(handle.dragging)

    def test_mouse_move_without_press_is_noop(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()

        cls.mouse_move(handle, 10, 90)

        handle.on_drag_begin.assert_not_called()
        handle.on_drag_update.assert_not_called()

    def test_draw_paints_only_while_dragging(self):
        cls = asset_bar_op.BL_UI_Resize_Handle
        handle = self.make_handle()

        cls.draw(handle)
        handle._draw_panel_batch.assert_not_called()

        handle.dragging = True
        cls.draw(handle)
        handle._draw_panel_batch.assert_called_once_with()


class TestAssetBarRowLimit(unittest.TestCase):
    def test_row_limit_is_based_on_visible_asset_cap(self):
        dummy = SimpleNamespace(wcount=10)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, 20)

    def test_row_limit_scales_with_narrow_layout(self):
        dummy = SimpleNamespace(wcount=4)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, 50)

    def test_row_limit_falls_back_when_wcount_is_zero(self):
        dummy = SimpleNamespace(wcount=0)
        limit = asset_bar_op.BlenderKitAssetBarOperator._get_row_limit(dummy)
        self.assertEqual(limit, asset_bar_op.ASSETBAR_MAX_VISIBLE_ASSETS)
