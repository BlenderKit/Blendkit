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

import dataclasses
import getpass
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from os import path
from typing import Optional, Union
from http.client import responses as http_responses


import bpy
import requests

from . import datas, global_vars, reports, utils

bk_logger = logging.getLogger(__name__)
NO_PROXIES = {"http": "", "https": ""}
TIMEOUT = (0.1, 1)
# Shorter timeout for the frequent report polling that runs on Blender's main thread.
# Kept small so a slow Client never blocks the UI for long, but not so small that
# a momentarily busy (but alive) Client is mistaken for dead and needlessly
# respawned - see handle_failed_reports / is_client_process_alive.
POLL_TIMEOUT = (0.05, 0.5)

# When the user's global_dir (default ~/blenderkit_data) is not writable - which
# happens for sandboxed Blender installs (Microsoft Store, some Linux packages,
# locked-down corporate environments) - we cannot copy the Blendkit-Client
# binary into global_dir/client/bin/vX.Y.Z. In that case we fall back to
# running the binary in-place directly from the add-on directory.
# This module-level flag is set once per Blender session and is sticky so all
# subsequent calls (binary path, log path) consistently use the fallback.
_use_inplace_client: bool = False
_inplace_notice_shown: bool = False


def get_address() -> str:
    """Get address of the Blendkit-Client."""
    return f"http://127.0.0.1:{get_port()}"


def get_port() -> str:
    """Get the most probable port of currently running Blendkit-Client.
    After add-on registration and if all goes well, the port is the same as
    """
    return global_vars.CLIENT_PORTS[0]


def get_api_version() -> str:
    """Get version of API Client is expected to use. To keep stuff simple the API version is derrived from Client's version.
    From Client version vX.Y.Z we remove the .Z part to effectively get the vX.Y version of the API. For nonbreaking changes
    we increase the patch version of the Client. If the change breaks the API, then increase of minor/major version is expected.
    ``global_vars.CLIENT_VERSION`` is normally already the minor pin (vX.Y), but
    we stay tolerant of a full vX.Y.Z value too.
    """
    splitted = global_vars.CLIENT_VERSION.split(".")
    if len(splitted) >= 3:
        return ".".join(splitted[:2])
    return global_vars.CLIENT_VERSION


def get_base_url() -> str:
    """The base URL on which we will interact with the Blendkit Client. Consists from address with port + version API path.
    All requests to Client goes to URLs starting with base URL in format: 127.0.0.1:{port}/vX.Y
    """
    address = get_address()
    vapi = get_api_version()
    return f"{address}/{vapi}"


def _read_api_key_threadsafe() -> str:
    """Return the user's API key without touching bpy from a non-main thread.
    On the main thread we read the live preference. On a worker thread we read
    the snapshot maintained by client_thread (updated each main timer tick).
    """
    if threading.current_thread() is threading.main_thread():
        try:
            return bpy.context.preferences.addons[__package__].preferences.api_key  # type: ignore
        except (AttributeError, KeyError):
            return ""
    # Lazy import to avoid circular dependency at module load time.
    from . import client_thread

    return client_thread.get_cached_api_key()


def ensure_minimal_data(data: Optional[dict] = None) -> dict:
    """Ensure that the data send to the Blendkit-Client contains:
    - app_id is the process ID of the Blender instance, so Blendkit-client can return reports to the correct instance.
    - api_key is the authentication token for the Blendkit server, so Blendkit-Client can authenticate the user.
    - addon_version is the version of the Blendkit add-on, so Blendkit-client has understanding of the version of the add-on making the request.
    """
    if data is None:
        data = {}

    av = global_vars.VERSION
    addon_version = f"{av[0]}.{av[1]}.{av[2]}.{av[3]}"
    if "api_key" not in data:
        # for BG instances and worker threads, fall back to a thread-safe accessor
        data.setdefault("api_key", _read_api_key_threadsafe())
    data.setdefault("app_id", os.getpid())
    data.setdefault("platform_version", platform.platform())
    data.setdefault("addon_version", addon_version)

    return data


