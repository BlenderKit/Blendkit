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
import time
import unittest
from unittest import mock
from urllib.parse import urlparse

import requests

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and any ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]


from . import client_lib, datas, download, global_vars, paths, utils


def client_is_responding() -> tuple[bool, str]:
    """Check whether Blendkit-client is responding."""
    address = client_lib.get_address()
    try:
        with requests.Session() as session:
            with session.get(
                address, timeout=client_lib.TIMEOUT, proxies=client_lib.NO_PROXIES
            ) as resp:
                if resp.status_code != 200:
                    return False, f"Server response not 200: {resp.status_code}"
                return True, f"Server alive, PID: {resp.text}"
    except requests.exceptions.ConnectionError as err:
        return False, f'EXCEPTION OCCURED:", {err}, {type(err)}'


### CLIENT IS NOT RUNNING ###


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test01ClientNotRunning(unittest.TestCase):
    def test01_client_not_running(self):
        """Tests run in background (bpy.app.background == True), so blenderkit-client is not started during registration.
        Also the client_communication_timer() and all other timers are not registered.
        So we expect blenderkit-client to be not running.
        """
        alive, pid = client_is_responding()
        self.assertFalse(alive)
        self.assertIsInstance(alive, bool)
        self.assertIsInstance(pid, str)

    def test02_get_reports_not_running(self):
        app_id = os.getpid()
        try:
            client_lib.get_reports(app_id)
            self.fail("got report but blenderkit-client should be offline")
        except requests.exceptions.ConnectionError as err:
            type(err)
            return
        except Exception as err:
            self.fail(f"expected requests.exceptions.ConnectionError, got {err}")


