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

import bpy

# We can store multiple preview collections here,
# however in this example we only store "main"
icon_collections = {}

icons_read = {
    "free_plan.png": "free",
    "full_plan.png": "full",
    "promo_sale_symbol.png": "promo_sale_symbol",
    "sale_purple.png": "for_sale",
    "trophy.png": "trophy",
    "dumbbell.png": "dumbbell",
    "cc0.png": "cc0",
    "royalty_free.png": "royalty_free",
    "categories.png": "categories",
    "categories_active.png": "categories_active",
    "filter.png": "filter",
    "filter_active.png": "filter_active",
    "filter_nsfw.png": "filter_active_nsfw",  # NFSW filter is on, but other filters are not
    "filter_active_nsfw.png": "filter_nsfw",  # NSFW filter on, classic filters on
    "nsfw.png": "nsfw",
    "bell.png": "bell",
    "post_comment.png": "post_comment",
    "blendkit_logo.png": "logo",
    "blendkit_logo_offline.png": "logo_offline",
    "bookmark_full.png": "bookmark_full",
    "bookmark_empty.png": "bookmark_empty",
    "bar_slider_up.png": "bar_slider_up",
    "logo_artstation.png": "logo_artstation",
    "logo_discord.png": "logo_discord",
    "logo_facebook.png": "logo_facebook",
    "logo_instagram.png": "logo_instagram",
    "logo_tiktok.png": "logo_tiktok",
    "logo_vimeo.png": "logo_vimeo",
    "logo_x.png": "logo_twitter",
    "logo_youtube.png": "logo_youtube",
    "asset_type_printable.png": "asset_type_printable",
    "asset_type_author.png": "asset_type_author",
}

# fill the icon_collections["previews"] with icons of numbers for complexity rating
possible_wh_values = [
    0.2,
    0.5,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
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
for w in possible_wh_values:
    if w < 1:
        icons_read[f"{w}.png"] = f"BK{w}"
    else:
        icons_read[f"{w:04}.png"] = f"BK{w}"

verification_icons = {
    "vs_ready.png": "ready",
    "vs_deleted.png": "deleted",
    "vs_uploaded.png": "uploaded",
    "vs_uploading.png": "uploading",
    "vs_on_hold.png": "on_hold",
    "vs_validated.png": "validated",
    "vs_rejected.png": "rejected",
}

icons_read.update(verification_icons)


def register_icons():
    # Note that preview collections returned by bpy.utils.previews
    # are regular py objects - you can use them to store custom data.
    import bpy.utils.previews

    pcoll = bpy.utils.previews.new()

    # path to the directory where the icon is
    # the path is calculated relative to this py file inside the addon directory
    icons_dir = os.path.join(os.path.dirname(__file__), "thumbnails")

    # load a preview thumbnail of a file and store in the previews collection
    for ir in icons_read.keys():
        pcoll.load(icons_read[ir], os.path.join(icons_dir, ir), "IMAGE")

        # iprev = pcoll.new(icons_read[ir])
        # img = bpy.data.images.load(os.path.join(icons_dir, ir))
        # iprev.image_size = (img.size[0], img.size[1])
        # iprev.image_pixels_float = img.pixels[:]

    icon_collections["main"] = pcoll
    icon_collections["previews"] = bpy.utils.previews.new()

    # Thumbnail angle previews shown in the thumbnail generator dialog. Files are
    # named "<SNAP>_<ANGLE>.png" (e.g. "GROUND_ANGLE_1.png") to match the
    # thumbnail_snap_to + thumbnail_angle enum values.
    angles_pcoll = bpy.utils.previews.new()
    angles_dir = os.path.join(icons_dir, "thumbnail_angles")
    if os.path.isdir(angles_dir):
        for fname in os.listdir(angles_dir):
            if fname.lower().endswith(".png"):
                key = os.path.splitext(fname)[0]
                angles_pcoll.load(key, os.path.join(angles_dir, fname), "IMAGE")
    icon_collections["thumbnail_angles"] = angles_pcoll


def unregister_icons():
    for pcoll in icon_collections.values():
        bpy.utils.previews.remove(pcoll)
    icon_collections.clear()
