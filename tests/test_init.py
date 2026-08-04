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
import sys
import unittest

import bpy

# ``test.py`` imports this as ``<addon>.tests.<name>``; strip ``.tests`` so
# ``__package__`` is the add-on's own module - needed by the relative import
# and the ``bpy...addons[__package__]`` lookups below. Scanning ``addons`` for
# "blenderkit" is unreliable when several blenderkit* add-ons are enabled.
if __package__:
    __package__ = __package__.rsplit(".tests", 1)[0]

else:
    # Running this file directly (e.g. in VSCode) sets ``__package__`` to None.
    # This is a hack to make the relative import work in that case.
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    __package__ = os.path.basename(os.path.dirname(__file__))

from . import client_lib, global_vars


class Test01Registration(unittest.TestCase):
    def test01_global_vars_VERSION_set(self):
        assert global_vars.VERSION is not None
        assert global_vars.VERSION != [0, 0, 0, 0]
        version = sys.modules[__package__].bl_info["version"]
        assert global_vars.VERSION == version

    def test02_global_vars_PREFS_set(self):
        assert global_vars.PREFS != {}
        user_preferences = bpy.context.preferences.addons[__package__].preferences
        ts = user_preferences.thumbnail_settings
        prefs = {
            # SYSTEM STUFF
            "debug_value": bpy.app.debug_value,
            "binary_path": bpy.app.binary_path,
            "addon_dir": client_lib.get_addon_dir(),
            "addon_module_name": __package__,
            "app_id": os.getpid(),
            # STATISTICS
            "download_counter": user_preferences.download_counter,
            "asset_popup_counter": user_preferences.asset_popup_counter,
            "welcome_operator_counter": user_preferences.welcome_operator_counter,
            # MAIN PREFERENCES
            "api_key": user_preferences.api_key,
            "api_key_refresh": user_preferences.api_key_refresh,
            "api_key_timeout": user_preferences.api_key_timeout,
            "experimental_features": user_preferences.experimental_features,
            "keep_preferences": user_preferences.keep_preferences,
            # FILE PATHS
            "directory_behaviour": user_preferences.directory_behaviour,
            "global_dir": user_preferences.global_dir,
            "project_subdir": user_preferences.project_subdir,
            "unpack_files": user_preferences.unpack_files,
            "create_asset_library": user_preferences.create_asset_library,
            # GUI
            "show_on_start": user_preferences.show_on_start,
            "thumb_size": user_preferences.thumb_size,
            "maximized_assetbar_rows": user_preferences.maximized_assetbar_rows,
            "assetbar_expanded": user_preferences.assetbar_expanded,
            "search_field_width": user_preferences.search_field_width,
            "search_in_header": user_preferences.search_in_header,
            "tips_on_start": user_preferences.tips_on_start,
            "announcements_on_start": user_preferences.announcements_on_start,
            "assetbar_follows_cursor": user_preferences.assetbar_follows_cursor,
            "proxor_enabled": user_preferences.proxor_enabled,
            "rating_nudge_enabled": user_preferences.rating_nudge_enabled,
            "comments_order": user_preferences.comments_order,
            # NETWORK
            "client_port": user_preferences.client_port,
            "ip_version": user_preferences.ip_version,
            "ssl_context": user_preferences.ssl_context,
            "proxy_which": user_preferences.proxy_which,
            "proxy_address": user_preferences.proxy_address,
            "trusted_ca_certs": user_preferences.trusted_ca_certs,
            # UPDATES
            "auto_check_update": user_preferences.auto_check_update,
            "enable_prereleases": user_preferences.enable_prereleases,
            "updater_interval_months": user_preferences.updater_interval_months,
            "updater_interval_days": user_preferences.updater_interval_days,
            # IMPORT SETTINGS
            "resolution": user_preferences.resolution,
            # THUMBNAIL SETTINGS
            "thumbnail_settings": {
                "thumbnail_render_engine": ts.thumbnail_render_engine,
                "thumbnail_resolution": ts.thumbnail_resolution,
                "thumbnail_samples": ts.thumbnail_samples,
                "thumbnail_denoising": ts.thumbnail_denoising,
                "thumbnail_background_lightness": ts.thumbnail_background_lightness,
                "thumbnail_angle": ts.thumbnail_angle,
                "thumbnail_snap_to": ts.thumbnail_snap_to,
                "thumbnail_material_color": list(ts.thumbnail_material_color),
                "thumbnail_generator_type": ts.thumbnail_generator_type,
                "thumbnail_scale": ts.thumbnail_scale,
                "thumbnail_background": ts.thumbnail_background,
                "adaptive_subdivision": ts.adaptive_subdivision,
                "thumbnail_use_gpu": ts.thumbnail_use_gpu,
            },
        }
        self.maxDiff = None
        self.assertDictEqual(global_vars.PREFS, prefs)
