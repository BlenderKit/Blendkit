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

"""Background communication thread for the Blendkit-Client.

The legacy code path makes every HTTP roundtrip to the local Go client on
Blender's main thread. Even on 127.0.0.1 these calls can block long enough to
stutter the UI when the client is busy. This module moves report polling and
explicitly opted-in fire-and-forget requests onto a daemon worker thread.

The module is opt-in: it is only activated when both ``experimental_features``
and ``thread_communication`` preferences are True. When disabled the worker is
stopped and timer.py falls back to the original synchronous path.

Threading rules:
    * The worker thread MUST NOT touch ``bpy.*`` or any Blender data.
    * The main thread is the only writer of the request state snapshot; the
      worker only reads it.
    * Tasks parsed from reports are still dispatched (``handle_task``) on the
      main thread. The worker just shuttles bytes over the wire.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

import requests


bk_logger = logging.getLogger(__name__)

NO_PROXIES = {"http": "", "https": ""}
# This poll runs on the worker thread, not Blender's main thread, so a longer
# read timeout here does NOT stutter the UI. A generous value lets a busy Client
# finish answering instead of being treated as unreachable (which would trigger
# a needless restart on the main thread).
POLL_TIMEOUT = (0.05, 2.0)
DEFAULT_TIMEOUT = (0.1, 1.0)
# Cap the worker's self-throttling so we keep checking on the Client.
_MAX_BACKOFF_SECONDS = 5.0
# Worst-case sleep between iterations; keeps outbound queue latency bounded.
_MAX_SLEEP_SECONDS = 0.1


# --- Shared state (main thread writer, worker reader) ---
_state_lock = threading.Lock()
_report_url: Optional[str] = None
_report_data: Optional[dict] = None
_report_fallback_urls: List[str] = []
_poll_interval: float = 0.2
_api_key_snapshot: str = ""

# --- Communication queues ---
# Outbound: main thread -> worker. Each item is (callable, args, kwargs) or None (wakeup).
_outbound_queue: "queue.Queue[Optional[Tuple[Callable, tuple, dict]]]" = queue.Queue()
# Inbound: worker -> main thread. Each item is a list of report dicts from the Client.
_reports_queue: "queue.Queue[List[Any]]" = queue.Queue()

# --- Single-slot state surfaced from worker to main thread ---
_error_lock = threading.Lock()
_last_error: Optional[BaseException] = None
# Port that started responding after a failover. Main thread reorders ports when set.
_recovered_port: Optional[str] = None

# --- Worker thread handle ---
_thread_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
# Worker-local: number of consecutive failed polls. Used to back off the worker
# without spamming the main thread with duplicate errors.
_consecutive_failures = 0


def is_running() -> bool:
    """True when the worker thread is alive."""
    with _thread_lock:
        return _thread is not None and _thread.is_alive()


def update_state(
    report_url: str,
    report_data: dict,
    fallback_urls: Optional[List[str]] = None,
    poll_interval: float = 0.2,
    api_key: str = "",
) -> None:
    """Refresh the worker's view of the request state.
    Called from the main thread on every ``client_communication_timer`` tick so
    the worker always has fresh values for project_name / api_key / port list.
    """
    global _report_url, _report_data, _report_fallback_urls, _poll_interval
    global _api_key_snapshot
    with _state_lock:
        _report_url = report_url
        _report_data = dict(report_data)
        _report_fallback_urls = list(fallback_urls) if fallback_urls else []
        _poll_interval = max(0.05, float(poll_interval))
        _api_key_snapshot = api_key


def get_cached_api_key() -> str:
    """Worker-thread accessor for the current api_key snapshot."""
    with _state_lock:
        return _api_key_snapshot


def submit_request(func: Callable, *args, **kwargs) -> None:
    """Queue a fire-and-forget callable to run on the worker thread.

    The callable's return value is dropped. The callable MUST be safe to call
    off the main thread - it cannot touch ``bpy.*``. Use this for outbound
    requests where the caller does not need the response (ratings, comments
    moderation, mark-notification-read, report_usages).
    """
    _outbound_queue.put((func, args, kwargs))


def submit_post(
    url: str, data: dict, timeout: Tuple[float, float] = DEFAULT_TIMEOUT
) -> None:
    """Fire-and-forget POST. The URL and data dict must be fully built on the
    main thread before submission."""
    _outbound_queue.put((_do_post, (url, data, timeout), {}))


def submit_get(
    url: str, data: dict, timeout: Tuple[float, float] = DEFAULT_TIMEOUT
) -> None:
    """Fire-and-forget GET. The URL and data dict must be fully built on the
    main thread before submission."""
    _outbound_queue.put((_do_get, (url, data, timeout), {}))


def drain_reports() -> Tuple[List[List[Any]], Optional[BaseException], Optional[str]]:
    """Pop everything the worker has produced since the last drain.
    Returns ``(batches, last_error, recovered_port)``. Called on the main thread.

    Errors are coalesced into a single slot - only the latest failure is surfaced
    between drains. The worker self-throttles while errors persist, so the main
    thread typically sees at most one error per drain in practice.
    """
    global _last_error, _recovered_port
    batches: List[List[Any]] = []
    while True:
        try:
            batches.append(_reports_queue.get_nowait())
        except queue.Empty:
            break
    with _error_lock:
        err = _last_error
        port = _recovered_port
        _last_error = None
        _recovered_port = None
    return batches, err, port


def reset_failure_count() -> None:
    """Main thread tells the worker that the client is healthy again."""
    global _consecutive_failures
    _consecutive_failures = 0


def start() -> None:
    """Ensure the worker thread is running. Idempotent."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(
            target=_worker_loop, name="Blendkit-ClientComm", daemon=True
        )
        _thread.start()
    bk_logger.info("Blendkit client communication thread started")


