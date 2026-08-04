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

import ctypes
import unittest
from unittest import mock

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import clipboard_x11


class _NoSymbols:
    """Fake CDLL handle whose every attribute access raises AttributeError."""

    def __getattr__(self, name):
        raise AttributeError(name)


class ClipboardX11TestBase(unittest.TestCase):
    def setUp(self):
        # Reset the module's lazily-cached state before every test so gating and
        # connection logic is exercised from a clean slate.
        clipboard_x11._xlib = None
        clipboard_x11._display = None
        clipboard_x11._window = None
        self.addCleanup(self._reset_state)

    def _reset_state(self):
        clipboard_x11._xlib = None
        clipboard_x11._display = None
        clipboard_x11._window = None


class TestLoadXlibGating(ClipboardX11TestBase):
    def test_cached_false_returns_none(self):
        clipboard_x11._xlib = False
        self.assertIsNone(clipboard_x11._load_xlib())

    def test_cached_lib_is_returned(self):
        sentinel = object()
        clipboard_x11._xlib = sentinel
        self.assertIs(clipboard_x11._load_xlib(), sentinel)

    def test_non_linux_disables(self):
        with mock.patch.object(clipboard_x11.sys, "platform", "win32"):
            self.assertIsNone(clipboard_x11._load_xlib())
        self.assertIs(clipboard_x11._xlib, False)

    def test_linux_without_display_disables(self):
        with (
            mock.patch.object(clipboard_x11.sys, "platform", "linux"),
            mock.patch.dict(clipboard_x11.os.environ, {}, clear=True),
        ):
            self.assertIsNone(clipboard_x11._load_xlib())
        self.assertIs(clipboard_x11._xlib, False)

    def test_wayland_session_disables(self):
        env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
        with (
            mock.patch.object(clipboard_x11.sys, "platform", "linux"),
            mock.patch.dict(clipboard_x11.os.environ, env, clear=True),
        ):
            self.assertIsNone(clipboard_x11._load_xlib())
        self.assertIs(clipboard_x11._xlib, False)

    def test_libx11_not_found_disables(self):
        env = {"DISPLAY": ":0"}
        with (
            mock.patch.object(clipboard_x11.sys, "platform", "linux"),
            mock.patch.dict(clipboard_x11.os.environ, env, clear=True),
            mock.patch.object(
                clipboard_x11.ctypes, "CDLL", side_effect=OSError("nope")
            ),
        ):
            self.assertIsNone(clipboard_x11._load_xlib())
        self.assertIs(clipboard_x11._xlib, False)

    def test_missing_symbol_disables(self):
        env = {"DISPLAY": ":0"}
        with (
            mock.patch.object(clipboard_x11.sys, "platform", "linux"),
            mock.patch.dict(clipboard_x11.os.environ, env, clear=True),
            mock.patch.object(clipboard_x11.ctypes, "CDLL", return_value=_NoSymbols()),
        ):
            self.assertIsNone(clipboard_x11._load_xlib())
        self.assertIs(clipboard_x11._xlib, False)

    def test_successful_load_returns_lib(self):
        env = {"DISPLAY": ":0"}
        fake_lib = mock.MagicMock()
        with (
            mock.patch.object(clipboard_x11.sys, "platform", "linux"),
            mock.patch.dict(clipboard_x11.os.environ, env, clear=True),
            mock.patch.object(clipboard_x11.ctypes, "CDLL", return_value=fake_lib),
        ):
            self.assertIs(clipboard_x11._load_xlib(), fake_lib)
            self.assertTrue(clipboard_x11.is_available())


class TestIsAvailable(ClipboardX11TestBase):
    def test_reflects_load_xlib_none(self):
        with mock.patch.object(clipboard_x11, "_load_xlib", return_value=None):
            self.assertFalse(clipboard_x11.is_available())

    def test_reflects_load_xlib_lib(self):
        with mock.patch.object(clipboard_x11, "_load_xlib", return_value=object()):
            self.assertTrue(clipboard_x11.is_available())


class TestEnsureConnection(ClipboardX11TestBase):
    def _fake_lib(self):
        lib = mock.MagicMock()
        lib.XOpenDisplay.return_value = 111
        lib.XDefaultRootWindow.return_value = 1
        lib.XCreateSimpleWindow.return_value = 222
        lib.XInternAtom.side_effect = [10, 20, 30, 40]
        return lib

    def test_success_sets_globals(self):
        lib = self._fake_lib()
        self.assertTrue(clipboard_x11._ensure_connection(lib))
        self.assertEqual(clipboard_x11._display, 111)
        self.assertEqual(clipboard_x11._window, 222)
        self.assertEqual(clipboard_x11._atom_clipboard, 10)

    def test_already_connected_short_circuits(self):
        clipboard_x11._display = 999
        lib = mock.MagicMock()
        self.assertTrue(clipboard_x11._ensure_connection(lib))
        lib.XOpenDisplay.assert_not_called()

    def test_open_display_failure(self):
        lib = mock.MagicMock()
        lib.XOpenDisplay.return_value = 0
        self.assertFalse(clipboard_x11._ensure_connection(lib))
        self.assertIsNone(clipboard_x11._display)

    def test_window_creation_failure_closes_display(self):
        lib = self._fake_lib()
        lib.XCreateSimpleWindow.return_value = 0
        self.assertFalse(clipboard_x11._ensure_connection(lib))
        lib.XCloseDisplay.assert_called_once_with(111)
        self.assertIsNone(clipboard_x11._display)


