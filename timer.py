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
import os
import queue
import time
import requests

import bpy

from .asset_bar import asset_bar_op
from . import (
    addon_updater_ops,
    bg_blender,
    bkit_oauth,
    categories,
    client_lib,
    client_tasks,
    client_thread,
    comments_utils,
    disclaimer_op,
    download,
    global_vars,
    persistent_preferences,
    rating_nudge,
    ratings_utils,
    reports,
    search,
    tasks_queue,
    ui_bgl,
    upload,
    utils,
)


bk_logger = logging.getLogger(__name__)
reports_queue: queue.Queue = queue.Queue()
pending_tasks = (
    list()
)  # pending tasks are tasks that were not parsed correctly and should be tried to be parsed later.

# Max wall-clock time (seconds) spent building thumbnail GPU textures per timer
# step. A search can complete many thumbnail downloads within one poll
# interval; building every GPU texture in a single step blocks the main thread
# (measured 480-650 ms bursts -> visible viewport stutter). We process finished
# thumbnails only up to this budget and defer the rest to the next step, so the
# work is spread across steps. Lower it for smoother frames; raise it to load
# thumbnails faster at the cost of slightly bigger hitches.
THUMBNAIL_BUILD_TIME_BUDGET = 0.1

# Minimum seconds between Blendkit-Client (re)start attempts. Without this a
# single transient poll timeout on a busy-but-alive Client would spawn a fresh
# Client every poll; each duplicate then dies on WSAEADDRINUSE (the old process
# still owns the port), producing a 10+/minute respawn loop that pins the CPU
# and makes Blender appear to hang. This acts as a simple circuit breaker.
CLIENT_RESTART_MIN_INTERVAL = 5.0
_last_client_start_attempt = 0.0


def _maybe_start_client(force: bool = False) -> bool:
    """Start the Blendkit-Client, but only when a (re)start is actually warranted.

    Guards against the respawn loop by refusing to spawn when either:
      * a Client subprocess we launched is still alive (merely slow to answer -
        a duplicate would fail to bind the port and die), or
      * we already attempted a start very recently (rate limit / circuit breaker).

    Args:
        force: skip the rate limiter. Used when the Client we launched has
            already exited (unusable port) and we want to restart on a different
            port immediately instead of waiting out the circuit-breaker interval.

    Returns:
        True if a Client is running or a start was attempted; False only when a
        PermissionError blocked the start (caller should back off longer).
    """
    global _last_client_start_attempt

    if client_lib.is_client_process_alive():
        bk_logger.debug(
            "Blendkit-Client process still alive; skipping respawn on failed poll"
        )
        return True

    now = time.monotonic()
    if not force and now - _last_client_start_attempt < CLIENT_RESTART_MIN_INTERVAL:
        bk_logger.debug(
            "Skipping Blendkit-Client restart; last attempt %.1fs ago (< %.1fs)",
            now - _last_client_start_attempt,
            CLIENT_RESTART_MIN_INTERVAL,
        )
        return True

    _last_client_start_attempt = now
    try:
        client_lib.start_blenderkit_client()
        return True
    except PermissionError as pe:
        bk_logger.error("Cannot start client due to permission error: %s", pe)
        return False