def stop(timeout: float = 1.0) -> None:
    """Signal the worker to exit and wait briefly for it to do so."""
    global _thread
    with _thread_lock:
        thread = _thread
        if thread is None or not thread.is_alive():
            _thread = None
            return
        _stop_event.set()
    # Wake the worker if it is sleeping on the outbound queue.
    try:
        _outbound_queue.put_nowait(None)
    except Exception:
        pass
    thread.join(timeout=timeout)
    with _thread_lock:
        _thread = None
    bk_logger.info("Blendkit client communication thread stopped")


def _do_post(url: str, data: dict, timeout: Tuple[float, float]) -> None:
    with requests.Session() as session:
        session.post(url, json=data, timeout=timeout, proxies=NO_PROXIES)


def _do_get(url: str, data: dict, timeout: Tuple[float, float]) -> None:
    with requests.Session() as session:
        session.get(url, json=data, timeout=timeout, proxies=NO_PROXIES)


def _drain_outbound() -> None:
    """Process every queued outbound request. Called from the worker thread."""
    while True:
        try:
            item = _outbound_queue.get_nowait()
        except queue.Empty:
            return
        if item is None:
            continue  # wakeup sentinel from stop()
        func, args, kwargs = item
        try:
            func(*args, **kwargs)
        except Exception:
            bk_logger.exception("Outbound Blendkit-Client request failed")


def _extract_port(url: str) -> Optional[str]:
    """Pull the port from a URL like http://127.0.0.1:62485/v1.2/report."""
    try:
        host_port = url.split("//", 1)[1].split("/", 1)[0]
        return host_port.rsplit(":", 1)[1]
    except (IndexError, ValueError):
        return None


def _poll_reports() -> None:
    """Try to fetch reports. Push results or the latest error into the queues."""
    global _consecutive_failures, _last_error, _recovered_port
    with _state_lock:
        url = _report_url
        data = dict(_report_data) if _report_data is not None else None
        fallback_urls = list(_report_fallback_urls)
    if url is None or data is None:
        return  # main thread has not seeded state yet

    # On long failure streaks try the alternative ports the main thread knows
    # about. The main thread will reorder its preferred port if we recover.
    urls_to_try: List[str] = [url]
    if _consecutive_failures >= 10 and fallback_urls:
        urls_to_try = fallback_urls

    last_exception: Optional[BaseException] = None
    for try_url in urls_to_try:
        try:
            with requests.Session() as session:
                resp = session.get(
                    try_url, json=data, timeout=POLL_TIMEOUT, proxies=NO_PROXIES
                )
            if resp.status_code != 200:
                raise requests.HTTPError(
                    f"{resp.status_code}: {resp.text}", response=resp
                )
            results = resp.json()
            _reports_queue.put(results)
            _consecutive_failures = 0
            with _error_lock:
                _last_error = None
                if try_url != url:
                    _recovered_port = _extract_port(try_url)
            return
        except Exception as e:
            last_exception = e
            continue

    _consecutive_failures += 1
    if last_exception is not None:
        with _error_lock:
            # Single-slot: keep only the most recent error so we don't hand
            # the main thread N copies to handle.
            _last_error = last_exception


def _worker_loop() -> None:
    """Main loop of the worker thread."""
    global _consecutive_failures
    last_poll = 0.0
    while not _stop_event.is_set():
        _drain_outbound()

        with _state_lock:
            interval = _poll_interval

        # Self-throttle on consecutive failures so the main thread isn't
        # buried under duplicate errors before it can react.
        if _consecutive_failures > 0:
            effective_interval = min(
                interval * (1 + _consecutive_failures), _MAX_BACKOFF_SECONDS
            )
        else:
            effective_interval = interval

        now = time.monotonic()
        if now - last_poll >= effective_interval:
            last_poll = now
            try:
                _poll_reports()
            except Exception:
                bk_logger.exception("Unexpected error in Blendkit poll worker")
                # Surface as a regular failure so backoff logic kicks in.
                _consecutive_failures += 1

        sleep_for = min(effective_interval / 4, _MAX_SLEEP_SECONDS)
        if _stop_event.wait(timeout=sleep_for):
            break

    bk_logger.info("Blendkit client communication worker exited")