### CLIENT IS RUNNING ###


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test02ClientRunning(unittest.TestCase):
    def test01_start_client_server(self):
        client_lib.start_blenderkit_client()
        for i in range(10):
            time.sleep(i * 0.5)
            alive, _ = client_is_responding()
            if alive == True:
                break
        self.assertTrue(alive)


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test03ClientUtilFunctions(unittest.TestCase):
    def test_get_port(self):
        ports = ["62485", "65425", "55428", "49452", "35452", "25152", "5152", "1234"]
        self.assertIn(client_lib.get_port(), ports)

    def test_get_address(self):
        address = client_lib.get_address()
        parsed = urlparse(address)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, int(client_lib.get_port()))

    def test_client_directory_path(self):
        dir_path = client_lib.get_client_directory()
        self.assertTrue(os.path.exists(dir_path))


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test04GetReportsClientRunning(unittest.TestCase):
    def test_get_reports_running(self):
        """Get reports for current Blender PID (app_id).
        Blendkit-Client since v1.10 reports also settings.
        """
        app_id = os.getpid()
        reports = client_lib.get_reports(app_id)
        self.assertEqual(
            2,  # task_type=client_report, task_type=settings
            len(reports),
            f"Reports were: {reports}",
        )
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")
        self.assertEqual(reports[1]["app_id"], app_id)
        self.assertEqual(reports[1]["task_type"], "settings")

    def test_get_reports_another_app_id(self):
        """Get reports for non-existing Blender PID (app_id).
        Blendkit-Client since v1.10 reports also settings.
        """
        app_id = os.getpid() + 10
        reports = client_lib.get_reports(app_id)
        self.assertEqual(
            2,  # task_type=client_report, task_type=settings
            len(reports),
            f"Reports were: {reports}",
        )
        self.assertEqual(reports[0]["app_id"], app_id)
        self.assertEqual(reports[0]["task_type"], "client_status")
        self.assertEqual(reports[1]["app_id"], app_id)
        self.assertEqual(reports[1]["task_type"], "settings")


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test05SearchAndDownloadAsset(unittest.TestCase):
    assets_to_download = []

    def _asset_search(self, search_word, asset_type):
        addon_version = utils.get_addon_version()
        blender_version = utils.get_blender_version()
        urlquery = f"https://www.blendkit.com/api/v1/search/?query={search_word}+asset_type:{asset_type}+order:_score&dict_parameters=1&page_size=15&addon_version={addon_version}&blender_version={blender_version}"
        tempdir = paths.get_temp_dir(f"{asset_type}_search")
        data = datas.SearchData(
            PREFS=utils.get_preferences(),
            tempdir=tempdir,
            urlquery=urlquery,
            asset_type=asset_type,
            blender_version=blender_version,
            page_size=15,
            get_next=False,
            scene_uuid="",
        )
        try:
            response = client_lib.asset_search(data)
            search_task_id = response["task_id"]
            deadline = time.monotonic() + 20
            last_status = None

            to_download = None
            while time.monotonic() < deadline:
                reports = client_lib.get_reports(os.getpid())
                for task in reports:
                    if search_task_id != task["task_id"]:
                        continue
                    last_status = task["status"]
                    if task["status"] == "error":
                        error_msg = task.get("message", "Unknown error")
                        self.fail(f"Search task failed: {error_msg}, query: {urlquery}")
                    if task["status"] != "finished":
                        continue
                    if task["result"] != {}:
                        for result in task["result"]["results"]:
                            if result["canDownload"] == True:
                                if to_download == None:
                                    to_download = result
                                    continue
                                result_size = result.get("filesSize", 9999999)
                                if result_size == None:
                                    result_size = 9999999
                                to_download_size = to_download.get("filesSize", 9999999)
                                if to_download_size == None:
                                    to_download_size = 9999999
                                if result_size < to_download_size:
                                    to_download = result
                        return to_download

                time.sleep(0.5)
            self.fail(
                "Error waiting for search task to be reported as finished, "
                f"last status: {last_status}, query: {urlquery}"
            )
        except Exception as e:
            self.fail(f"Search request failed: {str(e)}, query: {urlquery}")

    def _asset_download(self, asset_data):
        if asset_data == None:
            self.fail("Asset data from search are None")

        download.start_download(
            asset_data,
            resolution="resolution_0_5K",
            model_location=(0.0, 0.0, 0.0),
            model_rotation=(0.0, 0.0, 0.0),
        )

        for _ in range(100):
            reports = client_lib.get_reports(os.getpid())
            for task in reports:
                if task["task_type"] != "asset_download":
                    continue
                if task["status"] != "finished":
                    continue
                return
            time.sleep(1)

    # small assets are chosen here
    def test00Search(self):
        self.assets_to_download.append(self._asset_search("Toy+train-02", "model"))

    def test01Search(self):
        self.assets_to_download.append(self._asset_search("Wooden+toy+car", "model"))

    def test02Search(self):
        self.assets_to_download.append(
            self._asset_search("flowers1+wallpaper", "material")
        )

    def test03Search(self):
        self.assets_to_download.append(self._asset_search("hexa+wallpaper", "material"))

    def test04Search(self):
        self.assets_to_download.append(
            self._asset_search("Desk+for+product+visualization", "scene")
        )

    def test05Search(self):
        self.assets_to_download.append(
            self._asset_search("Butterfly+Mural+Room", "scene")
        )

    def test06Search(self):
        self.assets_to_download.append(self._asset_search("Garden+Nook", "hdr"))

    def test07Search(self):
        self.assets_to_download.append(self._asset_search("Dark+Autumn+Forest", "hdr"))

    def test08Search(self):
        self.assets_to_download.append(self._asset_search("bricks", "brush"))

    def test09Search(self):
        self.assets_to_download.append(self._asset_search("Human+eye+iris", "brush"))

    def test10Download(self):
        self._asset_download(self.assets_to_download[0])

    def test12Download(self):
        self._asset_download(self.assets_to_download[2])

    def test14Download(self):
        self._asset_download(self.assets_to_download[4])

    def test16Download(self):
        self._asset_download(self.assets_to_download[6])

    def test18Download(self):
        self._asset_download(self.assets_to_download[8])


### CLIENT IS NOT RUNNING ###


