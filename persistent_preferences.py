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

import json
import logging
import os

import bpy

from . import paths, utils


bk_logger = logging.getLogger(__name__)


def get_preferences_path() -> str:
    """Return path to the persistent JSON preferences file."""
    config_dir = paths.get_config_dir_path()
    preferences_path = os.path.join(config_dir, "preferences.json")
    return os.path.abspath(preferences_path)


def write_preferences_to_JSON(preferences: dict):
    """Write preferences to JSON file, called on save_prefs()."""
    paths.ensure_config_dir_exists()
    preferences_path = get_preferences_path()
    try:
        with open(preferences_path, "w", encoding="utf-8") as s:
            json.dump(preferences, s, ensure_ascii=False, indent=4)
        bk_logger.info("Saved preferences to %s", preferences_path)
    except Exception as e:
        bk_logger.warning("Failed to save preferences: %s", e)


def get_legacy_assetbar_expanded_preference(prefs: dict, user_preferences) -> bool:
    """Resolve asset bar expanded state for older preference files."""
    if "assetbar_expanded" in prefs:
        return bool(prefs["assetbar_expanded"])
    is_property_set = getattr(user_preferences, "is_property_set", None)
    if callable(is_property_set) and is_property_set("assetbar_expanded"):
        return bool(user_preferences.assetbar_expanded)
    saved_rows = prefs.get(
        "maximized_assetbar_rows", user_preferences.maximized_assetbar_rows
    )
    return int(saved_rows) > 1


def load_preferences_from_JSON():
    """Load preferences from JSON file and update the user preferences accordingly."""
    preferences_path = get_preferences_path()
    if os.path.exists(preferences_path) is not True:
        return utils.get_preferences_as_dict()

    try:
        with open(preferences_path, "r", encoding="utf-8") as s:
            prefs = json.load(s)
    except Exception as e:
        bk_logger.warning("Failed to read preferences from JSON: {e}")
        os.remove(preferences_path)
        return utils.get_preferences_as_dict()

    user_preferences = bpy.context.preferences.addons[__package__].preferences
    user_preferences.preferences_lock = True

    # STATISTICS
    user_preferences.download_counter = prefs.get(
        "download_counter", user_preferences.download_counter
    )
    user_preferences.asset_popup_counter = prefs.get(
        "asset_popup_counter", user_preferences.asset_popup_counter
    )
    user_preferences.welcome_operator_counter = prefs.get(
        "welcome_operator_counter", user_preferences.welcome_operator_counter
    )
    # MAIN PREFERENCES
    user_preferences.api_key = prefs.get("api_key", user_preferences.api_key)
    user_preferences.api_key_refresh = prefs.get(
        "api_key_refresh", user_preferences.api_key_refresh
    )
    user_preferences.api_key_timeout = prefs.get(
        "api_key_timeout", user_preferences.api_key_timeout
    )
    user_preferences.experimental_features = prefs.get(
        "experimental_features", user_preferences.experimental_features
    )
    user_preferences.send_usage_data = prefs.get(
        "send_usage_data", user_preferences.send_usage_data
    )
    user_preferences.keep_preferences = prefs.get(
        "keep_preferences", user_preferences.keep_preferences
    )

    # FILE PATHS
    user_preferences.directory_behaviour = prefs.get(
        "directory_behaviour", user_preferences.directory_behaviour
    )
    user_preferences.global_dir = prefs.get("global_dir", user_preferences.global_dir)
    user_preferences.project_subdir = prefs.get(
        "project_subdir", user_preferences.project_subdir
    )
    user_preferences.unpack_files = prefs.get(
        "unpack_files", user_preferences.unpack_files
    )
    user_preferences.create_asset_library = prefs.get(
        "create_asset_library", user_preferences.create_asset_library
    )

    # GUI
    user_preferences.show_on_start = prefs.get(
        "show_on_start", user_preferences.show_on_start
    )
    user_preferences.thumb_size = prefs.get("thumb_size", user_preferences.thumb_size)
    user_preferences.maximized_assetbar_rows = prefs.get(
        "maximized_assetbar_rows", user_preferences.maximized_assetbar_rows
    )
    user_preferences.assetbar_expanded = get_legacy_assetbar_expanded_preference(
        prefs, user_preferences
    )
    user_preferences.search_field_width = prefs.get(
        "search_field_width", user_preferences.search_field_width
    )
    user_preferences.search_in_header = prefs.get(
        "search_in_header", user_preferences.search_in_header
    )
    user_preferences.tips_on_start = prefs.get(
        "tips_on_start", user_preferences.tips_on_start
    )
    user_preferences.announcements_on_start = prefs.get(
        "announcements_on_start", user_preferences.announcements_on_start
    )
    user_preferences.assetbar_follows_cursor = prefs.get(
        "assetbar_follows_cursor", user_preferences.assetbar_follows_cursor
    )
    user_preferences.proxor_enabled = prefs.get(
        "proxor_enabled", user_preferences.proxor_enabled
    )
    user_preferences.rating_nudge_enabled = prefs.get(
        "rating_nudge_enabled", user_preferences.rating_nudge_enabled
    )

    # NETWORK
    user_preferences.client_port = prefs.get(
        "client_port", user_preferences.client_port
    )
    user_preferences.ip_version = prefs.get("ip_version", user_preferences.ip_version)
    try:
        user_preferences.ssl_context = prefs.get(
            "ssl_context", user_preferences.ssl_context
        )
    except Exception as e:
        print(f"Failed to load ssl_context: {e}")
    user_preferences.proxy_which = prefs.get(
        "proxy_which", user_preferences.proxy_which
    )
    user_preferences.proxy_address = prefs.get(
        "proxy_address", user_preferences.proxy_address
    )
    user_preferences.trusted_ca_certs = prefs.get(
        "trusted_ca_certs", user_preferences.trusted_ca_certs
    )

    # UPDATES
    user_preferences.auto_check_update = prefs.get(
        "auto_check_update", user_preferences.auto_check_update
    )
    user_preferences.enable_prereleases = prefs.get(
        "enable_prereleases", user_preferences.enable_prereleases
    )
    user_preferences.updater_interval_months = prefs.get(
        "updater_interval_months", user_preferences.updater_interval_months
    )
    user_preferences.updater_interval_days = prefs.get(
        "updater_interval_days", user_preferences.updater_interval_days
    )

    # IMPORT SETTINGS
    user_preferences.resolution = prefs.get("resolution", user_preferences.resolution)
    # THUMBNAIL SETTINGS
    utils.apply_thumbnail_settings_from_dict(
        getattr(user_preferences, "thumbnail_settings", None),
        prefs.get("thumbnail_settings", {}),
    )
    bk_logger.info("Successfully loaded preferences from %s", preferences_path)
    user_preferences.preferences_lock = False
    return prefs


def property_keep_preferences_updated(user_preferences, context):
    """Runs when keep_preferences BoolProperty is updated.
    Delete preferences JSON file if set to False. Call save_prefs() in all cases.
    """
    if user_preferences.keep_preferences is True:
        return utils.save_prefs(user_preferences, context)

    preferences_path = get_preferences_path()
    if os.path.exists(preferences_path) is False:
        return utils.save_prefs(user_preferences, context)

    try:
        os.remove(preferences_path)
        bk_logger.info("Deleted preferences file %s", preferences_path)
    except Exception as e:
        bk_logger.error("Failed to delete preferences file %s: %s", preferences_path, e)
    utils.save_prefs(user_preferences, context)
