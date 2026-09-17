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
import shutil

import bpy

from . import client_tasks, global_vars, paths


bk_logger = logging.getLogger(__name__)


def filter_category(category):
    """filter categories with no assets, so they aren't shown in search panel"""
    if category["assetCount"] < 1:
        return True
    else:
        to_remove = []
        for c in category["children"]:
            if filter_category(c):
                to_remove.append(c)
        for c in to_remove:
            category["children"].remove(c)


def filter_categories(categories):
    for category in categories:
        filter_category(category)


def get_category_path(categories, category):
    """finds the category in all possible subcategories and returns the path to it"""
    category_path = []
    check_categories = categories[:]
    parents = {}
    while len(check_categories) > 0:
        ccheck = check_categories.pop()
        if not ccheck.get("children"):
            continue

        for ch in ccheck["children"]:
            parents[ch["slug"]] = ccheck["slug"]

            if ch["slug"] == category:
                category_path = [ch["slug"]]
                slug = ch["slug"]
                while parents.get(slug):
                    slug = parents.get(slug)
                    category_path.insert(0, slug)
                return category_path
            check_categories.append(ch)
    return category_path


def get_category_name_path(categories, category):
    """Finds the category in all possible subcategories and returns the path to it."""
    category_path = []
    check_categories = categories[:]
    parents = {}
    while len(check_categories) > 0:
        ccheck = check_categories.pop()
        if not ccheck.get("children"):
            continue

        for ch in ccheck["children"]:
            parents[ch["slug"]] = ccheck

            if ch["slug"] == category:
                category_path = [ch["name"]]
                slug = ch["slug"]
                while parents.get(slug):
                    parent = parents.get(slug)
                    slug = parent["slug"]

                    category_path.insert(0, parent["name"])
                return category_path
            check_categories.append(ch)
    return category_path


def get_category(categories, cat_path=()) -> dict:
    """Finds the category in all possible subcategories and returns the category dict."""
    for category in cat_path:
        for c in categories:
            if c["slug"] == category:
                categories = c["children"]
                if category == cat_path[-1]:
                    return c
                break
    return {}


def handle_categories_task(task: client_tasks.Task):
    """Handle incomming categories_update task which contains information about fetching updated categories.
    TODO: would be ideal if the file handling (saving, reading fallback JSON) would be done on the Client side.
    """
    if task.status not in ["finished", "error"]:
        return
    tempdir = paths.get_temp_dir()
    categories_filepath = os.path.join(tempdir, "categories.json")
    global_vars.DATA["active_category_browse"] = {
        "MODEL": ["model"],
        "SCENE": ["scene"],
        "HDR": ["hdr"],
        "MATERIAL": ["material"],
        "BRUSH": ["brush"],
        "NODEGROUP": ["nodegroup"],
        "PRINTABLE": ["printable"],
        "ADDON": ["addon"],
        "AUTHOR": ["author"],
    }

    if task.status == "finished":
        global_vars.DATA["bkit_categories"] = task.result
        with open(categories_filepath, "w", encoding="utf-8") as file:
            json.dump(
                task.result, file, ensure_ascii=False, indent=4
            )  # TODO: do this in Client, just saving the file so next time it is updated even without internet
        return

    bk_logger.warning("Could not load categories: %s", task.message)
    if not os.path.exists(categories_filepath):
        source_path = paths.get_addon_file(subpath="data" + os.sep + "categories.json")
        try:
            shutil.copy(source_path, categories_filepath)
        except Exception as e:
            bk_logger.warning("Could not copy categories file: %s", e)
            return

    try:
        with open(categories_filepath, "r", encoding="utf-8") as catfile:
            global_vars.DATA["bkit_categories"] = json.load(catfile)
    except Exception as e:
        bk_logger.warning("Could not read categories file: %s", e)


