"""
This is a separate library that overrides the extension_draw_item method from Blender extensions list display.
The original code is in the bl_extension_ui.py file in the Blender source code.
The override library can be placed in multiple addons, and the override should happen only once.
The override is done by replacing the original method with the new one, and backing up the original method.
The original method is then called from the new method, with the same arguments, but with the new code added.
"""

import json
import os
import time
import re
import logging

from . import icons, version_compare

import blf
import bpy
import bl_pkg.bl_extension_ui as exui
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

EXTENSIONS_API_URL = "https://www.blendkit.com/api/v1/extensions/"
# Legacy repository URL used before the rename from BlenderKit to Blendkit.
LEGACY_EXTENSIONS_API_URL = "https://www.blenderkit.com/api/v1/extensions/"
# Canonical module name of the Blendkit extensions repository.
EXTENSIONS_REPO_MODULE = "www_blenderkit_com"

bk_logger = logging.getLogger(__name__)

# Per-draw-cycle caching for ensure_repo_cache() to avoid repeated
# filesystem stat calls when drawing hundreds of extension items.
_repo_cache_last_check: float = 0.0
_repo_cache_last_result: bool = False
_REPO_CACHE_CHECK_INTERVAL: float = 3.0  # seconds between filesystem checks

# Cached repository reference to avoid iterating repos per item.
_cached_repository = None
_cached_repository_time: float = 0.0
_REPO_LOOKUP_INTERVAL: float = 5.0  # seconds between repo lookups

# Cache for price padding strings to avoid repeated blf.dimensions() calls.
_price_padding_cache: dict = {}


def get_perfect_price_padding(price_str: str, target_length: int = 70) -> str:
    """Generate a padding string to align price text nicely in the UI."""
    cache_key = (price_str, target_length)
    cached = _price_padding_cache.get(cache_key)
    if cached is not None:
        return cached

    spaces = [
        (19, "\u2003"),  # em space = U+2003 > 19 units
        (2, "\u200a"),  # hair space = U+200A > 2 units
        (3, "\u2009"),  # 6 em space = U+2009 > 3 units
        (5, "\u2005"),  # 4 em space = U+2005 > 5 units
        (6, "\u2004"),  # 3 em space = U+2004 > 6 units
    ]
    out = ""
    size = blf.dimensions(0, price_str)
    w_size = size[0]
    final_size = target_length - w_size
    if final_size <= 0:
        _price_padding_cache[cache_key] = out
        return out
    while w_size < target_length:
        for spc_len, spc_char in spaces:
            if w_size + spc_len <= target_length:
                out += spc_char
                w_size += spc_len
                break
        else:
            break  # No suitable space found, exit loop
    # double check if we are exporting only white spaces to prevent issues
    if re.fullmatch(r"\s*", out) is None:
        _price_padding_cache[cache_key] = ""
        return ""
    _price_padding_cache[cache_key] = out
    return out