def handle_failed_reports(exception: Exception) -> float:
    """Function reacting to failing reports (Client is not accessible).
    On 11th, 21st, 31st etc. it will print error message and start Client on other ports.
    Iterating over the available ports for each start. Users did not want to change the
    ports manually, so we do this automatically for them.
    """
    global_vars.CLIENT_ACCESSIBLE = False
    global_vars.CLIENT_FAILED_REPORTS += 1  # De facto means we count from 1, not from 0

    # First failed report -> lets start the Client
    if global_vars.CLIENT_FAILED_REPORTS == 1:
        ### Expected - port probably free as connection was refused
        if isinstance(exception, requests.ConnectionError):
            bk_logger.info(
                f"Expectedly, first request for BKClient reports failed: {str(exception).strip()} {type(exception)}"
            )
        ### Something unsupported runs on the port (other program, or Client refusing for version reasons)
        elif isinstance(exception, requests.HTTPError):
            bk_logger.info(
                f"First request for BKClient reports was rejected: {str(exception).strip()} {type(exception)}. Port is occupied and has to be changed"
            )
            client_lib.reorder_ports()
        # Not so expected
        else:
            bk_logger.warning(
                f"First request for BKClient reports failed unexpectedly: {str(exception).strip()} {type(exception)}"
            )
        if not _maybe_start_client():
            return 5.0  # retry after 5s, user needs to fix permissions first
    elif global_vars.CLIENT_FAILED_REPORTS <= 10:
        # Failures 2..10 are the normal startup window while the Client boots;
        # keep them at debug so a slightly slow start does not look like an
        # error. Genuine problems are reported below once the window is passed.
        bk_logger.debug(
            f"Request for BKClient reports failed: {str(exception).strip()} {type(exception)}"
        )

    # Fast path: the Client we launched has already exited - it could not bind
    # the port (reserved range, already in use, or access denied). Polling the
    # dead port through the whole ~6s backoff window wastes several seconds, so
    # switch to the next port and restart right away. Gated to the startup
    # window so a port that keeps failing cannot cause an unbounded respawn
    # loop; past the window the slow, rate-limited path below takes over.
    proc = global_vars.client_process
    if (
        2 <= global_vars.CLIENT_FAILED_REPORTS <= 10
        and proc is not None
        and proc.poll() is not None
    ):
        return_code, meaning = client_lib.check_blenderkit_client_return_code()
        bk_logger.warning(
            "Blendkit-Client exited (code %s: %s); switching to next port",
            return_code,
            meaning,
        )
        client_lib.reorder_ports()
        if not _maybe_start_client(force=True):
            return 5.0  # permission error - user must fix first
        return 0.1  # re-check the freshly started Client on the new port soon

    if global_vars.CLIENT_FAILED_REPORTS <= 10:  # try 10 times
        return 0.1 * global_vars.CLIENT_FAILED_REPORTS

    # MORE THAN 10 FAILURES - enough time for the Client to get up and running
    # so we need to investigate why it failed to start and respond correctly
    log_msg = f"Could not get reports ({global_vars.CLIENT_FAILED_REPORTS}. failure): {str(exception).strip()} {type(exception)}"
    return_code, meaning = client_lib.check_blenderkit_client_return_code()

    # On FAILED_REPORTS == 11, 21, 31...
    if global_vars.CLIENT_FAILED_REPORTS % 10 == 1:
        reports.add_report(log_msg, 5, "ERROR")  # Let's show the message to user
        if return_code == -1:
            msg = "Client is not responding, add-on will not work."
            reports.add_report(msg, timeout=10, type="ERROR")
        if return_code != -1:
            msg = f"Client failed to start, add-on will not work. Error({return_code}): {meaning}"
            reports.add_report(msg, timeout=10, type="ERROR")
        # LETS START AGAIN - on different port
        # The catch is that the error message printed to user is outdated now.
        # But there is not a better solution.
        client_lib.reorder_ports()
        if not _maybe_start_client():
            return 5.0  # retry after 5s, user needs to fix permissions first
    else:  # On FAILED_REPORTS == 12..20,22..30,32..40 we just log into terminal
        bk_logger.warning(log_msg)

    wm = bpy.context.window_manager
    wm.blenderkitUI.logo_status = "logo_offline"  # type: ignore[attr-defined]
    global_vars.CLIENT_RUNNING = False

    # Gradually retry less frequently, but at least once in 30s...
    return min(30.0, 0.1 * global_vars.CLIENT_FAILED_REPORTS)


def _thread_communication_enabled(user_preferences) -> bool:
    """True when the experimental threaded client communication should be used."""
    return bool(
        getattr(user_preferences, "experimental_features", False)
        and getattr(user_preferences, "thread_communication", False)
    )