@unittest.skipIf(os.getenv("TESTS_TYPE") == "FAST", "slow")
class Test99ClientStopped(unittest.TestCase):
    def test_shutdown_client(self):
        client_lib.shutdown_client()
        for _ in range(5):
            alive, _ = client_is_responding()
            if alive == False:
                break
            time.sleep(1)
        self.assertFalse(alive)


### FAST UNIT TESTS (no running Client required) ###


class TestUrlHelpers(unittest.TestCase):
    """Pure URL/version helpers derived from global_vars."""

    def setUp(self):
        self._saved_ports = global_vars.CLIENT_PORTS
        self._saved_version = global_vars.CLIENT_VERSION

    def tearDown(self):
        global_vars.CLIENT_PORTS = self._saved_ports
        global_vars.CLIENT_VERSION = self._saved_version

    def test_get_address_uses_first_port(self):
        global_vars.CLIENT_PORTS = ["12345", "62485"]
        self.assertEqual(client_lib.get_address(), "http://127.0.0.1:12345")

    def test_get_port_returns_first(self):
        global_vars.CLIENT_PORTS = ["55555", "62485"]
        self.assertEqual(client_lib.get_port(), "55555")

    def test_get_api_version_drops_patch(self):
        global_vars.CLIENT_VERSION = "v1.10.3"
        self.assertEqual(client_lib.get_api_version(), "v1.10")

    def test_get_api_version_minor_pin_unchanged(self):
        global_vars.CLIENT_VERSION = "v1.12"
        self.assertEqual(client_lib.get_api_version(), "v1.12")

    def test_get_resolved_client_version_falls_back_to_pin(self):
        """Without a bundled client/RESOLVED_VERSION file, the resolver returns the pin."""
        global_vars.CLIENT_VERSION = "v1.12"
        saved_cache = client_lib._resolved_client_version
        client_lib._resolved_client_version = None
        try:
            with mock.patch(
                "builtins.open", side_effect=OSError("no RESOLVED_VERSION")
            ):
                self.assertEqual(client_lib.get_resolved_client_version(), "v1.12")
        finally:
            client_lib._resolved_client_version = saved_cache

    def test_get_base_url_combines_address_and_api_version(self):
        global_vars.CLIENT_PORTS = ["62485"]
        global_vars.CLIENT_VERSION = "v1.10.3"
        self.assertEqual(client_lib.get_base_url(), "http://127.0.0.1:62485/v1.10")

    def test_get_report_url_default_port(self):
        global_vars.CLIENT_PORTS = ["62485"]
        global_vars.CLIENT_VERSION = "v1.10.3"
        self.assertEqual(
            client_lib.get_report_url(), "http://127.0.0.1:62485/v1.10/report"
        )

    def test_get_report_url_explicit_port(self):
        global_vars.CLIENT_VERSION = "v1.10.3"
        self.assertEqual(
            client_lib.get_report_url("49452"),
            "http://127.0.0.1:49452/v1.10/report",
        )


class TestReorderPorts(unittest.TestCase):
    def setUp(self):
        self._saved_ports = global_vars.CLIENT_PORTS

    def tearDown(self):
        global_vars.CLIENT_PORTS = self._saved_ports

    def test_reorder_to_specific_port(self):
        global_vars.CLIENT_PORTS = ["1", "2", "3", "4"]
        client_lib.reorder_ports("3")
        self.assertEqual(global_vars.CLIENT_PORTS, ["3", "4", "1", "2"])

    def test_reorder_default_rotates_by_one(self):
        global_vars.CLIENT_PORTS = ["1", "2", "3", "4"]
        client_lib.reorder_ports()
        self.assertEqual(global_vars.CLIENT_PORTS, ["2", "3", "4", "1"])

    def test_reorder_first_port_is_noop(self):
        global_vars.CLIENT_PORTS = ["1", "2", "3"]
        client_lib.reorder_ports("1")
        self.assertEqual(global_vars.CLIENT_PORTS, ["1", "2", "3"])