# --- New Modal Operator ---
class BK_OT_buy_extension_and_watch(Operator):
    """Opens URL to buy extension and starts a modal timer to refresh repo periodically."""

    bl_idname = "bk.buy_extension_and_watch"
    bl_label = "Buy Extension Online and Watch"
    bl_options = {"REGISTER", "UNDO"}

    url: StringProperty(
        name="URL",
        description="Website URL to open",
    )  # type: ignore
    repo_index: IntProperty(
        name="Repository Index",
        description="Index of the repository to refresh",
        default=-1,
    )  # type: ignore

    _timer = None
    _last_refresh_time = 0
    _start_time = 0
    _refresh_interval = 60  # seconds
    _max_duration = 300  # seconds (5 minutes timeout)

    def execute(self, context):
        if not self.url:
            self.report({"ERROR"}, "No URL specified.")
            return {"CANCELLED"}
        if self.repo_index == -1:
            self.report({"ERROR"}, "No repository index specified.")
            return {"CANCELLED"}

        # Open the URL
        try:
            bpy.ops.wm.url_open(url=self.url)
            bk_logger.info("Opening buy URL: %s.", self.url)
        except Exception as e:
            self.report({"ERROR"}, f"Could not open URL: {e}")
            # Don't cancel, maybe the user still wants the refresh?
            # Decide if you want modal to continue even if URL fails

        # Add modal handler and timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(
            1.0, window=context.window
        )  # Check every second
        wm.modal_handler_add(self)
        self._start_time = time.time()
        self._last_refresh_time = (
            self._start_time
        )  # Initialize to avoid immediate refresh
        bk_logger.info(
            "Started watching repository index %s for updates.", self.repo_index
        )
        if context and context.area:
            context.area.tag_redraw()  # Update UI to show operator is running if needed
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        current_time = time.time()

        # --- Exit Conditions ---
        # 1. User closed Preferences or changed area
        if context.area is None or context.area.type != "PREFERENCES":
            bk_logger.info("Preferences window closed or changed, stopping watcher.")
            self.cancel(context)
            return {"CANCELLED"}

        # 2. Timeout
        if current_time - self._start_time > self._max_duration:
            bk_logger.info("Watcher timed out, stopping.")
            self.cancel(context)
            return {"CANCELLED"}

        # 3. User cancellation
        if event.type in {"RIGHTMOUSE", "ESC"}:
            bk_logger.info("Watcher cancelled by user.")
            self.cancel(context)
            return {"CANCELLED"}

        # --- Timer Logic ---
        if event.type == "TIMER":
            # Check if refresh interval has passed
            if current_time - self._last_refresh_time >= self._refresh_interval:
                bk_logger.info(
                    "Refresh interval reached, attempting sync for repo index %s...",
                    self.repo_index,
                )
                try:
                    # Check if repo still exists at that index
                    if self.repo_index < len(context.preferences.extensions.repos):
                        bpy.ops.extensions.repo_sync(repo_index=self.repo_index)
                        bk_logger.info(
                            "repo_sync called for index %s.", self.repo_index
                        )
                    else:
                        bk_logger.info(
                            "Repository index %s no longer valid.", self.repo_index
                        )
                        # Optionally cancel here if repo is gone
                except:
                    # This might fail if another operation is in progress
                    bk_logger.exception("extensions.repo_sync failed.")
                finally:
                    self._last_refresh_time = (
                        current_time  # Reset timer regardless of success
                    )

        return {"PASS_THROUGH"}  # Pass other events through

    def cancel(self, context):
        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            self._timer = None
            bk_logger.info("Watcher timer removed.")
        if context and context.area:
            context.area.tag_redraw()  # Update UI


# --- End New Modal Operator ---


def redraw_preferences_once():
    """Tag the redraw on the Blender preferences.
    Meant to be registered as a timer, runs just once.
    """
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type != "PREFERENCES":
                continue
            for region in area.regions:
                if region.type in {"UI", "WINDOW"}:
                    region.tag_redraw()

    return None