@bpy.app.handlers.persistent
def client_communication_timer():
    """Receive all responses from Client and run according followup commands.
    This function is the only one responsible for keeping the Client up and running.

    When the experimental ``thread_communication`` preference is enabled, HTTP
    polling is delegated to ``client_thread`` and we only drain the results
    here. Task dispatch (``handle_task``) always happens on the main thread.
    """
    global pending_tasks
    bk_logger.log(5, "Getting tasks from Client")
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    if user_preferences.use_clipboard_scan:
        search.check_clipboard()

    use_thread = _thread_communication_enabled(user_preferences)
    results: list = []
    got_successful_reports = False

    if use_thread:
        # Refresh the worker's view of our state, then start it if needed.
        app_id = os.getpid()
        report_data = client_lib.build_report_data(app_id)
        fallback_urls = [
            client_lib.get_report_url(port) for port in global_vars.CLIENT_PORTS
        ]
        api_key = getattr(user_preferences, "api_key", "") or ""
        client_thread.update_state(
            report_url=client_lib.get_report_url(),
            report_data=report_data,
            fallback_urls=fallback_urls,
            poll_interval=user_preferences.client_polling,
            api_key=api_key,
        )
        client_thread.start()

        batches, err, recovered_port = client_thread.drain_reports()
        if recovered_port:
            client_lib.reorder_ports(recovered_port)
        if err is not None:
            download.prune_stalled_downloads(now=time.monotonic())
            next_delay = handle_failed_reports(err)
            # Batches collected alongside an error are stale; drop them so we
            # process fresh ones once the Client recovers.
            return next_delay

        for batch in batches:
            results.extend(batch)
        if batches:
            got_successful_reports = True
            global_vars.CLIENT_FAILED_REPORTS = 0
            client_thread.reset_failure_count()
    else:
        # Preference flipped off (or was never on) - make sure the worker is
        # idle so two poll paths don't race.
        if client_thread.is_running():
            client_thread.stop()
        try:
            results = client_lib.get_reports(os.getpid())
            got_successful_reports = True
            global_vars.CLIENT_FAILED_REPORTS = 0
        except Exception as e:
            download.prune_stalled_downloads(now=time.monotonic())
            return handle_failed_reports(e)

    if global_vars.CLIENT_ACCESSIBLE is False and got_successful_reports:
        bk_logger.info(
            f"Blendkit-Client is running on port {global_vars.CLIENT_PORTS[0]}!"
        )
        global_vars.CLIENT_ACCESSIBLE = True
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"

    bk_logger.log(5, "Handling tasks")
    results_converted_tasks = []

    # convert to task type
    for task in results:
        task = client_tasks.Task(
            data=task["data"],
            task_id=task["task_id"],
            app_id=task["app_id"],
            task_type=task["task_type"],
            message=task["message"],
            message_detailed=task["message_detailed"],
            progress=task["progress"],
            status=task["status"],
            result=task["result"],
        )
        results_converted_tasks.append(task)

    # add pending tasks which were already parsed but not handled
    results_converted_tasks.extend(pending_tasks)
    pending_tasks.clear()

    # Throttle eager thumbnail GPU-texture builds so a burst of completed
    # downloads doesn't freeze the viewport in a single step. Finished
    # thumbnails are processed only up to THUMBNAIL_BUILD_TIME_BUDGET; the rest
    # are re-queued for the next step. Cache hits cost ~0 ms so they don't eat
    # the budget. Every other task type is handled immediately, never deferred.
    #
    # Small thumbnails are the asset-bar grid icons - cheap and the first thing
    # the user sees - so they are always built immediately and never deferred.
    # Only the larger full/photo/wire (tooltip-sized) thumbnails are throttled.
    thumb_build_time = 0.0
    deferred_thumbs = []
    for task in results_converted_tasks:
        is_thumb = task.task_type == "thumbnail_download" and task.status == "finished"
        deferrable = is_thumb and task.data.get("thumbnail_type") != "small"
        if deferrable and thumb_build_time >= THUMBNAIL_BUILD_TIME_BUDGET:
            deferred_thumbs.append(task)
            continue
        if is_thumb:
            _t0 = time.perf_counter()
            handle_task(task)
            thumb_build_time += time.perf_counter() - _t0
        else:
            handle_task(task)

    if deferred_thumbs:
        # Re-queue for the next timer step (drained at the top of this function).
        pending_tasks.extend(deferred_thumbs)

    download.prune_stalled_downloads(now=time.monotonic())
    bk_logger.log(5, "Task handling finished")
    delay = user_preferences.client_polling
    if deferred_thumbs:
        # Come back soon to keep draining the backlog without busy-polling.
        return min(0.05, delay)
    if len(download.download_tasks) > 0:
        return min(0.2, delay)
    return delay


