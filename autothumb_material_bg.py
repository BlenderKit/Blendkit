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
# type: ignore


import json
import os
import sys
from pathlib import Path
from traceback import print_exc

import bpy


def render_thumbnails():
    bpy.ops.render.render(write_still=True, animation=False)


def unhide_collection(cname):
    collection = bpy.context.scene.collection.children[cname]
    collection.hide_viewport = False
    collection.hide_render = False
    collection.hide_select = False


def patch_imports(addon_module_name: str):
    """Patch the python configuration, so the relative imports work as expected. There are few problems to fix:
    1. Script is not recognized as module which would break at relative import. We need to set __package__ = "blenderkit" for legacy addon.
    Or __package__ = "bl_ext.user_default.blenderkit"/"bl_ext.blenderkit_com.blenderkit_com". Otherwise we would see:
       from . import paths
       ImportError: attempted relative import with no known parent package
    2. External repository (e.g. blenderkit_com) is not available as we start with --factory-startup, we need to enable it.
    We can add it as LOCAL repo as the add-on is installed and we do not care about updates or anything in this BG script. Otherwise we would see:
       from . import paths
       ModuleNotFoundError: No module named 'bl_ext.blenderkit_com'; 'bl_ext' is not a package
    """
    print(f"- Setting __package__ = '{addon_module_name}'")
    global __package__
    __package__ = addon_module_name

    if bpy.app.version < (4, 2, 0):
        print(
            f"- Skipping, Blender version {bpy.app.version} < (4,2,0), no need to handle repositories"
        )
        return

    parts = addon_module_name.split(".")
    if len(parts) != 3:
        print("- Skipping, addon_module_name does not contain 3 parts")
        return

    bpy.ops.preferences.extension_repo_add(
        name=parts[1], type="LOCAL"
    )  # Local is enough
    print(f"- Local repository {parts[1]} added")


