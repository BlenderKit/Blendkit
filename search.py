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

import copy
import json
import logging
import math
import os
import re
import shutil
import unicodedata
import urllib.parse
import uuid
from typing import Optional, Union

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from .asset_bar import asset_bar_op
from . import (
    categories,
    client_lib,
    client_tasks,
    clipboard_x11,
    datas,
    download,
    global_vars,
    icons,
    image_utils,
    paths,
    reports,
    search_price,
    resolutions,
    tasks_queue,
    ui_bgl,
    utils,
)

if bpy.app.version >= (4, 2, 0):
    from . import override_extension_draw
else:
    override_extension_draw = None


bk_logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 80
"""Maximum number of assets to fetch per search page."""

search_tasks = {}


# ------------------------------------------------------------------
# Active filter helpers (per tab)
# ------------------------------------------------------------------


def _ensure_tab_filters(tab: dict) -> list[dict]:
    if "active_filters" not in tab:
        tab["active_filters"] = []
    if tab["active_filters"] is None:
        tab["active_filters"] = []
    return tab["active_filters"]


def get_active_filters(tab: Optional[dict] = None) -> list[dict]:
    tab = tab or get_active_tab()
    return copy.deepcopy(_ensure_tab_filters(tab))


PANEL_FILTER_TERMS: set[str] = {
    "style",
    "geometry_nodes",
    "design_year",
    "polycount",
    "texture_resolution",
    "file_size",
    "condition",
    "animated",
    "free_only",
    "bookmarks",
    "quality_limit",
    "license",
    "blender_version",
    "order",
    "category",
}


def _collect_panel_filters() -> list[dict]:
    """Translate UI filter state into active filter chip descriptors."""
    ui_props = bpy.context.window_manager.blenderkitUI
    sprops = utils.get_search_props()
    preferences = bpy.context.preferences.addons[__package__].preferences

    panel_filters: list[dict] = []

    if ui_props.free_only:
        panel_filters.append(
            {"term": "free_only", "value": "true", "label": "Free first"}
        )

    if ui_props.search_bookmarks:
        panel_filters.append(
            {"term": "bookmarks", "value": "true", "label": "Bookmarks"}
        )

    if getattr(sprops, "search_style", "ANY") != "ANY":
        panel_filters.append(
            {
                "term": "style",
                "value": sprops.search_style,
                "label": sprops.search_style.capitalize(),
            }
        )

    if getattr(sprops, "search_condition", "UNSPECIFIED") != "UNSPECIFIED":
        panel_filters.append(
            {
                "term": "condition",
                "value": sprops.search_condition,
                "label": sprops.search_condition.capitalize(),
            }
        )

    if getattr(sprops, "search_design_year", False):
        label = f"{sprops.search_design_year_min}-{sprops.search_design_year_max}"
        panel_filters.append(
            {
                "term": "design_year",
                "value": label,
                "label": label,
            }
        )

    if getattr(sprops, "search_polycount", False):
        label = f"Poly {sprops.search_polycount_min}-{sprops.search_polycount_max}"
        panel_filters.append(
            {
                "term": "polycount",
                "value": label,
                "label": label,
            }
        )

    if getattr(sprops, "search_texture_resolution", False):
        label = f"TexRes {sprops.search_texture_resolution_min}-{sprops.search_texture_resolution_max}"
        panel_filters.append(
            {
                "term": "texture_resolution",
                "value": label,
                "label": label,
            }
        )

    if getattr(sprops, "search_file_size", False):
        label = f"File {sprops.search_file_size_min}-{sprops.search_file_size_max}MB"
        panel_filters.append(
            {
                "term": "file_size",
                "value": label,
                "label": label,
            }
        )

    if getattr(sprops, "search_animated", False):
        panel_filters.append({"term": "animated", "value": "true", "label": "Animated"})

    if getattr(sprops, "search_geometry_nodes", False):
        panel_filters.append(
            {
                "term": "geometry_nodes",
                "value": "true",
                "label": "GeoNodes",
            }
        )

    if ui_props.quality_limit > 0:
        panel_filters.append(
            {
                "term": "quality_limit",
                "value": str(ui_props.quality_limit),
                "label": f"Q≥{ui_props.quality_limit}",
            }
        )

    if ui_props.search_license != "ANY":
        panel_filters.append(
            {
                "term": "license",
                "value": ui_props.search_license,
                "label": ui_props.search_license,
            }
        )

    if ui_props.search_blender_version:
        label = f"Blender {ui_props.search_blender_version_min}-{ui_props.search_blender_version_max}"
        panel_filters.append(
            {
                "term": "blender_version",
                "value": label,
                "label": label,
            }
        )

    if ui_props.search_order_by != "default":
        panel_filters.append(
            {
                "term": "order",
                "value": ui_props.search_order_by,
                "label": ui_props.search_order_by,
            }
        )

    # NSFW is intentionally left out; it already changes server query and badge state.

    category = getattr(sprops, "search_category", "")
    if category and category != ui_props.asset_type.lower():
        bkit_categories = global_vars.DATA.get("bkit_categories") or []
        name_path = categories.get_category_name_path(bkit_categories, category)
        label = name_path[-1] if name_path else category.split("/")[-1]
        panel_filters.append({"term": "category", "value": category, "label": label})

    return panel_filters


def _sync_panel_filters_into_active(tab: dict):
    """Merge panel-derived filters with existing ad-hoc filters (e.g., manufacturer)."""
    current = _ensure_tab_filters(tab)
    preserved = [f for f in current if f.get("term") not in PANEL_FILTER_TERMS]
    tab["active_filters"] = preserved + _collect_panel_filters()


def set_active_filter(
    term: str,
    value: str,
    label: Optional[str] = None,
    origin: Optional[str] = None,
):
    tab = get_active_tab()
    filters = _ensure_tab_filters(tab)
    # drop existing entry for the same term to keep one value per term for now
    filters = [f for f in filters if f.get("term") != term]
    filters.append(
        {"term": term, "value": value, "label": label or value, "origin": origin}
    )
    tab["active_filters"] = filters


def remove_active_filter(term: str, value: Optional[str] = None):
    tab = get_active_tab()
    filters = _ensure_tab_filters(tab)
    if term in PANEL_FILTER_TERMS:
        _clear_panel_filter(term)
    if value is None:
        filters = [f for f in filters if f.get("term") != term]
    else:
        filters = [
            f
            for f in filters
            if not (f.get("term") == term and f.get("value") == value)
        ]
    tab["active_filters"] = filters


def set_active_filters_for_tab(tab: dict, filters: list[dict]):
    tab["active_filters"] = copy.deepcopy(filters) if filters else []


def search_by_author_id(author_id: str, author_name: str = ""):
    """Set author filter, clean keywords of author name parts, and run search.

    This is the single entry point for all "search by author" actions:
    asset bar click, keyboard shortcut, popup card button, etc.
    """
    author_id = str(author_id)
    if not author_name or author_name == author_id:
        author = global_vars.BKIT_AUTHORS.get(int(author_id))
        if author:
            full = f"{author.firstName} {author.lastName}".strip()
            if full:
                author_name = full
    if not author_name:
        author_name = author_id

    ui_props = bpy.context.window_manager.blenderkitUI
    keywords = ui_props.search_keywords
    if keywords and author_name:
        kw_parts = keywords.split()
        if len(kw_parts) <= 1:
            # Single word — user was clearly searching for this author, clear it
            keywords = ""
        else:
            name_parts = author_name.lower().split()
            keywords = " ".join(w for w in kw_parts if w.lower() not in name_parts)
    # Strip any legacy +author_id: from keywords
    keywords = re.sub(r"\+author_id:\d+", "", keywords).strip()
    ui_props.search_keywords = keywords

    sprops = utils.get_search_props()
    if utils.profile_is_validator():
        sprops.search_verification_status = "ALL"

    set_active_filter(
        term="author_id",
        value=author_id,
        label=author_name,
        origin="data",
    )
    update_filters()
    create_history_step(get_active_tab())
    search()


def _clear_panel_filter(term: str):
    """Reset underlying filter props when a panel-derived chip is removed."""
    ui_props = bpy.context.window_manager.blenderkitUI
    sprops = utils.get_search_props()

    if term == "style" and hasattr(sprops, "search_style"):
        sprops.search_style = "ANY"
    elif term == "condition" and hasattr(sprops, "search_condition"):
        sprops.search_condition = "UNSPECIFIED"
    elif term == "design_year" and hasattr(sprops, "search_design_year"):
        sprops.search_design_year = False
    elif term == "polycount" and hasattr(sprops, "search_polycount"):
        sprops.search_polycount = False
    elif term == "texture_resolution" and hasattr(sprops, "search_texture_resolution"):
        sprops.search_texture_resolution = False
    elif term == "file_size" and hasattr(sprops, "search_file_size"):
        sprops.search_file_size = False
    elif term == "animated" and hasattr(sprops, "search_animated"):
        sprops.search_animated = False
    elif term == "geometry_nodes" and hasattr(sprops, "search_geometry_nodes"):
        sprops.search_geometry_nodes = False
    elif term == "free_only":
        ui_props.free_only = False
    elif term == "bookmarks":
        ui_props.search_bookmarks = False
    elif term == "quality_limit":
        ui_props.quality_limit = 0
    elif term == "license":
        ui_props.search_license = "ANY"
    elif term == "blender_version":
        ui_props.search_blender_version = False
    elif term == "order":
        ui_props.search_order_by = "default"
    elif term == "category" and hasattr(sprops, "search_category"):
        sprops.search_category = ""
        # Reset the category browse path back to the root for this asset type
        asset_type = ui_props.asset_type
        active_browse = global_vars.DATA.get("active_category_browse")
        if active_browse is not None and asset_type in active_browse:
            active_browse[asset_type] = [asset_type.lower()]


def get_active_filter_keywords(tab: Optional[dict] = None) -> list[str]:
    tab = tab or get_active_tab()
    filters = _ensure_tab_filters(tab)
    tokens = []
    for f in filters:
        term = f.get("term")
        value = f.get("value")
        # Panel-derived filters (style, free_only, order, etc.) are represented
        # directly in query parameters and should not emit keyword tokens.
        if term in PANEL_FILTER_TERMS:
            continue
        if term and value:
            tokens.append(f"+{term}:{value}")
    return tokens


