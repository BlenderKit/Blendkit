"""Search price lookup helper."""

from __future__ import annotations

import time
import logging
from typing import Iterable, List, Optional, Tuple

from . import client_lib, paths, utils

bk_logger = logging.getLogger(__name__)

# Simple in-memory cache to avoid repeated price lookups per version UUID.
# TTL keeps cache fresh-ish while drastically reducing chatter on paged searches.
_PRICE_CACHE: dict[str, tuple[float, dict]] = {}
_PRICE_CACHE_TTL_SEC = 300.0  # 5 minutes is plenty for session-level reuse


def _cache_get(uuid: str) -> Optional[dict]:
    entry = _PRICE_CACHE.get(uuid)
    if not entry:
        return None
    ts, payload = entry
    if time.perf_counter() - ts > _PRICE_CACHE_TTL_SEC:
        _PRICE_CACHE.pop(uuid, None)
        return None
    return payload


def _cache_put(uuid: str, payload: dict) -> None:
    _PRICE_CACHE[uuid] = (time.perf_counter(), payload)


def clear_price_cache() -> None:
    """Clear cached price responses (e.g. on login/logout/user switch)."""
    _PRICE_CACHE.clear()


def _normalize_version_uuid_list(values: Optional[Iterable[str]]) -> List[str]:
    if values is None:
        return []

    normalized: List[str] = []
    for value in values:
        if not value:
            continue
        as_str = str(value)
        if as_str not in normalized:
            normalized.append(as_str)
    return normalized


def query_user_price(
    version_uuids: list[str] = [],
    page_size: int = 15,
    timeout: Tuple[float, float] = (1, 30),
) -> list[dict]:
    """Return results for price lookup of multiple asset versions.

    The server endpoint now expects a POST body with `version_uuids`, so we keep
    the helper focused on returning the correct URL alongside the JSON payload
    that should be sent in the request.
    """

    if isinstance(version_uuids, str):
        version_uuids = [version_uuids]

    version_uuid_list = _normalize_version_uuid_list(version_uuids)
    if page_size > 0:
        version_uuid_list = version_uuid_list[:page_size]

    if not version_uuid_list:
        raise ValueError("No version UUIDs provided for price lookup.")

    # Pull cached entries first.
    fresh_uuids: list[str] = []
    cached_results: list[dict] = []
    for vu in version_uuid_list:
        cached = _cache_get(vu)
        if cached is None:
            fresh_uuids.append(vu)
        else:
            cached_results.append(cached)

    fetched_results: list[dict] = []
    if fresh_uuids:
        payload: dict = {"version_uuids": fresh_uuids}
        url = f"{paths.BLENDKIT_API}/cart/request-price-bulk/"

        headers = utils.get_simple_headers()
        headers.setdefault("Content-Type", "application/json")
        response = client_lib.blocking_request(
            url,
            "POST",
            headers,
            json_data=payload,
            timeout=timeout,
        )
        fetched_results = response.json() or []
        bk_logger.debug("Fetched price for %d version UUIDs", len(fetched_results))

        for entry in fetched_results:
            version_uuid = entry.get("versionUuid")
            if not version_uuid:
                continue
            _cache_put(str(version_uuid), entry)

    # Merge cached + fetched for the caller; order doesn't matter.
    merged = []
    merged.extend(cached_results)
    merged.extend(fetched_results)
    return merged