if __name__ == "__main__":
    try:
        # args order must match the order in blenderkit/autothumb.py:get_thumbnailer_args()!
        BLENDKIT_EXPORT_DATA = sys.argv[-3]
        BLENDKIT_EXPORT_API_KEY = sys.argv[-2]
        patch_imports(sys.argv[-1])
        bpy.ops.preferences.addon_enable(module=sys.argv[-1])

        from . import append_link, bg_blender, bg_utils, client_lib, utils

        bg_blender.progress("preparing thumbnail scene")
        with open(BLENDKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
            data = json.load(s)
            # append_material(file_name, matname = None, link = False, fake_user = True)

        thumbnail_use_gpu = data.get("thumbnail_use_gpu")
        if data.get("do_download"):
            # need to save the file, so that asset doesn't get downloaded into addon directory
            temp_blend_path = os.path.join(data["tempdir"], "temp.blend")

            # if this isn't here, blender crashes.
            if bpy.app.version >= (3, 0, 0):
                bpy.context.preferences.filepaths.file_preview_type = "NONE"

            bpy.ops.wm.save_as_mainfile(filepath=temp_blend_path)

            asset_data = data["asset_data"]
            has_url, download_url, file_name = client_lib.get_download_url(
                asset_data, utils.get_scene_id(), BLENDKIT_EXPORT_API_KEY
            )
            asset_data["files"][0]["url"] = download_url
            asset_data["files"][0]["file_name"] = file_name
            if not has_url:
                bg_blender.progress(
                    "couldn't download asset for thumbnail re-rendering"
                )
                exit()
            # download first, or rather make sure if it's already downloaded
            bg_blender.progress("downloading asset")
            fpath = bg_utils.download_asset_file(
                asset_data, api_key=BLENDKIT_EXPORT_API_KEY
            )
            data["filepath"] = fpath

        mat = append_link.append_material(
            file_name=data["filepath"],
            matname=data["asset_name"],
            link=True,
            fake_user=False,
        )

        s = bpy.context.scene

        colmapdict = {
            "BALL": "Ball",
            "BALL_COMPLEX": "Ball complex",
            "FLUID": "Fluid",
            "CLOTH": "Cloth",
            "HAIR": "Hair",
        }
        unhide_collection(colmapdict[data["thumbnail_type"]])
        if data["thumbnail_background"]:
            unhide_collection("Background")
            bpy.data.materials["bg checker colorable"].node_tree.nodes[
                "input_level"
            ].outputs["Value"].default_value = data["thumbnail_background_lightness"]
        tscale = data["thumbnail_scale"]
        scaler = bpy.context.view_layer.objects["scaler"]
        scaler.scale = (tscale, tscale, tscale)
        utils.activate(scaler)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        bpy.context.view_layer.update()

        for ob in bpy.context.visible_objects:
            if ob.name[:15] == "MaterialPreview":
                utils.activate(ob)
                if bpy.app.version >= (3, 3, 0):
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True, isolate_users=True
                    )
                else:
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True
                    )
                bpy.ops.object.transform_apply(
                    location=False, rotation=False, scale=True
                )

                ob.material_slots[0].material = mat
                ob.data.use_auto_texspace = False
                ob.data.texspace_size.x = 1  # / tscale
                ob.data.texspace_size.y = 1  # / tscale
                ob.data.texspace_size.z = 1  # / tscale

                # this option was moved in Blender 5.0 from cycles directly to modifier
                if bpy.app.version >= (5, 0, 0):
                    for mod in ob.modifiers:
                        if mod.type == "SUBSURF":
                            if data["adaptive_subdivision"] == True:
                                mod.use_adaptive_subdivision = True
                            else:
                                mod.use_adaptive_subdivision = False
                else:
                    if data["adaptive_subdivision"] == True:
                        ob.cycles.use_adaptive_subdivision = True
                    else:
                        ob.cycles.use_adaptive_subdivision = False
                ts = data["texture_size_meters"]
                if data["thumbnail_type"] in ["BALL", "BALL_COMPLEX", "CLOTH"]:
                    utils.automap(
                        ob.name,
                        tex_size=ts / tscale,
                        just_scale=True,
                        bg_exception=True,
                    )
        bpy.context.view_layer.update()

        # this option was removed in Blender 5.0
        # but we have option to set biased volumes
        if bpy.app.version >= (5, 0, 0):
            # usually small speedup with little quality loss
            s.cycles.volume_biased = True
        else:
            s.cycles.volume_step_size = tscale * 0.1

        if thumbnail_use_gpu is True:
            bpy.context.scene.cycles.device = "GPU"
            compute_device_type = data.get("cycles_compute_device_type")
            if compute_device_type is not None:
                # DOCS:https://github.com/dfelinto/blender/blob/master/intern/cycles/blender/addon/properties.py
                bpy.context.preferences.addons[
                    "cycles"
                ].preferences.compute_device_type = compute_device_type
                bpy.context.preferences.addons["cycles"].preferences.refresh_devices()

        s.cycles.samples = data["thumbnail_samples"]
        bpy.context.view_layer.cycles.use_denoising = data["thumbnail_denoising"]

        # import blender's HDR here
        hdr_path = Path("datafiles/studiolights/world/interior.exr")
        bpath = Path(bpy.utils.resource_path("LOCAL"))
        ipath = bpath / hdr_path
        ipath = str(ipath)

        # this  stuff is for mac and possibly linux. For blender // means relative path.
        # for Mac, // means start of absolute path
        if ipath.startswith("//"):
            ipath = ipath[1:]

        img = bpy.data.images["interior.exr"]
        img.filepath = ipath
        img.reload()

        bpy.context.scene.render.resolution_x = int(data["thumbnail_resolution"])
        bpy.context.scene.render.resolution_y = int(data["thumbnail_resolution"])

        bpy.context.scene.render.filepath = data["thumbnail_path"]
        bg_blender.progress("rendering thumbnail")
        # bpy.ops.wm.save_as_mainfile(filepath='C:/tmp/test.blend')
        # fal
        render_thumbnails()
        if not data.get("upload_after_render") or not data.get("asset_data"):
            bg_blender.progress(
                "background autothumbnailer finished successfully (no upload)"
            )
            sys.exit(0)

        bg_blender.progress("uploading thumbnail")
        ok = client_lib.complete_upload_file_blocking(
            api_key=BLENDKIT_EXPORT_API_KEY,
            asset_id=data["asset_data"]["id"],
            filepath=f"{data['thumbnail_path']}.png",
            filetype=f"thumbnail",
            fileindex=0,
        )
        if not ok:
            bg_blender.progress("thumbnail upload failed, exiting")
            sys.exit(1)

        bg_blender.progress(
            "background autothumbnailer finished successfully (with upload)"
        )

    except Exception as e:
        print(f"background autothumbnailer failed: {e}")
        print_exc()
        sys.exit(1)