def extension_draw_item_blenderkit(
    layout,
    *,
    pkg_id,  # `str`
    item_local,  # `PkgManifest_Normalized | None`
    item_remote,  # `PkgManifest_Normalized | None`
    is_enabled,  # `bool`
    is_outdated,  # `bool`
    show,  # `bool`.
    mark,  # `bool | None`.
    # General vars.
    repo_index,  # `int`
    repo_item,  # `RepoItem`
    operation_in_progress,  # `bool`
    extensions_warnings,  # `dict[str, list[str]]`
    show_developer_ui,  # `bool`
):
    ### Blendkit cache code
    # Ensure cache is up-to-date before drawing
    cache_reloaded = ensure_repo_cache()
    if cache_reloaded:
        # If cache was just reloaded, tag UI for redraw
        # as UILayout doesn't have tag_redraw we call a custom function
        if bpy.app.timers.is_registered(redraw_preferences_once):
            bpy.app.timers.unregister(redraw_preferences_once)
        bpy.app.timers.register(redraw_preferences_once, first_interval=0.01)
        bk_logger.info("Cache reloaded, tagging preferences for redraw.")

    # check if the cache is already in the window manager
    if "blenderkit_extensions_repo_cache" not in bpy.context.window_manager:
        # Log if cache is missing after trying to ensure it
        bk_logger.info(
            "Extension cache not available in window_manager after ensure_repo_cache call."
        )
        # Optionally draw a minimal representation or return early to avoid errors
        # For now, just return to avoid potential errors accessing bk_ext_cache
        return

    bk_ext_cache = bpy.context.window_manager["blenderkit_extensions_repo_cache"]
    bk_cache_pkg = bk_ext_cache.get(pkg_id[:32], None)
    ### end of Blendkit cache code
    item = item_local or item_remote
    is_installed = item_local is not None
    has_remote = repo_item.remote_url != ""

    if item_remote is not None:
        pkg_block = item_remote.block
    else:
        pkg_block = None

    if is_enabled:
        item_warnings = extensions_warnings.get(
            exui.pkg_repo_module_prefix(repo_item) + pkg_id, []
        )
    else:
        item_warnings = []

    # Left align so the operator text isn't centered.
    colsub = layout.column()
    row = colsub.row(align=True)

    if show:
        props = row.operator(
            "extensions.package_show_clear", text="", icon="DOWNARROW_HLT", emboss=False
        )
    else:
        props = row.operator(
            "extensions.package_show_set", text="", icon="RIGHTARROW", emboss=False
        )
    props.pkg_id = pkg_id
    props.repo_index = repo_index

    if mark is not None:
        if mark:
            props = row.operator(
                "extensions.package_mark_clear",
                text="",
                icon="RADIOBUT_ON",
                emboss=False,
            )
        else:
            props = row.operator(
                "extensions.package_mark_set",
                text="",
                icon="RADIOBUT_OFF",
                emboss=False,
            )
        props.pkg_id = pkg_id
        props.repo_index = repo_index

    sub = row.row()
    sub.active = is_enabled
    # Without checking `is_enabled` here, there is no way for the user to know if an extension
    # is enabled or not, which is useful to show - when they may be considering removing/updating
    # extensions based on them being used or not.
    if pkg_block or item_warnings:
        sub.label(text=item.name, icon="ERROR", translate=False)
    else:
        sub.label(text=item.name, translate=False)

    # Add a top-level row so `row_right` can have a grayed out button/label
    # without graying out the menu item since# that is functional.
    row_right_toplevel = row.row(align=True)
    if operation_in_progress:
        row_right_toplevel.enabled = False
    row_right_toplevel.alignment = "RIGHT"
    row_right = row_right_toplevel.row()
    row_right.alignment = "RIGHT"

    if has_remote and (item_remote is not None):
        if pkg_block is not None:
            row_right.label(text="Blocked   ")
        elif is_installed:
            # double check if we are truly outdated
            # local repo can have a newer version than remote if user installed a dev version
            # so we compare versions here again
            local_older = version_compare.compare_versions(
                item_local.version, item_remote.version
            )
            if local_older < 0:
                props = row_right.operator("extensions.package_install", text="Update")
                props.repo_index = repo_index
                props.pkg_id = pkg_id
                props.enable_on_install = is_enabled
            elif local_older == 0:
                row_right.label(text="Up to date   ")
            else:
                props = row_right.operator(
                    "extensions.package_install",
                    text=f"Downgrade {item_remote.version}",
                )
                props.repo_index = repo_index
                props.pkg_id = pkg_id
                props.enable_on_install = is_enabled
        else:
            ### Blendkit specific code
            # Blendkit logo icon
            pcoll = icons.icon_collections["main"]
            icon_value = pcoll["logo"].icon_id

            # only enable install for those for whom it's available
            if bk_cache_pkg is not None:
                can_download_value = bk_cache_pkg.get("can_download")
                is_for_sale_flag = bk_cache_pkg.get("is_for_sale") is True
                is_free_flag = bk_cache_pkg.get("is_free") is True

                # special case for Blendkit addon itself
                if pkg_id == "blenderkit":
                    can_download_value = True

                # Free , purchased and subscribed add-ons, probably also private add-ons
                if can_download_value is True:
                    # if the addon is also for sale, it means the user purchased it and we write "install purchased"
                    if is_for_sale_flag:
                        props = row_right.operator(
                            "extensions.package_install",
                            text="Install purchased",
                            icon_value=icon_value,
                        )
                    else:
                        props = row_right.operator(
                            "extensions.package_install",
                            text="Install",
                            icon_value=icon_value,
                        )
                    props.repo_index = repo_index
                    props.pkg_id = pkg_id

                # Free addon but limited to full plan
                elif (can_download_value == "Rejected in this plan") or (
                    not is_free_flag and not is_for_sale_flag
                ):
                    props = row_right.operator(
                        "wm.url_open",
                        text="Requires Full Plan",
                        icon_value=icon_value,
                    )
                    props.url = "https://www.blendkit.com/plans/pricing/"

                # Paid addons get a buy button and lead to their website link
                else:
                    # Use the new modal operator
                    base_price_value = bk_cache_pkg.get("user_price")
                    if base_price_value in {None, "", "None"}:
                        base_price_value = bk_cache_pkg.get("base_price")
                    if base_price_value in {None, "", "None"}:
                        buy_label = "Buy online"
                    else:
                        pad_str = get_perfect_price_padding(base_price_value)
                        buy_label = f"Buy online {pad_str}${base_price_value}"
                    props = row_right.operator(
                        BK_OT_buy_extension_and_watch.bl_idname,  # Use bl_idname
                        text=buy_label,
                        icon_value=icon_value,
                    )
                    props.url = bk_cache_pkg.get("website", "")  # Pass URL
                    props.repo_index = repo_index  # Pass repo index
            ### end of Blendkit specific code
    else:
        # Right space for alignment with the button.
        if has_remote and (item_remote is None):
            # There is a local item with no remote
            row_right.label(text="Orphan   ")

        row_right.active = False

    row_right = row_right_toplevel.row(align=True)
    row_right.alignment = "RIGHT"
    row_right.separator()

    # NOTE: Keep space between any buttons and this menu to prevent stray clicks accidentally running install.
    # The separator is around together with the align to give some space while keeping the button and the menu
    # still close-by. Used `extension_path` so the menu can access "this" extension.
    row_right.context_string_set(
        "extension_path", "{:s}.{:s}".format(repo_item.module, pkg_id)
    )
    row_right.menu("USERPREF_MT_extensions_item", text="", icon="DOWNARROW_HLT")

    if show:
        import os

        from bpy.app.translations import pgettext_iface as iface_

        col = layout.column()

        row = col.row()
        row.active = is_enabled

        # The full tagline may be multiple lines (not yet supported by Blender's UI).
        row.label(text=" {:s}.".format(item.tagline), translate=False)

        col.separator(type="LINE")

        col_info = layout.column()
        col_info.active = is_enabled
        split = col_info.split(factor=0.15)
        col_a = split.column()
        col_b = split.column()
        col_a.alignment = "RIGHT"

        if pkg_block is not None:
            col_a.label(text="Blocked")
            col_b.label(text=pkg_block.reason, translate=False)

        if item_warnings:
            col_a.label(text="Warning")
            col_b.label(text=item_warnings[0])
            if len(item_warnings) > 1:
                for value in item_warnings[1:]:
                    col_a.label(text="")
                    col_b.label(text=value)
                # pylint: disable-next=undefined-loop-variable

        if value := (item_remote or item_local).website:
            col_a.label(text="Website")
            col_b.split(factor=0.5).operator(
                "wm.url_open",
                text=exui.domain_extract_from_url(value),
                icon="URL",
            ).url = value
        del value

        if item.type == "add-on":
            col_a.label(text="Permissions")
            # WARNING: while this is documented to be a dict, old packages may contain a list of strings.
            # As it happens dictionary keys & list values both iterate over string,
            # however we will want to show the dictionary values eventually.
            if value := item.permissions:
                col_b.label(
                    text=", ".join([iface_(x).title() for x in value]), translate=False
                )
            else:
                col_b.label(text="No permissions specified")
            del value

        col_a.label(text="Maintainer")
        col_b.label(text=item.maintainer, translate=False)

        col_a.label(text="Version")
        if is_outdated:
            col_b.label(
                text=iface_("{:s} ({:s} available)").format(
                    item.version, item_remote.version
                ),
                translate=False,
            )
        else:
            col_b.label(text=item.version, translate=False)

        if has_remote and (item_remote is not None):
            col_a.label(text="Size")
            col_b.label(
                text=exui.size_as_fmt_string(item_remote.archive_size), translate=False
            )

        col_a.label(text="License")
        col_b.label(text=item.license, translate=False)

        col_a.label(text="Repository")
        col_b.label(text=repo_item.name, translate=False)

        if is_installed:
            col_a.label(text="Path")
            col_b.label(text=os.path.join(repo_item.directory, pkg_id), translate=False)


