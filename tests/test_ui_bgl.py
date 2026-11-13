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

import unittest
from types import SimpleNamespace
from unittest.mock import patch


# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module for the relative imports below.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import ui_bgl


class _FakeGpuState:
    """Depth state as left behind by another add-on's draw handler."""

    def __init__(self):
        self.depth_test = "LESS"
        self.depth_mask = True

    def depth_test_get(self):
        return self.depth_test

    def depth_test_set(self, mode):
        self.depth_test = mode

    def depth_mask_get(self):
        return self.depth_mask

    def depth_mask_set(self, value):
        self.depth_mask = value


class TestOverlayDepthStateGuard(unittest.TestCase):
    def setUp(self):
        self.state = _FakeGpuState()
        patcher = patch.object(ui_bgl, "gpu", SimpleNamespace(state=self.state))
        patcher.start()
        self.addCleanup(patcher.stop)

    def current(self):
        return (self.state.depth_test, self.state.depth_mask)

    def test_disables_inherited_depth_test_and_restores_it(self):
        with ui_bgl.overlay_depth_state_guard():
            self.assertEqual(self.current(), ("NONE", False))
        self.assertEqual(self.current(), ("LESS", True))

    def test_restores_state_when_decorated_draw_callback_raises(self):
        seen = []

        @ui_bgl.overlay_depth_state_guard()
        def draw_callback():
            seen.append(self.current())
            raise RuntimeError("draw failed")

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                draw_callback()
            self.assertEqual(self.current(), ("LESS", True))
        self.assertEqual(seen, [("NONE", False), ("NONE", False)])


if __name__ == "__main__":
    unittest.main()
