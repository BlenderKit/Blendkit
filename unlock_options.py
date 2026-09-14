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

"""Copy options for the premium-asset unlock popup.

Provides the header, message and button text shown when a user opens a Full
Plan asset. Several wordings are offered and one is picked per session; the
selected option's identifier is passed along to the server.

Options are defined locally for now. A server endpoint may later provide them
as JSON with the same fields; only ``_load_variants`` needs to change.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from . import client_lib

bk_logger = logging.getLogger(__name__)

LOCKED_ASSET_EVENT = "locked_asset_clicked"


def report_locked_asset_click(
    asset_data: dict, placement: str, variant_id: str | None
) -> None:
    """Telemetry for an attempt to use a locked asset (a drag, or the unlock button).

    Goes through Blendkit-Client's optional /report_event route, so it is covered by
    the "Send usage data" preference. Asset ids make locked assets comparable by
    demand and let the web side follow up on real interest; ``placement`` and
    ``variant_id`` mirror the unlock link's UTM tags so encounters and click-throughs
    share one vocabulary.
    """
    client_lib.report_event(
        LOCKED_ASSET_EVENT,
        {
            "asset_base_id": asset_data.get("assetBaseId"),
            "asset_id": asset_data.get("id"),
            "asset_type": asset_data.get("assetType"),
            "placement": placement,
            "variant": variant_id,
        },
    )


@dataclass(frozen=True)
class UnlockVariant:
    """A single copy option for the unlock popup.

    ``colors`` is advisory: Blender's native popup has very limited color
    control, so it is kept for a future custom renderer and for reading the
    optional server payload. ``identifier`` labels the option and is passed to
    the server.
    """

    identifier: str
    header: str
    message: str
    button_text: str = "Unlock all assets"
    colors: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "UnlockVariant":
        """Build an option from a JSON-like dict."""
        return cls(
            identifier=str(data["identifier"]),
            header=data.get("header", ""),
            message=data.get("message", ""),
            button_text=data.get("button_text") or "Unlock all assets",
            colors=data.get("colors"),
        )


# Locally defined copy options for the unlock popup.
_HARDCODED_VARIANTS: tuple[UnlockVariant, ...] = (
    UnlockVariant(
        identifier="support",
        header="This asset is included in Full Plan.",
        message="Unlock all assets\n"
        "and support creators & open-source\n"
        "by subscribing.",
        button_text="Get Full Plan",
    ),
    UnlockVariant(
        identifier="now",
        header="This asset is included in Full Plan.",
        message="Unlock all assets\n"
        "Support creators & open-source\n"
        "Subscribe now",
        button_text="Get Full Plan",
    ),
    UnlockVariant(
        identifier="join",
        header="Unlock this asset with the Full Plan.",
        message="Join thousands of artists.\n"
        "Your subscription funds the creators\n"
        "and keeps Blendkit open-source.",
        button_text="Get Full Plan",
    ),
)

# Last option shown, used to avoid repeating it on the next popup.
_last_variant: UnlockVariant | None = None


def _load_variants() -> list[UnlockVariant]:
    """Return the available copy options.

    Reads from the local list for now. To source options from the server,
    change this to build :class:`UnlockVariant` instances via ``from_dict``.
    """
    return list(_HARDCODED_VARIANTS)


def get_unlock_variant() -> UnlockVariant:
    """Return a copy option for the unlock popup, different each time it shows."""
    global _last_variant
    variants = _load_variants()
    choices = [v for v in variants if v is not _last_variant] or variants
    _last_variant = random.choice(choices)
    bk_logger.debug("Selected unlock option: %s", _last_variant.identifier)
    return _last_variant