@bpy.app.handlers.persistent
def timer_image_cleanup():
    from . import ui_panels

    protected = ui_panels._protected_images
    imgs = bpy.data.images[:]
    for i in imgs:
        if (
            (i.name[:11] == ".thumbnail_" or i.filepath.find("bkit_g") > -1)
            and not i.has_data
            and i.users == 0
            and i.name not in protected
        ):
            bpy.data.images.remove(i)
    protected.clear()
    return 60


def save_prefs_cancel_all_tasks_and_restart_client(user_preferences, context):
    """Save preferences, cancel all blenderkit-client tasks, shutdown the blenderkit-client and reorder ports.
    Unset the CLIENT_FAILED_REPORTS and restart client_communication_timer() so add-on will check for the reports ASAP.
    Timer func client_communication_timer() will take care of starting the Client and checking the reports.
    """
    utils.save_prefs(user_preferences, context)
    if user_preferences.preferences_lock == True:
        return

    reports.add_report("Restarting Client server", timeout=2)
    try:
        cancel_all_tasks(user_preferences, context)
        client_lib.shutdown_client()
    except Exception:
        bk_logger.exception("Error shutting down client")

    # Stop the worker so the next timer tick restarts it against the fresh port.
    client_thread.stop()
    client_lib.reorder_ports(
        user_preferences.client_port
    )  # reorder after shutdown was requested
    global_vars.CLIENT_FAILED_REPORTS = 0  # reset failed reports so next attempt to get report or start client is immediate
    client_thread.reset_failure_count()
    bpy.app.timers.unregister(client_communication_timer)
    bpy.app.timers.register(client_communication_timer, persistent=True)


def trusted_CA_certs_property_updated(user_preferences, context):
    """Update trusted CA certs environment variables and call save_prefs()."""
    update_trusted_CA_certs(user_preferences.trusted_ca_certs)
    return save_prefs_cancel_all_tasks_and_restart_client(user_preferences, context)


def update_trusted_CA_certs(certs: str):
    if certs == "":
        os.environ.pop("REQUESTS_CA_BUNDLE", None)
        os.environ.pop("CURL_CA_BUNDLE", None)
        return

    os.environ["REQUESTS_CA_BUNDLE"] = certs
    os.environ["CURL_CA_BUNDLE"] = certs
    return


def cancel_all_tasks(self, context):
    """Cancel all tasks."""
    global pending_tasks
    pending_tasks.clear()
    download.cancel_running_downloads("cancel all tasks")
    search.clear_searches()
    # TODO: should add uploads


def task_error_overdrive(task: client_tasks.Task) -> None:
    """Handle error task - overdrive some error messages, trigger functions common for all errors."""
    if task.message.count("Invalid token.") > 0 and utils.user_logged_in():
        preferences = bpy.context.preferences.addons[__package__].preferences  # type: ignore

        # Invalid token and api_key_refresh present -> trying to refresh the token
        if preferences.api_key_refresh != "":  # type: ignore
            client_lib.refresh_token(preferences.api_key_refresh, preferences.api_key)  # type: ignore
            msg = "Invalid API key token. Refreshing the token now. If problem persist, please log-out and log-in."
            reports.add_report(msg, type="ERROR")
            return

        # Invalid token and no api_key_refresh token -> nothing else we can try...
        bkit_oauth.logout()
        msg = "Invalid permanent API key token. Logged out. Please login again."
        reports.add_report(msg, type="ERROR")