def ensure_minimal_data_class(data_class: datas.SearchData) -> datas.SearchData:
    """Ensure that the data send to the Blendkit-Client contains:
    - app_id is the process ID of the Blender instance, so Blendkit-client can return reports to the correct instance.
    - api_key is the authentication token for the Blendkit server, so Blendkit-Client can authenticate the user.
    - addon_version is the version of the Blendkit add-on, so Blendkit-client has understanding of the version of the add-on making the request.
    """
    if data_class == None:
        data_class = dataclasses.dataclass()

    av = global_vars.VERSION
    if hasattr(data_class, "api_key"):
        # for BG instances, where preferences are not available
        api_key = bpy.context.preferences.addons[__package__].preferences.api_key
        setattr(data_class, "api_key", api_key)
    setattr(data_class, "app_id", os.getpid())
    setattr(data_class, "platform_version", platform.platform())
    setattr(data_class, "addon_version", f"{av[0]}.{av[1]}.{av[2]}.{av[3]}")
    return data_class


def reorder_ports(port: str = ""):
    """Reorder CLIENT_PORTS so the specified port is first.
    If no port is specified, the current first port is moved to back so second becomes the first.
    """
    if port == "":
        i = 1
    else:
        i = global_vars.CLIENT_PORTS.index(port)
    global_vars.CLIENT_PORTS = (
        global_vars.CLIENT_PORTS[i:] + global_vars.CLIENT_PORTS[:i]
    )
    bk_logger.info(
        f"Ports reordered so first port is now {global_vars.CLIENT_PORTS[0]} (previous index was {i})"
    )


def build_report_data(app_id: int) -> dict:
    """Construct the JSON body sent to the /report endpoint.
    Touches bpy and so MUST be called from the main thread.
    Worker threads should consume the dict produced here, not call this themselves.
    """
    data = ensure_minimal_data({"app_id": app_id})
    data["project_name"] = utils.get_project_name()
    data["blender_version"] = utils.get_blender_version()
    return data


def get_report_url(port: Optional[str] = None) -> str:
    """Return the /report endpoint URL for the current (or a specific) port."""
    vapi = get_api_version()
    if port is None:
        return f"{get_base_url()}/report"
    return f"http://127.0.0.1:{port}/{vapi}/report"


def get_reports(app_id: int):
    """Get reports for all tasks of app_id Blender instance at once.
    If few last calls failed, then try to get reports also from other than default ports.
    """
    data = build_report_data(app_id)

    # on 10, there is second Blendkit-Client start
    if global_vars.CLIENT_FAILED_REPORTS < 10:
        return request_report(get_report_url(), data)

    last_exception = None
    for port in global_vars.CLIENT_PORTS:
        url = get_report_url(port)
        try:
            report = request_report(url, data)
            bk_logger.warning(
                f"Got reports from Blendkit-Client on port {port}, setting it as default for this instance"
            )
            reorder_ports(port)
            return report
        except Exception as e:
            bk_logger.info("Failed to get Blendkit-Client reports: %s", e)
            last_exception = e
    if last_exception is not None:
        raise last_exception


def request_report(url: str, data: dict) -> dict:
    """Make HTTP request to /report endpoint. If all goes well a JSON dict is returned.
    If something goes south, this function raises requests.HTTPError or requests.JSONDecodeError.
    """
    with requests.Session() as session:
        resp = session.get(url, json=data, timeout=POLL_TIMEOUT, proxies=NO_PROXIES)
        if resp.status_code != 200:
            # not using resp.raise_for_status() for better message
            raise requests.HTTPError(
                f"{http_responses[resp.status_code]}: {resp.text}", response=resp
            )
        return resp.json()


