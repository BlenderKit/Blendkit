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

import logging
from typing import Optional, Union

# mainly update functions and callbacks for ratings properties, here to avoid circular imports.
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Context, PropertyGroup

from . import (
    client_lib,
    client_tasks,
    datas,
    global_vars,
    icons,
    reports,
    tasks_queue,
    utils,
)


bk_logger = logging.getLogger(__name__)


def handle_get_rating_task(task: client_tasks.Task):
    """Handle incoming get_rating task by saving the results into global_vars."""
    if task.status == "created":
        return
    if task.status == "error":
        return bk_logger.warning("%s task failed: %s", task.task_type, task.message)

    asset_id = task.data["asset_id"]
    ratings = task.result["results"]
    if len(ratings) == 0:
        store_rating_local(asset_id, "quality", None)
        store_rating_local(asset_id, "working_hours", None)
        return

    for rating in ratings:
        store_rating_local(asset_id, rating["ratingType"], rating["score"])


def handle_get_ratings_task(task: client_tasks.Task):
    """Handle incoming get_ratings task. This is a special task used only by validators which fetches the ratings
    in big batch right after the search results come into the Client. This is used only to signal problems in the
    Goroutine which fetches the ratings. The individual ratings are then sent as normal 'get_rating' tasks.
    """
    if task.status == "error":  # only reason this task type exists right now
        return bk_logger.warning("%s task failed: %s", task.task_type, task.message)


def handle_get_bookmarks_task(task: client_tasks.Task):
    """Handle incoming get_bookmarks task by saving the results into global_vars.
    This is different from standard ratings - the results come from elastic search API
    instead of ratings API.
    """
    if task.status == "created":
        return
    if task.status == "error":
        bk_logger.warning("Could not load bookmarks: %s", task.message)
        return

    for asset in task.result["results"]:
        store_rating_local(asset["id"], "bookmarks", 1)
    bk_logger.info("Bookmarks loaded")


def handle_send_rating_task(task: client_tasks.Task):
    """Handle send rating task."""
    if task.status == "created":
        return
    if task.status == "error":
        return reports.add_report(
            task.message, type="ERROR", details=task.message_detailed
        )
    if task.status == "finished":
        if utils.profile_is_validator():
            return reports.add_report(task.message, type="VALIDATOR")


def store_rating_local(
    asset_id: str, rating_type: str = "quality", value: Optional[int] = None
):
    """Store the rating locally in the global_vars.
    - rating_type can be: "quality", "working_hours", "bookmarks"
    - value set None to create empty rating and prevent add-on from fetching it again next time
    """
    allowed_rating_types = ["quality", "working_hours", "bookmarks"]
    if rating_type not in allowed_rating_types:
        raise ValueError(f"rating_type must be one of {allowed_rating_types}")

    rating = global_vars.RATINGS.get(asset_id, datas.AssetRating())
    rating.working_hours_fetched = True
    rating.quality_fetched = True
    setattr(rating, rating_type, value)
    global_vars.RATINGS[asset_id] = rating


def get_rating_local(asset_id: str) -> Optional[datas.AssetRating]:
    """Get the rating locally from global_vars.RATINGS."""
    return global_vars.RATINGS.get(asset_id)


def ensure_rating(asset_id: str):
    """Ensure the rating is available. First check if it is available in local cache. If it is not then download it from the server.
    If the rating is present, we need to check if rating.quality_fetched and rating.working_hours_fetched are not False
    because bookmarked assets will have rating created, but for them the quality and wh was not fetched (bookmarked are get from search
    and these data does not contain quality and working_hours - and even bookmarked but that can be deduced from searching for bookmarked).
    """
    rating = get_rating_local(asset_id)
    if rating is None:
        client_lib.get_rating(asset_id)
        return
    if not rating.quality_fetched or not rating.working_hours_fetched:
        client_lib.get_rating(asset_id)


def update_ratings_quality(self, context: Context):
    if not (hasattr(self, "rating_quality")):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset["asset_data"]["id"]
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    local_rating = get_rating_local(self.asset_id)
    if local_rating is None:
        local_rating = datas.AssetRating(quality=0)
    if local_rating.quality == self.rating_quality:
        return store_rating_local(
            asset_id, rating_type="quality", value=bkit_ratings.rating_quality
        )

    store_rating_local(
        asset_id, rating_type="quality", value=bkit_ratings.rating_quality
    )
    if self.rating_quality_lock is True:
        return

    args = (asset_id, "quality", bkit_ratings.rating_quality)
    tasks_queue.add_task((client_lib.send_rating, args), wait=0.5, only_last=True)


