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

"""Timeout-bounded reading of the X11 CLIPBOARD selection.

On X11, reading the clipboard is a synchronous round-trip to whichever client
owns the CLIPBOARD selection. When that owner dies without a clipboard manager
taking over ownership, the reply never arrives and the reader blocks forever
(see issue #2244). Blender's ``window_manager.clipboard`` has no timeout, so a
blocked read freezes the whole UI.

This module reads the clipboard on our own short-lived X11 connection using the
system ``libX11`` via ``ctypes`` (no shipped binaries, no third-party
dependency) and bounds the wait with ``select()`` so it can never hang. It is
used only on a genuine X11 session: ``is_available()`` returns ``False`` on
non-Linux platforms and on Wayland sessions (where ``WAYLAND_DISPLAY`` is set,
including XWayland shims that also set ``DISPLAY``), and callers should keep
using ``window_manager.clipboard`` there.
"""

import ctypes
import logging
import os
import select
import sys
import time

bk_logger = logging.getLogger(__name__)

# X protocol constants
_SELECTION_NOTIFY = 31
_ANY_PROPERTY_TYPE = 0
_CURRENT_TIME = 0

_Atom = ctypes.c_ulong
_Window = ctypes.c_ulong
_Time = ctypes.c_ulong


class _XSelectionEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("requestor", _Window),
        ("selection", _Atom),
        ("target", _Atom),
        ("property", _Atom),
        ("time", _Time),
    ]


class _XEventBuffer(ctypes.Structure):
    # Must be at least sizeof(XEvent) (24 longs on LP64) so XNextEvent cannot
    # write past the buffer; we only read the leading ``type`` field directly.
    _fields_ = [("type", ctypes.c_int), ("pad", ctypes.c_long * 32)]


# Lazily-initialised libX11 handle: None = not tried yet, False = unavailable.
_xlib = None


def _load_xlib():
    global _xlib
    if _xlib is not None:
        return _xlib or None

    # Wayland sessions (incl. XWayland shims like xwayland-satellite, which set
    # DISPLAY) keep the real clipboard on the Wayland side, so the X11 CLIPBOARD
    # selection is empty/unrelated there. Defer to window_manager.clipboard,
    # which reads the correct clipboard and doesn't hit the X11 dead-owner hang
    # under a compositor.
    if (
        not sys.platform.startswith("linux")
        or not os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
    ):
        _xlib = False
        return None

    lib = None
    for name in ("libX11.so.6", "libX11.so"):
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        bk_logger.info("libX11 not found; using window_manager.clipboard fallback")
        _xlib = False
        return None

    try:
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XInternAtom.restype = _Atom
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XDefaultRootWindow.restype = _Window
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XCreateSimpleWindow.restype = _Window
        lib.XCreateSimpleWindow.argtypes = [
            ctypes.c_void_p,
            _Window,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        lib.XDestroyWindow.argtypes = [ctypes.c_void_p, _Window]
        lib.XConvertSelection.argtypes = [
            ctypes.c_void_p,
            _Atom,
            _Atom,
            _Atom,
            _Window,
            _Time,
        ]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XConnectionNumber.restype = ctypes.c_int
        lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
        lib.XPending.restype = ctypes.c_int
        lib.XPending.argtypes = [ctypes.c_void_p]
        lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.XGetWindowProperty.restype = ctypes.c_int
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            _Window,
            _Atom,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            _Atom,
            ctypes.POINTER(_Atom),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        lib.XFree.argtypes = [ctypes.c_void_p]
    except AttributeError as e:
        bk_logger.info("libX11 missing expected symbol (%s); using fallback", e)
        _xlib = False
        return None

    _xlib = lib
    return lib


# Cached per-process connection and window so we don't reconnect every tick.
_display = None
_window = None
_atom_clipboard = None
_atom_utf8 = None
_atom_prop = None
_atom_incr = None


def _ensure_connection(lib):
    global _display, _window
    global _atom_clipboard, _atom_utf8, _atom_prop, _atom_incr
    if _display is not None:
        return True

    display = lib.XOpenDisplay(None)
    if not display:
        return False

    root = lib.XDefaultRootWindow(display)
    window = lib.XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0)
    if not window:
        lib.XCloseDisplay(display)
        return False

    _display = display
    _window = window
    _atom_clipboard = lib.XInternAtom(display, b"CLIPBOARD", False)
    _atom_utf8 = lib.XInternAtom(display, b"UTF8_STRING", False)
    _atom_prop = lib.XInternAtom(display, b"BLENDERKIT_CLIPBOARD", False)
    _atom_incr = lib.XInternAtom(display, b"INCR", False)
    return True


def _reset_connection(lib):
    global _display, _window
    if _display is not None:
        try:
            if _window:
                lib.XDestroyWindow(_display, _window)
            lib.XCloseDisplay(_display)
        except Exception:
            pass
    _display = None
    _window = None


def _read_property(lib):
    actual_type = _Atom()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    data_ptr = ctypes.POINTER(ctypes.c_ubyte)()

    status = lib.XGetWindowProperty(
        _display,
        _window,
        _atom_prop,
        0,
        0x7FFFFFFF,
        False,
        _ANY_PROPERTY_TYPE,
        ctypes.byref(actual_type),
        ctypes.byref(actual_format),
        ctypes.byref(nitems),
        ctypes.byref(bytes_after),
        ctypes.byref(data_ptr),
    )
    if status != 0 or not data_ptr:
        return None
    try:
        if actual_type.value == 0 or actual_type.value == _atom_incr:
            return None  # empty, or an INCR chunked transfer we intentionally skip
        nbytes = nitems.value * (actual_format.value // 8)
        raw = ctypes.string_at(ctypes.cast(data_ptr, ctypes.c_void_p), nbytes)
    finally:
        lib.XFree(data_ptr)
    return raw.decode("utf-8", "replace")


def is_available():
    """True when the ctypes X11 clipboard path can be used on this platform."""
    return _load_xlib() is not None


def get_clipboard_text(timeout=0.2):
    """Return the CLIPBOARD selection as text, or None if unavailable/timed out.

    Never blocks longer than ``timeout`` seconds. A None result means "could not
    read this tick" (no owner, refused, timed out, or empty) and callers should
    simply skip; it must NOT be treated as an empty clipboard to act on.
    """
    lib = _load_xlib()
    if lib is None:
        return None

    try:
        if not _ensure_connection(lib):
            return None

        lib.XConvertSelection(
            _display,
            _atom_clipboard,
            _atom_utf8,
            _atom_prop,
            _window,
            _CURRENT_TIME,
        )
        lib.XFlush(_display)

        fd = lib.XConnectionNumber(_display)
        deadline = time.monotonic() + timeout
        event = _XEventBuffer()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                return None
            while lib.XPending(_display) > 0:
                lib.XNextEvent(_display, ctypes.byref(event))
                if event.type != _SELECTION_NOTIFY:
                    continue
                sel = ctypes.cast(
                    ctypes.byref(event), ctypes.POINTER(_XSelectionEvent)
                ).contents
                if sel.property == 0:
                    return None  # conversion refused (e.g. dead/absent owner)
                return _read_property(lib)
    except Exception as e:
        bk_logger.warning("X11 clipboard read failed: %s", e)
        _reset_connection(lib)
        return None
