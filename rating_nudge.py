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

"""Nudges power users to rate assets they recently downloaded.

After a qualifying user downloads an asset that does not have enough ratings yet,
we wait a while and then automatically open the regular rating popup
(``wm.blenderkit_menu_rating_upload``) with a friendly message.

Two tiers exist:
* Casual power users (lots of downloads): rarely nudged.
* Creators (users who have uploaded at least one asset): nudged more often and
  after fewer downloads, since their feedback is especially valuable.

Download events are tracked locally only (in ``config_dir/rating_nudge.json``);
nothing about this is sent to the server.
"""

import json
import logging
import os
import time

import bpy

from . import client_lib, global_vars, paths, tasks_queue, utils


bk_logger = logging.getLogger(__name__)

# --- Tunable thresholds (edit here) -----------------------------------------
# Casual power users.
CASUAL_MIN_WEEKLY_DOWNLOADS = 50
CASUAL_COOLDOWN_DAYS = 3
# Creators (users who have uploaded at least one asset).
CREATOR_MIN_WEEKLY_DOWNLOADS = 5
CREATOR_COOLDOWN_DAYS = 1
# Common.
NUDGE_DELAY_MINUTES = 30  # how long after download before we ask
MAX_RATINGS_TO_NUDGE = 3  # only nudge for assets with fewer quality ratings than this
DOWNLOAD_WINDOW_DAYS = 7  # window for "downloads per week"; also prunes the store
TIMER_INTERVAL = 60.0  # seconds between checks

NUDGE_MESSAGE = "How do you like this asset? Please help us by rating."

# Set just before invoking the rating operator from a nudge, so the operator can
# pick up the specific (possibly not currently-selected) asset to rate.
# Read in ratings.FastRateMenu.execute().
# ---------------------------------------------------------------------------

DAY = 24 * 3600


def _store_path() -> str:
    """Path to the local JSON store of download events."""
    config_dir = paths.get_config_dir_path()
    return os.path.abspath(os.path.join(config_dir, "rating_nudge.json"))