def extension_draw_item_override(
    layout,
    *,
    pkg_id,  # `str`
    item_local,  # `PkgManifest_Normalized | None`
    item_remote,  # `PkgManifest_Normalized | None`
    is_enabled,  # `bool`
    is_outdated,  # `bool`
    show,  # `bool`.
    mark,  # `bool | None`.
    # General vars.
    repo_index,  # `int`
    repo_item,  # `RepoItem`
    operation_in_progress,  # `bool`
    extensions_warnings,  # `dict[str, list[str]]`
    show_developer_ui=False,  # `bool`
):
    # filter by verification state, only for Blendkit repository
    if repo_item.remote_url == EXTENSIONS_API_URL:
        extension_draw_item_blenderkit(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
            show_developer_ui=show_developer_ui,
        )
        return True

    # show developer ui only needs to be passed since blender 4.4
    if bpy.app.version >= (4, 4):
        exui.extension_draw_item_original(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
            show_developer_ui=show_developer_ui,
        )
    else:
        exui.extension_draw_item_original(
            layout,
            pkg_id=pkg_id,
            item_local=item_local,
            item_remote=item_remote,
            is_enabled=is_enabled,
            is_outdated=is_outdated,
            show=show,
            mark=mark,
            repo_index=repo_index,
            repo_item=repo_item,
            operation_in_progress=operation_in_progress,
            extensions_warnings=extensions_warnings,
        )

    return True


