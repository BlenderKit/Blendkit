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

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import bpy
import rna_keymap_ui


bk_logger = logging.getLogger(__name__)


@dataclass
class KeyMapItemDef:
    """Description of a keymap item we want to register."""

    idname: str
    type: str
    value: str
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    oskey: bool = False
    key_modifier: str = "NONE"
    properties: dict[str, object] = field(default_factory=dict)


@dataclass
class KeyMapDef:
    """Description of a keymap with its items."""

    name: str
    space_type: str
    region_type: str = "WINDOW"
    items: list[KeyMapItemDef] = field(default_factory=list)


# Default bindings we ship. Users can edit these in Preferences.
DEFAULT_KEYMAP_ITEMS: list[KeyMapItemDef] = [
    KeyMapItemDef(
        idname="view3d.run_assetbar_fix_context",
        type="SEMI_COLON",
        value="PRESS",
        properties={"keep_running": False, "do_search": False},
    ),
    # NOTE: 'R' collides with Blender's default Rotate shortcut in the 3D viewport,
    # so this binding effectively only fires in editors where 'R' is unbound (e.g. the
    # Outliner). We keep it as the shipped default; users who want to rate from the
    # viewport can rebind it to a free key in Preferences > Keymap.
    KeyMapItemDef(
        idname="wm.blenderkit_menu_rating_upload",
        type="R",
        value="PRESS",
    ),
]

DEFAULT_KEYMAPS: list[KeyMapDef] = [
    # Register into the standard "Window" keymap so Blender shows it in the main tree.
    KeyMapDef(
        name="Window",  # must be windows otherwise blender will not show it in the default keymap
        space_type="EMPTY",
        region_type="WINDOW",
        items=DEFAULT_KEYMAP_ITEMS,
    ),
]

# Store only the keymap items we create so we can clean them up without touching user overrides.
_registered_keymaps: list[
    tuple[bpy.types.KeyConfig, bpy.types.KeyMap, bpy.types.KeyMapItem]
] = []


def _keymap_has_item(km: bpy.types.KeyMap, idname: str) -> bpy.types.KeyMapItem | None:
    for item in km.keymap_items:
        if item.idname == idname:
            return item
    return None


def _find_in_keyconfig(
    keyconfig: bpy.types.KeyConfig, idname: str
) -> bpy.types.KeyMapItem | None:
    for km in keyconfig.keymaps:
        kmi = _keymap_has_item(km, idname)
        if kmi:
            return kmi
    return None


def register_keymaps(custom_keymaps: list[KeyMapDef] | None = None) -> None:
    """Register keymaps for the add-on.

    Args:
        custom_keymaps: Optional iterable of KeyMapDef if callers want to override defaults.
    """

    wm = bpy.context.window_manager
    if not wm:
        bk_logger.warning("Unable to register keymaps: no window manager available")
        return
    kc_addon = wm.keyconfigs.addon
    kc_user = wm.keyconfigs.user
    if not kc_addon:
        bk_logger.warning("Unable to register keymaps: no add-on keyconfig available")
        return
    bk_logger.debug("Registering keymaps for Blendkit add-on")

    keymaps = list(custom_keymaps) if custom_keymaps is not None else DEFAULT_KEYMAPS

    for km_def in keymaps:
        km = kc_addon.keymaps.find(
            km_def.name, space_type=km_def.space_type, region_type=km_def.region_type
        )
        if km is None:
            bk_logger.debug(
                f"Keymap {km_def.name} not found in {kc_addon.name}, creating new one"
            )
            km = kc_addon.keymaps.new(
                name=km_def.name,
                space_type=km_def.space_type,
                region_type=km_def.region_type,
            )

        for item_def in km_def.items:
            # If the user already has this binding in their keyconfig, don't recreate
            # it - re-adding the add-on default would clobber their per-item edits,
            # including a shortcut they intentionally disabled (see issue #2230).
            if kc_user and _find_in_keyconfig(kc_user, item_def.idname):
                bk_logger.debug(
                    f"User keyconfig already has binding for {item_def.idname}; leaving user override intact"
                )
                continue
            if _keymap_has_item(km, item_def.idname):
                bk_logger.debug(
                    f"Keymap {km_def.name} in {kc_addon.name} already has item {item_def.idname}, skipping"
                )
                continue
            bk_logger.debug(
                f"Adding keymap item {item_def.idname} to keymap {km_def.name} in {kc_addon.name}"
            )
            kmi = km.keymap_items.new(
                idname=item_def.idname,
                type=item_def.type,
                value=item_def.value,
                shift=item_def.shift,
                ctrl=item_def.ctrl,
                alt=item_def.alt,
                oskey=item_def.oskey,
                key_modifier=item_def.key_modifier,
            )
            for prop_name, prop_value in item_def.properties.items():
                bk_logger.debug(
                    f"Setting property {prop_name}={prop_value} on keymap item {item_def.idname} in {kc_addon.name}"
                )
                setattr(kmi.properties, prop_name, prop_value)
            _registered_keymaps.append((kc_addon, km, kmi))