def load_store() -> dict:
    """Load the local store. Returns a dict with 'downloads' and 'last_nudge_time'."""
    path = _store_path()
    if not os.path.exists(path):
        return {"downloads": [], "last_nudge_time": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        bk_logger.warning("Failed to read rating nudge store: %s", e)
        return {"downloads": [], "last_nudge_time": 0}
    data.setdefault("downloads", [])
    data.setdefault("last_nudge_time", 0)
    return data


def save_store(data: dict):
    """Persist the store to disk."""
    try:
        paths.ensure_config_dir_exists()
        with open(_store_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        bk_logger.warning("Failed to save rating nudge store: %s", e)


def _prune(downloads: list, now: float) -> list:
    """Drop download events older than the tracking window."""
    cutoff = now - DOWNLOAD_WINDOW_DAYS * DAY
    return [d for d in downloads if d.get("time", 0) >= cutoff]


def record_download(asset_data: dict):
    """Record that an asset was just downloaded. Called from download.append_asset()."""
    try:
        now = time.time()
        rc = asset_data.get("ratingsCount") or {}
        store = load_store()
        store["downloads"] = _prune(store.get("downloads", []), now)
        store["downloads"].append(
            {
                "time": now,
                "id": asset_data.get("id", ""),
                "name": asset_data.get("name", ""),
                "asset_type": asset_data.get("assetType", ""),
                "ratings_quality": rc.get("quality"),
                "nudged": False,
                # Full asset_data copy so the popup can render without a fresh fetch.
                "asset_data": asset_data,
            }
        )
        save_store(store)
    except Exception:
        bk_logger.exception("Failed to record download for rating nudge")


def _is_creator() -> bool:
    """User has uploaded at least one asset (sum of their asset file sizes > 0)."""
    profile = global_vars.BKIT_PROFILE
    if not profile:
        return False
    return (getattr(profile, "sumAssetFilesSize", 0) or 0) > 0


def _thresholds():
    """Return (min_weekly_downloads, cooldown_seconds) for the current user tier."""
    if _is_creator():
        return CREATOR_MIN_WEEKLY_DOWNLOADS, CREATOR_COOLDOWN_DAYS * DAY
    return CASUAL_MIN_WEEKLY_DOWNLOADS, CASUAL_COOLDOWN_DAYS * DAY


def _already_rated(asset_id: str) -> bool:
    rating = global_vars.RATINGS.get(asset_id)
    return rating is not None and rating.quality is not None


def _is_eligible(entry: dict) -> bool:
    """Whether a single download entry can be nudged right now."""
    asset_data = entry.get("asset_data") or {}
    if not asset_data:
        return False
    # Skip assets that can't be downloaded/rated (e.g. Full-plan without subscription).
    if not asset_data.get("canDownload", True):
        return False
    # Skip assets the user owns.
    if utils.user_is_owner(asset_data=asset_data):
        return False
    # Only assets that don't have enough ratings yet.
    rc = asset_data.get("ratingsCount") or {}
    quality_count = rc.get("quality") or 0
    if quality_count >= MAX_RATINGS_TO_NUDGE:
        return False
    # Skip assets the user already rated.
    if _already_rated(asset_data.get("id", "")):
        return False
    return True


def rating_nudge_timer():
    """Periodic check that decides whether to open the rating popup."""
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        if not getattr(prefs, "rating_nudge_enabled", True):
            return TIMER_INTERVAL
        if not utils.user_logged_in():
            return TIMER_INTERVAL

        now = time.time()
        store = load_store()
        downloads = _prune(store.get("downloads", []), now)
        store["downloads"] = downloads  # keep pruned

        # Nothing to do if no downloads tracked yet.
        if not downloads:
            return TIMER_INTERVAL

        min_weekly, cooldown = _thresholds()

        # Respect the per-tier cooldown.
        if now - store.get("last_nudge_time", 0) < cooldown:
            save_store(store)
            return TIMER_INTERVAL

        # Power-user / creator gate: enough downloads within the window.
        if len(downloads) < min_weekly:
            save_store(store)
            return TIMER_INTERVAL

        # Find the oldest un-nudged, eligible asset whose delay has elapsed.
        delay = NUDGE_DELAY_MINUTES * 60
        candidate = None
        for entry in sorted(downloads, key=lambda d: d.get("time", 0)):
            if entry.get("nudged"):
                continue
            if now - entry.get("time", 0) < delay:
                continue
            if _is_eligible(entry):
                candidate = entry
                break

        if candidate is None:
            save_store(store)
            return TIMER_INTERVAL

        candidate["nudged"] = True
        store["last_nudge_time"] = now
        save_store(store)

        _enqueue_popup(candidate["asset_data"])
    except Exception:
        bk_logger.exception("rating_nudge_timer failed")
    return TIMER_INTERVAL


def _enqueue_popup(asset_data: dict):
    """Schedule the rating popup to open on the main thread via the task queue."""
    # NOTE: do not use only_last=True here - that code path in tasks_queue indexes
    # task.arguments[0] and [1], and our task has a single argument.
    tasks_queue.add_task(
        (_show_rating_popup, (asset_data,)),
        wait=0,
    )


def _ensure_thumbnail_downloaded(asset_data: dict) -> bool:
    """Ensure the large thumbnail file for asset_data exists in the search temp dir.

    The nudge asset is outside the current search and its large thumbnail may never
    have been fetched (only small asset-bar thumbnails download automatically), so we
    download it synchronously via the Client. Returns True if the file is present.
    """
    from . import search, ui

    tpath = ui.get_large_thumbnail_path(asset_data)
    if not tpath:
        return False
    if os.path.exists(tpath):
        global_vars.DATA["images available"][tpath] = True
        return True
    url = search.get_large_thumbnail_url(asset_data)
    if not url:
        return False
    try:
        api_key = bpy.context.preferences.addons[__package__].preferences.api_key
        client_lib.blocking_file_download(url, tpath, api_key)
    except Exception:
        bk_logger.exception("Failed to download rating nudge thumbnail")
        return False
    ready = os.path.exists(tpath)
    if ready:
        global_vars.DATA["images available"][tpath] = True
    return ready


def _show_rating_popup(asset_data: dict):
    """Open the rating popup for a specific asset with the nudge message."""
    from . import ratings

    fake_context = utils.get_fake_context(bpy.context)
    if not fake_context.get("region"):
        # No VIEW_3D area available; skip silently, try again on a later download.
        return

    # The nudge asset is outside the current search, so its large thumbnail may not
    # be cached yet - fetch it now so the popup doesn't show a "Loading..." placeholder.
    _ensure_thumbnail_downloaded(asset_data)

    ratings.nudge_asset_data = asset_data
    try:
        if bpy.app.version < (4, 0, 0):
            bpy.ops.wm.blenderkit_menu_rating_upload(
                fake_context,
                "INVOKE_DEFAULT",
                asset_id=asset_data.get("id", ""),
                asset_name=asset_data.get("name", ""),
                asset_type=asset_data.get("assetType", ""),
                message=NUDGE_MESSAGE,
                from_nudge=True,
            )
        else:
            with bpy.context.temp_override(**fake_context):
                bpy.ops.wm.blenderkit_menu_rating_upload(
                    "INVOKE_DEFAULT",
                    asset_id=asset_data.get("id", ""),
                    asset_name=asset_data.get("name", ""),
                    asset_type=asset_data.get("assetType", ""),
                    message=NUDGE_MESSAGE,
                    from_nudge=True,
                )
    except Exception:
        bk_logger.exception("Failed to open rating nudge popup")