def update_ratings_work_hours(self, context: Context):
    if not (hasattr(self, "rating_work_hours")):
        # first option is for rating of assets that are from scene
        asset = self.id_data
        bkit_ratings = asset.bkit_ratings
        asset_id = asset["asset_data"]["id"]
    else:
        # this part is for operator rating:
        bkit_ratings = self
        asset_id = self.asset_id

    local_rating = get_rating_local(self.asset_id)
    if local_rating is None:  # rating was not available online
        local_rating = datas.AssetRating(working_hours=0)

    if local_rating.working_hours == self.rating_work_hours:
        return store_rating_local(
            asset_id, rating_type="working_hours", value=bkit_ratings.rating_work_hours
        )

    store_rating_local(
        asset_id, rating_type="working_hours", value=bkit_ratings.rating_work_hours
    )
    if self.rating_work_hours_lock is True:
        return

    args = (asset_id, "working_hours", bkit_ratings.rating_work_hours)
    tasks_queue.add_task((client_lib.send_rating, args), wait=0.5, only_last=True)


def update_quality_ui(self, context: Context):
    """Converts the _ui the enum into actual quality number."""
    user_preferences = bpy.context.preferences.addons[__package__].preferences  # type: ignore
    api_key = user_preferences.api_key  # type: ignore
    # we need to check for matching value not to update twice/call the popup twice.
    if api_key == "" and self.rating_quality != int(self.rating_quality_ui):
        bpy.ops.wm.blenderkit_login(  # type: ignore
            "INVOKE_DEFAULT",
            message="Please login/signup to rate assets. Clicking OK takes you to web login.",
            placement="rating_prompt",
        )
        return

    self.rating_quality = int(self.rating_quality_ui)


def update_ratings_work_hours_ui(self, context: Context):
    user_preferences = bpy.context.preferences.addons[__package__].preferences  # type: ignore
    api_key = user_preferences.api_key  # type: ignore
    if api_key == "" and self.rating_work_hours != float(self.rating_work_hours_ui):
        bpy.ops.wm.blenderkit_login(  # type: ignore
            "INVOKE_DEFAULT",
            message="Please login/signup to rate assets. Clicking OK takes you to web login.",
            placement="rating_prompt",
        )
        return
    self.rating_work_hours = float(self.rating_work_hours_ui)


_stars_enum_items = []
_stars_enum_cache_key = None


def stars_enum_callback(self, context):
    """regenerates the enum property used to display rating stars, so that there are filled/empty stars correctly."""
    global _stars_enum_items, _stars_enum_cache_key
    key = int(self.rating_quality)
    if key == _stars_enum_cache_key and _stars_enum_items:
        return _stars_enum_items
    _stars_enum_cache_key = key
    items = []
    for a in range(0, 11):
        if a == 0:
            icon = "REMOVE"

        elif self.rating_quality < a:
            icon = "SOLO_OFF"
        else:
            icon = "SOLO_ON"
        # has to have something before the number in the value, otherwise fails on registration.

        items.append((f"{a}", "  ", "", icon, a))
    _stars_enum_items = items
    return _stars_enum_items


_wh_enum_items = []
_wh_enum_cache_key = None


def wh_enum_callback(self, context):
    """Regenerates working hours enum.

    NOTE: The items list is stored in ``_wh_enum_items`` so that it is not
    garbage-collected before Blender reads the icon IDs.  Without this,
    Blender 5.1+ may render corrupted icons because it only keeps an
    internal pointer to the returned data.
    """
    global _wh_enum_items, _wh_enum_cache_key
    key = (self.asset_type, self.rating_work_hours)
    if key == _wh_enum_cache_key and _wh_enum_items:
        return _wh_enum_items
    _wh_enum_cache_key = key

    if self.asset_type in ("model", "scene", "printable", "nodegroup"):
        possible_wh_values = [
            0,
            0.5,
            1,
            2,
            3,
            4,
            5,
            6,
            8,
            10,
            15,
            20,
            30,
            50,
            100,
            150,
            200,
            250,
        ]
    elif self.asset_type == "hdr":
        possible_wh_values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    else:  # for material, brush assets
        possible_wh_values = [0, 0.2, 0.5, 1, 2, 3, 4, 5]

    work_hours = self.rating_work_hours
    if work_hours < 1:
        work_hours = int(work_hours * 10) / 10
    else:
        work_hours = int(work_hours)

    if work_hours not in possible_wh_values:
        closest_index = 0
        closest_diff = abs(possible_wh_values[0] - work_hours)
        for i in range(1, len(possible_wh_values)):
            diff = abs(possible_wh_values[i] - work_hours)
            if diff < closest_diff:
                closest_diff = diff
                closest_index = i
        possible_wh_values[closest_index] = work_hours

    items = []
    items.append(("0", " ", "", "REMOVE", 0))
    pcoll = icons.icon_collections["main"]

    for w in possible_wh_values:
        if w > 0:
            if w < 1:
                icon_name = f"BK{int(w*10)/10}"
            else:
                icon_name = f"BK{int(w)}"
            if icon_name not in pcoll:
                icon_name = "bar_slider_up"
            icon = pcoll[icon_name]
            # index of the item(last value) is multiplied by 10 to get always integer values that aren't zero
            items.append((f"{w}", "  ", "", icon.icon_id, int(w * 10)))

    _wh_enum_items = items
    return _wh_enum_items