### ASSETS
# SEARCH
def asset_search(search_data: datas.SearchData):
    """Search for specified asset."""
    bk_logger.info("Starting search request: %s", search_data.urlquery)

    search_data = ensure_minimal_data_class(search_data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_search"
        resp = session.post(
            url, json=datas.asdict(search_data), timeout=TIMEOUT, proxies=NO_PROXIES
        )
        bk_logger.log(5, "Got search response")
        return resp.json()


# DOWNLOAD
def asset_download(data):
    """Download specified asset."""
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_download"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


def cancel_download(task_id: str):
    """Cancel the specified task with ID on the Blendkit-Client."""
    data = ensure_minimal_data({"task_id": task_id})
    with requests.Session() as session:
        url = get_base_url() + "/blender/cancel_download"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def asset_prxc_download(
    asset_base_id: str, download_url: str, file_path: str, scene_uuid: str
):
    """Schedule a single .prxc proxy mesh download on the Blendkit-Client.

    Fire-and-forget: the client creates a ``prxc_download`` task whose
    completion is delivered via the normal task channel and handled by
    ``search.handle_prxc_download_task``.
    """
    data = {
        "assetBaseId": asset_base_id,
        "download_url": download_url,
        "file_path": file_path,
        "scene_uuid": scene_uuid,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_prxc_download"
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp.json()


# UPLOAD
def asset_upload(upload_data, export_data, upload_set):
    """Upload specified asset."""
    data = {
        "PREFS": utils.get_preferences_as_dict(),
        "upload_data": upload_data,
        "export_data": export_data,
        "upload_set": upload_set,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/blender/asset_upload"
        bk_logger.debug("making a request to: %s", url)
        resp = session.post(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


### PROFILES
def download_gravatar_image(author_data: datas.UserProfile) -> requests.Response:
    """Fetch gravatar image for specified user. Find it on disk or download it from server."""
    data = {
        "id": author_data.id,
        "avatar128": author_data.avatar128,
        "gravatarHash": author_data.gravatarHash,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        url = get_base_url() + "/profiles/download_gravatar_image"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def get_user_profile() -> requests.Response:
    """Fetch profile of currently logged-in user.
    This creates task on Blendkit-Client to fetch data which are later handled once available.
    """
    data = ensure_minimal_data()
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/profiles/get_user_profile",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### COMMENTS
def get_comments(asset_id, api_key=""):
    """Get all comments on the asset."""
    data = ensure_minimal_data({"asset_id": asset_id})
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/comments/get_comments",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def create_comment(asset_id, comment_text, api_key, reply_to_id=0):
    """Create a new comment."""
    data = {
        "asset_id": asset_id,
        "comment_text": comment_text,
        "reply_to_id": reply_to_id,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/comments/create_comment",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def feedback_comment(asset_id, comment_id, api_key, flag="like"):
    """Feedback the comment - by default with like. Other flags can be used also."""
    data = {
        "asset_id": asset_id,
        "comment_id": comment_id,
        "flag": flag,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/comments/feedback_comment",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def mark_comment_private(asset_id, comment_id, api_key, is_private=False):
    """Mark the comment as private or public."""
    data = {
        "asset_id": asset_id,
        "comment_id": comment_id,
        "is_private": is_private,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/comments/mark_comment_private",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### NOTIFICATIONS
def mark_notification_read(notification_id):
    """Mark the notification as read on the server."""
    data = ensure_minimal_data({"notification_id": notification_id})
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/notifications/mark_notification_read",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### REPORTS
def report_usages(data: dict):
    """Report usages of assets in current scene via Blendkit-Client to the server."""
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/report_usages",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# RATINGS
def get_rating(asset_id: str):
    data = ensure_minimal_data({"asset_id": asset_id})
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/ratings/get_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


def send_rating(asset_id: str, rating_type: str, rating_value: Union[str, int]):
    data = {
        "asset_id": asset_id,
        "rating_type": rating_type,
        "rating_value": rating_value,
    }
    if rating_type == "bookmarks":
        data["rating_value"] = int(rating_value)  # type: ignore

    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.post(
            f"{get_base_url()}/ratings/send_rating",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


# BOOKMARKS
def get_bookmarks():
    data = ensure_minimal_data()
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/ratings/get_bookmarks",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### BLOCKING WRAPPERS
def get_download_url(asset_data, scene_id, api_key):
    """Get download url from server. This is a blocking wrapper, will not return until results are available.
    Returns: (bool, str, str) - can_download, download_url, filename.
    """
    data = {
        "resolution": "blend",
        "asset_data": asset_data,
        "api_key": api_key,  # needs to be here, because prefs are not available in BG instances
        "PREFS": {
            "api_key": api_key,
            "scene_id": scene_id,
        },
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_base_url()}/wrappers/get_download_url",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        resp = resp.json()
        return (resp["can_download"], resp["download_url"], resp["filename"])


def complete_upload_file_blocking(
    api_key, asset_id, filepath, filetype: str, fileindex: int
) -> bool:
    """Complete file upload in just one step, blocks until upload is finished. Useful for background scripts."""
    data = {
        "api_key": api_key,
        "assetId": asset_id,
        "fileType": filetype,
        "fileIndex": fileindex,
        "filePath": filepath,
        "originalFilename": os.path.basename(filepath),  # teoreticky asi nemusi byt
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        resp = session.get(
            f"{get_base_url()}/wrappers/complete_upload_file_blocking",
            json=data,
            timeout=(1, 600),
            proxies=NO_PROXIES,
        )

        print("complete_upload_file_blocking resp:", resp)
        return resp.ok


def blocking_file_download(url: str, filepath: str, api_key: str) -> requests.Response:
    """Upload file to server. This is a blocking wrapper, will not return until results are available."""
    data = {
        "url": url,
        "filepath": filepath,
    }
    data = ensure_minimal_data(data)
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/blocking_file_download",
            json=data,
            timeout=(1, 600),
            proxies=NO_PROXIES,
        )


def blocking_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    json_data: Optional[dict] = None,
    timeout: tuple = TIMEOUT,
) -> requests.Response:
    """Make blocking HTTP request through Blendkit-Client.
    Will not return until results are available."""
    if headers is None:
        headers = {}
    data = {
        "url": url,
        "method": method,
        "headers": headers,
    }
    if json_data is not None:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/blocking_request",
            json=data,
            timeout=timeout,
            proxies=NO_PROXIES,
        )


### REQUEST WRAPPERS
def nonblocking_request(
    url: str,
    method: str,
    headers: Optional[dict] = None,
    json_data: Optional[dict] = None,
    messages: Optional[dict] = None,
) -> requests.Response:
    """Make non-blocking HTTP request through Blendkit-Client.
    This function will return ASAP, not returning any actual data.
    """
    if headers is None:
        headers = {}
    if messages is None:
        messages = {}
    data = {
        "url": url,
        "method": method,
        "headers": headers,
        "messages": messages,
    }
    data = ensure_minimal_data(data)
    if json_data is not None:
        data["json"] = json_data
    with requests.Session() as session:
        return session.get(
            f"{get_base_url()}/wrappers/nonblocking_request",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )


### AUTHORIZATION
def send_oauth_verification_data(code_verifier, state: str):
    """Send OAUTH2 Code Verifier and State parameters to Blendkit-Client.
    So it can later use them to authenticate the redirected response from the browser.
    """
    data = ensure_minimal_data(
        {
            "code_verifier": code_verifier,
            "state": state,
        }
    )
    with requests.Session() as session:
        resp = session.post(
            f"{get_base_url()}/oauth2/verification_data",
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def refresh_token(refresh_token, old_api_key):
    """Refresh authentication token. Blendkit-Client will use refresh token to get new API key token to replace the old_api_key.
    old_api_key is used later to replace token only in Blender instances with the same api_key. (User can be logged into multiple accounts.)
    """
    bk_logger.info("Calling API token refresh")
    data = ensure_minimal_data({"refresh_token": refresh_token})
    with requests.Session() as session:
        url = get_base_url() + "/refresh_token"
        resp = session.get(
            url,
            json=data,
            timeout=TIMEOUT,
            proxies=NO_PROXIES,
        )
        return resp


def oauth2_logout():
    """Logout from OAUTH2. Blendkit-Client will revoke the token on the server."""
    data = ensure_minimal_data()
    data["refresh_token"] = global_vars.PREFS["api_key_refresh"]
    with requests.Session() as session:
        url = get_base_url() + "/oauth2/logout"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def unsubscribe_addon():
    """Unsubscribe the add-on from the Blendkit-Client. Called when the add-on is disabled, uninstalled or when Blender is closed."""
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = get_base_url() + "/blender/unsubscribe_addon"
        resp = session.get(url, json=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def shutdown_client():
    """Request to shutdown the Blendkit-Client."""
    data = ensure_minimal_data()
    with requests.Session() as session:
        url = get_base_url() + "/shutdown"
        resp = session.get(url, data=data, timeout=TIMEOUT, proxies=NO_PROXIES)
        return resp


def handle_client_status_task(task):
    if global_vars.CLIENT_RUNNING is False:
        wm = bpy.context.window_manager
        wm.blenderkitUI.logo_status = "logo"
    global_vars.CLIENT_RUNNING = True


def is_client_process_alive() -> bool:
    """Return True if we spawned a Blendkit-Client subprocess that is still running.

    Used to avoid respawning the Client on a transient poll timeout: a live but
    momentarily busy Client would otherwise get a duplicate spawned, which then
    fails to bind the same port (WSAEADDRINUSE) and dies - the respawn loop that
    pins the CPU. Only when no live process exists is a (re)start warranted.
    """
    proc = global_vars.client_process
    return proc is not None and proc.poll() is None


def check_blenderkit_client_return_code() -> tuple[int, str]:
    """Check the return code for the started Blendkit-Client. If the return code returned from process.poll() is None - returned by this func as -1, it means Client still runs - we consider this a success!
    However if the return code from poll() is present, it failed to start and we check the return code value. If the return code is known,
    we print information to user about the reason. So they do not need to dig in the Client log.
    """
    # Return codes - as defined in main.go
    rcServerStartOtherError = 40
    rcServerStartOtherNetworkingError = 41
    rcServerStartOtherSyscallError = 42
    rcServerStartSyscallEADDRINUSE = 43
    rcServerStartSyscallEACCES = 44
    if global_vars.client_process is None:
        return -2, "Unexpectedly global_vars.client_process is None"

    exit_code = global_vars.client_process.poll()
    if exit_code is None:
        return -1, "Blendkit-Client process is running."

    # need to initialize msg, was throwing an error
    msg = f"Unknown error."
    if exit_code == rcServerStartOtherError:
        msg = f"Other starting problem."
    if exit_code == rcServerStartOtherNetworkingError:
        msg = f"Other networking problem."
    if exit_code == rcServerStartOtherSyscallError:
        msg = f"Other syscall error."

    if exit_code == rcServerStartSyscallEADDRINUSE:  # This is known solution
        return (
            exit_code,
            "Address already in use: please change the port in add-on preferences.",
        )
    if exit_code == rcServerStartSyscallEACCES:  # This needs verification
        return (
            exit_code,
            "Access denied: change port in preferences, check permissions and antivirus rights.",
        )

    message = (
        f"{msg} Please report a bug and paste content of log {get_client_log_path()}"
    )
    return exit_code, message


def start_blenderkit_client():
    """Start Blendkit-client in separate process.
    1. Check if binary is available at global_dir/client/vX.Y.Z/bk_client-<os>-<arch>(.exe)
    2. Copy the binary from add-on directory to global_dir/client/vX.Y.Z/, or fall back
       to running the binary in-place from the add-on directory if the global_dir is not writable.
    3. Start the Blendkit-Client process which serves as bridge between Blendkit add-on and Blendkit server.
    """
    global _use_inplace_client
    ensure_client_binary_installed()
    log_path = get_client_log_path()
    client_binary_path, client_version = get_client_binary_path()

    creation_flags = 0
    if platform.system() == "Windows":
        creation_flags = subprocess.CREATE_NO_WINDOW

    # Open the log file. If even that fails (global_dir/client exists but is
    # not writable - e.g. UWP virtualized location), switch to in-place mode
    # which redirects the log to the system temp dir.
    try:
        log_file = open(log_path, "wb")
    except (PermissionError, OSError) as e:
        bk_logger.warning(
            "Cannot open Client log at %s: %s. Switching to in-place mode.",
            log_path,
            e,
        )
        _use_inplace_client = True
        log_path = get_client_log_path()
        client_binary_path, client_version = get_client_binary_path()
        try:
            log_file = open(log_path, "wb")
        except (PermissionError, OSError) as e2:
            bk_logger.error(
                "Cannot open fallback Client log at %s: %s. Client cannot start.",
                log_path,
                e2,
            )
            raise

    try:
        with log_file as log:
            global_vars.client_process = subprocess.Popen(
                args=[
                    client_binary_path,
                    "--port",
                    get_port(),
                    "--server",
                    global_vars.SERVER,
                    "--proxy_which",
                    global_vars.PREFS.get("proxy_which", ""),
                    "--proxy_address",
                    global_vars.PREFS.get("proxy_address", ""),
                    "--trusted_ca_certs",
                    global_vars.PREFS.get("trusted_ca_certs", ""),
                    "--ssl_context",
                    global_vars.PREFS.get("ssl_context", ""),
                    "--version",
                    f"{global_vars.VERSION[0]}.{global_vars.VERSION[1]}.{global_vars.VERSION[2]}.{global_vars.VERSION[3]}",
                    "--software",
                    "Blender",
                    "--pid",
                    str(os.getpid()),
                ],
                stdout=log,
                stderr=log,
                creationflags=creation_flags,
            )
    except Exception as e:
        msg = f"Error: Blendkit-Client {client_version} failed to start on {get_address()}:{e}"
        reports.add_report(msg, type="ERROR")
        raise (e)

    bk_logger.info("Blendkit-Client %s starting on %s", client_version, get_address())


def decide_client_binary_name() -> str:
    """Decide the name of the Blendkit-Client binary based on the current operating system and architecture.
    We unify the OS and CPU architecture naming to make it more accessible for general public.
    Darwin is renamed to MacOS. The CPU architecture is aligned to x86_64 or arm64.
    On pre-Windows-10 machines (Windows 7/8/8.1) the dedicated legacy binary is
    used, because the standard binary is built with a modern Go toolchain that
    requires Windows 10+.
    Possible return values:
    - bk_client-windows-x86_64.exe
    - bk_client-windows-arm64.exe
    - bk_client-windows7-x86_64.exe
    - bk_client-linux-x86_64
    - bk_client-linux-arm64
    - bk_client-macos-x86_64
    - bk_client-macos-arm64
    """
    os_name = platform.system().lower()
    if os_name == "darwin":  # more user-friendly name for macOS
        os_name = "macos"

    architecture = platform.machine().lower()
    if architecture == "amd64":  # align Windows convention
        architecture = "x86_64"
    elif architecture == "aarch64":  # align Linux convention
        architecture = "arm64"

    if os_name == "windows":
        if architecture == "x86_64" and _is_pre_windows_10():
            return "bk_client-windows7-x86_64.exe"
        return f"bk_client-{os_name}-{architecture}.exe".lower()

    return f"bk_client-{os_name}-{architecture}".lower()


def _is_pre_windows_10() -> bool:
    """True on Windows 7/8/8.1 (anything older than Windows 10).

    Used to select the legacy Client binary, since the standard build requires
    Windows 10+. Non-Windows platforms always return False.
    """
    if platform.system().lower() != "windows":
        return False
    try:
        winver = sys.getwindowsversion()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    # Windows 10/11 report major version 10; Windows 7/8/8.1 report major 6.
    return (winver.major, winver.minor) < (10, 0)


def get_client_directory() -> str:
    """Get the path to the Blendkit-Client directory located in global_dir."""
    global_dir = bpy.context.preferences.addons[__package__].preferences.global_dir  # type: ignore
    directory = path.join(global_dir, "client")
    return directory


def is_using_inplace_client() -> bool:
    """True if Blendkit-Client is being run in-place from the add-on directory
    because we couldn't install it into global_dir/client/bin/vX.Y.Z.
    """
    return _use_inplace_client


def _get_fallback_client_log_dir() -> str:
    """Return a writable directory for the Client log when global_dir is not writable.
    Mirrors the temp-dir scheme used by paths.get_temp_dir() so the location is predictable.
    """
    try:
        username = getpass.getuser()
    except (
        ModuleNotFoundError,
        KeyError,
        OSError,
    ):  # KeyError on Windows when USERNAME env var is missing (e.g. sandboxed/Store installs)
        username = "bkuser"
    safe_username = "".join(c for c in username if c.isalnum())
    log_dir = path.join(tempfile.gettempdir(), f"bktemp_{safe_username}", "client")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        # Last resort: just use the temp root, which is virtually always writable.
        log_dir = tempfile.gettempdir()
    return log_dir


def get_client_log_path() -> str:
    """Get path to Blendkit-Client log file.
    Normally located in global_dir/client. If we are running the client in-place
    (because global_dir is not writable), the log file is placed under the system
    temp directory instead.
    If the port is the default port 62485, the log file is named default.log,
    otherwise it is named client-<port>.log.
    """
    port = get_port()
    log_name = "default.log" if port == "62485" else f"client-{port}.log"
    if _use_inplace_client:
        log_dir = _get_fallback_client_log_dir()
    else:
        log_dir = get_client_directory()
    return path.abspath(path.join(log_dir, log_name))


_resolved_client_version = None


def get_resolved_client_version() -> str:
    """Exact vX.Y.Z of the bundled Blendkit-Client binary.

    Read once from ``client/RESOLVED_VERSION`` in the add-on directory, which is
    written at build time from the exact GitHub release that was downloaded
    (bk_client auto-bumps the patch on each PR). Falls back to
    ``global_vars.CLIENT_VERSION`` (the minor pin) when the file is missing -
    e.g. a plain source checkout that has not been built yet.
    """
    global _resolved_client_version
    if _resolved_client_version:
        return _resolved_client_version
    addon_dir = path.dirname(__file__)
    version_file = path.join(addon_dir, "client", "RESOLVED_VERSION")
    try:
        with open(version_file) as f:
            resolved = f.read().strip()
    except OSError:
        resolved = ""
    _resolved_client_version = resolved or global_vars.CLIENT_VERSION
    return _resolved_client_version


def get_preinstalled_client_path() -> str:
    """Get the path to the preinstalled Blendkit-Client binary - located in add-on directory.
    This is the binary that is shipped with the add-on. It is copied to global_dir/client/vX.Y.Z on first run.
    """
    addon_dir = path.dirname(__file__)
    binary_name = decide_client_binary_name()
    binary_path = path.join(
        addon_dir, "client", get_resolved_client_version(), binary_name
    )
    return path.abspath(binary_path)


def get_client_binary_path():
    """Get the path to the Blendkit-Client binary that should be executed.
    Normally this is the copy in global_dir/client/bin/vX.Y.Z. We do not start
    from the add-on directory because that might block update or delete of the
    add-on. However, when global_dir is not writable (e.g. Microsoft Store
    Blender, sandboxed installs) we fall back to running the binary in-place
    from the add-on directory.
    Returns: (str, str) - path to the Client binary, version of the Client binary
    """
    ver_string = get_resolved_client_version()
    if _use_inplace_client:
        return get_preinstalled_client_path(), ver_string
    client_dir = get_client_directory()
    binary_name = decide_client_binary_name()
    binary_path = path.join(client_dir, "bin", ver_string, binary_name)
    return path.abspath(binary_path), ver_string


def ensure_client_binary_installed():
    """Ensure that the Blendkit-Client binary is available for execution.
    Preferred location is global_dir/client/bin/vX.Y.Z. If the binary is not
    there yet, we copy it from the add-on directory blenderkit/client.
    As a side effect, this function also creates the global_dir/client/bin/vX.Y.Z
    directory.
    If the target directory is not writable (e.g. Microsoft Store Blender or
    other sandboxed installs), we switch the module into in-place mode and
    return without raising. The Client will then be started directly from the
    add-on directory.
    """
    global _use_inplace_client, _inplace_notice_shown
    if _use_inplace_client:
        return  # already decided to run from the add-on directory

    client_binary_path, _ = get_client_binary_path()
    if path.exists(client_binary_path):
        return

    preinstalled_client_path = get_preinstalled_client_path()
    bk_logger.info("Copying Blendkit-Client binary %s", preinstalled_client_path)
    try:
        os.makedirs(path.dirname(client_binary_path), exist_ok=True)
        shutil.copy(preinstalled_client_path, client_binary_path)
        os.chmod(client_binary_path, 0o711)
    except (PermissionError, OSError) as e:
        bk_logger.warning(
            "Cannot install Blendkit-Client to %s: %s. "
            "Falling back to in-place execution from the add-on directory.",
            path.dirname(client_binary_path),
            e,
        )
        _use_inplace_client = True
        if not _inplace_notice_shown:
            _inplace_notice_shown = True
            try:
                reports.add_report(
                    "Blendkit could not copy the Client binary to your global "
                    "directory (read-only or sandboxed). Running the Client "
                    "in-place from the add-on folder instead.",
                    timeout=10,
                    type="WARNING",
                )
            except Exception:  # pragma: no cover - defensive
                pass
        return
    bk_logger.info("Blendkit-Client binary copied to %s", client_binary_path)


def get_addon_dir():
    """Get the path to the add-on directory."""
    addon_dir = path.dirname(__file__)
    return addon_dir
