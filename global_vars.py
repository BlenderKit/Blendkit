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

from logging import DEBUG, INFO, WARN
from os import environ
from subprocess import Popen
from typing import Any, Optional

try:
    from . import datas
except ImportError:
    # for release CI action
    import datas  # type: ignore

CLIENT_VERSION = "v1.12"
"""Pinned Blendkit-Client MINOR series (vX.Y) the add-on is API-compatible with.
Only the minor version is pinned here; the exact patch (vX.Y.Z) of the bundled
binary is resolved at build time from the matching GitHub release and recorded in
``client/RESOLVED_VERSION``. bk_client auto-bumps the patch on each PR, so pinning
only the minor keeps this stable and avoids churn. Bump this only on a breaking
API change (which also bumps the Client's minor/major)."""
CLIENT_ACCESSIBLE = False
"""Is Client accessible? Can add-on access it and call stuff which uses it?"""
CLIENT_RUNNING = False
"""Just  for on_startup_client_online_timer()."""
CLIENT_FAILED_REPORTS = 0
"""Number of failed requests to get reports from the Blendkit-Client. If too many, something is wrong."""
CLIENT_PORTS = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
"""Ports are ordered during the start, and later after malfunction."""

DATA: dict = {  # TODO: move these
    "images available": {},
    "history steps": {},
    "bkit notifications": None,
    "asset comments": {},
}

TABS: dict[str, Any] = {
    "active_tab": 0,  # Index of currently active tab
    "tabs": [  # List of all tabs
        {
            "name": "Default",  # Tab name
            "history": [],  # List of history steps
            "history_index": -1,  # Current position in history
            "active_filters": [],  # Per-tab active filter chips
        }
    ],
}

RATINGS: dict[str, datas.AssetRating] = {}
BKIT_PROFILE: datas.MineProfile = datas.MineProfile()
"""Profile of the current user."""
BKIT_AUTHORS: dict[int, datas.UserProfile] = {}
"""All loaded profiles of other users. Current user is also present in stripped down version. Key is the UserProfile.id."""

LOGGING_LEVEL_BLENDKIT = INFO

# read special DEBUG env var to set logging level to DEBUG
if environ.get("BLENDKIT_DEBUG", "0") == "1":
    LOGGING_LEVEL_BLENDKIT = DEBUG

LOGGING_LEVEL_IMPORTED = WARN
PREFS = {}

SERVER = environ.get(
    "BLENDKIT_SERVER", environ.get("BLENDERKIT_SERVER", "https://www.blendkit.com")
)
DISCORD_INVITE_URL = "https://discord.gg/tCKyjFMRar"

TIPS = [
    (
        "You can disable tips in the add-on preferences.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#preferences",
    ),
    ("Ratings help us distribute funds to creators.", f"{SERVER}/docs/rating/"),
    (
        "Creators also gain credits for free assets from subscribers.",
        f"{SERVER}/docs/fair-share/",
    ),
    (
        "Click on or drag a model or material into the scene to link or append it.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage",
    ),
    (
        "Press ESC while dragging a model or material to cancel the action and avoid any download.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#cancel-drag-and-drop",
    ),
    (
        "During drag-and-drop, rotate the dragged asset's outline box by 90 degrees using the mouse wheel.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#rotate-asset",
    ),
    (
        "Right click in the asset bar for a detailed asset card.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation",
    ),
    (
        "Use Append in import settings if you want to edit downloaded objects.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings",
    ),
    (
        "Go to import settings to set default texture resolution.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#import-settings",
    ),
    (
        "Please rate responsively and plentifully. This helps us distribute rewards to the authors.",
        f"{SERVER}/docs/rating/",
    ),
    (
        "All materials are free.",
        f"{SERVER}/asset-gallery?query=category_subtree:material%20order:-created",
    ),
    ("Storage for public assets is unlimited.", f"{SERVER}/become-creator/"),
    (
        "Locked models are available if you subscribe to Full plan.",
        f"{SERVER}/plans/pricing/",
    ),
    ("Login to upload your own models, materials or brushes.", f"{SERVER}/"),
    (
        "Use 'A' key over the asset bar to search assets by the same author.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#basic-usage",
    ),
    (
        "Use semicolon - ; to hide or show the AssetBar.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    ("Support the authors by subscribing to Full plan.", f"{SERVER}/plans/pricing/"),
    (
        "Use the 'P' key over the asset bar to open the Author's profile on BlenderKit.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'W' key over the asset bar to open Author's personal webpage.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'R' key over the asset bar for fast rating of assets.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'X' key over the asset bar to delete the asset from your hard drive.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'S' key over the asset bar to search similar assets.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'C' key over the asset bar to search assets in same subcategory.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use the 'B' key over the asset bar to bookmark the asset.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Get latest experimental versions of add-on by enabling prerelases in preferences.",
        "",
    ),
    (
        "On Discord? Jump into assets & add-on talks.",
        DISCORD_INVITE_URL,
    ),
    (
        "Right-click on the downloaded asset to rate, bookmark and more in the 'Selected Model' submenu.",
        "",
    ),
    (
        "Use Ctrl+T to open a new tab, Ctrl+W to close the current tab in the asset bar.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Navigate between tabs with Ctrl+Tab (next) and Ctrl+Shift+Tab (previous).",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Jump directly to a specific tab using Ctrl+1 through Ctrl+9 in the asset bar.",
        "https://github.com/BlenderKit/blenderkit/wiki/BlenderKit-add-on-documentation#assetbar",
    ),
    (
        "Use keys 1 and 2 to toggle photo thumbnail over printable assets in the asset bar.",
        "",
    ),
    (
        "Use keys [ and ] to toggle between normal and photo thumbnail over printable assets.",
        "",
    ),
]
VERSION = [0, 0, 0, 0]  # filled in register()

client_process: Optional[Popen] = None
"""Holds return value of subprocess.Popen() which starts the Blendkit-Client."""