def override_draw_function():
    if hasattr(exui, "extension_draw_item_original"):
        return False
    exui.extension_draw_item_original = exui.extension_draw_item
    exui.extension_draw_item = extension_draw_item_override
    return True


def get_repository_by_url(url: str):
    """Get the repository by its remote URL, from registered Blendkit Extension repositories."""
    for r in bpy.context.preferences.extensions.repos:
        if r.remote_url == url:
            return r
    return None


def get_blenderkit_repository_cached():
    """Get Blendkit repository with time-based caching to avoid iterating repos per item."""
    global _cached_repository, _cached_repository_time
    now = time.time()
    if (
        now - _cached_repository_time < _REPO_LOOKUP_INTERVAL
        and _cached_repository is not None
    ):
        # Verify the cached reference is still valid
        try:
            _ = _cached_repository.remote_url
            return _cached_repository
        except ReferenceError:
            pass
    _cached_repository = get_repository_by_url(EXTENSIONS_API_URL)
    _cached_repository_time = now
    return _cached_repository


def clear_repo_cache():
    """Clear the repository cache."""
    global _repo_cache_last_check, _repo_cache_last_result
    wm = bpy.context.window_manager
    cache_key = "blenderkit_extensions_repo_cache"
    if cache_key in wm:
        del wm[cache_key]
    # Reset throttle so next ensure_repo_cache() does a fresh check
    _repo_cache_last_check = 0.0
    _repo_cache_last_result = False


def _sanitize_pkg_for_cache(pkg):
    """Keep values stored as string to prevent C overflow."""
    sanitized = {}
    for k, v in pkg.items():
        if isinstance(v, bool):
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return sanitized