def handle_task(task: client_tasks.Task):
    """Handle incoming task information. Sort tasks by type and call appropriate functions."""
    if task.status == "error":
        task_error_overdrive(task)

    # HANDLE ASSET DOWNLOAD
    if task.task_type == "asset_download":
        return download.handle_download_task(task)

    # HANDLE ASSET UPLOAD
    if task.task_type == "asset_upload":
        return upload.handle_asset_upload(task)

    if task.task_type == "asset_metadata_upload":
        return upload.handle_asset_metadata_upload(task)

    # HANDLE SEARCH (candidate to be a function)
    if task.task_type == "search":
        if task.status == "finished":
            return search.handle_search_task(task)
        elif task.status == "error":
            return search.handle_search_task_error(task)

    # HANDLE THUMBNAIL DOWNLOAD (candidate to be a function)
    if task.task_type == "thumbnail_download":
        return search.handle_thumbnail_download_task(task)

    # HANDLE PRXC DOWNLOAD
    if task.task_type == "prxc_download":
        return search.handle_prxc_download_task(task)

    # HANDLE LOGIN
    if task.task_type == "login":
        return bkit_oauth.handle_login_task(task)

    # HANDLE TOKEN REFRESH - most likely not needed anymore, TODO: remove
    if task.task_type == "token_refresh":
        return bkit_oauth.handle_token_refresh_task(task)

    # HANDLE OAUTH LOGOUT
    if task.task_type == "oauth2/logout":
        return bkit_oauth.handle_logout_task(task)

    # HANDLE CLIENT STATUS REPORT
    if task.task_type == "client_status":
        return client_lib.handle_client_status_task(task)

    # HANDLE DISCLAIMER
    if task.task_type == "disclaimer":
        return disclaimer_op.handle_disclaimer_task(task)

    # HANDLE CATEGORIES FETCH
    if task.task_type == "categories_update":
        return categories.handle_categories_task(task)

    # HANDLE NOTIFICATIONS FETCH
    if task.task_type == "notifications":
        return comments_utils.handle_notifications_task(task)

    # HANDLE VARIOUS COMMENTS TASKS
    if task.task_type == "comments/get_comments":
        return comments_utils.handle_get_comments_task(task)
    if task.task_type == "comments/create_comment":
        return comments_utils.handle_create_comment_task(task)
    if task.task_type == "comments/feedback_comment":
        return comments_utils.handle_feedback_comment_task(task)
    if task.task_type == "comments/mark_comment_private":
        return comments_utils.handle_mark_comment_private_task(task)

    # HANDLE PROFILE
    if task.task_type == "profiles/fetch_gravatar_image":
        return search.handle_fetch_gravatar_task(task)
    if task.task_type == "profiles/get_user_profile":
        return search.handle_get_user_profile(task)

    # HANDLE RATINGS
    if task.task_type == "ratings/get_rating":
        return ratings_utils.handle_get_rating_task(task)
    if task.task_type == "ratings/get_ratings":
        return ratings_utils.handle_get_ratings_task(task)
    if task.task_type == "ratings/send_rating":
        return ratings_utils.handle_send_rating_task(task)

    # HANDLE BOOKMARKS
    if task.task_type == "ratings/get_bookmarks":
        return ratings_utils.handle_get_bookmarks_task(task)

    # HANDLE NONBLOCKING_REQUEST
    if task.task_type == "wrappers/nonblocking_request":
        return utils.handle_nonblocking_request_task(task)

    # BKCLIENTJS - Download from web
    if task.task_type == "bkclientjs/get_asset":
        return asset_bar_op.handle_bkclientjs_get_asset(task)

    # HANDLE MESSAGE FROM CLIENT
    if (
        task.task_type == "message_from_daemon"  # TODO: deprecate message_from_daemon
        or task.task_type == "message_from_client"
    ):
        level = task.result.get("level", "INFO").upper()
        duration = task.result.get("duration", 20)
        destination = task.result.get("destination", "GUI")
        if destination == "GUI":
            return reports.add_report(task.message, duration, level)
        if level == "INFO" or level == "VALIDATOR":
            return bk_logger.info(task.message)
        if level == "WARNING":
            return bk_logger.warning(task.message)
        if level == "ERROR":
            return bk_logger.error(task.message)


