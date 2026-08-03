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

import os
import unittest
from types import SimpleNamespace
from unittest import mock

import requests

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]
from . import client_tasks, global_vars, timer


def make_task(task_type="search", status="finished", data=None, result=None):
    """Build a minimal ``client_tasks.Task`` for dispatch tests."""
    return client_tasks.Task(
        data=data if data is not None else {},
        app_id="app",
        task_type=task_type,
        status=status,
        result=result if result is not None else {},
    )


class TestThreadCommunicationEnabled(unittest.TestCase):
    def test_both_flags_true(self):
        prefs = SimpleNamespace(experimental_features=True, thread_communication=True)
        self.assertTrue(timer._thread_communication_enabled(prefs))

    def test_experimental_off(self):
        prefs = SimpleNamespace(experimental_features=False, thread_communication=True)
        self.assertFalse(timer._thread_communication_enabled(prefs))

    def test_thread_flag_off(self):
        prefs = SimpleNamespace(experimental_features=True, thread_communication=False)
        self.assertFalse(timer._thread_communication_enabled(prefs))

    def test_missing_attributes_default_false(self):
        prefs = SimpleNamespace()
        self.assertFalse(timer._thread_communication_enabled(prefs))

    def test_returns_bool_not_truthy_value(self):
        prefs = SimpleNamespace(experimental_features=1, thread_communication=2)
        result = timer._thread_communication_enabled(prefs)
        self.assertIs(result, True)


class TestUpdateTrustedCACerts(unittest.TestCase):
    def setUp(self):
        # Preserve and restore whatever was set before the test.
        self._saved = {
            key: os.environ.get(key) for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
        }

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_sets_both_env_vars(self):
        timer.update_trusted_CA_certs("/path/to/certs.pem")
        self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], "/path/to/certs.pem")
        self.assertEqual(os.environ["CURL_CA_BUNDLE"], "/path/to/certs.pem")

    def test_empty_string_clears_env_vars(self):
        os.environ["REQUESTS_CA_BUNDLE"] = "x"
        os.environ["CURL_CA_BUNDLE"] = "y"
        timer.update_trusted_CA_certs("")
        self.assertNotIn("REQUESTS_CA_BUNDLE", os.environ)
        self.assertNotIn("CURL_CA_BUNDLE", os.environ)

    def test_empty_string_when_already_unset(self):
        os.environ.pop("REQUESTS_CA_BUNDLE", None)
        os.environ.pop("CURL_CA_BUNDLE", None)
        # Must not raise even though the keys are absent.
        timer.update_trusted_CA_certs("")
        self.assertNotIn("REQUESTS_CA_BUNDLE", os.environ)


class TestMaybeStartClient(unittest.TestCase):
    def setUp(self):
        self._saved_attempt = timer._last_client_start_attempt
        timer._last_client_start_attempt = 0.0

    def tearDown(self):
        timer._last_client_start_attempt = self._saved_attempt

    def test_skips_when_process_alive(self):
        with (
            mock.patch.object(
                timer.client_lib, "is_client_process_alive", return_value=True
            ),
            mock.patch.object(timer.client_lib, "start_blenderkit_client") as start,
        ):
            result = timer._maybe_start_client()
        self.assertTrue(result)
        start.assert_not_called()

    def test_starts_when_not_alive_and_no_recent_attempt(self):
        with (
            mock.patch.object(
                timer.client_lib, "is_client_process_alive", return_value=False
            ),
            mock.patch.object(timer.client_lib, "start_blenderkit_client") as start,
            mock.patch.object(timer.time, "monotonic", return_value=1000.0),
        ):
            result = timer._maybe_start_client()
        self.assertTrue(result)
        start.assert_called_once()
        self.assertEqual(timer._last_client_start_attempt, 1000.0)

    def test_rate_limited_when_recent_attempt(self):
        timer._last_client_start_attempt = 100.0
        with (
            mock.patch.object(
                timer.client_lib, "is_client_process_alive", return_value=False
            ),
            mock.patch.object(timer.client_lib, "start_blenderkit_client") as start,
            mock.patch.object(
                timer.time,
                "monotonic",
                return_value=100.0 + timer.CLIENT_RESTART_MIN_INTERVAL - 0.1,
            ),
        ):
            result = timer._maybe_start_client()
        self.assertTrue(result)
        start.assert_not_called()

    def test_permission_error_returns_false(self):
        with (
            mock.patch.object(
                timer.client_lib, "is_client_process_alive", return_value=False
            ),
            mock.patch.object(
                timer.client_lib,
                "start_blenderkit_client",
                side_effect=PermissionError("denied"),
            ),
            mock.patch.object(timer.time, "monotonic", return_value=5000.0),
        ):
            result = timer._maybe_start_client()
        self.assertFalse(result)


