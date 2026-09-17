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

"""Pure-data layout description for the BlenderKit asset bar.

This module owns the geometric layout math. It has no dependency on
``bpy`` and no side effects: feed it inputs, get back a ``LayoutSpec``.

The asset bar operator collects inputs (region size, UI scale, search
results size, sub-section heights from filter chips and manufacturer
chips) and calls :func:`build_layout_spec`. The resulting ``LayoutSpec``
holds every cached pixel value the operator needs to render and
hit-test the bar. Because it is a pure function, we can later cache by
input signature and skip recomputation on frames where nothing changed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class LayoutInputs:
    """Everything :func:`build_layout_spec` needs to compute geometry.

    Kept as a frozen dataclass so it can act as a cache key (its
    ``__eq__``/``__hash__`` are derived from the field tuple).
    """

    # Region / window
    region_width: int
    region_height: int
    window_width: int

    # Side panel widths visible inside the area (already adjusted for
    # ``preferences.system.use_region_overlap``).
    ui_region_width: int
    tools_region_width: int

    # UI scale factor (Blender UI scale).
    ui_scale: float

    # Asset bar offset from area edges (panel-defined).
    bar_x_offset: float
    bar_y_offset: float

    # User preferences inputs.
    thumb_size_pref: int
    assetbar_expanded: bool
    maximized_assetbar_rows: int

    # Search results count (None when no search has run yet).
    search_results_count: Optional[int]

    # Identity of the search results list (``id(list)``, or ``0`` when
    # there are no results). Two different result lists with equal
    # length must not produce a cache hit, so the operator passes the
    # list identity here. ``id()`` is acceptable because each new search
    # builds a new list and the prior list is replaced atomically.
    search_results_id: int

    # Heights (in pixels) of optional sub-sections that push the grid down.
    active_filter_height: int
    manufacturer_section_height: int


@dataclass(frozen=True)
class LayoutSpec:
    """Computed asset-bar geometry.

    All values are pixel coordinates (Blender region space). Field names
    match the legacy ``self.<attr>`` names on the operator so the
    operator can apply the spec via :meth:`apply_to`.
    """

    # UI scale factor used to derive these values.
    ui_scale_factor: float

    # Per-element pixel sizes.
    button_margin: int
    assetbar_margin: int
    thumb_size: int
    button_size: int
    other_button_size: int
    filter_button_height: int
    filter_button_text_size: int
    free_button_margin: int
    free_button_text_size: int
    icon_size: int
    validation_icon_margin: int

    # Bar position and size.
    bar_x: int
    bar_y: int
    bar_end: int
    bar_width: int
    base_bar_height: int
    bar_height: int

    # Grid dimensions.
    wcount: int
    hcount: int
    max_hcount: int
    max_wcount: int

    # Convenience: keep the inputs around so callers can compare
    # signatures cheaply ("did anything that affects layout change?").
    inputs: LayoutInputs

    def apply_to(self, target) -> None:
        """Copy fields onto ``target`` (typically the operator instance).

        Backwards-compat shim: existing code reads ``self.bar_x``,
        ``self.button_size``, etc. directly. Until those reads are
        migrated to ``self._layout.<attr>``, the operator keeps working
        if we mirror every field onto the instance.
        """
        target._ui_scale_factor = self.ui_scale_factor
        target.button_margin = self.button_margin
        target.assetbar_margin = self.assetbar_margin
        target.thumb_size = self.thumb_size
        target.button_size = self.button_size
        target.other_button_size = self.other_button_size
        target.filter_button_height = self.filter_button_height
        target.filter_button_text_size = self.filter_button_text_size
        target.free_button_margin = self.free_button_margin
        target.free_button_text_size = self.free_button_text_size
        target.icon_size = self.icon_size
        target.validation_icon_margin = self.validation_icon_margin
        target.bar_x = self.bar_x
        target.bar_y = self.bar_y
        target.bar_end = self.bar_end
        target.bar_width = self.bar_width
        target.base_bar_height = self.base_bar_height
        target.bar_height = self.bar_height
        target.wcount = self.wcount
        target.hcount = self.hcount
        target.max_hcount = self.max_hcount
        target.max_wcount = self.max_wcount


def build_layout_spec(inputs: LayoutInputs) -> LayoutSpec:
    """Pure function: compute a :class:`LayoutSpec` from inputs.

    No reads from ``bpy``, no widget side effects. Mirrors the math
    previously inlined in ``BlenderKitAssetBarOperator.update_assetbar_sizes``.
    """
    scale = inputs.ui_scale

    # Element sizes (the historical ``button_margin = round(0 * scale)``
    # is preserved on purpose - changing it would shift hit-test rects).
    button_margin = int(round(0 * scale))
    assetbar_margin = int(round(2 * scale))
    thumb_size = int(round(inputs.thumb_size_pref * scale))
    button_size = int(2 * button_margin + thumb_size)

    other_button_size = int(round(30 * scale))
    filter_button_height = int(round(25 * scale))
    filter_button_text_size = int(round(20 * scale))

    free_button_margin = int(button_size * 0.05)
    free_button_text_size = int(other_button_size * 0.4)

    icon_size = int(round(24 * scale))
    validation_icon_margin = int(round(3 * scale))

    # Horizontal placement.
    bar_x = int(inputs.tools_region_width + button_margin + inputs.bar_x_offset * scale)
    base_bar_y = int(button_margin + inputs.bar_y_offset * scale)

    bar_end = int(inputs.ui_region_width + 180 + other_button_size)
    bar_width = max(1, int(inputs.region_width - bar_x - bar_end))

    # Quad view / very small regions can squeeze the bar below a single
    # thumb width. Keep the math stable so buttons don't vanish.
    effective_bar_width = max(bar_width, button_size)
    wcount = max(1, math.floor(effective_bar_width / button_size))

    max_hcount = math.floor(max(inputs.region_width, inputs.window_width) / button_size)
    max_wcount = inputs.maximized_assetbar_rows

    # Filter chips push the bar down.
    bar_y = base_bar_y + (inputs.active_filter_height or 0)

    # Row count depends on expanded state and available vertical space.
    sr_count = inputs.search_results_count
    if sr_count is not None and wcount > 0:
        if inputs.assetbar_expanded:
            max_rows = inputs.maximized_assetbar_rows
            available_height = (
                inputs.region_height - bar_y - 2 * assetbar_margin - other_button_size
            )
            max_rows_by_height = math.floor(available_height / button_size)
            max_rows = (
                min(max_rows, max_rows_by_height) if max_rows_by_height > 0 else 1
            )
        else:
            max_rows = 1
        hcount = min(max_rows, math.ceil(sr_count / wcount))
        hcount = max(hcount, 1)
    else:
        hcount = 1

    base_bar_height = button_size * hcount + 2 * assetbar_margin
    bar_height = base_bar_height + inputs.manufacturer_section_height

    return LayoutSpec(
        ui_scale_factor=scale,
        button_margin=button_margin,
        assetbar_margin=assetbar_margin,
        thumb_size=thumb_size,
        button_size=button_size,
        other_button_size=other_button_size,
        filter_button_height=filter_button_height,
        filter_button_text_size=filter_button_text_size,
        free_button_margin=free_button_margin,
        free_button_text_size=free_button_text_size,
        icon_size=icon_size,
        validation_icon_margin=validation_icon_margin,
        bar_x=bar_x,
        bar_y=bar_y,
        bar_end=bar_end,
        bar_width=bar_width,
        base_bar_height=base_bar_height,
        bar_height=bar_height,
        wcount=wcount,
        hcount=hcount,
        max_hcount=max_hcount,
        max_wcount=max_wcount,
        inputs=inputs,
    )


def collect_side_panel_widths(area, use_region_overlap: bool) -> Tuple[int, int]:
    """Read UI/TOOLS region widths from a Blender area.

    Kept here so the operator does not have to repeat the loop. Returns
    ``(ui_region_width, tools_region_width)`` already adjusted for
    region overlap.
    """
    multiplier = 1 if use_region_overlap else 0
    ui_width = 0
    tools_width = 0
    for r in area.regions:
        if r.type == "UI":
            ui_width = r.width * multiplier
        elif r.type == "TOOLS":
            tools_width = r.width * multiplier
    return int(ui_width), int(tools_width)