class TestResetConnection(ClipboardX11TestBase):
    def test_reset_when_connected(self):
        clipboard_x11._display = 5
        clipboard_x11._window = 6
        lib = mock.MagicMock()
        clipboard_x11._reset_connection(lib)
        lib.XDestroyWindow.assert_called_once_with(5, 6)
        lib.XCloseDisplay.assert_called_once_with(5)
        self.assertIsNone(clipboard_x11._display)
        self.assertIsNone(clipboard_x11._window)

    def test_reset_when_not_connected_is_noop(self):
        lib = mock.MagicMock()
        clipboard_x11._reset_connection(lib)
        lib.XCloseDisplay.assert_not_called()

    def test_reset_swallows_errors(self):
        clipboard_x11._display = 5
        clipboard_x11._window = 6
        lib = mock.MagicMock()
        lib.XDestroyWindow.side_effect = RuntimeError("boom")
        clipboard_x11._reset_connection(lib)  # must not raise
        self.assertIsNone(clipboard_x11._display)


class TestReadProperty(ClipboardX11TestBase):
    def test_bad_status_returns_none(self):
        clipboard_x11._display = 1
        clipboard_x11._window = 1
        clipboard_x11._atom_prop = 1
        clipboard_x11._atom_incr = 2
        lib = mock.MagicMock()
        lib.XGetWindowProperty.return_value = 1  # non-zero X status
        self.assertIsNone(clipboard_x11._read_property(lib))


class TestGetClipboardText(ClipboardX11TestBase):
    def _fake_select(self, result):
        fake = mock.MagicMock()
        fake.select.return_value = result
        return fake

    def test_unavailable_returns_none(self):
        with mock.patch.object(clipboard_x11, "_load_xlib", return_value=None):
            self.assertIsNone(clipboard_x11.get_clipboard_text())

    def test_connection_failure_returns_none(self):
        with (
            mock.patch.object(
                clipboard_x11, "_load_xlib", return_value=mock.MagicMock()
            ),
            mock.patch.object(clipboard_x11, "_ensure_connection", return_value=False),
        ):
            self.assertIsNone(clipboard_x11.get_clipboard_text())

    def test_timeout_returns_none(self):
        lib = mock.MagicMock()
        lib.XConnectionNumber.return_value = 7
        with (
            mock.patch.object(clipboard_x11, "_load_xlib", return_value=lib),
            mock.patch.object(clipboard_x11, "_ensure_connection", return_value=True),
            mock.patch.object(clipboard_x11, "select", self._fake_select(([], [], []))),
        ):
            clipboard_x11._display = 1
            clipboard_x11._window = 1
            self.assertIsNone(clipboard_x11.get_clipboard_text(timeout=0.2))

    def test_exception_returns_none_and_resets(self):
        lib = mock.MagicMock()
        with (
            mock.patch.object(clipboard_x11, "_load_xlib", return_value=lib),
            mock.patch.object(
                clipboard_x11, "_ensure_connection", side_effect=RuntimeError("boom")
            ),
            mock.patch.object(clipboard_x11, "_reset_connection") as reset,
        ):
            self.assertIsNone(clipboard_x11.get_clipboard_text())
            reset.assert_called_once_with(lib)

    def _run_with_event(self, prop_value, read_return):
        """Drive get_clipboard_text through one SelectionNotify event."""
        lib = mock.MagicMock()
        lib.XConnectionNumber.return_value = 7
        lib.XPending.side_effect = [1, 0]
        buffer = clipboard_x11._XEventBuffer()

        def fake_next_event(_display, _ref):
            sel = ctypes.cast(
                ctypes.byref(buffer),
                ctypes.POINTER(clipboard_x11._XSelectionEvent),
            ).contents
            sel.type = clipboard_x11._SELECTION_NOTIFY
            sel.property = prop_value

        lib.XNextEvent.side_effect = fake_next_event

        with (
            mock.patch.object(clipboard_x11, "_load_xlib", return_value=lib),
            mock.patch.object(clipboard_x11, "_ensure_connection", return_value=True),
            mock.patch.object(clipboard_x11, "_XEventBuffer", lambda: buffer),
            mock.patch.object(
                clipboard_x11, "_read_property", return_value=read_return
            ),
            mock.patch.object(
                clipboard_x11, "select", self._fake_select(([7], [], []))
            ),
        ):
            clipboard_x11._display = 1
            clipboard_x11._window = 1
            return clipboard_x11.get_clipboard_text(timeout=0.5)

    def test_successful_read(self):
        self.assertEqual(
            self._run_with_event(prop_value=42, read_return="asset_base_id:x"),
            "asset_base_id:x",
        )

    def test_refused_conversion_returns_none(self):
        self.assertIsNone(self._run_with_event(prop_value=0, read_return="ignored"))

    def test_non_selection_event_then_timeout(self):
        lib = mock.MagicMock()
        lib.XConnectionNumber.return_value = 7
        lib.XPending.side_effect = [1, 0, 0]
        buffer = clipboard_x11._XEventBuffer()

        def fake_next_event(_display, _ref):
            buffer.type = clipboard_x11._SELECTION_NOTIFY + 1  # some other event

        lib.XNextEvent.side_effect = fake_next_event
        # First select() is readable (delivers the unrelated event), second
        # select() times out, so the call returns None without blocking.
        fake_select = mock.MagicMock()
        fake_select.select.side_effect = [([7], [], []), ([], [], [])]

        with (
            mock.patch.object(clipboard_x11, "_load_xlib", return_value=lib),
            mock.patch.object(clipboard_x11, "_ensure_connection", return_value=True),
            mock.patch.object(clipboard_x11, "_XEventBuffer", lambda: buffer),
            mock.patch.object(clipboard_x11, "select", fake_select),
        ):
            clipboard_x11._display = 1
            clipboard_x11._window = 1
            self.assertIsNone(clipboard_x11.get_clipboard_text(timeout=0.5))


if __name__ == "__main__":
    unittest.main()