class TestHandleFailedReports(unittest.TestCase):
    def setUp(self):
        self._saved_failed = global_vars.CLIENT_FAILED_REPORTS
        self._saved_accessible = global_vars.CLIENT_ACCESSIBLE
        self._saved_proc = global_vars.client_process
        global_vars.CLIENT_FAILED_REPORTS = 0
        global_vars.CLIENT_ACCESSIBLE = True
        # No spawned Client by default so the dead-process fast path stays inert.
        global_vars.client_process = None

    def tearDown(self):
        global_vars.CLIENT_FAILED_REPORTS = self._saved_failed
        global_vars.CLIENT_ACCESSIBLE = self._saved_accessible
        global_vars.client_process = self._saved_proc

    def test_sets_client_inaccessible_and_increments(self):
        with mock.patch.object(timer, "_maybe_start_client", return_value=True):
            timer.handle_failed_reports(requests.ConnectionError("refused"))
        self.assertFalse(global_vars.CLIENT_ACCESSIBLE)
        self.assertEqual(global_vars.CLIENT_FAILED_REPORTS, 1)

    def test_first_connection_error_starts_client(self):
        with mock.patch.object(
            timer, "_maybe_start_client", return_value=True
        ) as start:
            delay = timer.handle_failed_reports(requests.ConnectionError("refused"))
        start.assert_called_once()
        self.assertEqual(delay, 0.1)

    def test_first_http_error_reorders_ports(self):
        with (
            mock.patch.object(timer, "_maybe_start_client", return_value=True),
            mock.patch.object(timer.client_lib, "reorder_ports") as reorder,
        ):
            timer.handle_failed_reports(requests.HTTPError("occupied"))
        reorder.assert_called_once()

    def test_first_report_permission_error_backs_off(self):
        with mock.patch.object(timer, "_maybe_start_client", return_value=False):
            delay = timer.handle_failed_reports(requests.ConnectionError("refused"))
        self.assertEqual(delay, 5.0)

    def test_backoff_scales_up_to_ten(self):
        global_vars.CLIENT_FAILED_REPORTS = 4  # becomes 5 inside
        delay = timer.handle_failed_reports(Exception("boom"))
        self.assertEqual(global_vars.CLIENT_FAILED_REPORTS, 5)
        self.assertAlmostEqual(delay, 0.5)

    def test_capped_at_thirty_seconds(self):
        # 405 -> 406 inside; 406 % 10 == 6 hits the log-only branch and avoids
        # any real client restart / port reordering.
        global_vars.CLIENT_FAILED_REPORTS = 405
        saved_running = global_vars.CLIENT_RUNNING
        try:
            with mock.patch.object(
                timer.client_lib,
                "check_blenderkit_client_return_code",
                return_value=(0, "ok"),
            ):
                delay = timer.handle_failed_reports(Exception("boom"))
        finally:
            global_vars.CLIENT_RUNNING = saved_running
        self.assertEqual(delay, 30.0)

    def test_dead_client_switches_port_immediately(self):
        # The spawned Client exited (poll() returns a code) - within the startup
        # window we must not keep polling the dead port; reorder and restart now.
        global_vars.CLIENT_FAILED_REPORTS = 1  # becomes 2 inside
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=41))
        with (
            mock.patch.object(
                timer.client_lib,
                "check_blenderkit_client_return_code",
                return_value=(41, "Other networking problem."),
            ),
            mock.patch.object(timer.client_lib, "reorder_ports") as reorder,
            mock.patch.object(timer, "_maybe_start_client", return_value=True) as start,
        ):
            delay = timer.handle_failed_reports(Exception("boom"))
        reorder.assert_called_once()
        start.assert_called_once_with(force=True)
        self.assertEqual(delay, 0.1)

    def test_alive_client_uses_normal_backoff(self):
        # A still-booting Client (poll() is None) must NOT trigger the fast path.
        global_vars.CLIENT_FAILED_REPORTS = 4  # becomes 5 inside
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=None))
        with mock.patch.object(timer, "_maybe_start_client") as start:
            delay = timer.handle_failed_reports(Exception("boom"))
        start.assert_not_called()
        self.assertAlmostEqual(delay, 0.5)


