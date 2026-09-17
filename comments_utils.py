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

import logging

from . import client_lib, client_tasks, global_vars


bk_logger = logging.getLogger(__name__)


# Track in-flight / already-requested comment fetches so we don't hammer the
# backend when the asset bar tooltip is hovered repeatedly. Cleared on error
# so a subsequent hover can retry.
_requested_comment_ids: set = set()


### COMMENTS
def handle_get_comments_task(task: client_tasks.Task):
    """Handle incoming task which downloads comments on asset."""
    if task.status == "error":
        # allow a future hover to retry this asset
        asset_id = task.data.get("asset_id") if isinstance(task.data, dict) else None
        if asset_id is not None:
            _requested_comment_ids.discard(asset_id)
        return bk_logger.warning("failed to get comments: %s", task.message)
    if task.status == "finished":
        comments = task.result["results"]
        asset_id = task.data["asset_id"]
        store_comments_local(asset_id, comments)
        # Refresh the asset bar tooltip and any open popup card so the
        # "Loading comments..." placeholder gets replaced as soon as the
        # data arrives — without waiting for the next hover/redraw.
        try:
            from .asset_bar import asset_bar_op

            asset_bar_op.refresh_comments_for_asset(asset_id)
        except Exception as e:
            bk_logger.debug("Could not refresh asset bar comments: %s", e)
        try:
            import bpy

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass
        return


def request_comments_if_needed(asset_id, api_key=""):
    """Lazily request comments for an asset.

    Returns the cached comments if present. If they are not cached and we
    haven't already issued a request for this asset, fires one off via the
    Go client. Subsequent calls for the same asset are no-ops until the
    response (or an error) arrives, which prevents the asset bar tooltip
    from issuing one HTTP request per hover and hitting the backend
    rate-limit (100 req/min) on validator search-result pages.
    """
    cached = get_comments_local(asset_id)
    if cached is not None:
        return cached
    if asset_id in _requested_comment_ids:
        return None
    _requested_comment_ids.add(asset_id)
    try:
        client_lib.get_comments(asset_id, api_key)
    except Exception as e:
        _requested_comment_ids.discard(asset_id)
        bk_logger.warning("Requesting comments for %s failed: %s", asset_id, e)
    return None


def handle_create_comment_task(task: client_tasks.Task):
    """Handle incoming task for creating a new comment."""
    if task.status == "finished":
        return bk_logger.debug("Creating comment finished - %s", task.message)
    if task.status == "error":
        return bk_logger.warning("Creating comment failed - %s", task.message)


def handle_feedback_comment_task(task: client_tasks.Task):
    """Handle incoming task for update of feedback on comment."""
    if task.status == "finished":  # action not needed
        return bk_logger.debug("Comment feedback finished - %s", task.message)
    if task.status == "error":
        return bk_logger.warning("Comment feedback failed - %s", task.message)


def handle_mark_comment_private_task(task: client_tasks.Task):
    """Handle incoming task for marking the comment as private/public."""
    if task.status == "finished":  # action not needed
        return bk_logger.debug("Marking comment visibility finished - %s", task.message)
    if task.status == "error":
        return bk_logger.warning("Marking comment visibility failed - %s", task.message)


def store_comments_local(asset_id, comments):
    global_vars.DATA["asset comments"][asset_id] = comments


def get_comments_local(asset_id):
    return global_vars.DATA["asset comments"].get(asset_id)


### NOTIFICATIONS
def handle_notifications_task(task: client_tasks.Task):
    """Handle incoming task with notifications data."""
    if task.status == "finished":
        global_vars.DATA["bkit notifications"] = task.result
        return
    if task.status == "error":
        return bk_logger.warning("Could not load notifications: %s", task.message)


def check_notifications_read():
    """Check if all notifications were already read, and remove them if so."""
    notifications = global_vars.DATA.get("bkit notifications")
    if notifications is None:
        return True
    if notifications.get("count") == 0:
        return True

    for notification in notifications["results"]:
        if notification["unread"] == 1:
            return False

    global_vars.DATA["bkit notifications"] = None
    return True