def ensure_repo_cache():
    r"""
    Reads the .json file blender stores in \extensions\www_blenderkit_com\.blender_ext
    and parses it to a dict from json, we can use it then for drawing purposes and have the extra data Blendkit api provides.
    Checks the modification time of the cache file and reloads it if necessary.

    Uses a time-based throttle so filesystem checks happen at most once per
    _REPO_CACHE_CHECK_INTERVAL seconds, avoiding repeated stat calls when this
    function is called per-item during extension list drawing.
    """
    global _repo_cache_last_check, _repo_cache_last_result

    now = time.time()
    if now - _repo_cache_last_check < _REPO_CACHE_CHECK_INTERVAL:
        # Consume the reload signal so only the first caller in the throttle window
        # sees True — prevents the redraw timer from being registered on every draw tick.
        result = _repo_cache_last_result
        _repo_cache_last_result = False
        return result
    _repo_cache_last_check = now

    reloaded_flag = False  # Track if we actually reloaded
    wm = bpy.context.window_manager
    cache_key = "blenderkit_extensions_repo_cache"
    mtime_key = "blenderkit_extensions_repo_cache_mtime"

    blenderkit_repository = get_blenderkit_repository_cached()
    if blenderkit_repository is None:
        # If repo doesn't exist, clear cache if it exists in window manager
        if cache_key in wm:
            del wm[cache_key]
            bk_logger.info("Cleared stale extension cache for missing repository.")
        if mtime_key in wm:
            del wm[mtime_key]
        bk_logger.debug("Repository not found, exiting check.")
        return False  # No repo, nothing loaded

    # get the path to the cache file which is in repository directory under /.blender_ext/index.json
    cache_file = os.path.join(
        blenderkit_repository.directory, ".blender_ext", "index.json"
    )

    current_mtime = None
    try:
        if os.path.exists(cache_file):
            # Use int to avoid float precision loss when stored in Blender IDProperty
            # (IDProperties use single-precision floats, os.path.getmtime() returns double)
            current_mtime = int(os.path.getmtime(cache_file))
    except OSError as e:  # Handle potential race condition or permission issue
        bk_logger.exception("Could not get modification time for %s.", cache_file)
        # Clear cache if we can't verify its freshness? Safer approach.
        if cache_key in wm:
            del wm[cache_key]
            bk_logger.info("Cleared extension cache due to mtime access error.")
        if mtime_key in wm:
            del wm[mtime_key]
        return False  # Error, nothing loaded

    stored_mtime = wm.get(mtime_key, None)

    # --- Determine if reload is needed ---
    should_reload = False
    if cache_key not in wm:
        if current_mtime is not None:  # Only load if file actually exists
            should_reload = True  # Cache doesn't exist, need initial load.
        else:
            # Cache doesn't exist and file doesn't exist/accessible. Fall through to check if we need to clear.
            pass

    elif current_mtime is None:
        # Cache exists in wm, but file is gone/inaccessible. Clear stale cache.
        del wm[cache_key]
        if mtime_key in wm:
            del wm[mtime_key]
        return False  # Cleared stale cache, did not load new data

    elif cache_key not in wm and current_mtime is None:
        # Cache doesn't exist, and file doesn't exist. Nothing to do or load.
        return False

    elif (
        cache_key in wm and (stored_mtime is None or stored_mtime != current_mtime)
    ) or (
        cache_key not in wm and current_mtime is not None
    ):  # Reload if cache exists and is outdated, OR if cache doesn't exist but file does
        should_reload = True  # Cache exists but is outdated or missing mtime.

    if not should_reload:
        # Cache exists and is up-to-date
        return False  # Nothing reloaded

    # --- (Re)Load cache ---
    try:
        with open(cache_file, "r", encoding="utf-8") as f:  # Specify encoding
            data_str = f.read()
        data = json.loads(data_str)

        # store the data as a dict with keys being the package names (first 32 chars)
        new_cache = {}
        for pkg in data.get(
            "data", []
        ):  # Handle case where 'data' key might be missing
            if not (isinstance(pkg, dict) and "id" in pkg):
                bk_logger.info("Skipping invalid package entry in cache: %s.", pkg)
                continue
            new_cache[pkg["id"][:32]] = _sanitize_pkg_for_cache(pkg)

        wm[cache_key] = new_cache
        wm[mtime_key] = current_mtime  # Stored as int to survive IDProperty round-trip

        reloaded_flag = True  # Mark that we reloaded successfully

    except json.JSONDecodeError:
        bk_logger.warning(
            "Error decoding JSON from %s. Cache not loaded/updated.", cache_file
        )
        # Clear potentially corrupt cache? Or leave old one? Clearing is safer.
        if cache_key in wm:
            del wm[cache_key]
            bk_logger.info("Cleared cache due to JSON error.")
        if mtime_key in wm:
            del wm[mtime_key]
    except Exception:
        bk_logger.exception("Error reading or processing cache file %s.", cache_file)
        # Clear potentially corrupt cache?
        if cache_key in wm:
            del wm[cache_key]
            bk_logger.info("Cleared cache due to file processing error.")
        if mtime_key in wm:
            del wm[mtime_key]

    _repo_cache_last_result = reloaded_flag
    return reloaded_flag  # Return whether cache was actually reloaded