def unregister_keymaps() -> None:
    if not _registered_keymaps:
        return

    for kc, km, kmi in _registered_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except RuntimeError:
            # Already removed by user; ignore.
            pass
    _registered_keymaps.clear()


def get_keymap_item(idname: str) -> bpy.types.KeyMapItem | None:
    """Return the current keymap item for the given operator.

    Prefers the user's key configuration (where edits are stored) and falls back to the
    add-on keyconfig defaults.
    """

    wm = bpy.context.window_manager
    if not wm:
        return None

    for cfg in (wm.keyconfigs.user, wm.keyconfigs.addon):
        if cfg:
            kmi = _find_in_keyconfig(cfg, idname)
            if kmi:
                return kmi
    return None


def format_keymap_item(kmi: bpy.types.KeyMapItem) -> str:
    """Return a human readable shortcut label for a KeyMapItem."""

    parts = []
    if kmi.ctrl:
        parts.append("Ctrl")
    if kmi.alt:
        parts.append("Alt")
    if kmi.shift:
        parts.append("Shift")
    if kmi.oskey:
        parts.append("Cmd")
    if kmi.key_modifier and kmi.key_modifier != "NONE":
        parts.append(kmi.key_modifier.replace("_", " ").title())
    parts.append(kmi.type.replace("_", " ").title())
    return "+".join(parts)


def get_shortcut_label(idname: str, fallback: str = "") -> str:
    """Return a formatted shortcut string for the operator if available."""

    kmi = get_keymap_item(idname)
    if not kmi:
        return fallback
    return format_keymap_item(kmi)


def _find_km_and_kmi(
    keyconfig: bpy.types.KeyConfig, idname: str
) -> tuple[bpy.types.KeyMap, bpy.types.KeyMapItem] | None:
    if not keyconfig:
        return None
    for km in keyconfig.keymaps:
        kmi = _keymap_has_item(km, idname)
        if kmi:
            return km, kmi
    return None


def draw_keymap(self, context):
    layout = self.layout
    wm = context.window_manager
    kc_addon = wm.keyconfigs.addon
    kc_user = wm.keyconfigs.user
    if not kc_addon:
        return

    box = layout.box()
    box.label(text="Blendkit Keymaps")

    for item_def in DEFAULT_KEYMAP_ITEMS:
        # Prefer user override if available, otherwise show addon default.
        entry = _find_km_and_kmi(kc_user, item_def.idname) if kc_user else None
        source_kc = kc_user if entry else kc_addon
        km, kmi = (
            entry
            if entry
            else _find_km_and_kmi(kc_addon, item_def.idname) or (None, None)
        )
        if not km or not kmi:
            continue
        rna_keymap_ui.draw_kmi([], source_kc, km, kmi, box, 0)