class TestEnsureMinimalData(unittest.TestCase):
    def test_fills_defaults(self):
        with mock.patch.object(
            client_lib, "_read_api_key_threadsafe", return_value="KEY"
        ):
            data = client_lib.ensure_minimal_data()
        self.assertEqual(data["api_key"], "KEY")
        self.assertEqual(data["app_id"], os.getpid())
        self.assertIn("platform_version", data)
        # addon_version has 4 dot-separated components: X.Y.Z.W
        self.assertEqual(data["addon_version"].count("."), 3)

    def test_preserves_existing_values(self):
        data = client_lib.ensure_minimal_data(
            {"api_key": "existing", "app_id": 42, "extra": "keep"}
        )
        self.assertEqual(data["api_key"], "existing")
        self.assertEqual(data["app_id"], 42)
        self.assertEqual(data["extra"], "keep")

    def test_none_input_returns_new_dict(self):
        with mock.patch.object(client_lib, "_read_api_key_threadsafe", return_value=""):
            data = client_lib.ensure_minimal_data(None)
        self.assertIsInstance(data, dict)


class TestRequestReport(unittest.TestCase):
    def _make_session(self, resp):
        session = mock.MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = resp
        return session

    def test_returns_json_on_200(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"tasks": []}
        session = self._make_session(resp)
        with mock.patch.object(client_lib.requests, "Session", return_value=session):
            result = client_lib.request_report("http://127.0.0.1:1/report", {})
        self.assertEqual(result, {"tasks": []})

    def test_raises_http_error_on_non_200(self):
        resp = mock.Mock(status_code=500, text="boom")
        session = self._make_session(resp)
        with mock.patch.object(client_lib.requests, "Session", return_value=session):
            with self.assertRaises(requests.HTTPError):
                client_lib.request_report("http://127.0.0.1:1/report", {})


class TestGetReports(unittest.TestCase):
    def setUp(self):
        self._saved_failed = global_vars.CLIENT_FAILED_REPORTS
        self._saved_ports = global_vars.CLIENT_PORTS

    def tearDown(self):
        global_vars.CLIENT_FAILED_REPORTS = self._saved_failed
        global_vars.CLIENT_PORTS = self._saved_ports

    def test_single_request_when_few_failures(self):
        global_vars.CLIENT_FAILED_REPORTS = 0
        with (
            mock.patch.object(client_lib, "build_report_data", return_value={}),
            mock.patch.object(
                client_lib, "request_report", return_value=["report"]
            ) as req,
        ):
            result = client_lib.get_reports(123)
        self.assertEqual(result, ["report"])
        req.assert_called_once()

    def test_iterates_ports_after_many_failures(self):
        global_vars.CLIENT_FAILED_REPORTS = 10
        global_vars.CLIENT_PORTS = ["1", "2", "3"]

        def fake_request(url, data):
            # Fail on the first port, succeed on the second.
            if "127.0.0.1:1/" in url:
                raise requests.ConnectionError("refused")
            return ["ok"]

        with (
            mock.patch.object(client_lib, "build_report_data", return_value={}),
            mock.patch.object(client_lib, "request_report", side_effect=fake_request),
            mock.patch.object(client_lib, "reorder_ports") as reorder,
        ):
            result = client_lib.get_reports(123)
        self.assertEqual(result, ["ok"])
        reorder.assert_called_once_with("2")

    def test_raises_last_exception_when_all_ports_fail(self):
        global_vars.CLIENT_FAILED_REPORTS = 10
        global_vars.CLIENT_PORTS = ["1", "2"]
        with (
            mock.patch.object(client_lib, "build_report_data", return_value={}),
            mock.patch.object(
                client_lib,
                "request_report",
                side_effect=requests.ConnectionError("refused"),
            ),
        ):
            with self.assertRaises(requests.ConnectionError):
                client_lib.get_reports(123)