# def get_upload_asset_type(self):
#     typemapper = {
#         bpy.types.Object.blenderkit: 'model',
#         bpy.types.Scene.blenderkit: 'scene',
#         bpy.types.Image.blenderkit: 'hdr',
#         bpy.types.Material.blenderkit: 'material',
#         bpy.types.Brush.blenderkit: 'brush'
#     }
#     asset_type = typemapper[type(self)]
#     return asset_type


def update_category_enums(self, context):
    """Fixes if lower level is empty - sets it to None, because enum value can be higher."""
    enums = get_subcategory_enums(self, context)
    if enums[0][0] == "NONE" and (
        self.subcategory != "NONE" and self.subcategory != "EMPTY"
    ):
        self.subcategory = "NONE"


def update_subcategory_enums(self, context):
    """Fixes if lower level is empty - sets it to None, because enum value can be higher."""
    enums = get_subcategory1_enums(self, context)
    if enums[0][0] == "NONE" and (
        self.subcategory1 != "NONE" and self.subcategory1 != "EMPTY"
    ):
        self.subcategory1 = "NONE"


def get_category_enums(self, context):
    props = bpy.context.window_manager.blenderkitUI
    asset_type = props.asset_type.lower()
    # asset_type = self.asset_type#get_upload_asset_type(self)
    if global_vars.DATA.get("bkit_categories") is None:
        return [
            ("EMPTY", "Empty", "no categories on this level defined"),
        ]

    asset_categories = get_category(
        global_vars.DATA["bkit_categories"], cat_path=(asset_type,)
    )
    items = []
    if asset_categories is not None and asset_categories.get("children") is not None:
        for c in asset_categories["children"]:
            items.append((c["slug"], c["name"], c["description"]))
    if len(items) == 0:
        items.append(("EMPTY", "Empty", "no categories on this level defined"))
    else:
        items.insert(
            0,
            ("NONE", "None", "Default state, category not defined by user"),
        )
    return items


def get_subcategory_enums(self, context):
    props = bpy.context.window_manager.blenderkitUI
    asset_type = props.asset_type.lower()
    if global_vars.DATA.get("bkit_categories") is None:
        return [
            ("EMPTY", "Empty", "no categories on this level defined"),
        ]

    items = []
    if self.category != "None":
        asset_categories = get_category(
            global_vars.DATA["bkit_categories"],
            cat_path=(
                asset_type,
                self.category,
            ),
        )
        if (
            asset_categories is not None
            and asset_categories.get("children") is not None
        ):
            for c in asset_categories["children"]:
                items.append((c["slug"], c["name"], c["description"]))
    if len(items) == 0:
        items.append(("EMPTY", "Empty", "no categories on this level defined"))
    else:
        items.insert(
            0,
            ("NONE", "None", "Default state, category not defined by user"),
        )
        items.append(
            (
                "OTHER",
                "Other...",
                "The asset does not belong to any of the subcategories listed above.",
            ),
        )

    return items


def get_subcategory1_enums(self, context):
    props = bpy.context.window_manager.blenderkitUI
    asset_type = props.asset_type.lower()
    if global_vars.DATA.get("bkit_categories") is None:
        return [
            ("EMPTY", "Empty", "no categories on this level defined"),
        ]

    items = []
    if self.category != "None" and self.subcategory != "Empty":
        asset_categories = get_category(
            global_vars.DATA["bkit_categories"],
            cat_path=(
                asset_type,
                self.category,
                self.subcategory,
            ),
        )
        if (
            asset_categories is not None
            and asset_categories.get("children") is not None
        ):
            for c in asset_categories["children"]:
                items.append((c["slug"], c["name"], c["description"]))
    if len(items) == 0:
        items.append(("EMPTY", "Empty", "no categories on this level defined"))
    else:
        items.insert(
            0,
            ("NONE", "None", "Default state, category not defined by user"),
        )
        items.append(
            (
                "OTHER",
                "Other...",
                "The asset does not belong to any of the sub-subcategories listed above.",
            ),
        )

    return items