@bpy.app.handlers.persistent
def check_timers_timer():
    """Checks if all timers are registered regularly. Prevents possible bugs from stopping the addon."""
    if not bpy.app.timers.is_registered(tasks_queue.queue_worker):
        bpy.app.timers.register(tasks_queue.queue_worker)
    if not bpy.app.timers.is_registered(bg_blender.bg_update):
        bpy.app.timers.register(bg_blender.bg_update)
    if not bpy.app.timers.is_registered(client_communication_timer):
        bpy.app.timers.register(client_communication_timer, persistent=True)
    if not bpy.app.timers.is_registered(timer_image_cleanup):
        bpy.app.timers.register(timer_image_cleanup, persistent=True, first_interval=60)
    if not bpy.app.timers.is_registered(rating_nudge.rating_nudge_timer):
        bpy.app.timers.register(
            rating_nudge.rating_nudge_timer, persistent=True, first_interval=60
        )
    return 5.0


def on_startup_timer():
    """Run once on the startup of add-on (Blender start with enabled add-on, add-on enabled)."""
    persistent_preferences.load_preferences_from_JSON()
    addon_updater_ops.check_for_update_background()
    ui_bgl.create_image_shader()
    ok, message = utils.check_globaldir_permissions()
    if not ok:
        recovered = utils.try_recover_global_dir()
        if not recovered:
            global_dir = bpy.context.preferences.addons[
                __package__
            ].preferences.global_dir
            utils._show_permission_popup(global_dir, message)

    return None


def on_startup_client_online_timer():
    """Run once when Client is online after startup."""
    if not global_vars.CLIENT_RUNNING:
        return 1

    preferences = bpy.context.preferences.addons[__package__].preferences
    refresh_needed = bkit_oauth.ensure_token_refresh()
    if refresh_needed:  # called for new API token, lets wait for a while
        return 1

    if preferences.show_on_start:
        search.search()

    return


def register_timers():
    """Register all timers if add-on is not running in background (thumbnail rendering, upload, unpacking and also tests).
    It registers check_timers_timer which registers all other periodic non-ending timers.
    And individually it register all timers which are expected to end.
    """
    if bpy.app.background:
        return

    # PERIODIC TIMERS
    bpy.app.timers.register(
        check_timers_timer, persistent=True
    )  # registers all other non-ending timers

    # ONETIMERS
    bpy.app.timers.register(on_startup_timer)
    bpy.app.timers.register(on_startup_client_online_timer, first_interval=1)
    bpy.app.timers.register(disclaimer_op.show_disclaimer_timer, first_interval=1)


def unregister_timers():
    """Unregister all timers at the very start of unregistration.
    This prevents the timers being called before the unregistration finishes.
    """
    if bpy.app.background:
        return

    # Stop the optional client communication worker before touching timers so
    # it doesn't race against unregistration.
    try:
        client_thread.stop()
    except Exception:
        bk_logger.exception("Error stopping client communication thread")

    if bpy.app.timers.is_registered(check_timers_timer):
        bpy.app.timers.unregister(check_timers_timer)
    if bpy.app.timers.is_registered(tasks_queue.queue_worker):
        bpy.app.timers.unregister(tasks_queue.queue_worker)
    if bpy.app.timers.is_registered(bg_blender.bg_update):
        bpy.app.timers.unregister(bg_blender.bg_update)
    if bpy.app.timers.is_registered(client_communication_timer):
        bpy.app.timers.unregister(client_communication_timer)
    if bpy.app.timers.is_registered(timer_image_cleanup):
        bpy.app.timers.unregister(timer_image_cleanup)
    if bpy.app.timers.is_registered(rating_nudge.rating_nudge_timer):
        bpy.app.timers.unregister(rating_nudge.rating_nudge_timer)

    if bpy.app.timers.is_registered(on_startup_timer):
        bpy.app.timers.unregister(on_startup_timer)
    if bpy.app.timers.is_registered(on_startup_client_online_timer):
        bpy.app.timers.unregister(on_startup_client_online_timer)
    if bpy.app.timers.is_registered(disclaimer_op.show_disclaimer_timer):
        bpy.app.timers.unregister(disclaimer_op.show_disclaimer_timer)