def update_cache_with_asset_prices(assets):
    """Copy addon pricing info from search assets into the extensions cache."""
    if not assets:
        return

    wm = bpy.context.window_manager
    cache_key = "blenderkit_extensions_repo_cache"
    if cache_key not in wm:
        wm[cache_key] = {}

    cache = wm[cache_key]
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("assetType") != "addon":
            continue
        dict_params = asset.get("dictParameters") or {}
        extension_id = dict_params.get("extensionId") or asset.get("extensionId")
        if not extension_id:
            continue

        cache_key_entry = extension_id[:32]
        cache_entry = cache.get(cache_key_entry)
        if cache_entry is None:
            cache_entry = {}
            cache[cache_key_entry] = cache_entry

        base_price = asset.get("basePrice")
        if base_price not in {None, "", "None"}:
            cache_entry["base_price"] = str(base_price)

        user_price = asset.get("userPrice")
        if user_price not in {None, "", "None"}:
            cache_entry["user_price"] = str(user_price)


def ensure_repo_order():
    """Ensure order of repositories in Blender's preferences."""
    # get the Blendkit repository
    blenderkit_repository = get_repository_by_url(EXTENSIONS_API_URL)
    if blenderkit_repository is None:
        return

    # get all repositories
    all_repos = bpy.context.preferences.extensions.repos
    # get all online repositories except Blendkit
    online_repos = []  # need to convert repos to dicts
    remove_online_repos = []
    for r in all_repos:
        if r.remote_url != EXTENSIONS_API_URL and r.remote_url != "":

            repo_dict = {
                "name": r.name,
                "module": r.module,
                "use_remote_url": r.use_remote_url,
                "remote_url": r.remote_url,
                "use_sync_on_startup": r.use_sync_on_startup,
                "use_cache": r.use_cache,
                "use_access_token": r.use_access_token,
                "access_token": r.access_token,
                "use_custom_directory": r.use_custom_directory,
                "custom_directory": r.custom_directory,
                "enabled": r.enabled,
            }
            online_repos.append(repo_dict)
            remove_online_repos.append(r)

    # remove all online repositories except Blendkit
    for r in remove_online_repos:
        all_repos.remove(r)

    # add all other repositories back
    for r in online_repos:
        # complete list of properties of a repository:
        #'access_token', 'custom_directory', 'directory', 'enabled', 'module', 'name', 'remote_url', 'rna_type', 'source', 'use_access_token', 'use_cache', 'use_custom_directory', 'use_remote_url', 'use_sync_on_startup'

        new_repo = all_repos.new()
        new_repo.name = r["name"]
        new_repo.module = r["module"]
        new_repo.use_remote_url = r["use_remote_url"]
        new_repo.remote_url = r["remote_url"]
        new_repo.use_sync_on_startup = r["use_sync_on_startup"]
        new_repo.use_cache = r["use_cache"]
        new_repo.use_access_token = r["use_access_token"]
        new_repo.access_token = r["access_token"]
        new_repo.use_custom_directory = r["use_custom_directory"]
        new_repo.custom_directory = r["custom_directory"]
        new_repo.enabled = r["enabled"]


