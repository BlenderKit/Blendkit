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
import os
import time

import bpy


bk_logger = logging.getLogger(__name__)

resolutions = {
    "resolution_0_5K": 512,
    "resolution_1K": 1024,
    "resolution_2K": 2048,
    "resolution_4K": 4096,
    "resolution_8K": 8192,
}
rkeys = list(resolutions.keys())

resolution_props_to_server = {
    "512": "resolution_0_5K",
    "1024": "resolution_1K",
    "2048": "resolution_2K",
    "4096": "resolution_4K",
    "8192": "resolution_8K",
    "ORIGINAL": "blend",
}


def get_current_resolution():
    actres = 0
    for i in bpy.data.images:
        if i.name != "Render Result":
            actres = max(actres, i.size[0], i.size[1])
    return actres


def regenerate_thumbnail_material(data):
    # this should re-generate material thumbnail and re-upload it.
    # first let's skip procedural assets
    base_fpath = bpy.data.filepath
    blend_file_name = os.path.basename(base_fpath)
    bpy.ops.mesh.primitive_cube_add()
    aob = bpy.context.active_object
    bpy.ops.object.material_slot_add()
    aob.material_slots[0].material = bpy.data.materials[0]
    props = aob.active_material.blenderkit
    props.thumbnail_generator_type = "BALL"
    props.thumbnail_background = False
    props.thumbnail_resolution = "256"
    # layout.prop(props, 'thumbnail_generator_type')
    # layout.prop(props, 'thumbnail_scale')
    # layout.prop(props, 'thumbnail_background')
    # if props.thumbnail_background:
    #     layout.prop(props, 'thumbnail_background_lightness')
    # layout.prop(props, 'thumbnail_resolution')
    # layout.prop(props, 'thumbnail_samples')
    # layout.prop(props, 'thumbnail_denoising')
    # layout.prop(props, 'adaptive_subdivision')
    # preferences = bpy.context.preferences.addons['blenderkit'].preferences
    # layout.prop(preferences, "thumbnail_use_gpu")
    # TODO: here it should call start_material_thumbnailer , but with the wait property on, so it can upload afterwards.
    bpy.ops.object.blenderkit_generate_material_thumbnail()
    time.sleep(130)
    # save
    # this does the actual job

    return