class TestCancelAllTasks(unittest.TestCase):
    def test_clears_pending_and_calls_dependencies(self):
        timer.pending_tasks.append(make_task())
        with (
            mock.patch.object(timer.download, "cancel_running_downloads") as cancel,
            mock.patch.object(timer.search, "clear_searches") as clear,
        ):
            timer.cancel_all_tasks(None, None)
        self.assertEqual(timer.pending_tasks, [])
        cancel.assert_called_once()
        clear.assert_called_once()


class TestTaskErrorOverdrive(unittest.TestCase):
    def test_ignores_non_token_errors(self):
        task = make_task(task_type="search", status="error")
        task.message = "some unrelated error"
        with (
            mock.patch.object(timer.utils, "user_logged_in", return_value=True),
            mock.patch.object(timer.client_lib, "refresh_token") as refresh,
        ):
            timer.task_error_overdrive(task)
        refresh.assert_not_called()

    def test_ignored_when_not_logged_in(self):
        task = make_task(task_type="search", status="error")
        task.message = "Invalid token."
        with (
            mock.patch.object(timer.utils, "user_logged_in", return_value=False),
            mock.patch.object(timer.client_lib, "refresh_token") as refresh,
        ):
            timer.task_error_overdrive(task)
        refresh.assert_not_called()


class TestHandleTaskDispatch(unittest.TestCase):
    """``handle_task`` is a large dispatch table - verify it routes each task
    type to the correct handler."""

    def _assert_dispatch(self, task, module, func_name, **task_kwargs):
        with mock.patch.object(module, func_name) as handler:
            timer.handle_task(task)
        handler.assert_called_once_with(task)

    def test_asset_download(self):
        task = make_task(task_type="asset_download")
        with mock.patch.object(timer.download, "handle_download_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_asset_upload(self):
        task = make_task(task_type="asset_upload")
        with mock.patch.object(timer.upload, "handle_asset_upload") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_search_finished(self):
        task = make_task(task_type="search", status="finished")
        with mock.patch.object(timer.search, "handle_search_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_search_error(self):
        task = make_task(task_type="search", status="error")
        with (
            mock.patch.object(timer, "task_error_overdrive"),
            mock.patch.object(timer.search, "handle_search_task_error") as h,
        ):
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_thumbnail_download(self):
        task = make_task(task_type="thumbnail_download")
        with mock.patch.object(timer.search, "handle_thumbnail_download_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_login(self):
        task = make_task(task_type="login")
        with mock.patch.object(timer.bkit_oauth, "handle_login_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_client_status(self):
        task = make_task(task_type="client_status")
        with mock.patch.object(timer.client_lib, "handle_client_status_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_get_rating(self):
        task = make_task(task_type="ratings/get_rating")
        with mock.patch.object(timer.ratings_utils, "handle_get_rating_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_get_bookmarks(self):
        task = make_task(task_type="ratings/get_bookmarks")
        with mock.patch.object(timer.ratings_utils, "handle_get_bookmarks_task") as h:
            timer.handle_task(task)
        h.assert_called_once_with(task)

    def test_unknown_task_type_returns_none(self):
        task = make_task(task_type="totally_unknown")
        self.assertIsNone(timer.handle_task(task))

    def test_message_from_client_gui_adds_report(self):
        task = make_task(
            task_type="message_from_client",
            result={"level": "INFO", "duration": 5, "destination": "GUI"},
        )
        task.message = "hello"
        with mock.patch.object(timer.reports, "add_report") as add_report:
            timer.handle_task(task)
        add_report.assert_called_once_with("hello", 5, "INFO")

    def test_message_from_client_error_logs(self):
        task = make_task(
            task_type="message_from_client",
            result={"level": "ERROR", "destination": "CONSOLE"},
        )
        task.message = "boom"
        with mock.patch.object(timer.bk_logger, "error") as log_error:
            timer.handle_task(task)
        log_error.assert_called_once_with("boom")

    def test_error_status_triggers_overdrive(self):
        task = make_task(task_type="asset_download", status="error")
        with (
            mock.patch.object(timer, "task_error_overdrive") as overdrive,
            mock.patch.object(timer.download, "handle_download_task"),
        ):
            timer.handle_task(task)
        overdrive.assert_called_once_with(task)


if __name__ == "__main__":
    unittest.main()