def migrate_repository():
    """Migrate legacy BlenderKit extension repositories to the new Blendkit URL.

    Installs created before the rename from BlenderKit to Blendkit registered
    the extensions repository with the old server URL (www.blenderkit.com).
    After the rename ``ensure_repository()`` adds a fresh repository pointing to
    the new URL (www.blendkit.com), leaving the user with two colliding
    repositories (e.g. "www.blenderkit.com" and "www.blenderkit.com.001").

    This updates any repository still pointing at the legacy URL to the new URL
    and removes the resulting duplicates, keeping a single repository.
    """
    repos = bpy.context.preferences.extensions.repos

    # Point any repository still using the legacy URL at the new one.
    for r in repos:
        if r.remote_url == LEGACY_EXTENSIONS_API_URL:
            bk_logger.info(
                "Migrating extensions repository '%s' from %s to %s",
                r.name,
                LEGACY_EXTENSIONS_API_URL,
                EXTENSIONS_API_URL,
            )
            r.remote_url = EXTENSIONS_API_URL

    # Collect all repositories now pointing at the new URL.
    matching = [r for r in repos if r.remote_url == EXTENSIONS_API_URL]
    if not matching:
        return

    # Choose which repository to keep. Prefer the one with the canonical module
    # name, then one whose name has no numeric ".001" suffix, then the first.
    def _rank(r):
        if r.module == EXTENSIONS_REPO_MODULE:
            return 0
        if not re.search(r"\.\d{3}$", r.name):
            return 1
        return 2

    keep = min(matching, key=_rank)
    keep_module = keep.module

    # Remove any duplicate repositories pointing at the new URL.
    to_remove = [
        r
        for r in repos
        if r.remote_url == EXTENSIONS_API_URL and r.module != keep_module
    ]
    for r in to_remove:
        bk_logger.info("Removing duplicate extensions repository '%s'", r.name)
        repos.remove(r)

    # Normalize the surviving repository's module back to the canonical value.
    # Installed extensions are registered as ``bl_ext.<module>.<pkg>`` and their
    # files live in the directory derived from the module, so a leftover
    # "_001" module orphans every previously installed extension. Only one
    # Blendkit repo remains at this point, so the canonical module is free.
    if keep.module != EXTENSIONS_REPO_MODULE:
        bk_logger.info(
            "Restoring extensions repository module '%s' to '%s'",
            keep.module,
            EXTENSIONS_REPO_MODULE,
        )
        # A custom directory would keep files in the old "_001" location; clear
        # it so Blender uses the canonical module-derived directory.
        keep.use_custom_directory = False
        keep.module = EXTENSIONS_REPO_MODULE

    # Normalize the surviving repository's display name (e.g. strip a ".001"
    # suffix left over from the duplicate collision).
    if keep.name != "www.blenderkit.com":
        bk_logger.info(
            "Renaming extensions repository '%s' to 'www.blenderkit.com'", keep.name
        )
        keep.name = "www.blenderkit.com"


def ensure_repository(api_key: str = ""):
    """Ensure that the Blendkit extensions repository is correctly added in Blender's preferences.
    If the repository is not present, it is added. If the repository is present, but the API key is not set, it is set.
    """

    migrate_repository()
    blenderkit_repository = get_repository_by_url(EXTENSIONS_API_URL)

    if blenderkit_repository is None:

        blenderkit_repository = bpy.context.preferences.extensions.repos.new()
        blenderkit_repository.name = "www.blenderkit.com"
        blenderkit_repository.module = "www_blenderkit_com"
        blenderkit_repository.use_remote_url = True
        blenderkit_repository.remote_url = EXTENSIONS_API_URL
        blenderkit_repository.use_sync_on_startup = True

    if api_key != "":
        blenderkit_repository.use_access_token = True
        blenderkit_repository.access_token = api_key
    else:
        # let's try to import Blendkit preferences and get the api key
        # try:
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        api_key = user_preferences.api_key
        if api_key != "":
            blenderkit_repository.use_access_token = True
            blenderkit_repository.access_token = api_key
        else:
            # clear after logout
            blenderkit_repository.use_access_token = False
            blenderkit_repository.access_token = ""
        # pass
    # ensure_repo_order()
    ensure_repo_cache()


def register():

    ensure_repository()
    override_draw_function()
    bpy.utils.register_class(BK_OT_buy_extension_and_watch)  # Register new operator


def unregister():
    exui.extension_draw_item = exui.extension_draw_item_original
    del exui.extension_draw_item_original
    bpy.utils.unregister_class(BK_OT_buy_extension_and_watch)  # Unregister new operator
