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
# ##### END GPL LICENSE BLOCK #####

"""Microsoft Store Blender warning dialog.

Uses Blender's standard ``window_manager.invoke_props_dialog`` so the popup
matches the rest of the editor UI. The acceptance state is persisted in
the addon preferences as ``accepted_ms_store_warning`` and is surfaced
under "Experimental settings" so it can be reset for debugging.
"""

import logging
import os
import sys

import bpy

bk_logger = logging.getLogger(__name__)

# Top-level addon package - used to look up addon preferences.
_ADDON_PACKAGE = __package__


# ---------------------------------------------------------------------------
# Microsoft Store Blender detection
# ---------------------------------------------------------------------------


def is_microsoft_store_blender() -> bool:
    """Return True if Blender appears to be installed via the Microsoft Store.

    Microsoft Store apps live under the per-user ``WindowsApps`` folder which
    is sandboxed (read-only locations, no child process spawn). That breaks
    several Blendkit features: launching the Blendkit-Client binary from
    outside the addon, writing to the user ``blenderkit_data`` folder and
    spawning background Blender processes for thumbnails / unpacking.
    """
    if sys.platform != "win32":
        return False
    candidates = []
    try:
        candidates.append(bpy.app.binary_path or "")
    except Exception:
        pass
    candidates.append(sys.executable or "")
    try:
        candidates.append(os.path.dirname(sys.executable or ""))
    except Exception:
        pass
    for path in candidates:
        if path and "windowsapps" in path.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Microsoft Store warning gating
# ---------------------------------------------------------------------------

BLENDER_DOWNLOAD_URL = "https://www.blender.org/download/"

# Body lines shown in the dialog. Kept short so the standard popup stays
# readable at default widths.
_MS_STORE_LINES = (
    "You are running Blender installed from the Microsoft Store.",
    "This sandboxed install can break several Blendkit features:",
    "  - launching the Blendkit-Client binary",
    "  - background Blender processes (thumbnails, unpacking)",
    "  - writing into the user blenderkit_data folder",
    "",
    "If everything works for you, you can keep using Blendkit.",
    "Otherwise we recommend installing Blender from blender.org.",
)

# Guard so we do not stack multiple warning popups when the asset bar is
# repeatedly retriggered (search results, area changes, ...).
_ms_store_warning_pending = False


def _get_prefs():
    addon = bpy.context.preferences.addons.get(_ADDON_PACKAGE)
    if addon is None:
        return None
    return addon.preferences


def ms_store_warning_accepted() -> bool:
    """True if the user has already acknowledged the Microsoft Store warning."""
    prefs = _get_prefs()
    if prefs is None:
        return False
    return bool(getattr(prefs, "accepted_ms_store_warning", False))


def should_block_for_ms_store() -> bool:
    """True when we must show the warning instead of starting the asset bar."""
    if not is_microsoft_store_blender():
        return False
    return not ms_store_warning_accepted()


class BlenderKitMSStoreWarningOperator(bpy.types.Operator):
    """Warn the user that Blender was installed from the Microsoft Store."""

    bl_idname = "wm.blenderkit_ms_store_warning"
    bl_label = "Blendkit - Microsoft Store Blender detected"
    bl_options = {"REGISTER", "INTERNAL"}

    def draw(self, context):
        # local import to avoid circular import
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        layout = self.layout
        for line in _MS_STORE_LINES:
            # Empty rows render as a vertical spacer to mimic blank lines.
            layout.label(text=line if line else " ")
        row = layout.row()
        row.operator(
            "wm.url_open", text="Get Blender from blender.org", icon="URL"
        ).url = BLENDER_DOWNLOAD_URL

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        # OK button = "Proceed anyway": persist the acceptance and re-launch
        # the asset bar.
        global _ms_store_warning_pending
        _ms_store_warning_pending = False
        prefs = _get_prefs()
        if prefs is not None:
            prefs.accepted_ms_store_warning = True
        bk_logger.info("User accepted Microsoft Store warning - re-enabling asset bar.")
        try:
            bpy.ops.view3d.run_assetbar_fix_context(  # type: ignore[attr-defined]
                keep_running=True, do_search=True
            )
        except Exception:
            bk_logger.exception(
                "Could not start asset bar after accepting Microsoft Store warning"
            )
        return {"FINISHED"}

    def cancel(self, context):
        global _ms_store_warning_pending
        _ms_store_warning_pending = False
        bk_logger.info(
            "User dismissed Microsoft Store warning - asset bar not started."
        )


def show_ms_store_warning() -> None:
    """Invoke the standard Blender props-dialog popup for the MS Store warning."""
    global _ms_store_warning_pending
    if _ms_store_warning_pending:
        return
    _ms_store_warning_pending = True
    try:
        bpy.ops.wm.blenderkit_ms_store_warning("INVOKE_DEFAULT")  # type: ignore[attr-defined]
    except Exception:
        _ms_store_warning_pending = False
        bk_logger.exception("Could not invoke Microsoft Store warning dialog")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (BlenderKitMSStoreWarningOperator,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