class RatingProperties(PropertyGroup):
    message: StringProperty(  # type: ignore
        name="message",
        description="message",
        default="Rating asset",
        options={"SKIP_SAVE"},
    )

    asset_id: StringProperty(  # type: ignore
        name="Asset Base Id",
        description="Unique id of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    asset_name: StringProperty(  # type: ignore
        name="Asset Name",
        description="Name of the asset (hidden)",
        default="",
        options={"SKIP_SAVE"},
    )

    asset_type: StringProperty(  # type: ignore
        name="Asset type", description="asset type", default="", options={"SKIP_SAVE"}
    )

    ### QUALITY RATING
    rating_quality_lock: BoolProperty(  # type: ignore
        name="Quality Lock",
        description="Quality is locked -> rating is not sent online",
        default=False,
        options={"SKIP_SAVE"},
    )

    rating_quality: IntProperty(  # type: ignore
        name="Quality",
        description="quality of the material",
        default=0,
        min=-1,
        max=10,
        update=update_ratings_quality,
        options={"SKIP_SAVE"},
    )

    # the following enum is only to ease interaction - enums support 'drag over' and enable to draw the stars easily.
    rating_quality_ui: EnumProperty(  # type: ignore
        name="Quality",
        items=stars_enum_callback,
        description="Rate the quality of the asset from 1 to 10 stars.\nShortcut: Hover over asset in the asset bar and press 'R' to show rating menu",
        default=0,
        update=update_quality_ui,
        options={"SKIP_SAVE"},
    )

    ### WORK HOURS RATING
    rating_work_hours_lock: BoolProperty(  # type: ignore
        name="Work Hours Lock",
        description="Work hours are locked -> rating is not sent online",
        default=False,
        options={"SKIP_SAVE"},
    )
    rating_work_hours: FloatProperty(  # type: ignore
        name="Work Hours",
        description="nonUI How many hours did this work take?\nShortcut: Hover over asset in the asset bar and press 'R' to show rating menu.",
        default=0.00,
        min=0.0,
        max=300,
        update=update_ratings_work_hours,
        options={"SKIP_SAVE"},
    )
    rating_work_hours_ui: EnumProperty(  # type: ignore
        name="Work Hours",
        description="UI How many hours did this work take?\nShortcut: Hover over asset in the asset bar and press 'R' to show rating menu",
        items=wh_enum_callback,
        default=0,
        update=update_ratings_work_hours_ui,
        options={"SKIP_SAVE"},
    )

    def prefill_ratings(self) -> None:
        """Pre-fill the quality and work hours ratings if available.
        Locks the ratings locks so that the update function is not called and ratings are not sent online.
        """
        if not utils.user_logged_in():
            return
        rating = get_rating_local(self.asset_id)
        if rating is None:
            return
        if rating.quality is None and rating.working_hours is None:
            return
        if self.rating_quality != 0:
            return  # return if the rating was already filled
        if self.rating_work_hours != 0:
            return  # return if the rating was already filled

        if rating.quality is not None:
            self.rating_quality_lock = True
            self.rating_quality = int(rating.quality)
            self.rating_quality_lock = False

        if rating.working_hours is not None:
            wh: Union[float, int]
            if rating.working_hours >= 1:
                wh = int(rating.working_hours)
            else:
                wh = round(rating.working_hours, 1)
            whs = str(wh)
            self.rating_work_hours_lock = True
            self.rating_work_hours = round(rating.working_hours, 2)
            try:
                # when the value is not in the enum, it throws an error
                if whs == "0.0":
                    whs = "0"
                self.rating_work_hours_ui = whs
            except Exception as e:
                bk_logger.warning("exception setting rating_work_hours_ui: %s", e)

            self.rating_work_hours = round(rating.working_hours, 2)
            self.rating_work_hours_lock = False

        bpy.context.area.tag_redraw()


# class RatingPropsCollection(PropertyGroup):
#   ratings = CollectionProperty(type = RatingProperties)