def _inject_user_price_data(assets: list[dict]) -> None:
    """Augment search results with per-user pricing info when available."""
    if not assets:
        bk_logger.debug("User price lookup skipped: empty assets list.")
        return

    version_uuids: list[str] = [ass["id"] for ass in assets]
    if not version_uuids:
        bk_logger.debug("User price lookup skipped: empty version UUIDs list.")
        return

    try:
        # returns entry per versionUuid
        price_response = search_price.query_user_price(
            version_uuids=version_uuids,
            page_size=len(version_uuids),
        )
    except Exception as exc:
        bk_logger.warning("Failed to fetch user prices: %s", exc)
        return

    if not price_response:
        bk_logger.debug(
            "User price lookup skipped: %s",
            price_response,
        )
        return

    price_by_uuid: dict[str, dict] = {}
    for entry in price_response:
        base_uuid = entry.get("versionUuid")
        if not base_uuid:
            continue
        price_by_uuid[base_uuid] = entry

    if not price_by_uuid:
        return

    for asset in assets:
        base_uuid = asset["id"]
        price_info = price_by_uuid.get(base_uuid)
        if not price_info:
            continue
        asset["userPrice"] = price_info["discountedPrice"]


def update_ad(ad):
    if not ad.get("assetBaseId"):
        try:
            ad["assetBaseId"] = ad[
                "asset_base_id"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["assetType"] = ad[
                "asset_type"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["verificationStatus"] = ad[
                "verification_status"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["author"] = {}
            ad["author"]["id"] = ad[
                "author_id"
            ]  # this should stay ONLY for compatibility with older scenes
            ad["canDownload"] = ad[
                "can_download"
            ]  # this should stay ONLY for compatibility with older scenes
        except Exception as e:
            bk_logger.error("Blendkit failed to update older asset data")
    return ad


def update_assets_data():  # updates assets data on scene load.
    """updates some properties that were changed on scenes with older assets.
    The properties were mainly changed from snake_case to CamelCase to fit the data that is coming from the server.
    """
    datablocks = [
        bpy.data.objects,
        bpy.data.materials,
        bpy.data.brushes,
    ]
    for dtype in datablocks:
        for block in dtype:
            if block.get("asset_data") is not None:
                update_ad(block["asset_data"])

    dicts = [
        "assets used",
    ]
    for s in bpy.data.scenes:
        for bkdict in dicts:
            d = s.get(bkdict)
            if not d:
                continue

            for asset_id in d.keys():
                update_ad(d[asset_id])
                # bpy.context.scene['assets used'][ad] = ad


@persistent
def undo_post_reload_previews(context):
    load_previews()


@persistent
def undo_pre_end_assetbar(context):
    ui_props = bpy.context.window_manager.blenderkitUI

    ui_props.turn_off = True
    ui_props.assetbar_on = False


@persistent
def scene_load(context):
    """Load categories, check timers registration, and update scene asset data.
    Should (probably) also update asset data from server (after user consent).
    """
    update_assets_data()


last_clipboard = ""


def check_clipboard():
    """Check clipboard for an exact string containing asset ID.
    The string is generated on www.blendkit.com as for example here:
    https://www.blendkit.com/get-blendkit/54ff5c85-2c73-49e9-ba80-aec18616a408/
    """
    global last_clipboard
    if clipboard_x11.is_available():
        # X11: bounded, non-blocking read so a dead selection owner cannot hang
        # Blender's main thread (issue #2244). None = unreadable this tick, skip.
        current_clipboard = clipboard_x11.get_clipboard_text()
        if current_clipboard is None:
            return
    else:
        try:  # could be problematic on Linux
            current_clipboard = str(bpy.context.window_manager.clipboard)
        except Exception as e:
            bk_logger.warning("Failed to get clipboard: %s", e)
            return

    if current_clipboard == last_clipboard:
        return

    asset_type_index = current_clipboard.find("asset_type:")
    if asset_type_index == -1:
        return

    if not current_clipboard.startswith("asset_base_id:"):
        return

    last_clipboard = current_clipboard

    asset_type_string = current_clipboard[asset_type_index:].lower()
    if asset_type_string.find("model") > -1:
        target_asset_type = "MODEL"
    elif asset_type_string.find("material") > -1:
        target_asset_type = "MATERIAL"
    elif asset_type_string.find("brush") > -1:
        target_asset_type = "BRUSH"
    elif asset_type_string.find("scene") > -1:
        target_asset_type = "SCENE"
    elif asset_type_string.find("hdr") > -1:
        target_asset_type = "HDR"
    elif asset_type_string.find("printable") > -1:
        target_asset_type = "PRINTABLE"
    elif asset_type_string.find("nodegroup") > -1:
        target_asset_type = "NODEGROUP"
    elif asset_type_string.find("addon") > -1 or asset_type_string.find("add-on") > -1:
        target_asset_type = "ADDON"
    elif asset_type_string.find("artist") > -1 or asset_type_string.find("author") > -1:
        target_asset_type = "AUTHOR"
    else:
        bk_logger.debug("Clipboard does not contain valid asset type.")
        return

    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.asset_type != target_asset_type:
        ui_props.asset_type = target_asset_type  # switch asset type before placing keywords, so it does not search under wrong asset type

    # all modifications in
    ui_props.search_keywords = current_clipboard[:asset_type_index].rstrip()


def parse_author_result(r) -> dict:
    """Parse an author-type search result into asset_data with safe defaults.

    Author results have full author data in the ``author`` sub-object (same
    structure as regular assets).  We use it to populate ``BKIT_AUTHORS`` and
    fetch the gravatar, then synthesize the remaining fields that downstream
    code expects but the server doesn't provide for authors.
    """
    author_id = r.get("id", r.get("author", {}).get("id", 0))
    display_name = r.get("displayName", r.get("name", ""))

    asset_data = {
        "thumbnail": "",
        "thumbnail_small": "",
        "downloaded": 0,
        "available_resolutions": [],
        "max_resolution": 0,
        "filesSize": 0,
        "dictParameters": {},
        "files": [],
        "verificationStatus": "validated",
        "canDownload": False,
        "isFree": True,
        "score": 0,
        "ratingsCount": {},
        "ratingsAverage": {},
        "assetBaseId": str(author_id),
        "displayName": display_name,
    }

    # Process full author profile data (fetches gravatar, populates BKIT_AUTHORS)
    # NOTE: generate_author_profile sends id to the GO client which expects int,
    # so we must NOT convert id to string before calling it (same as parse_result).
    adata = r.get("author")
    if adata and isinstance(adata, dict) and len(adata) > 1:
        # Full author data available — parse it like regular assets do
        author = datas.UserProfile.from_dict(adata)
        generate_author_profile(author)
        r["author"]["id"] = str(r["author"]["id"])
    else:
        # Minimal author data — just ensure id is a string
        if "author" not in r:
            r["author"] = {"id": str(author_id)}
        else:
            r["author"]["id"] = str(r["author"]["id"])

    # Apply server data, then re-apply safe defaults for any fields that ended
    # up as None or empty (Go serializes nil maps/slices as null → Python None,
    # and some string fields come back as "" instead of a valid value).
    safe_defaults = {
        "dictParameters": {},
        "files": [],
        "ratingsCount": {},
        "ratingsAverage": {},
        "verificationStatus": "validated",
    }
    asset_data.update(r)
    for key, default in safe_defaults.items():
        if not asset_data.get(key):
            asset_data[key] = default
    return asset_data


# TODO: type annotate and check this crazy function!
# Are we sure it behaves correctly on network issues, malfunctioning search etc?
def parse_result(r) -> dict:
    """Parse search result into an asset_data by tweaking some of its parameters.
    We need to generate some extra data in the result (for now).
    Parameters
    ----------
    r - search result, also called asset_data
    """
    scene = bpy.context.scene
    # TODO remove this fix when filesSize is fixed.
    # this is a temporary fix for too big numbers from the server.
    # can otherwise get the Python int too large to convert to C int
    try:
        r["filesSize"] = int(r["filesSize"] / 1024)
    except:
        utils.p("asset with no files-size")

    asset_type = r["assetType"]
    if asset_type == "author":
        return parse_author_result(r)

    adata = r["author"]
    author = datas.UserProfile.from_dict(adata)
    generate_author_profile(author)

    r["available_resolutions"] = []
    use_webp = True
    if bpy.app.version < (3, 4, 0) or r.get("webpGeneratedTimestamp", 0) == 0:
        use_webp = False  # WEBP was optimized in Blender 3.4.0

    # BIG THUMB - HDR CASE
    if r["assetType"] == "hdr":
        if use_webp:
            thumb_url = r.get("thumbnailLargeUrlNonsquaredWebp")
        else:
            thumb_url = r.get("thumbnailLargeUrlNonsquared")
    # BIG THUMB - NON HDR CASE
    else:
        if use_webp:
            thumb_url = r.get("thumbnailMiddleUrlWebp")
        else:
            thumb_url = r.get("thumbnailMiddleUrl")

    # SMALL THUMB
    if use_webp:
        small_thumb_url = r.get("thumbnailSmallUrlWebp")
    else:
        small_thumb_url = r.get("thumbnailSmallUrl")

    tname = paths.extract_filename_from_url(thumb_url)
    small_tname = paths.extract_filename_from_url(small_thumb_url)
    for f in r["files"]:
        # if f['fileType'] == 'thumbnail':
        #     tname = paths.extract_filename_from_url(f['fileThumbnailLarge'])
        #     small_tname = paths.extract_filename_from_url(f['fileThumbnail'])
        #     allthumbs.append(tname)  # TODO just first thumb is used now.

        if f["fileType"] == "blend":
            durl = f["downloadUrl"].split("?")[0]
            # fname = paths.extract_filename_from_url(f['filePath'])

        if f["fileType"].find("resolution") > -1:
            r["available_resolutions"].append(resolutions.resolutions[f["fileType"]])

    # code for more thumbnails
    # tdict = {}
    # for i, t in enumerate(allthumbs):
    #     tdict['thumbnail_%i'] = t

    r["max_resolution"] = 0
    if r["available_resolutions"]:  # should check only for non-empty sequences
        r["max_resolution"] = max(r["available_resolutions"])

    # tooltip = generate_tooltip(r)
    # for some reason, the id was still int on some occurrences. investigate this.
    r["author"]["id"] = str(r["author"]["id"])

    # some helper props, but generally shouldn't be renaming/duplifiying original properties,
    # so blender's data is same as on server.
    asset_data = {
        "thumbnail": tname,
        "thumbnail_small": small_tname,
        # 'tooltip': tooltip,
    }
    asset_data["downloaded"] = 0

    # parse extra params needed for blender here
    params = r["dictParameters"]  # utils.params_to_dict(r['parameters'])

    if asset_type in ["model", "printable"]:
        if (
            params.get("boundBoxMinX") != None
            and params.get("boundBoxMinY") != None
            and params.get("boundBoxMinZ") != None
            and params.get("boundBoxMaxX") != None
            and params.get("boundBoxMaxY") != None
            and params.get("boundBoxMaxZ") != None
        ):
            bbox = {
                "bbox_min": (
                    float(params["boundBoxMinX"]),
                    float(params["boundBoxMinY"]),
                    float(params["boundBoxMinZ"]),
                ),
                "bbox_max": (
                    float(params["boundBoxMaxX"]),
                    float(params["boundBoxMaxY"]),
                    float(params["boundBoxMaxZ"]),
                ),
            }

        else:
            bbox = {"bbox_min": (-0.5, -0.5, 0), "bbox_max": (0.5, 0.5, 1)}
        asset_data.update(bbox)
    if asset_type == "material":
        asset_data["texture_size_meters"] = params.get("textureSizeMeters", 1.0)

    # asset_data.update(tdict)

    au = scene.get("assets used", {})  # type: ignore
    if au == {}:
        scene["assets used"] = au  # type: ignore
    if r["assetBaseId"] in au.keys():
        asset_data["downloaded"] = 100
        # transcribe all urls already fetched from the server
        r_previous = au[r["assetBaseId"]]
        if r_previous.get("files"):
            for f in r_previous["files"]:
                if f.get("url"):
                    for f1 in r["files"]:
                        if f1["fileType"] == f["fileType"]:
                            f1["url"] = f["url"]

    # attempt to switch to use original data gradually, since the parsing as itself should become obsolete.
    asset_data.update(r)

    # Compute a unified upload date used for client-side sorting.
    # lastBlendUpload is null for zip-based assets (e.g. VDB volumes),
    # lastZipFileUpload is null/empty for blend-based assets.
    # Pick the newest of the two; fall back to "created" so every asset has a value.
    last_blend = asset_data.get("lastBlendUpload") or ""
    last_zip = asset_data.get("lastZipFileUpload") or ""
    asset_data["last_upload"] = max(last_blend, last_zip) or asset_data.get(
        "created", ""
    )

    return asset_data


def clear_searches():
    global search_tasks
    search_tasks.clear()


def cleanup_search_results():
    """Cleanup all search results in history steps and global vars."""
    # First clean up history steps
    for history_step in get_history_steps().values():
        history_step.pop("search_results", None)
        history_step.pop("search_results_orig", None)


def handle_search_task_error(task: client_tasks.Task) -> None:
    """Handle incoming search task error."""
    # First find the history step that the task belongs to
    for history_step in get_history_steps().values():
        if task.task_id in history_step.get("search_tasks", {}).keys():
            history_step["is_searching"] = False
            break
    return reports.add_report(task.message, type="ERROR", details=task.message_detailed)


def handle_search_task(task: client_tasks.Task) -> bool:
    """Parse search results, try to load all available previews."""
    global search_tasks

    if len(search_tasks) == 0:
        # First find the history step that the task belongs to
        history_step = get_history_step(task.data.get("history_id", ""))
        if history_step is not None:
            history_step["is_searching"] = False
        return True

    # don't do anything while dragging - this could switch asset during drag, and make results list length different,
    # causing a lot of trouble.
    if bpy.context.window_manager.blenderkitUI.dragging:  # type: ignore[attr-defined]
        return False

    # if original task was already removed (because user initiated another search), results are dropped- Returns True
    # because that's OK.
    orig_task = search_tasks.get(task.task_id)
    if orig_task is None:
        return True

    search_tasks.pop(task.task_id)

    # this fixes black thumbnails in asset bar, test if this bug still persist in blender and remove if it's fixed
    if bpy.app.version < (3, 3, 0):
        sys_prefs = bpy.context.preferences.system
        sys_prefs.gl_texture_limit = "CLAMP_OFF"

    ###################

    props = utils.get_search_props()

    # Get current history step
    history_step = get_history_step(orig_task.history_id)

    if not task.data.get("get_next"):
        result_field = []  # type: ignore
    else:
        # Strip trailing placeholder entries before appending real results
        previous = history_step.get("search_results", []) or []
        result_field = [r for r in previous if not r.get("placeholder")]  # type: ignore

    ui_props = bpy.context.window_manager.blenderkitUI  # type: ignore[attr-defined]
    for result in task.result["results"]:
        asset_data = parse_result(result)
        if not asset_data:
            bk_logger.warning("Parsed asset data are empty for search result", result)
            continue

        result_field.append(asset_data)

    # Flush batched gravatar downloads via Go client
    _flush_pending_gravatars()

    # Comments are fetched lazily on hover (asset bar tooltip) / on popup to
    # avoid hammering the backend rate-limit (100 req/min). See
    # comments_utils.request_comments_if_needed().

    # Results are kept strictly in arrival order. The asset bar relies on
    # stable positions: once an asset is placed it must never move, otherwise
    # the layout (and the user's scroll position) jumps every time a new page
    # arrives. This applies to authors as well — they are appended in the
    # order the backend returned them and are never promoted/resorted on the
    # client.
    #
    # A previous version did a client-side coalesced sort by
    # max(lastBlendUpload, lastZipFileUpload) here so that zip-only assets
    # (e.g. VDB volumes) interleaved with blend-based ones. That re-sort was
    # applied to the union of all already-fetched pages on every get_next,
    # which actively reshuffled previously-placed items. The proper fix
    # belongs on the server (a single coalesced "-last_core_upload" sort
    # key); until then, we trust the server order verbatim.

    # Apply addon-specific status checking and filtering if needed
    if ui_props.asset_type == "ADDON":
        # Always process addon search results to store installation status
        result_field = filter_addon_search_results(
            result_field, filter_installed_only=False
        )

        addon_props = bpy.context.window_manager.blenderkit_addon
        if addon_props.search_installed:
            # Filter to only show installed addons, but preserve author results
            result_field = [
                asset
                for asset in result_field
                if asset.get("assetType") == "author" or asset.get("downloaded", 0) > 0
            ]
        if addon_props.search_compatible_only:
            # Filter out addons that don't support the running Blender version.
            result_field = [
                asset
                for asset in result_field
                if asset.get("assetType") != "addon"
                or utils.is_addon_blender_compatible(asset)
            ]

        # TODO: if ever needed, implement for other future types
        if result_field:
            _inject_user_price_data(result_field)
            if override_extension_draw is not None:
                override_extension_draw.update_cache_with_asset_prices(result_field)

    # Store results in history step
    history_step["search_results"] = result_field
    history_step["search_results_orig"] = task.result
    history_step["is_searching"] = False

    if len(result_field) < ui_props.scroll_offset or not (task.data.get("get_next")):
        # jump back
        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.scroll_offset = 0
        ui_props.scroll_offset = 0

    # show asset bar automatically, but only on first page - others are loaded also when asset bar is hidden.
    if not ui_props.assetbar_on and not task.data.get("get_next"):
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]

    if len(result_field) < ui_props.scroll_offset or not (task.data.get("get_next")):
        # jump back
        ui_props.scroll_offset = 0
    props.report = f"Found {task.result['count']} results."
    if len(result_field) == 0:
        tasks_queue.add_task((reports.add_report, ("No matching results found.",)))
    else:
        tasks_queue.add_task(
            (
                reports.add_report,
                (f"Found {task.result['count']} results.",),
            )
        )
    # show asset bar automatically, but only on first page - others are loaded also when asset bar is hidden.
    if not ui_props.assetbar_on and not task.data.get("get_next"):
        bpy.ops.view3d.run_assetbar_fix_context(keep_running=True, do_search=False)  # type: ignore[attr-defined]

    return True


def handle_thumbnail_download_task(task: client_tasks.Task) -> None:
    if task.status == "finished":
        global_vars.DATA["images available"][task.data["image_path"]] = True
        ui_bgl.path_to_gpu_texture(task.data["image_path"])
    elif task.status == "error":
        global_vars.DATA["images available"][task.data["image_path"]] = False
        if task.message != "":
            bk_logger.warning(
                "Thumbnail download failed (%s): %s",
                task.data.get("thumbnail_type", "unknown"),
                task.message,
            )
    else:
        return
    if asset_bar_op.asset_bar_operator is None:
        return

    if task.data["thumbnail_type"] == "small":
        asset_bar_op.asset_bar_operator.update_image(task.data["assetBaseId"])
        return

    if task.data["thumbnail_type"] == "full":
        asset_bar_op.asset_bar_operator.update_tooltip_image(task.data["assetBaseId"])
        return

    if task.data["thumbnail_type"] in {"photo_full", "wire_full"}:
        asset_bar_op.asset_bar_operator.needs_tooltip_update = True
        return


def handle_prxc_download_task(task: client_tasks.Task) -> None:
    """Handle completed .prxc proxy mesh download.

    On success we keep the file in temp and only mark it as available.
    Persisting it next to the downloaded .blend is deferred until the asset
    download itself finishes.
    """
    asset_base_id = task.data.get("assetBaseId", "")
    file_path = task.data.get("file_path", "")
    if task.status == "finished" and file_path:
        global_vars.DATA.setdefault("prxc available", {})[asset_base_id] = file_path
        bk_logger.debug(f"prxc available in temp for {asset_base_id}: {file_path}")
    elif task.status == "error":
        bk_logger.debug(f"prxc download failed for {asset_base_id}: {task.message}")


def persist_prxc_after_asset_download(asset_data: dict) -> None:
    """Persist cached .prxc next to the downloaded model/printable asset.

    This must be called only after the main asset download has finished.
    """
    asset_type = asset_data.get("assetType")
    if asset_type not in ("model", "printable"):
        return

    asset_base_id = asset_data.get("assetBaseId", "")
    if not asset_base_id:
        return

    src_path = global_vars.DATA.get("prxc available", {}).get(asset_base_id, "")
    if not src_path or not os.path.exists(src_path):
        return

    persistent_path = _copy_prxc_to_asset_dir(asset_base_id, src_path)
    if persistent_path:
        global_vars.DATA.setdefault("prxc available", {})[
            asset_base_id
        ] = persistent_path
        bk_logger.debug(
            f"prxc persisted after asset download for {asset_base_id}: {persistent_path}"
        )


def _copy_prxc_to_asset_dir(asset_base_id: str, src_path: str) -> str:
    """Copy *src_path* to the asset's persistent download directory.

    Looks up the asset in the current search results by ``assetBaseId``.  If
    found, the file is copied to the first candidate asset directory as
    ``{assetBaseId}.prxc``.  The directory is created when it does not yet
    exist (the model download may arrive later).

    Returns the destination path on success, or an empty string on failure.
    """
    if not src_path or not os.path.exists(src_path):
        return ""

    # Find the asset data in the active search results.
    asset_data = None
    for result in get_search_results():
        if result.get("assetBaseId") == asset_base_id:
            asset_data = result
            break

    if asset_data is None:
        bk_logger.debug(
            f"prxc: asset {asset_base_id} not in search results, keeping temp path"
        )
        return ""

    try:
        asset_dirs = paths.get_asset_directories(asset_data)
        if not asset_dirs:
            return ""
        # A single .prxc file applies to every resolution of the asset, so
        # the first directory (primary/highest resolution) is a sufficient
        # canonical location; other resolutions will find it via lookup.
        dest_dir = asset_dirs[0]
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{asset_base_id}.prxc")
        shutil.copy2(src_path, dest_path)
        bk_logger.debug(f"prxc copied to asset dir: {dest_path}")
        return dest_path
    except Exception as e:
        bk_logger.warning(f"prxc: failed to copy to asset dir: {e}")
        return ""


def load_preview(asset):
    # FIRST START SEARCH
    props = bpy.context.window_manager.blenderkitUI
    directory = paths.get_temp_dir("%s_search" % props.asset_type.lower())

    tpath = os.path.join(directory, asset["thumbnail_small"])
    tpath_exists = os.path.exists(tpath)
    if (
        not asset["thumbnail_small"]
        or asset["thumbnail_small"] == ""
        or not tpath_exists
    ):
        # tpath = paths.get_addon_thumbnail_path('thumbnail_notready.jpg')
        asset["thumb_small_loaded"] = False

    iname = f".{asset['thumbnail_small']}"
    # if os.path.exists(tpath):  # sometimes we are unlucky...
    img = bpy.data.images.get(iname)

    if img is None or len(img.pixels) == 0:
        if not tpath_exists:
            return False
        # wrap into try statement since sometimes
        try:
            img = bpy.data.images.load(tpath, check_existing=True)
            img.name = iname
            if len(img.pixels) > 0:
                return True
        except Exception as e:
            print(f"search.py: could not load image {iname}: {e}")
        return False
    elif img.filepath != tpath:
        if not tpath_exists:
            # unload loaded previews from previous results
            bpy.data.images.remove(img)
            return False
        # had to add this check for autopacking files...
        if bpy.data.use_autopack and img.packed_file is not None:
            img.unpack(method="USE_ORIGINAL")
        img.filepath = tpath
        try:
            img.reload()
        except Exception as e:
            print(f"search.py: could not reload image {iname}: {e}")
            return False

    image_utils.set_colorspace(img)
    asset["thumb_small_loaded"] = True
    return True


def load_previews():
    results = get_search_results()
    if results is None:
        return
    for _, result in enumerate(results):
        load_preview(result)


#  line splitting for longer texts...
def split_subs(text, threshold=40):
    if text == "":
        return []
    # temporarily disable this, to be able to do this in drawing code

    text = text.rstrip()
    text = text.replace("\r\n", "\n")

    lines = []

    while len(text) > threshold:
        # first handle if there's an \n line ending
        i_rn = text.find("\n")
        if 1 < i_rn < threshold:
            i = i_rn
            text = text.replace("\n", "", 1)
        else:
            i = text.rfind(" ", 0, threshold)
            i1 = text.rfind(",", 0, threshold)
            i2 = text.rfind(".", 0, threshold)
            i = max(i, i1, i2)
            if i <= 0:
                i = threshold
        lines.append(text[:i])
        text = text[i:]
    lines.append(text)
    return lines


def list_to_str(input):
    output = ""
    for i, text in enumerate(input):
        output += text
        if i < len(input) - 1:
            output += ", "
    return output


def writeblock(t, input, width=40):  # for longer texts
    dlines = split_subs(input, threshold=width)
    for i, l in enumerate(dlines):
        t += "%s\n" % l
    return t


def write_block_from_value(tooltip, value, pretext="", width=2000):  # for longer texts
    if not value:
        return tooltip

    intext = value
    if type(value) == list:
        intext = list_to_str(value)
    elif type(value) == float:
        intext = round(intext, 3)
    else:
        intext = value

    intext = str(intext)
    if intext.rstrip() == "":
        return tooltip

    if pretext != "":
        pretext = pretext + ": "

    text = pretext + intext
    dlines = split_subs(text, threshold=width)
    for _, line in enumerate(dlines):
        tooltip += f"{line}\n"

    return tooltip


def has(mdata, prop):
    if (
        mdata.get(prop) is not None
        and mdata[prop] is not None
        and mdata[prop] is not False
    ):
        return True
    else:
        return False


def generate_tooltip(mdata):
    col_w = 40
    if type(mdata["parameters"]) == list:
        mparams = utils.params_to_dict(mdata["parameters"])
    else:
        mparams = mdata["parameters"]
    t = ""
    t = writeblock(t, mdata["displayName"], width=int(col_w * 0.6))
    # t += '\n'

    # t = writeblockm(t, mdata, key='description', pretext='', width=col_w)
    return t


def generate_author_textblock(first_name: str, last_name: str, about_me: str):
    if len(first_name + last_name) == 0:
        return ""

    text = f"{first_name} {last_name}\n"
    if about_me:
        text = write_block_from_value(text, about_me)

    return text


def handle_fetch_gravatar_task(task: client_tasks.Task):
    """Handle incoming fetch_gravatar_task which contains path to author's image on the disk."""
    if task.status == "finished":
        author_id = int(task.data["id"])
        gravatar_path = task.result["gravatar_path"]
        author = global_vars.BKIT_AUTHORS.get(author_id)
        if author is None:
            # Author profile was not registered (e.g. cleared between request and response)
            return
        author.gravatarImg = gravatar_path
        # Notify asset bar to refresh author thumbnails
        if asset_bar_op.asset_bar_operator is not None:
            asset_bar_op.asset_bar_operator.update_image(str(author_id))


_pending_gravatar_authors: list = []


def generate_author_profile(author_data: datas.UserProfile):
    """Register author profile immediately and queue gravatar download for later.
    The actual gravatar HTTP request is batched in _flush_pending_gravatars()
    so that handle_search_task() does not block on N individual HTTP calls.
    """
    author_id = int(author_data.id)
    if author_id in global_vars.BKIT_AUTHORS:
        return

    author_data.tooltip = generate_author_textblock(
        author_data.firstName, author_data.lastName, author_data.aboutMe
    )
    global_vars.BKIT_AUTHORS[author_id] = author_data
    _pending_gravatar_authors.append(author_data)


def _flush_pending_gravatars():
    """Send gravatar download requests for all pending authors to the Go client.
    The Go client handles each download asynchronously (goroutine), so each call
    returns immediately and we don't need a background thread.
    """
    global _pending_gravatar_authors
    authors = _pending_gravatar_authors
    _pending_gravatar_authors = []
    for author_data in authors:
        try:
            resp = client_lib.download_gravatar_image(author_data)
            if resp.status_code != 200:
                bk_logger.warning(resp.text)
        except Exception as e:
            bk_logger.warning("Gravatar download request failed: %s", e)


def handle_get_user_profile(task: client_tasks.Task):
    """Handle incoming get_user_profile task which contains data about current logged-in user."""
    if task.status not in ["finished", "error"]:
        return

    if task.status == "error":
        bk_logger.warning("Could not load user profile: %s", task.message)
        return

    user_data = task.result.get("user")
    if not user_data:
        bk_logger.warning("Got empty user profile")
        return

    can_edit_all_assets = task.result.get("canEditAllAssets", False)
    user = datas.MineProfile.from_dict(
        {**user_data, "canEditAllAssets": can_edit_all_assets}
    )
    user.tooltip = generate_author_textblock(
        user.firstName, user.lastName, user.aboutMe
    )
    global_vars.BKIT_PROFILE = user

    public_user = datas.UserProfile(
        aboutMe=user.aboutMe,
        aboutMeUrl=user.aboutMeUrl,
        avatar128=user.avatar128,
        firstName=user.firstName,
        fullName=user.fullName,
        gravatarHash=user.gravatarHash,
        id=user.id,
        lastName=user.lastName,
        socialNetworks=user.socialNetworks,
        avatar256=user.avatar256,
        gravatarImg=user.gravatarImg,
        tooltip=user.tooltip,
    )
    global_vars.BKIT_AUTHORS[user.id] = public_user

    # after profile arrives, we can check for gravatar image
    resp = client_lib.download_gravatar_image(public_user)
    if resp.status_code != 200:
        bk_logger.warning(resp.text)

    if user.canEditAllAssets:  # IS VALIDATOR
        utils.enforce_prerelease_update_check()


def query_to_url(
    query: Optional[dict] = None,
    addon_version: str = "",
    blender_version: str = "",
    scene_uuid: str = "",
    page_size: int = 15,
) -> str:
    """Build a new search request by parsing query dictionary into appropriate URL.
    Also modifies query and adds some stuff in there which is very misleading anti-pattern.
    TODO: just convert to URL here and move the sorting and adding of params to separate function.
    https://www.blendkit.com/api/v1/search/
    """
    if query is None:
        query = {}

    url = f"{paths.BLENDKIT_API}/search/"

    requeststring = "?query="
    if query.get("query") not in ("", None):
        requeststring += urllib.parse.quote_plus(query["query"])
    for q in query:
        if q in ["query", "free_first", "search_order_by"]:
            continue
        value = str(query[q])
        if q == "asset_type" and value != "author":
            has_keywords = query.get("query") not in ("", None)
            has_author_filter = query.get("author_id") not in ("", None)
            if has_keywords and not has_author_filter:
                value += ",author"
        requeststring += f"+{q}:{urllib.parse.quote_plus(value)}"

    # add dict_parameters to make results smaller

    # query with category_subtree:model etc gives irrelevant results
    if query.get("category_subtree") in (
        "model",
        "material",
        "scene",
        "brush",
        "hdr",
        "nodegroup",
        "printable",
    ):
        query["category_subtree"] = None

    order = decide_ordering(query)
    if requeststring.find("+order:") == -1:
        requeststring += "+order:" + ",".join(order)
    requeststring += "&dict_parameters=1"

    requeststring += "&page_size=" + str(page_size)
    requeststring += f"&addon_version={addon_version}"
    if not (query.get("query") and query.get("query", "").find("asset_base_id") > -1):
        requeststring += f"&blender_version={blender_version}"
    if scene_uuid:
        requeststring += f"&scene_uuid={scene_uuid}"

    urlquery = url + requeststring
    return urlquery


def decide_ordering(query: dict) -> list:
    """Decides which ordering should be used based on the search_order_by.
    If search_order_by is not default, its value is used for the sorting (quality, uploaded, etc.).
    Otherwise the 'legacy' mode is used which
    """
    # result ordering: _score - relevance, score - Blendkit score
    order = []
    if query.get("free_first", False):
        order = [
            "-is_free",
        ]

    search_order_by = query.get("search_order_by", "default")
    if search_order_by != "default":
        order.append(search_order_by)
        return order

    # DEFAULT TRADITIONAL SMART ORDERING
    if query.get("query") is None and query.get("category_subtree") == None:
        # assumes no keywords and no category, thus an empty search that is triggered on start.
        # orders by last core file upload
        if query.get("verification_status") == "uploaded":
            # for validators, sort uploaded from oldest
            # blend-based assets sort by last_blend_upload; zip-only ones
            # (e.g. VDB volumes) have that field null and fall through to
            # last_zip_file_upload as the secondary sort key.
            order.append("last_blend_upload")
            order.append("last_zip_file_upload")
        else:
            if query.get("asset_type") == "addon":
                # addons don't have a blend so need to sort by created
                order.append("-created")
            else:
                # Server-side multi-key sort:
                #   1) -last_blend_upload  -- blend-based assets (most users)
                #   2) -last_zip_file_upload -- zip-only assets (VDB volumes,
                #      etc.) which have lastBlendUpload=null and would
                #      otherwise sort arbitrarily among themselves.
                # handle_search_task() then does a client-side coalesced
                # re-sort by "last_upload" (max of the two) so within an
                # already-fetched chunk blend and zip assets are interleaved
                # by actual recency. A single coalesced server field would
                # be needed for fully correct cross-page interleaving.
                order.append("-last_blend_upload")
                order.append("-last_zip_file_upload")
    elif (
        query.get("author_id") is not None
        or query.get("query", "").find("+author_id:") > -1
    ) and utils.profile_is_validator():
        order.append("-created")
    else:
        if query.get("category_subtree") is not None:
            order.append("-score,_score")
        else:
            order.append("_score")

    return order


def build_query_common(query: dict, props, ui_props) -> dict:
    """Pure function to add shared parameters based on props to query dict.
    Returns the updated version of the query dict.
    """
    query = copy.deepcopy(query)
    query_common = {}
    base_keywords = ui_props.search_keywords.strip()
    filter_tokens = get_active_filter_keywords()
    combined_parts = []
    if base_keywords:
        combined_parts.append(base_keywords.replace("&", "%26"))
    combined_parts.extend(filter_tokens)
    combined_keywords = " ".join(part for part in combined_parts if part)
    if combined_keywords:
        query_common["query"] = combined_keywords

    if props.search_verification_status != "ALL" and utils.profile_is_validator():
        query_common["verification_status"] = props.search_verification_status.lower()

    if props.unrated_quality_only and utils.profile_is_validator():
        query["quality_count"] = 0

    if props.unrated_wh_only and utils.profile_is_validator():
        query["working_hours_count"] = 0

    if props.search_file_size:
        query_common["files_size_gte"] = props.search_file_size_min * 1024 * 1024
        query_common["files_size_lte"] = props.search_file_size_max * 1024 * 1024

    if ui_props.quality_limit > 0:
        query["quality_gte"] = ui_props.quality_limit

    if ui_props.search_bookmarks:
        query["bookmarks_rating"] = 1

    if ui_props.search_license != "ANY":
        query["license"] = ui_props.search_license

    if ui_props.search_blender_version == True:
        query["source_app_version_gte"] = ui_props.search_blender_version_min
        query["source_app_version_lt"] = ui_props.search_blender_version_max

    query.update(query_common)
    return query


def build_query_model(props, ui_props, preferences) -> dict:
    """Use all search inputs (props) and add-on preferences
    to build search query request to get results from server.
    """
    query: dict[str, Union[str, bool]] = {"asset_type": "model"}
    if props.search_style != "ANY":
        if props.search_style != "OTHER":
            query["modelStyle"] = props.search_style
        else:
            query["modelStyle"] = props.search_style_other

    if props.search_condition != "UNSPECIFIED":
        query["condition"] = props.search_condition
    if props.search_design_year:
        query["designYear_gte"] = props.search_design_year_min
        query["designYear_lte"] = props.search_design_year_max
    if props.search_polycount:
        query["faceCount_gte"] = props.search_polycount_min
        query["faceCount_lte"] = props.search_polycount_max
    if props.search_texture_resolution:
        query["textureResolutionMax_gte"] = props.search_texture_resolution_min
        query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    if props.search_animated:
        query["animated"] = True
    if props.search_geometry_nodes:
        query["modifiers"] = "nodes"
    if (
        preferences.nsfw_filter
    ):  # nsfw_filter is toggle for predefined subsets (users could fine-tune in future)
        query["sexualizedContent"] = False
        # TODO: add here more subsets, NSFW is general switch for subsets defined by user (sexualized, violence, etc)
    else:
        query["sexualizedContent"] = ""
    return build_query_common(query, props, ui_props)


def build_query_scene(
    props,
    ui_props,
) -> dict:
    """Use all search input to request results from server."""
    query = {
        "asset_type": "scene",
    }
    return build_query_common(query, props, ui_props)


def build_query_HDR(props, ui_props) -> dict:
    """Use all search input to request results from server."""
    query = {
        "asset_type": "hdr",
    }
    if props.search_texture_resolution:
        query["textureResolutionMax_gte"] = props.search_texture_resolution_min
        query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    if props.true_hdr:
        query["trueHDR"] = props.true_hdr
    return build_query_common(query, props, ui_props)


def build_query_material(
    props,
    ui_props,
) -> dict:
    query: dict[str, Union[str, int]] = {"asset_type": "material"}
    if props.search_style != "ANY":
        if props.search_style != "OTHER":
            query["style"] = props.search_style
        else:
            query["style"] = props.search_style_other
    if props.search_procedural == "TEXTURE_BASED":
        # todo this procedural hack should be replaced with the parameter
        query["textureResolutionMax_gte"] = 0
        # query["procedural"] = False
        if props.search_texture_resolution:
            query["textureResolutionMax_gte"] = props.search_texture_resolution_min
            query["textureResolutionMax_lte"] = props.search_texture_resolution_max
    elif props.search_procedural == "PROCEDURAL":
        # todo this procedural hack should be replaced with the parameter
        query["files_size_lte"] = 1024 * 1024
        # query["procedural"] = True
    return build_query_common(query, props, ui_props)


def build_query_brush(props, ui_props, image_paint_object) -> dict:
    """Pure function to construct search query dict for brushes."""
    if image_paint_object:  # could be just else, but for future p
        brush_type = "texture_paint"
    # automatically fallback to sculpt since most brushes are sculpt anyway.
    else:  # if bpy.context.sculpt_object is not None:
        brush_type = "sculpt"

    query = {"asset_type": "brush", "mode": brush_type}
    return build_query_common(query, props, ui_props)


def build_query_nodegroup(
    props,
    ui_props,
) -> dict:
    """Pure function to construct search query dict for nodegroups."""
    query = {"asset_type": "nodegroup"}
    return build_query_common(query, props, ui_props)


def build_query_addon(props, ui_props) -> dict:
    """Pure function to construct search query dict for addons."""
    query = {"asset_type": "addon"}
    return build_query_common(query, props, ui_props)


def build_query_author(props, ui_props) -> dict:
    """Pure function to construct search query dict for authors."""
    query = {"asset_type": "author"}
    query = build_query_common(query, props, ui_props)
    # +author_id:XXX doesn't match author profile documents in elasticsearch
    # (that field only exists on asset documents). Replace it with the
    # author's name so the API can do a text-search for the profile instead.
    q = query.get("query", "")
    match = re.search(r"\+author_id:(\d+)", q)
    if match:
        aid = int(match.group(1))
        author = global_vars.BKIT_AUTHORS.get(aid)
        name = author.fullName if author else ""
        q = re.sub(r"\+author_id:\d+\s*", "", q).strip()
        if name:
            q = f"{name} {q}".strip() if q else name
        query["query"] = q or None
    return query


def filter_addon_search_results(search_results, filter_installed_only=False):
    """
    Filter addon search results based on local installation status.
    This is called after search results arrive since installation info isn't stored on server.
    Also stores installation and enablement status in the search results data.

    Args:
        search_results: List of addon asset data from search
        filter_installed_only: If True, only return installed addons

    Returns:
        Filtered list of add-on assets with installation status stored
    """

    filtered_results = []

    for asset in search_results:
        if not filter_installed_only:
            filtered_results.append(asset)
            continue

        # Check installation and enablement status for addon
        try:
            status = download.get_addon_installation_status(asset)
            is_installed = status.get("installed", False)
            is_enabled = status.get("enabled", False)

            # Store installation status in asset data using existing 'downloaded' field
            # Use 100 for installed, 0 for not installed (matching existing pattern)
            asset["downloaded"] = 100 if is_installed else 0

            # Store enablement status in new 'enabled' field
            asset["enabled"] = is_enabled

            if filter_installed_only:
                if is_installed:
                    filtered_results.append(asset)
            else:
                filtered_results.append(asset)

        except Exception as e:
            # If we can't determine status, mark as not installed/enabled
            bk_logger.warning(
                "Could not determine installation status for addon %s : %s",
                asset.get("name", "Unknown"),
                e,
            )
            asset["downloaded"] = 0
            asset["enabled"] = False

            if not filter_installed_only:
                filtered_results.append(asset)

    return filtered_results


def add_search_process(
    query, get_next: bool, page_size: int, next_url: str, history_id: str
):
    """Initialize search task and add it to the task queue."""
    global search_tasks
    addon_version = utils.get_addon_version()
    blender_version = utils.get_blender_version()
    scene_uuid = utils.get_scene_id()

    tempdir = paths.get_temp_dir("%s_search" % query["asset_type"])
    if get_next and next_url:
        urlquery = next_url
    else:
        urlquery = query_to_url(
            query, addon_version, blender_version, scene_uuid, page_size
        )

    search_data = datas.SearchData(
        PREFS=utils.get_preferences(),  # change this
        tempdir=tempdir,
        urlquery=urlquery,
        asset_type=query["asset_type"],
        scene_uuid=scene_uuid,
        get_next=get_next,
        page_size=page_size,
        blender_version=blender_version,
        is_validator=utils.profile_is_validator(),
        history_id=history_id,
        search_order_by=query.get("search_order_by", "default"),
    )
    response = client_lib.asset_search(search_data)
    search_tasks[response["task_id"]] = search_data


def get_search_simple(
    parameters, filepath=None, page_size=100, max_results=100000000, api_key=""
):
    """Searches and returns the search results.

    Parameters
    ----------
    parameters - dict of Blendkit elastic parameters
    filepath - a file to save the results. If None, results are returned
    page_size - page size for retrieved results
    max_results - max results of the search
    api_key - Blendkit api key

    Returns
    -------
    Returns search results as a list, and optionally saves to filepath
    """
    headers = utils.get_headers(api_key)
    url = f"{paths.BLENDKIT_API}/search/"
    requeststring = url + "?query="
    for p in parameters.keys():
        requeststring += f"+{p}:{parameters[p]}"

    requeststring += "&page_size=" + str(page_size)
    requeststring += "&dict_parameters=1"

    bk_logger.debug(requeststring)
    response = client_lib.blocking_request(requeststring, "GET", headers)

    # print(response.json())
    search_results = response.json()

    results = []
    results.extend(search_results["results"])
    page_index = 2
    page_count = math.ceil(search_results["count"] / page_size)
    while search_results.get("next") and len(results) < max_results:
        bk_logger.info("getting page %d , total pages %d", page_index, page_count)
        response = client_lib.blocking_request(search_results["next"], "GET", headers)
        search_results = response.json()
        results.extend(search_results["results"])
        page_index += 1

    if not filepath:
        return results

    with open(filepath, "w", encoding="utf-8") as s:
        json.dump(results, s, ensure_ascii=False, indent=4)
    bk_logger.info("retrieved %d assets from elastic search", len(results))
    return results


def search(get_next=False, query=None, author_id=""):
    """Initialize searching
    query : submit an already built query from search history
    """
    if global_vars.CLIENT_ACCESSIBLE != True:
        reports.add_report(
            "Cannot search, Client is not accessible.", timeout=5, type="ERROR"
        )
        return

    user_preferences = bpy.context.preferences.addons[__package__].preferences
    wm = bpy.context.window_manager
    ui_props = bpy.context.window_manager.blenderkitUI

    # if search is locked, don't trigger search update
    if ui_props.search_lock:
        return

    props = utils.get_search_props()
    active_history_step = get_active_history_step()

    # it's possible get_next was requested more than once.
    if active_history_step.get("is_searching") and get_next == True:
        # search already running, skipping
        return

    if not query:
        if ui_props.asset_type == "MODEL":
            if not hasattr(wm, "blenderkit_models"):
                return
            query = build_query_model(
                bpy.context.window_manager.blenderkit_models,
                ui_props=bpy.context.window_manager.blenderkitUI,
                preferences=bpy.context.preferences.addons[__package__].preferences,
            )

        if ui_props.asset_type == "PRINTABLE":
            if not hasattr(wm, "blenderkit_models"):
                return
            query = build_query_model(
                bpy.context.window_manager.blenderkit_models,
                ui_props=bpy.context.window_manager.blenderkitUI,
                preferences=bpy.context.preferences.addons[__package__].preferences,
            )
            query["asset_type"] = "printable"  # Override the asset type for PRINTABLE

        if ui_props.asset_type == "SCENE":
            if not hasattr(wm, "blenderkit_scene"):
                return
            query = build_query_scene(
                bpy.context.window_manager.blenderkit_scene,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "HDR":
            if not hasattr(wm, "blenderkit_HDR"):
                return
            query = build_query_HDR(
                bpy.context.window_manager.blenderkit_HDR,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "MATERIAL":
            if not hasattr(wm, "blenderkit_mat"):
                return
            query = build_query_material(
                bpy.context.window_manager.blenderkit_mat,
                bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "TEXTURE":
            if not hasattr(wm, "blenderkit_tex"):
                return
            # props = scene.blenderkit_tex
            # query = build_query_texture()

        if ui_props.asset_type == "BRUSH":
            if not hasattr(wm, "blenderkit_brush"):
                return
            query = build_query_brush(
                bpy.context.window_manager.blenderkit_brush,
                bpy.context.window_manager.blenderkitUI,
                bpy.context.image_paint_object,
            )

        if ui_props.asset_type == "NODEGROUP":
            if not hasattr(wm, "blenderkit_nodegroup"):
                return
            query = build_query_nodegroup(
                props=bpy.context.window_manager.blenderkit_nodegroup,
                ui_props=bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "ADDON":
            query = build_query_addon(
                props=bpy.context.window_manager.blenderkit_addon,
                ui_props=bpy.context.window_manager.blenderkitUI,
            )

        if ui_props.asset_type == "AUTHOR":
            query = build_query_author(
                props=bpy.context.window_manager.blenderkit_author,
                ui_props=bpy.context.window_manager.blenderkitUI,
            )

        # crop long searches
        if query.get("query"):
            if len(query["query"]) > 50:
                query["query"] = strip_accents(query["query"])

            if len(query["query"]) > 150:
                idx = query["query"].find(" ", 142)
                query["query"] = query["query"][:idx]

        if props.search_category != "":
            if utils.profile_is_validator() and user_preferences.categories_fix:
                query["category"] = props.search_category
            else:
                query["category_subtree"] = props.search_category

        if author_id != "":
            query["author_id"] = author_id
        elif ui_props.own_only:
            # if user searches for [another] author, 'only my assets' is invalid. that's why in elif.
            profile = global_vars.BKIT_PROFILE
            if profile is not None:
                query["author_id"] = str(profile.id)

                # add user validation status filter here
                if ui_props.own_verification_status.lower() != "all":
                    query["verification_status"] = (
                        ui_props.own_verification_status.lower()
                    )

        # free first has to by in query to be evaluated as changed as another search, otherwise the filter is not updated.
        query["free_first"] = ui_props.free_only
        query["search_order_by"] = ui_props.search_order_by

    active_history_step["is_searching"] = True

    page_size = min(
        MAX_PAGE_SIZE, ui_props.wcount * user_preferences.maximized_assetbar_rows + 5
    )
    next_url = ""
    if get_next and active_history_step.get("search_results_orig"):
        next_url = active_history_step["search_results_orig"].get("next", "")

    add_search_process(query, get_next, page_size, next_url, active_history_step["id"])
    props.report = "Blendkit searching...."


def clean_filters():
    """Cleanup filters in case search needs to be reset, typically when asset id is copy pasted."""
    sprops = utils.get_search_props()
    ui_props = bpy.context.window_manager.blenderkitUI
    active_tab = get_active_tab()
    ui_props.property_unset("own_only")
    ui_props.property_unset("own_verification_status")
    sprops.property_unset("search_texture_resolution")
    sprops.property_unset("search_file_size")
    sprops.property_unset("search_procedural")
    ui_props.property_unset("free_only")
    ui_props.property_unset("quality_limit")
    ui_props.property_unset("search_bookmarks")
    if ui_props.asset_type == "MODEL":
        sprops.property_unset("search_style")
        sprops.property_unset("search_condition")
        sprops.property_unset("search_design_year")
        sprops.property_unset("search_polycount")
        sprops.property_unset("search_animated")
        sprops.property_unset("search_geometry_nodes")
    if ui_props.asset_type == "HDR":
        # Set without triggering update functions:
        sprops["true_hdr"] = False
        while True:  # Wait until true_hdr is updated
            sprops = utils.get_search_props()
            if sprops["true_hdr"] == False:
                break
            print("waiting for sprops.true_hdr to be updated")


def update_filters():
    """Update filters for 2 reasons
    - first to show if filters are active
    - second to show login popup if user needs to log in

    returns True if search should proceed, False to bounce search(like in the case of bookmarks)
    """

    sprops = utils.get_search_props()
    ui_props = bpy.context.window_manager.blenderkitUI
    active_tab = get_active_tab()

    if ui_props.search_bookmarks and not utils.user_logged_in():
        ui_props.search_bookmarks = False
        bpy.ops.wm.blenderkit_login_dialog(
            "INVOKE_DEFAULT",
            message="Please login to use bookmarks.",
            placement="bookmarks_prompt",
        )
        return False
    if ui_props.own_only and not utils.user_logged_in():
        ui_props.own_only = False
        bpy.ops.wm.blenderkit_login_dialog(
            "INVOKE_DEFAULT",
            message="Please login to upload and filter your own assets.",
            placement="own_assets_prompt",
        )
        return False

    _sync_panel_filters_into_active(active_tab)

    fcommon = (
        ui_props.own_only
        or sprops.search_texture_resolution
        or sprops.search_file_size
        or sprops.search_procedural != "BOTH"
        or ui_props.free_only
        or ui_props.quality_limit > 0
        or ui_props.search_bookmarks
        or ui_props.search_license != "ANY"
        or ui_props.search_blender_version
        or ui_props.search_order_by != "default"
        or len(get_active_filters()) > 0
        # NSFW filter is signaled in a special way and should not affect the filter icon
    )

    if ui_props.asset_type == "MODEL":
        sprops.use_filters = (
            fcommon
            or sprops.search_style != "ANY"
            or sprops.search_condition != "UNSPECIFIED"
            or sprops.search_design_year
            or sprops.search_polycount
            or sprops.search_animated
            or sprops.search_geometry_nodes
        )
    elif ui_props.asset_type == "SCENE":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "MATERIAL":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "BRUSH":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "HDR":
        sprops.use_filters = sprops.true_hdr
    elif ui_props.asset_type == "NODEGROUP":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "ADDON":
        sprops.use_filters = fcommon
    elif ui_props.asset_type == "AUTHOR":
        sprops.use_filters = fcommon
    return True


def search_update_delayed(self, context):
    """run search after user changes a search parameter,
    but with a delay.
    This reduces number of calls during slider UI interaction (like texture resolution, polycount)
    """

    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_lock:
        return

    tasks_queue.add_task((search_update, (None, None)), wait=0.5, only_last=True)


def search_update_verification_status(self, context):
    """run search after user changes a search parameter"""
    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    if ui_props.search_lock:
        return

    # if there is an author_id in search_keywords, we want to clear those for validators
    if ui_props.search_keywords.find("+author_id:") > -1:
        ui_props.search_keywords = ""
    search_update(self, context)


def detect_asset_type_from_keywords(keywords: str) -> tuple[str, str]:
    """Detect asset type from keywords and return tuple of (asset_type, cleaned_keywords).
    Returns ('', original_keywords) if no asset type is detected."""

    # Dictionary mapping keyword variations to asset types
    asset_type_map = {
        "model": "MODEL",
        "material": "MATERIAL",
        "mat": "MATERIAL",
        "brush": "BRUSH",
        "scene": "SCENE",
        "hdr": "HDR",
        "hdri": "HDR",
        "nodegroup": "NODEGROUP",
        "node": "NODEGROUP",
        "printable": "PRINTABLE",
        "addon": "ADDON",
        "add-on": "ADDON",
        "extension": "ADDON",
        "artist": "AUTHOR",
        "author": "AUTHOR",
    }

    # Convert to lowercase for matching
    keywords_lower = keywords.lower()

    # Check each word in the search string
    for word in keywords_lower.split():
        if word in asset_type_map:
            # Remove the asset type word from keywords
            cleaned_keywords = keywords_lower.replace(word, "").strip()
            return asset_type_map[word], cleaned_keywords

    return "", keywords


def search_update(self, context):
    """run search after user changes a search parameter"""

    # when search is locked, don't trigger search update
    ui_props = bpy.context.window_manager.blenderkitUI

    # Drop data-driven filters (e.g. manufacturer chips) when switching asset type.
    # Seed the tracker on first run to avoid wiping filters during the initial update.
    last_asset_type = getattr(ui_props, "_last_asset_type", None)
    if last_asset_type is None:
        ui_props._last_asset_type = ui_props.asset_type
    elif last_asset_type != ui_props.asset_type:
        tab = get_active_tab()
        filters = _ensure_tab_filters(tab)
        # Keep only panel-defined filters; drop all ad-hoc/data-derived ones
        tab["active_filters"] = [
            f for f in filters if f.get("term") in PANEL_FILTER_TERMS
        ]
        ui_props._last_asset_type = ui_props.asset_type

    if ui_props.search_lock:
        return

    # update filters
    go_on = update_filters()
    if not go_on:
        return

    ui_props = bpy.context.window_manager.blenderkitUI

    # Remove this feature for now, but leave the code here for future reference
    # Check if keywords contain asset type before processing clipboard
    # if ui_props.search_keywords != "":
    #     detected_type, cleaned_keywords = detect_asset_type_from_keywords(
    #         ui_props.search_keywords
    #     )
    # if detected_type and detected_type != ui_props.asset_type:
    #     # Store keywords before switching
    #     ui_props.search_lock = True
    #     ui_props.search_keywords = cleaned_keywords
    #     # Switch asset type
    #     ui_props.asset_type = detected_type
    #     ui_props.search_lock = False
    # Return since changing keywords will trigger this function again
    # not now - let's try it with lock

    # if ui_props.down_up != "SEARCH":
    #     ui_props.down_up = "SEARCH"

    # Input tweaks if user manually placed asset-link from website -> we need to get rid of asset type and set it in UI.
    # This is not normally needed as check_clipboard() asset_type switching but without recursive shit.
    instr = "asset_base_id:"
    atstr = "asset_type:"
    kwds = ui_props.search_keywords
    id_index = kwds.find(instr)
    if id_index > -1:
        asset_type_index = kwds.find(atstr)
        # if the asset type already isn't there it means this update function
        # was triggered by it's last iteration and needs to cancel
        if asset_type_index > -1:
            asset_type_string = kwds[asset_type_index:].lower()
            # uncertain length of the remaining string -  find as better method to check the presence of asset type
            if asset_type_string.find("model") > -1:
                target_asset_type = "MODEL"
            elif asset_type_string.find("material") > -1:
                target_asset_type = "MATERIAL"
            elif asset_type_string.find("brush") > -1:
                target_asset_type = "BRUSH"
            elif asset_type_string.find("scene") > -1:
                target_asset_type = "SCENE"
            elif asset_type_string.find("hdr") > -1:
                target_asset_type = "HDR"
            elif asset_type_string.find("nodegroup") > -1:
                target_asset_type = "NODEGROUP"
            elif asset_type_string.find("printable") > -1:
                target_asset_type = "PRINTABLE"
            elif asset_type_string.find("addon") > -1:
                target_asset_type = "ADDON"
            elif (
                asset_type_string.find("artist") > -1
                or asset_type_string.find("author") > -1
            ):
                target_asset_type = "AUTHOR"

            if ui_props.asset_type != target_asset_type:
                ui_props.search_keywords = ""
                ui_props.asset_type = target_asset_type

            # now we trim the input copypaste by anything extra that is there,
            # this is also a way for this function to recognize that it already has parsed the clipboard
            # the search props can have changed and this needs to transfer the data to the other field
            # this complex behaviour is here for the case where the user needs to paste manually into blender,
            # Otherwise it could be processed directly in the clipboard check function.
            sprops = utils.get_search_props()
            clean_filters()
            ui_props.search_keywords = kwds[:asset_type_index].rstrip()
            # return here since writing into search keywords triggers this update function once more.
            return

    if global_vars.CLIENT_ACCESSIBLE:
        reports.add_report(f"Searching for: '{kwds}'", 2)

    # create history step
    active_tab = get_active_tab()
    create_history_step(active_tab)
    search()


# accented_string is of type 'unicode'
def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def refresh_search():
    """Refresh search results. Useful after login/logout."""
    sprops = utils.get_search_props()
    ui_props = bpy.context.window_manager.blenderkitUI
    active_tab = get_active_tab()

    ui_props = bpy.context.window_manager.blenderkitUI
    if ui_props.assetbar_on:
        ui_props.turn_off = True
        ui_props.assetbar_on = False
    cleanup_search_results()  # TODO: is it possible to start this from Client automatically? probably YEA


# TODO: fix the tooltip?
class SearchOperator(Operator):
    """Tooltip"""

    bl_idname = "view3d.blenderkit_search"
    bl_label = "Blendkit asset search"
    bl_description = "Search online for assets"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    esc: BoolProperty(  # type: ignore[valid-type]
        name="Escape window",
        description="Escape window right after start",
        default=False,
        options={"SKIP_SAVE"},
    )

    own: BoolProperty(  # type: ignore[valid-type]
        name="own assets only",
        description="Find all own assets",
        default=False,
        options={"SKIP_SAVE"},
    )

    # category: StringProperty(
    #     name="category",
    #     description="search only subtree of this category",
    #     default="",
    #     options={"SKIP_SAVE"},
    # )

    author_id: StringProperty(  # type: ignore[valid-type]
        name="Author ID",
        description="Author ID - search only assets by this author",
        default="",
        options={"SKIP_SAVE"},
    )

    get_next: BoolProperty(  # type: ignore[valid-type]
        name="next page",
        description="get next page from previous search",
        default=False,
        options={"SKIP_SAVE"},
    )

    keywords: StringProperty(  # type: ignore[valid-type]
        name="Keywords", description="Keywords", default="", options={"SKIP_SAVE"}
    )

    # close_window: BoolProperty(name='Close window',
    #                            description='Try to close the window below mouse before download',
    #                            default=False)

    tooltip: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    force_clear: BoolProperty(  # type: ignore[valid-type]
        name="Force clear keywords, before programmatic search",
        description="Force clear keywords before search",
        default=True,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        # TODO ; this should all get transferred to properties of the search operator, so sprops don't have to be fetched here at all.
        if self.esc:
            bpy.ops.view3d.close_popup_button("INVOKE_DEFAULT")
        ui_props = bpy.context.window_manager.blenderkitUI

        search_keywords = str(ui_props.search_keywords)

        # remove all search keywords if force_clear is set
        if self.force_clear:
            # self.force_clear = False  # reset the force clear
            search_keywords = ""

        if self.keywords != "":
            search_keywords = self.keywords

        if self.author_id != "":
            ui_props.search_keywords = search_keywords
            search_by_author_id(self.author_id)
            return {"FINISHED"}

        ui_props.search_keywords = search_keywords

        search(get_next=self.get_next)

        return {"FINISHED"}


class UrlOperator(Operator):
    """"""

    bl_idname = "wm.blenderkit_url"
    bl_label = ""
    bl_description = "Search online for assets"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooltip: bpy.props.StringProperty(default="Open a web page")  # type: ignore[valid-type]
    url: bpy.props.StringProperty(  # type: ignore[valid-type]
        default="Runs search and displays the asset bar at the same time"
    )

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def execute(self, context):
        bpy.ops.wm.url_open(url=self.url)
        return {"FINISHED"}


class TooltipLabelOperator(Operator):
    """"""

    bl_idname = "wm.blenderkit_tooltip"
    bl_label = ""
    bl_description = "Empty operator to be able to create tooltips on labels in UI"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooltip: bpy.props.StringProperty(default="Open a web page")  # type: ignore[valid-type]

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip

    def execute(self, context):
        return {"FINISHED"}


def get_search_similar_keywords(asset_data: dict) -> str:
    """Generate search similar keywords from the given asset_data.
    Could be tuned in the future to provide better search results.
    """
    keywords = asset_data["name"]
    if asset_data.get("description"):
        keywords += f" {asset_data.get('description')} "
    keywords += " ".join(asset_data.get("tags", []))
    return keywords


class AuthorAssetTypeSearch(Operator):
    """Switch to a specific asset type tab and search by author"""

    bl_idname = "view3d.blenderkit_author_asset_type_search"
    bl_label = "Search Author Assets"
    bl_options = {"REGISTER", "INTERNAL"}

    author_id: StringProperty(name="Author ID", default="", options={"SKIP_SAVE"})  # type: ignore
    author_name: StringProperty(name="Author Name", default="", options={"SKIP_SAVE"})  # type: ignore
    asset_type: StringProperty(
        name="Asset Type", default="MODEL", options={"SKIP_SAVE"}
    )  # type: ignore

    def execute(self, context):
        ui_props = bpy.context.window_manager.blenderkitUI
        ui_props.search_lock = True
        ui_props.asset_type = self.asset_type
        ui_props.search_keywords = ""
        ui_props.search_lock = False
        search_by_author_id(self.author_id, self.author_name)
        return {"FINISHED"}


class AuthorAssetTypePopup(Operator):
    """Choose which asset type to browse for this author"""

    bl_idname = "view3d.blenderkit_author_asset_type_popup"
    bl_label = "Find Author's Assets"
    bl_options = {"REGISTER", "INTERNAL"}

    author_id: StringProperty(name="Author ID", default="", options={"SKIP_SAVE"})  # type: ignore
    author_name: StringProperty(name="Author Name", default="", options={"SKIP_SAVE"})  # type: ignore

    # Set by caller before invoke — per-type asset counts from the author result
    _asset_type_counts: dict = {}

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_popup(self, width=200)

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports search)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        layout = self.layout
        layout.label(text=self.author_name or "Author")
        layout.separator()

        counts = self._asset_type_counts
        pcoll = icons.icon_collections["main"]
        asset_types = [
            ("MODEL", "Models", "OBJECT_DATAMODE", "model"),
            ("MATERIAL", "Materials", "MATERIAL", "material"),
            ("SCENE", "Scenes", "SCENE_DATA", "scene"),
            ("HDR", "HDRs", "WORLD", "hdr"),
            ("BRUSH", "Brushes", "BRUSH_DATA", "brush"),
            ("NODEGROUP", "Node Groups", "NODETREE", "nodegroup"),
        ]

        for at_id, at_label, at_icon, at_key in asset_types:
            count = counts.get(at_key, 0)
            if counts and count == 0:
                continue
            label = f"{at_label} ({count})" if count else at_label
            op = layout.operator(
                "view3d.blenderkit_author_asset_type_search",
                text=label,
                icon=at_icon,
            )
            op.author_id = self.author_id
            op.author_name = self.author_name
            op.asset_type = at_id

        # Printable
        printable_count = counts.get("printable", 0)
        if not counts or printable_count > 0:
            label = (
                f"Printables ({printable_count})" if printable_count else "Printables"
            )
            op = layout.operator(
                "view3d.blenderkit_author_asset_type_search",
                text=label,
                icon_value=pcoll["asset_type_printable"].icon_id,
            )
            op.author_id = self.author_id
            op.author_name = self.author_name
            op.asset_type = "PRINTABLE"

        # Add-ons (Blender 4.2+)
        addon_count = counts.get("addon", 0)
        if bpy.app.version >= (4, 2, 0) and (not counts or addon_count > 0):
            label = f"Add-ons ({addon_count})" if addon_count else "Add-ons"
            op = layout.operator(
                "view3d.blenderkit_author_asset_type_search",
                text=label,
                icon="PLUGIN",
            )
            op.author_id = self.author_id
            op.author_name = self.author_name
            op.asset_type = "ADDON"


classes = [
    SearchOperator,
    UrlOperator,
    TooltipLabelOperator,
    AuthorAssetTypeSearch,
    AuthorAssetTypePopup,
]


def register_search():
    bpy.app.handlers.load_post.append(scene_load)
    bpy.app.handlers.load_post.append(undo_post_reload_previews)
    bpy.app.handlers.undo_post.append(undo_post_reload_previews)
    bpy.app.handlers.undo_pre.append(undo_pre_end_assetbar)

    for c in classes:
        bpy.utils.register_class(c)


def unregister_search():
    bpy.app.handlers.load_post.remove(scene_load)

    for c in classes:
        bpy.utils.unregister_class(c)


# Storing history steps
# History step is a dictionary with the following keys:
# - id: uuid
# - ui_state: dict
# - search_results: list
# - search_results_orig: list
# - scroll_offset: int - this is separate since it doesn't influence when a new history step can be created

# ui_state contains search_keywords, asset_type, all search filters, common ones and also those from advanced search panels for all asset types.
# if anything in UI that influences search and is in ui_state changes, a new history step is created.
# a history step isn't created when search results land or when more pages get retrieved
# each history step has own id. This id is used to identify the history step when a new search is started. It gets sent to the client.
# After the search results land, the results are written to the respective history step.

# first let's try to setup storing of ui_state


def get_ui_state():
    """Get the current UI state."""
    ui_props = bpy.context.window_manager.blenderkitUI
    active_tab = get_active_tab()

    ui_state = {
        "ui_props": {
            "search_keywords": ui_props.search_keywords,
            "asset_type": ui_props.asset_type,
            "free_only": ui_props.free_only,
            "own_only": ui_props.own_only,
            "own_verification_status": ui_props.own_verification_status,
            "search_bookmarks": ui_props.search_bookmarks,
            "quality_limit": ui_props.quality_limit,
            "search_license": ui_props.search_license,
            "search_blender_version": ui_props.search_blender_version,
            "search_blender_version_min": ui_props.search_blender_version_min,
            "search_blender_version_max": ui_props.search_blender_version_max,
        },
        "search_props": {},
        "active_filters": get_active_filters(active_tab),
    }

    # we need to add all props manually since they are a mess now and some should not be stored.
    # model props
    common_search_props = [
        "search_category",
        "search_texture_resolution",
        "search_texture_resolution_min",
        "search_texture_resolution_max",
        "search_file_size",
        "search_file_size_min",
        "search_file_size_max",
        "search_procedural",
        "search_verification_status",
        "unrated_quality_only",
        "unrated_wh_only",
    ]

    store_model_props = [
        "search_animated",
        "search_condition",
        "search_design_year",
        "search_design_year_max",
        "search_design_year_min",
        "search_engine",
        "search_engine_other",
        "search_geometry_nodes",
        "search_polycount",
        "search_polycount_max",
        "search_polycount_min",
        "search_style",
        "search_style_other",
    ]
    store_material_props = [
        "search_style",
        "search_style_other",
    ]
    store_brush_props = []
    store_nodegroup_props = []
    store_hdr_props = [
        "true_hdr",
    ]
    store_scene_props = [
        "search_style",
    ]
    store_props = []
    # we could use match here but older blender versions have older python and don't support it
    asset_type = ui_props.asset_type
    if asset_type == "MODEL":
        store_props = store_model_props
    elif asset_type == "MATERIAL":
        store_props = store_material_props
    elif asset_type == "BRUSH":
        store_props = store_brush_props
    elif asset_type == "NODEGROUP":
        store_props = store_nodegroup_props
    elif asset_type == "HDR":
        store_props = store_hdr_props
    elif asset_type == "SCENE":
        store_props = store_scene_props
    elif asset_type == "PRINTABLE":
        store_props = store_model_props
    elif asset_type == "ADDON":
        store_props = []  # Addons don't need to store specific props
    elif asset_type == "AUTHOR":
        store_props = []  # Authors don't need to store specific props

    search_props = utils.get_search_props()

    store_props.extend(common_search_props)
    # Store all properties from each property group
    for prop_name in store_props:
        if prop_name != "rna_type":
            ui_state["search_props"][prop_name] = getattr(search_props, prop_name)

    # Store addon-specific search properties
    if ui_props.asset_type == "ADDON":
        addon_props = bpy.context.window_manager.blenderkit_addon
        ui_state["addon_props"] = {
            "search_installed": addon_props.search_installed,
            "search_compatible_only": addon_props.search_compatible_only,
        }

    return ui_state


def update_tab_name(active_tab):
    """Update the name of the active tab."""
    history_step = get_active_history_step()
    ui_state = history_step.get("ui_state", {})

    # Update tab name based on search or category
    search_keywords = ui_state.get("ui_props", {}).get("search_keywords", "").strip()
    # Check active filters for author_id
    author_name = None
    active_filters = ui_state.get("active_filters", [])
    for flt in active_filters:
        if flt.get("term") == "author_id":
            author_name = flt.get("label")
            break

    search_category = (
        ui_state.get("search_props", {}).get("search_category", "").strip()
    )
    asset_type = ui_state.get("ui_props", {}).get("asset_type", "").strip()
    if author_name is not None:
        tab_name = author_name
    elif search_keywords:
        # Use search keywords for tab name
        tab_name = search_keywords
    elif search_category:
        # Use category name if no search keywords
        tab_name = search_category.split("/")[-1]  # Get last part of category path
    else:
        # Keep existing name if no keywords or category
        tab_name = asset_type.lower()

    # Crop name to max 9 characters
    if len(tab_name) > 9:
        tab_name = tab_name[:8] + "…"

    # Update tab name
    active_tab["name"] = tab_name

    # Update UI if asset bar exists and is properly initialized
    asset_bar = asset_bar_op.asset_bar_operator
    if asset_bar and hasattr(asset_bar, "tab_buttons"):
        active_tab_index = global_vars.TABS["active_tab"]
        if 0 <= active_tab_index < len(asset_bar.tab_buttons):
            try:
                asset_bar.tab_buttons[active_tab_index].text = tab_name
                # Only try to redraw if we have a valid region
                if asset_bar.area and asset_bar.area.region:
                    asset_bar.area.tag_redraw()
            except Exception as e:
                bk_logger.debug("Could not update tab name in UI: %s", e)

    return history_step


# now let's create a history function that creates a new history step
def create_history_step(active_tab):
    """Create a new history step and update tab name."""
    ui_props = bpy.context.window_manager.blenderkitUI
    ui_state = get_ui_state()
    history_step = {
        "id": str(uuid.uuid4()),
        "ui_state": ui_state,
        "scroll_offset": ui_props.scroll_offset,
    }

    # Delete any future history steps
    if active_tab["history_index"] < len(active_tab["history"]) - 1:
        # Remove future steps from global history steps dict first
        for step in active_tab["history"][active_tab["history_index"] + 1 :]:
            global_vars.DATA["history steps"].pop(step["id"], None)
        # Then truncate the tab's history list
        active_tab["history"] = active_tab["history"][: active_tab["history_index"] + 1]

    active_tab["history"].append(history_step)
    active_tab["history_index"] = len(active_tab["history"]) - 1

    # Add this history step to the global history steps dictionary
    global_vars.DATA["history steps"][history_step["id"]] = history_step
    print(f"Created history step {history_step['id']}")
    reports.add_report("Created new search history step", 1, "INFO")

    # Update tab name and history button visibility
    update_tab_name(active_tab)

    # Update history button visibility if asset bar exists
    # if history length is 1, hide the back button

    asset_bar = asset_bar_op.asset_bar_operator
    if asset_bar and hasattr(asset_bar, "history_back_button"):
        asset_bar.history_back_button.visible = active_tab["history_index"] > 0
        asset_bar.history_forward_button.visible = (
            False  # forward is never possible if we create new history step
        )
        asset_bar.update_tab_icons()

    return history_step


def append_history_step(
    search_keywords,
    search_results,
    active_tab=None,
    asset_type=None,
    search_results_orig=None,
) -> dict:
    """Append a complete history step consisting of search keywords and results. No search is triggered.
    Use this function when you already have search results data and want to add them to the history step.
    Function also switches the asset type to the one provided, refreshes the UI and updates the tab name.

    Parameters
    ----------
    search_keywords : str
        The search keywords to use for this history step
    search_results : list
        List of parsed search results to store in the history step
    active_tab : dict
        The active tab to add the history step to
    asset_type : str, optional
        The asset type to use. If None, current asset type will be used
    search_results_orig : dict, optional
        The original search results from the server. If None, will be constructed from search_results

    Returns
    -------
    dict
        The newly created history step
    """
    if active_tab is None:
        active_tab = get_active_tab()

    ui_state = get_ui_state()
    ui_state["ui_props"]["search_keywords"] = search_keywords

    ui_props = bpy.context.window_manager.blenderkitUI
    ui_props.search_lock = True
    if asset_type:
        ui_state["ui_props"]["asset_type"] = asset_type
        ui_props.asset_type = asset_type

    ui_props.search_keywords = search_keywords
    ui_props.search_lock = False

    # Create the history step
    history_step = {
        "id": str(uuid.uuid4()),
        "ui_state": ui_state,
        "scroll_offset": 0,  # Reset scroll offset for new search
        "search_results": search_results,
        "is_searching": False,
    }

    # Add original search results if provided, otherwise construct from search_results
    if search_results_orig:
        history_step["search_results_orig"] = search_results_orig
    else:
        history_step["search_results_orig"] = {
            "results": search_results,
            "count": len(search_results),
        }

    # Delete any future history steps
    if active_tab["history_index"] < len(active_tab["history"]) - 1:
        # Remove future steps from global history steps dict first
        for step in active_tab["history"][active_tab["history_index"] + 1 :]:
            global_vars.DATA["history steps"].pop(step["id"], None)
        # Then truncate the tab's history list
        active_tab["history"] = active_tab["history"][: active_tab["history_index"] + 1]

    # Add to tab history
    active_tab["history"].append(history_step)
    active_tab["history_index"] = len(active_tab["history"]) - 1

    # Add to global history steps
    global_vars.DATA["history steps"][history_step["id"]] = history_step

    # Update tab name
    update_tab_name(active_tab)

    # Update history button visibility if asset bar exists
    asset_bar = asset_bar_op.asset_bar_operator
    if asset_bar and hasattr(asset_bar, "history_back_button"):
        asset_bar.history_back_button.visible = active_tab["history_index"] > 0
        asset_bar.history_forward_button.visible = False
        asset_bar.update_tab_icons()

    return history_step


def get_history_step(history_step_id):
    return global_vars.DATA["history steps"].get(history_step_id)


def get_history_steps():
    return global_vars.DATA["history steps"]


def get_active_history_step():
    """Get the currently active history step from the active tab."""
    active_tab = global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
    # if there's no history step, create one
    if len(active_tab["history"]) == 0:
        history_step = create_history_step(active_tab)
    else:
        history_step = active_tab["history"][active_tab["history_index"]]
    return history_step


def get_search_results() -> list[dict]:
    """Get search results from the active history step."""
    history_step = get_active_history_step()
    return history_step.get("search_results", [])


def get_active_tab():
    """Get the active tab."""
    return global_vars.TABS["tabs"][global_vars.TABS["active_tab"]]
