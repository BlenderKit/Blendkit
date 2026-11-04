import unittest
from contextlib import ExitStack
from unittest import mock


if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

from . import client_tasks, download, global_vars


class DownloadFailureTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tracked = {
            "asset_data": {"id": "asset-id", "name": "Round table"},
            "text": "Getting download URL",
            "progress": 0,
            "started_at": 100.0,
            "last_report_time": 100.0,
            "download_dirs": ["asset-cache"],
        }
        self.stack.enter_context(
            mock.patch.object(download, "download_tasks", {"task-id": self.tracked})
        )
        self.add_report = download.reports.add_report
        self.report = self.stack.enter_context(
            mock.patch.object(download.reports, "add_report")
        )
        self.cancel = self.stack.enter_context(
            mock.patch.object(download.client_lib, "cancel_download")
        )
        self.reset = self.stack.enter_context(
            mock.patch.object(download, "_reset_progress_for_asset_ids")
        )
        self.stack.enter_context(
            mock.patch.object(global_vars, "CLIENT_ACCESSIBLE", True)
        )
        self.stack.enter_context(
            mock.patch.object(download.search, "get_search_results", return_value=None)
        )

    def make_task(self, **kwargs):
        return client_tasks.Task(
            data={"asset_data": self.tracked["asset_data"]},
            app_id="app",
            task_type="asset_download",
            task_id="task-id",
            **kwargs,
        )

    def report_text(self):
        self.report.assert_called_once()
        self.assertEqual(self.report.call_args.kwargs["type"], "ERROR")
        return self.report.call_args.args[0]

    def test_stall_reports_actual_idle_time_and_last_step(self):
        download.prune_stalled_downloads(now=127.0)
        text = self.report_text()
        self.assertIn("Round table", text)
        self.assertIn("27 seconds", text)
        self.assertIn("status update", text)
        self.assertIn("Getting download URL", text)
        self.assertIn("0%", text)
        self.assertIn("Client log", text)
        self.assertIn("Copy the log text", text)
        self.cancel.assert_called_once_with("task-id")
        self.reset.assert_called_once_with({"asset-id"})
        self.assertEqual(download.download_tasks, {})

    def test_stall_at_threshold_is_cancelled(self):
        download.prune_stalled_downloads(now=120.0)
        self.report.assert_called_once()
        self.cancel.assert_called_once_with("task-id")

    def test_active_download_is_not_cancelled(self):
        download.prune_stalled_downloads(now=119.99)
        self.report.assert_not_called()
        self.cancel.assert_not_called()
        self.assertIn("task-id", download.download_tasks)

    def test_missing_timestamp_starts_observation_without_cancelling(self):
        self.tracked.pop("started_at")
        self.tracked.pop("last_report_time")
        download.prune_stalled_downloads(now=120.0)
        self.assertEqual(self.tracked["last_report_time"], 120.0)
        self.report.assert_not_called()
        self.cancel.assert_not_called()

    def test_lost_client_is_not_reported_as_internet_failure(self):
        with mock.patch.object(global_vars, "CLIENT_ACCESSIBLE", False):
            download.prune_stalled_downloads(now=125.0)
        text = self.report_text()
        self.assertIn("local Blendkit Client", text)
        self.assertIn("Restart Blender", text)
        self.assertNotIn("internet", text.lower())

    def test_error_preserves_reason_asset_and_detailed_diagnostics(self):
        task = self.make_task(
            status="error",
            message="error downloading asset: permission denied",
            message_detailed="Cannot write asset-cache",
        )
        download.handle_download_task(task)
        text = self.report_text()
        self.assertIn("Round table", text)
        self.assertIn("permission denied", text)
        self.assertIn("write permission", text)
        diagnostics = self.report.call_args.kwargs["details"]
        self.assertIn("Cannot write asset-cache", diagnostics)
        self.assertIn("task-id", diagnostics)
        self.assertIn("asset-id", diagnostics)
        self.assertIn("asset-cache", diagnostics)
        self.assertEqual(download.download_tasks, {})
        self.reset.assert_called_once_with({"asset-id"})

    def test_empty_error_uses_detailed_message(self):
        download.handle_download_task(
            self.make_task(status="error", message_detailed="Disk is full")
        )
        self.assertIn("Disk is full", self.report_text())

    def test_whitespace_error_uses_detailed_message(self):
        download.handle_download_task(
            self.make_task(
                status="error", message=" \n ", message_detailed="Disk is full"
            )
        )
        self.assertIn("Disk is full", self.report_text())

    def test_empty_error_explains_missing_reason(self):
        download.handle_download_task(self.make_task(status="error"))
        self.assertIn("did not provide an error reason", self.report_text())

    def test_humanizes_server_reason_before_adding_context(self):
        download.handle_download_task(
            self.make_task(
                status="error",
                message='HTTP 403: {"detail": "A subscription is required."}',
            )
        )
        text = self.report_text()
        self.assertIn("Round table", text)
        self.assertIn("A subscription is required.", text)
        self.assertIn("Client log", text)
        self.assertNotIn('{"detail"', text)

    def test_import_error_is_not_described_as_download_failure(self):
        with (
            mock.patch.object(
                download,
                "download_post",
                side_effect=RuntimeError("Invalid blend file"),
            ),
            self.assertLogs(download.bk_logger, level="ERROR"),
        ):
            download.handle_download_task(self.make_task(status="finished"))
        text = self.report_text()
        self.assertIn("downloaded", text)
        self.assertIn("could not import", text)
        self.assertIn("Invalid blend file", text)
        self.assertEqual(download.download_tasks, {})

    def test_finished_download_keeps_existing_behavior(self):
        with mock.patch.object(download, "download_post") as post:
            download.handle_download_task(self.make_task(status="finished"))
        post.assert_called_once()
        self.report.assert_not_called()
        self.assertEqual(download.download_tasks, {})

    def test_late_error_is_ignored(self):
        download.download_tasks.clear()
        download.handle_download_task(self.make_task(status="error", message="late"))
        self.report.assert_not_called()

    def test_error_guidance(self):
        cases = (
            ("no space left on device", "Free up disk space"),
            ("Access is denied.", "write permission"),
            ("x509: certificate signed by unknown authority", "Keep SSL"),
            ("dial tcp: no such host", "DNS"),
            ("request failed: connection reset by peer", "proxy/firewall"),
        )
        for reason, expected in cases:
            with self.subTest(reason=reason):
                self.report.reset_mock()
                download.download_tasks["task-id"] = self.tracked
                download.handle_download_task(
                    self.make_task(status="error", message=reason)
                )
                self.assertIn(expected, self.report_text())

    def test_long_reason_is_wrapped_and_full_text_is_logged(self):
        reason = "The download server returned an unexpected response. " * 8
        download.handle_download_task(self.make_task(status="error", message=reason))
        text = self.report_text()
        self.assertIn("The download server returned an unexpected response.", text)
        self.assertIn("full error in Blender console", " ".join(text.split()))
        self.assertIn(reason.strip(), self.report.call_args.kwargs["details"])
        self.assertIn("Copy the log text", text)
        self.assertTrue(all(len(line) <= 88 for line in text.splitlines()))

    def test_real_report_keeps_context_and_logs_diagnostics(self):
        with (
            mock.patch.object(download.reports, "add_report", wraps=self.add_report),
            mock.patch.object(download.reports, "reports", []),
            mock.patch.object(download.reports, "Report") as create_report,
            self.assertLogs(download.reports.bk_logger, level="ERROR") as logged,
        ):
            download.handle_download_task(
                self.make_task(
                    status="error",
                    message='HTTP 403: {"detail": "A subscription is required."}',
                    message_detailed="Additional Client diagnostics",
                )
            )
        text = create_report.call_args.kwargs["text"]
        self.assertIn("Round table", text)
        self.assertIn("A subscription is required.", text)
        self.assertIn("Client log", text)
        self.assertNotIn("Additional Client diagnostics", text)
        self.assertIn("Additional Client diagnostics", logged.output[0])
        self.assertIn("task-id", logged.output[0])
        self.assertIn('HTTP 403: {"detail":', logged.output[0])

    def test_progress_update_prevents_stale_cancellation(self):
        with mock.patch.object(download.time, "monotonic", return_value=118.0):
            download.handle_download_task(
                self.make_task(status="created", message="Downloading", progress=42)
            )
        download.prune_stalled_downloads(now=125.0)
        self.assertEqual(self.tracked["progress"], 42)
        self.assertEqual(self.tracked["text"], "Downloading")
        self.assertEqual(self.tracked["last_report_time"], 118.0)
        self.report.assert_not_called()
        self.cancel.assert_not_called()

    def test_stalled_download_does_not_remove_active_download(self):
        download.download_tasks["active-id"] = {
            **self.tracked,
            "last_report_time": 119.0,
        }
        download.prune_stalled_downloads(now=125.0)
        self.cancel.assert_called_once_with("task-id")
        self.assertEqual(list(download.download_tasks), ["active-id"])
