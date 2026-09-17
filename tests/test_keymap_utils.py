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

import types
import unittest

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module for the relative import below.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import keymap_utils


def _kmi(
    type="R", ctrl=False, alt=False, shift=False, oskey=False, key_modifier="NONE"
):
    """Build a minimal stand-in for a bpy KeyMapItem."""
    return types.SimpleNamespace(
        type=type,
        ctrl=ctrl,
        alt=alt,
        shift=shift,
        oskey=oskey,
        key_modifier=key_modifier,
    )


class TestFormatKeymapItem(unittest.TestCase):
    def test_plain_key(self):
        self.assertEqual(keymap_utils.format_keymap_item(_kmi(type="R")), "R")

    def test_multi_word_key_is_title_cased(self):
        self.assertEqual(
            keymap_utils.format_keymap_item(_kmi(type="SEMI_COLON")), "Semi Colon"
        )

    def test_modifier_ordering(self):
        # Order is Ctrl, Alt, Shift, Cmd, key_modifier, then the key itself.
        kmi = _kmi(type="R", ctrl=True, alt=True, shift=True, oskey=True)
        self.assertEqual(keymap_utils.format_keymap_item(kmi), "Ctrl+Alt+Shift+Cmd+R")

    def test_key_modifier_included(self):
        kmi = _kmi(type="A", ctrl=True, key_modifier="LEFT_CTRL")
        self.assertEqual(keymap_utils.format_keymap_item(kmi), "Ctrl+Left Ctrl+A")

    def test_none_key_modifier_excluded(self):
        self.assertEqual(
            keymap_utils.format_keymap_item(_kmi(type="B", key_modifier="NONE")), "B"
        )


class TestGetShortcutLabel(unittest.TestCase):
    def test_unknown_idname_returns_fallback(self):
        self.assertEqual(
            keymap_utils.get_shortcut_label("wm.definitely_not_an_operator", "N/A"),
            "N/A",
        )

    def test_unknown_idname_default_fallback_is_empty(self):
        self.assertEqual(
            keymap_utils.get_shortcut_label("wm.definitely_not_an_operator"), ""
        )


class TestKeymapLookupHelpers(unittest.TestCase):
    def _fake_keyconfig(self, *keymaps):
        return types.SimpleNamespace(keymaps=list(keymaps))

    def _fake_keymap(self, *idnames):
        items = [types.SimpleNamespace(idname=i) for i in idnames]
        return types.SimpleNamespace(keymap_items=items)

    def test_keymap_has_item_found(self):
        km = self._fake_keymap("a.op", "b.op")
        found = keymap_utils._keymap_has_item(km, "b.op")
        self.assertIsNotNone(found)
        self.assertEqual(found.idname, "b.op")

    def test_keymap_has_item_missing(self):
        km = self._fake_keymap("a.op")
        self.assertIsNone(keymap_utils._keymap_has_item(km, "z.op"))

    def test_find_in_keyconfig_searches_all_keymaps(self):
        kc = self._fake_keyconfig(
            self._fake_keymap("a.op"), self._fake_keymap("b.op", "c.op")
        )
        found = keymap_utils._find_in_keyconfig(kc, "c.op")
        self.assertIsNotNone(found)
        self.assertEqual(found.idname, "c.op")

    def test_find_in_keyconfig_missing(self):
        kc = self._fake_keyconfig(self._fake_keymap("a.op"))
        self.assertIsNone(keymap_utils._find_in_keyconfig(kc, "z.op"))


class TestDefaultKeymaps(unittest.TestCase):
    def test_default_items_cover_expected_operators(self):
        idnames = {item.idname for item in keymap_utils.DEFAULT_KEYMAP_ITEMS}
        self.assertIn("view3d.run_assetbar_fix_context", idnames)
        self.assertIn("wm.blenderkit_menu_rating_upload", idnames)

    def test_rating_default_is_r_press(self):
        rating = next(
            item
            for item in keymap_utils.DEFAULT_KEYMAP_ITEMS
            if item.idname == "wm.blenderkit_menu_rating_upload"
        )
        self.assertEqual(rating.type, "R")
        self.assertEqual(rating.value, "PRESS")

    def test_registered_into_window_keymap(self):
        # Must be the built-in "Window" keymap, otherwise Blender won't surface
        # the shortcut in the default keymap tree.
        self.assertTrue(any(km.name == "Window" for km in keymap_utils.DEFAULT_KEYMAPS))


if __name__ == "__main__":
    unittest.main()