class TestClientProcessState(unittest.TestCase):
    def setUp(self):
        self._saved_proc = global_vars.client_process

    def tearDown(self):
        global_vars.client_process = self._saved_proc

    def test_is_alive_false_when_no_process(self):
        global_vars.client_process = None
        self.assertFalse(client_lib.is_client_process_alive())

    def test_is_alive_true_when_running(self):
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=None))
        self.assertTrue(client_lib.is_client_process_alive())

    def test_is_alive_false_when_exited(self):
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=0))
        self.assertFalse(client_lib.is_client_process_alive())

    def test_return_code_none_process(self):
        global_vars.client_process = None
        code, msg = client_lib.check_blenderkit_client_return_code()
        self.assertEqual(code, -2)

    def test_return_code_still_running(self):
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=None))
        code, msg = client_lib.check_blenderkit_client_return_code()
        self.assertEqual(code, -1)

    def test_return_code_address_in_use(self):
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=43))
        code, msg = client_lib.check_blenderkit_client_return_code()
        self.assertEqual(code, 43)
        self.assertIn("Address already in use", msg)

    def test_return_code_access_denied(self):
        global_vars.client_process = mock.Mock(poll=mock.Mock(return_value=44))
        code, msg = client_lib.check_blenderkit_client_return_code()
        self.assertEqual(code, 44)
        self.assertIn("Access denied", msg)


class TestDecideClientBinaryName(unittest.TestCase):
    def test_windows_amd64(self):
        with (
            mock.patch.object(client_lib.platform, "system", return_value="Windows"),
            mock.patch.object(client_lib.platform, "machine", return_value="AMD64"),
            mock.patch.object(client_lib, "_is_pre_windows_10", return_value=False),
        ):
            self.assertEqual(
                client_lib.decide_client_binary_name(),
                "bk_client-windows-x86_64.exe",
            )

    def test_windows_amd64_pre_win10_uses_legacy(self):
        with (
            mock.patch.object(client_lib.platform, "system", return_value="Windows"),
            mock.patch.object(client_lib.platform, "machine", return_value="AMD64"),
            mock.patch.object(client_lib, "_is_pre_windows_10", return_value=True),
        ):
            self.assertEqual(
                client_lib.decide_client_binary_name(),
                "bk_client-windows7-x86_64.exe",
            )

    def test_windows_arm64_pre_win10_stays_modern(self):
        # No legacy ARM build exists; ARM Windows is Windows 10+ only anyway.
        with (
            mock.patch.object(client_lib.platform, "system", return_value="Windows"),
            mock.patch.object(client_lib.platform, "machine", return_value="ARM64"),
            mock.patch.object(client_lib, "_is_pre_windows_10", return_value=True),
        ):
            self.assertEqual(
                client_lib.decide_client_binary_name(),
                "bk_client-windows-arm64.exe",
            )

    def test_linux_aarch64(self):
        with (
            mock.patch.object(client_lib.platform, "system", return_value="Linux"),
            mock.patch.object(client_lib.platform, "machine", return_value="aarch64"),
        ):
            self.assertEqual(
                client_lib.decide_client_binary_name(),
                "bk_client-linux-arm64",
            )

    def test_macos_renamed_from_darwin(self):
        with (
            mock.patch.object(client_lib.platform, "system", return_value="Darwin"),
            mock.patch.object(client_lib.platform, "machine", return_value="arm64"),
        ):
            self.assertEqual(
                client_lib.decide_client_binary_name(),
                "bk_client-macos-arm64",
            )


class TestClientLogPath(unittest.TestCase):
    def setUp(self):
        self._saved_ports = global_vars.CLIENT_PORTS

    def tearDown(self):
        global_vars.CLIENT_PORTS = self._saved_ports

    def test_default_port_names_default_log(self):
        global_vars.CLIENT_PORTS = ["62485"]
        with mock.patch.object(
            client_lib, "get_client_directory", return_value=os.sep + "logs"
        ):
            log_path = client_lib.get_client_log_path()
        self.assertTrue(log_path.endswith("default.log"))

    def test_non_default_port_names_client_log(self):
        global_vars.CLIENT_PORTS = ["49452"]
        with mock.patch.object(
            client_lib, "get_client_directory", return_value=os.sep + "logs"
        ):
            log_path = client_lib.get_client_log_path()
        self.assertTrue(log_path.endswith("client-49452.log"))
