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

"""Functions for background processes.
Not used directly in Blendkit addon, but in Blendkit background processes.
"""

import logging
import os

import addon_utils  # type: ignore

from . import client_lib, download, paths


bk_logger = logging.getLogger(__name__)


def download_asset_file(asset_data, resolution="blend", api_key=""):
    """This is a simple non-threaded way to download files for background thumbnail rerender and others."""

    # make sure Blendkit is enabled, needed for downloading.
    addon_utils.enable(
        "blenderkit", default_set=True, persistent=True, handle_error=None
    )

    file_names = paths.get_download_filepaths(asset_data, resolution)
    if len(file_names) == 0:
        return None
    file_name = file_names[0]
    if download.check_existing(asset_data, resolution=resolution):
        # this sends the thread for processing, where another check should occur, since the file might be corrupted.
        bk_logger.debug("not downloading, already in db")
        return file_name

    res_file_info, resolution = paths.get_res_file(asset_data, resolution)
    response = client_lib.blocking_file_download(
        str(res_file_info["url"]), filepath=file_name, api_key=api_key
    )
    return file_name


def delete_unfinished_file(file_name):
    """Deletes download if it wasn't finished. If the directory it's containing is empty, it also removes the directory."""
    try:
        os.remove(file_name)
    except Exception as e:
        bk_logger.error("Could not delete unfinished file %s: %s", file_name, e)
    asset_dir = os.path.dirname(file_name)
    if len(os.listdir(asset_dir)) == 0:
        os.rmdir(asset_dir)
    return
