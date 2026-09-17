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
import random
import subprocess
import tempfile
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    FloatVectorProperty,
    StringProperty,
)

from . import bg_blender, paths, tasks_queue, utils, upload, search

bk_logger = logging.getLogger(__name__)
BLENDKIT_EXPORT_DATA_FILE = "data.json"

thumbnail_resolutions = (
    ("256", "256", ""),
    ("512", "512", ""),
    ("1024", "1024 - minimum for public", ""),
    ("2048", "2048", ""),
)

thumbnail_angles = (
    ("ANGLE_1", "Angle 1", "Lower hanging camera angle"),
    ("ANGLE_2", "Angle 2", "Higher hanging camera angle"),
    ("FRONT", "front", ""),
    ("SIDE", "side", ""),
    ("TOP", "top", ""),
)

thumbnail_snap = (
    ("GROUND", "ground", ""),
    ("WALL", "wall", ""),
    ("CEILING", "ceiling", ""),
    ("FLOAT", "floating", ""),
)


# ---------------------------------------------------------------------------
# Shared thumbnail property factories
# ---------------------------------------------------------------------------
# Every thumbnail setting is defined exactly once below. The per-asset upload
# property groups (object/material .blenderkit), the persisted
# BlenderKitThumbnailSettings group and the thumbnail operators all build their
# properties from these factories, so a setting's name/description/limits live
# in a single place. Each factory returns a *fresh* deferred property because
# Blender requires a new property object per registered class.


def thumbnail_render_engine_prop(update=None):
    return EnumProperty(
        name="Thumbnail Render Engine",
        items=utils.available_render_engines,
        default=0,
        description="Render engine for thumbnail",
        update=update,
    )


def thumbnail_resolution_prop(update=None):
    return EnumProperty(
        name="Resolution",
        items=thumbnail_resolutions,
        description="Thumbnail resolution",
        default="1024",
        update=update,
    )


def thumbnail_samples_prop(update=None):
    return IntProperty(
        name="Cycles Samples",
        description="Cycles samples setting",
        default=100,
        min=5,
        max=5000,
        update=update,
    )


def thumbnail_denoising_prop(update=None):
    return BoolProperty(
        name="Use Denoising",
        description="Use denoising",
        default=True,
        update=update,
    )


def thumbnail_angle_prop(update=None):
    return EnumProperty(
        name="Thumbnail Angle",
        items=thumbnail_angles,
        default="ANGLE_1",
        description="Thumbnailer angle",
        update=update,
    )


def thumbnail_snap_to_prop(update=None):
    return EnumProperty(
        name="Model Snaps To",
        items=thumbnail_snap,
        default="GROUND",
        description="Typical placing of the interior. Leave on ground for most objects that respect gravity",
        update=update,
    )


def thumbnail_background_lightness_prop(
    update=None,
    default=0.7,
    lo=0.01,
    hi=10.0,
    description="Set to make your asset stand out",
):
    return FloatProperty(
        name="Thumbnail Background Lightness",
        description=description,
        default=default,
        min=lo,
        max=hi,
        update=update,
    )


def thumbnail_material_color_prop(update=None):
    return FloatVectorProperty(
        name="Thumbnail Material Color",
        description="Color of the material for printable models",
        default=(random.random(), random.random(), random.random()),
        subtype="COLOR",
        update=update,
    )


def thumbnail_generator_type_prop(update=None):
    return EnumProperty(
        name="Thumbnail Style",
        items=(
            ("BALL", "Ball", ""),
            (
                "BALL_COMPLEX",
                "Ball complex",
                "Complex ball to highlight edgewear or material thickness",
            ),
            ("FLUID", "Fluid", "Fluid"),
            ("CLOTH", "Cloth", "Cloth"),
            ("HAIR", "Hair", "Hair  "),
        ),
        description="Style of asset",
        default="BALL",
        update=update,
    )


def thumbnail_scale_prop(update=None):
    return FloatProperty(
        name="Thumbnail Object Size",
        description="Size of material preview object in meters."
        "Change for materials that look better at sizes different than 1m",
        default=1,
        min=0.00001,
        max=10,
        update=update,
    )


def thumbnail_background_prop(update=None):
    return BoolProperty(
        name="Thumbnail Background (for Glass only)",
        description="For refractive materials, you might need a background.\n"
        "Don't use for other types of materials.\n"
        "Transparent background is preferred",
        default=False,
        update=update,
    )


def adaptive_subdivision_prop(update=None):
    return BoolProperty(
        name="Adaptive Subdivide",
        description="Use adaptive displacement subdivision",
        default=False,
        update=update,
    )


def thumbnail_use_gpu_prop(update=None):
    return BoolProperty(
        name="Use GPU for Thumbnails Rendering",
        description="By default this is off so you can continue your work without any lag",
        default=False,
        update=update,
    )


def save_thumbnail_settings(self, context):
    """Update callback for BlenderKitThumbnailSettings fields.

    The callback receives the settings group as ``self`` (not the add-on
    preferences), so we fetch the real preferences and persist them.
    """
    preferences = bpy.context.preferences.addons[__package__].preferences
    utils.save_prefs(preferences, context)


def get_thumbnail_settings():
    """Return the persisted, global BlenderKitThumbnailSettings group."""
    return bpy.context.preferences.addons[__package__].preferences.thumbnail_settings


def reset_thumbnail_render_engine(target) -> None:
    """Force the thumbnail render engine on ``target`` back to Cycles."""
    try:
        if getattr(target, "thumbnail_render_engine", "CYCLES") != "CYCLES":
            target.thumbnail_render_engine = "CYCLES"
    except Exception as e:
        bk_logger.debug("Could not reset thumbnail render engine: %s", e)


def get_texture_ui(tpath, iname):
    img = bpy.data.images.get(iname)
    tex = bpy.data.textures.get(iname)
    if tpath.startswith("//"):
        tpath = bpy.path.abspath(tpath)

    if not tex or not tex.image or not tex.image.filepath == tpath:
        if img is None:
            tasks_queue.add_task(
                (utils.get_hidden_image, (tpath, iname)), only_last=True
            )

        tasks_queue.add_task((utils.get_hidden_texture, (iname, False)), only_last=True)

        return None
    return tex


def check_thumbnail(
    props,
    imgpath,
    *,
    texture_name="upload_preview",
    flag_attr="has_thumbnail",
    state_attr="thumbnail_generating_state",
):
    """Reload a thumbnail preview and update status attributes."""

    def _set_prop(attr_name, value):
        if attr_name and hasattr(props, attr_name):
            setattr(props, attr_name, value)

    # TODO implement check if the file exists, if size is correct etc. needs some care
    if imgpath == "":
        _set_prop(flag_attr, False)
        return None
    img = utils.get_hidden_image(imgpath, texture_name, force_reload=True)
    if img is not None:  # and img.size[0] == img.size[1] and img.size[0] >= 512 and (
        # img.file_format == 'JPEG' or img.file_format == 'PNG'):
        _set_prop(flag_attr, True)
        if hasattr(props, "THUMBNAIL_GENERATING_STATE"):
            props.THUMBNAIL_GENERATING_STATE = ""
        _set_prop(state_attr, "")

        utils.get_hidden_texture(img.name)
        # pcoll = icons.icon_collections["previews"]
        # pcoll.load(img.name, img.filepath, 'IMAGE')

        return img
    else:
        _set_prop(flag_attr, False)
    output = ""
    if (
        img is None
        or img.size[0] == 0
        or img.filepath.find("thumbnail_notready.jpg") > -1
    ):
        output += "No thumbnail or wrong file path\n"
    else:
        pass
        # this is causing problems on some platforms, don't know why..
        # if img.size[0] != img.size[1]:
        #     output += 'image not a square\n'
        # if img.size[0] < 512:
        #     output += 'image too small, should be at least 512x512\n'
        # if img.file_format != 'JPEG' or img.file_format != 'PNG':
        #     output += 'image has to be a jpeg or png'
    _set_prop(state_attr, output)


def update_upload_model_preview(self, context):
    ob = utils.get_active_model()
    if ob is not None:
        props = ob.blenderkit
        imgpath = props.thumbnail
        check_thumbnail(props, imgpath)


def update_wire_thumbnail_preview(self, context):
    ob = utils.get_active_model()
    if ob is not None:
        props = ob.blenderkit
        imgpath = props.wire_thumbnail
        check_thumbnail(
            props,
            imgpath,
            texture_name=".upload_preview_wire",
            flag_attr=None,
            state_attr="wire_thumbnail_generating_state",
        )


def update_upload_scene_preview(self, context):
    s = bpy.context.scene
    props = s.blenderkit
    imgpath = props.thumbnail
    check_thumbnail(props, imgpath)


def update_upload_material_preview(self, context):
    if (
        hasattr(bpy.context, "active_object")
        and bpy.context.view_layer.objects.active is not None
        and bpy.context.active_object.active_material is not None
    ):
        mat = bpy.context.active_object.active_material
        props = mat.blenderkit
        imgpath = props.thumbnail
        check_thumbnail(props, imgpath)


def update_upload_brush_preview(self, context):
    brush = utils.get_active_brush()
    if brush is not None:
        props = brush.blenderkit
        imgpath = props.thumbnail
        check_thumbnail(props, imgpath)


def get_thumbnailer_args(script_name, thumbnailer_filepath, datafile, api_key):
    """Get the arguments to start Blender in background to render model or material thumbnails.
    Watch out: the ending arguments must match order of those in: autothumb_model_bg.py and autothumb_material_bg.py.
    """
    script_path = os.path.dirname(os.path.realpath(__file__))
    script_path = os.path.join(script_path, script_name)
    args = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--addons",
        __package__,
        "-noaudio",
        thumbnailer_filepath,
        "--python",
        script_path,
        "--",
        datafile,
        api_key,
        __package__,  # Legacy has it as "blendkit", extensions have it like bl_ext.user_default.blendkit or anything else
    ]
    return args


def start_model_thumbnailer(
    self=None, json_args=None, props=None, wait=False, add_bg_process=True
):
    """Start Blender in background and render the thumbnail."""
    SCRIPT_NAME = "autothumb_model_bg.py"
    thumbnail_upload_type = (
        json_args.get("thumbnail_upload_type") if json_args else None
    )
    is_wire_upload = thumbnail_upload_type == "wire_thumbnail"
    computing_attr = (
        "is_generating_wire_thumbnail" if is_wire_upload else "is_generating_thumbnail"
    )
    state_attr = (
        "wire_thumbnail_generating_state"
        if is_wire_upload
        else "thumbnail_generating_state"
    )

    def _set_prop(attr_name, value):
        if props and hasattr(props, attr_name):
            setattr(props, attr_name, value)

    if props:
        _set_prop(computing_attr, True)
        _set_prop(state_attr, "Saving .blend file")

    datafile = os.path.join(json_args["tempdir"], BLENDKIT_EXPORT_DATA_FILE)
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    settings = user_preferences.thumbnail_settings
    json_args["thumbnail_use_gpu"] = settings.thumbnail_use_gpu
    if settings.thumbnail_use_gpu is True:
        json_args["cycles_compute_device_type"] = bpy.context.preferences.addons[
            "cycles"
        ].preferences.compute_device_type

    try:
        with open(datafile, "w", encoding="utf-8") as s:
            json.dump(json_args, s, ensure_ascii=False, indent=4)
    except Exception as e:
        self.report({"WARNING"}, f"Error while exporting file: {e}")
        return {"FINISHED"}
    args = get_thumbnailer_args(
        SCRIPT_NAME,
        paths.get_thumbnailer_filepath(),
        datafile,
        user_preferences.api_key,
    )
    bk_logger.debug("%s", args)

    blender_user_scripts_dir = (
        Path(__file__).resolve().parents[2]
    )  # scripts/addons/blenderkit/autothumb.py

    env = {"BLENDER_USER_SCRIPTS": str(blender_user_scripts_dir)}
    env.update(os.environ)

    # both must be enabled
    if (
        user_preferences.experimental_features
        and user_preferences.ignore_env_for_thumbnails
    ):
        env = None

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=utils.get_process_flags(),
        env=env,
    )
    bk_logger.info("Started Blender executing %s on file %s", SCRIPT_NAME, datafile)
    eval_path_base = f"bpy.data.objects['{json_args['asset_name']}']"
    eval_path = eval_path_base
    eval_path_computing = f"{eval_path_base}.blenderkit.{computing_attr}"
    eval_path_state = f"{eval_path_base}.blenderkit.{state_attr}"
    name = f"{json_args['asset_name']} thumbnailer"
    bg_blender.add_bg_process(
        name=name,
        eval_path_computing=eval_path_computing,
        eval_path_state=eval_path_state,
        eval_path=eval_path,
        process_type="THUMBNAILER",
        process=proc,
    )
    if props:
        _set_prop(state_attr, "Started Blender instance")

    if wait:
        while proc.poll() is None:
            stdout_data, stderr_data = proc.communicate()
            bk_logger.info(stdout_data, stderr_data)


def start_material_thumbnailer(
    self=None, json_args=None, props=None, wait=False, add_bg_process=True
):
    """Start Blender in background and render the thumbnail.

    Parameters
    ----------
    self
    json_args - all arguments:
    props - blenderkit upload props with thumbnail settings, to communicate back, if not present, not used.
    wait - wait for the rendering to finish

    Returns
    -------

    """
    SCRIPT_NAME = "autothumb_material_bg.py"
    if props:
        props.is_generating_thumbnail = True
        props.thumbnail_generating_state = "Saving .blend file"

    datafile = os.path.join(json_args["tempdir"], BLENDKIT_EXPORT_DATA_FILE)
    user_preferences = bpy.context.preferences.addons[__package__].preferences
    settings = user_preferences.thumbnail_settings
    json_args["thumbnail_use_gpu"] = settings.thumbnail_use_gpu
    if settings.thumbnail_use_gpu is True:
        json_args["cycles_compute_device_type"] = bpy.context.preferences.addons[
            "cycles"
        ].preferences.compute_device_type
    try:
        with open(datafile, "w", encoding="utf-8") as s:
            json.dump(json_args, s, ensure_ascii=False, indent=4)
    except Exception as e:
        self.report({"WARNING"}, f"Error while exporting file: {e}")
        return {"FINISHED"}

    args = get_thumbnailer_args(
        SCRIPT_NAME,
        paths.get_material_thumbnailer_filepath(),
        datafile,
        user_preferences.api_key,
    )
    blender_user_scripts_dir = (
        Path(__file__).resolve().parents[2]
    )  # scripts/addons/blenderkit/autothumb.py

    env = {"BLENDER_USER_SCRIPTS": str(blender_user_scripts_dir)}
    env.update(os.environ)

    if (
        user_preferences.experimental_features
        and user_preferences.ignore_env_for_thumbnails
    ):
        env = None

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        creationflags=utils.get_process_flags(),
        env=env,
    )
    bk_logger.info("Started Blender executing %s on file %s", SCRIPT_NAME, datafile)

    eval_path_computing = f"bpy.data.materials['{json_args['asset_name']}'].blenderkit.is_generating_thumbnail"
    eval_path_state = f"bpy.data.materials['{json_args['asset_name']}'].blenderkit.thumbnail_generating_state"
    eval_path = f"bpy.data.materials['{json_args['asset_name']}']"
    name = f"{json_args['asset_name']} thumbnailer"
    bg_blender.add_bg_process(
        name=name,
        eval_path_computing=eval_path_computing,
        eval_path_state=eval_path_state,
        eval_path=eval_path,
        process_type="THUMBNAILER",
        process=proc,
    )
    if props:
        props.thumbnail_generating_state = "Started Blender instance"

    if wait:
        while proc.poll() is None:
            stdout_data, stderr_data = proc.communicate()
            bk_logger.info(stdout_data, stderr_data)


class GenerateThumbnailOperator(bpy.types.Operator):
    """Generate Cycles thumbnail for model assets"""

    bl_idname = "object.blenderkit_generate_thumbnail"
    bl_label = "Blendkit Thumbnail Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    thumbnail_type: EnumProperty(  # type: ignore[valid-type]
        name="Thumbnail Type",
        items=(
            ("REGULAR", "Regular", "Standard rendered thumbnail"),
            ("WIREFRAME", "Wireframe", "Wireframe thumbnail"),
        ),
        default="REGULAR",
        description="Choose whether to render a regular or a wireframe thumbnail",
    )

    @classmethod
    def poll(cls, context):
        return bpy.context.view_layer.objects.active is not None

    def check(self, context):
        # Re-run the popup layout when an operator property changes (e.g. the
        # regular/wireframe switch) so conditionally shown fields update live.
        return True

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports autothumb)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        ui_props = bpy.context.window_manager.blenderkitUI
        asset_type = ui_props.asset_type
        experimental = utils.experimental_enabled()

        ob = utils.get_active_model()
        if ob is None:
            return
        settings = get_thumbnail_settings()
        layout = self.layout
        layout.label(text="thumbnailer settings")
        # Preview image for the selected snap + angle combination. Files are
        # named "<SNAP>_<ANGLE>.png" in thumbnails/thumbnail_angles/.
        from . import icons

        angles_pcoll = icons.icon_collections.get("thumbnail_angles")
        if angles_pcoll is not None:
            preview_key = f"{settings.thumbnail_snap_to}_{settings.thumbnail_angle}"
            preview = angles_pcoll.get(preview_key)
            if preview is not None:
                layout.template_icon(icon_value=preview.icon_id, scale=6.0)
        # The regular/wireframe switch and the render engine choice are
        # experimental. Non-experimental users always get a regular Cycles
        # thumbnail, so these controls are hidden.
        if experimental:
            layout.prop(self, "thumbnail_type")
        layout.prop(settings, "thumbnail_background_lightness")
        # for printable models
        if asset_type == "PRINTABLE":
            layout.prop(settings, "thumbnail_material_color")
        layout.prop(settings, "thumbnail_angle")
        layout.prop(settings, "thumbnail_snap_to")
        layout.prop(settings, "thumbnail_samples")
        layout.prop(settings, "thumbnail_resolution")
        layout.prop(settings, "thumbnail_denoising")

    def execute(self, context):
        experimental = utils.experimental_enabled()
        settings = get_thumbnail_settings()
        asset = utils.get_active_model()
        bkit = asset.blenderkit

        # Non-experimental users always get a regular Cycles thumbnail: reset the
        # experimental options so a previously stored value can't leak through.
        if not experimental:
            self.thumbnail_type = "REGULAR"
        if not utils.elevated_experimental_enabled():
            reset_thumbnail_render_engine(settings)

        is_wire = experimental and self.thumbnail_type == "WIREFRAME"

        tempdir = tempfile.mkdtemp()
        blend_name = (
            "thumbnailer_wf_blenderkit" if is_wire else "thumbnailer_blenderkit"
        )
        filepath = os.path.join(tempdir, blend_name + ".blend")

        path_can_be_relative = True
        thumb_dir = os.path.dirname(bpy.data.filepath)
        if thumb_dir == "":
            thumb_dir = tempdir
            path_can_be_relative = False

        an_slug = paths.slugify(asset.name)
        if is_wire:
            # add suffix to distinguish from regular thumbnail
            an_slug += "_wf"

        thumb_path = os.path.join(thumb_dir, an_slug)

        if path_can_be_relative:
            rel_thumb_path = f"//{an_slug}"
        else:
            rel_thumb_path = thumb_path

        i = 0
        while os.path.isfile(thumb_path + ".jpg"):
            thumb_name = f"{an_slug}_{str(i).zfill(4)}"
            thumb_path = os.path.join(thumb_dir, thumb_name)
            if path_can_be_relative:
                rel_thumb_path = f"//{thumb_name}"

            i += 1

        if is_wire:
            bkit.is_generating_wire_thumbnail = True
            bkit.wire_thumbnail = rel_thumb_path + ".jpg"
            bkit.wire_thumbnail_generating_state = "Saving .blend file"
        else:
            bkit.is_generating_thumbnail = True
            bkit.thumbnail = rel_thumb_path + ".jpg"
            bkit.thumbnail_generating_state = "Saving .blend file"

        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"
        # save a copy of actual scene but don't interfere with the users models

        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=False, copy=True)
        # get all included objects
        obs = utils.get_hierarchy(asset)
        obnames = []
        for ob in obs:
            obnames.append(ob.name)
        # asset type can be model or printable
        ui_props = bpy.context.window_manager.blenderkitUI
        asset_type = ui_props.asset_type
        args_dict = {
            "type": asset_type,
            "asset_name": asset.name,
            "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
        }
        thumbnail_args = {
            "type": asset_type,
            "models": str(obnames),
            "thumbnail_angle": settings.thumbnail_angle,
            "thumbnail_snap_to": settings.thumbnail_snap_to,
            "thumbnail_material_color": (
                settings.thumbnail_material_color[0],
                settings.thumbnail_material_color[1],
                settings.thumbnail_material_color[2],
            ),
            "thumbnail_resolution": settings.thumbnail_resolution,
            "thumbnail_samples": settings.thumbnail_samples,
            "thumbnail_denoising": settings.thumbnail_denoising,
            "thumbnail_background_lightness": settings.thumbnail_background_lightness,
        }
        if is_wire:
            # Wireframe renders in Cycles with a fixed dark background.
            thumbnail_args["thumbnail_render_type"] = "WIREFRAME"
            thumbnail_args["thumbnail_upload_type"] = "wire_thumbnail"
        else:
            thumbnail_args["thumbnail_render_engine"] = settings.thumbnail_render_engine

        args_dict.update(thumbnail_args)

        start_model_thumbnailer(
            self, json_args=args_dict, props=asset.blenderkit, wait=False
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager

        return wm.invoke_props_dialog(self, width=400)


class ReGenerateThumbnailOperator(bpy.types.Operator):
    """
    Generate default thumbnail with Cycles renderer and upload it.
    Works also for assets from search results, without being downloaded before.
    By default marks the asset for server-side thumbnail regeneration.
    """

    bl_idname = "object.blenderkit_regenerate_thumbnail"
    bl_label = "Blendkit Thumbnail Re-generate"
    bl_options = {"REGISTER", "INTERNAL"}

    asset_index: IntProperty(  # type: ignore[valid-type]
        name="Asset Index", description="asset index in search results", default=-1
    )

    asset_type: StringProperty(  # type: ignore[valid-type]
        name="Asset Type",
        description="Asset type used for thumbnail generation",
        default="",
    )

    render_locally: BoolProperty(  # type: ignore[valid-type]
        name="Render Locally",
        description="Render thumbnail locally instead of using server-side rendering",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return True  # bpy.context.view_layer.objects.active is not None

    def check(self, context):
        # Re-run the popup layout when an operator property changes so
        # conditionally shown fields update live.
        return True

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports autothumb)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        settings = get_thumbnail_settings()
        layout = self.layout
        layout.prop(self, "render_locally")
        layout.label(text="Server-side rendering may take several hours", icon="INFO")
        layout.label(text="thumbnailer settings")
        layout.prop(settings, "thumbnail_background_lightness")
        # for printable models
        asset_type = (
            getattr(self, "asset_type", "")
            or getattr(self, "asset_data", {}).get("assetType", "")
            or bpy.context.window_manager.blenderkitUI.asset_type
        ).upper()
        if asset_type == "PRINTABLE":
            layout.prop(settings, "thumbnail_material_color")
        layout.prop(settings, "thumbnail_angle")
        layout.prop(settings, "thumbnail_snap_to")
        layout.prop(settings, "thumbnail_samples")
        layout.prop(settings, "thumbnail_resolution")
        layout.prop(settings, "thumbnail_denoising")

    def execute(self, context):
        if not self.asset_index > -1:
            return {"CANCELLED"}

        preferences = bpy.context.preferences.addons[__package__].preferences
        settings = preferences.thumbnail_settings

        if not utils.elevated_experimental_enabled():
            reset_thumbnail_render_engine(settings)

        # Ensure asset_type is set when execution is triggered directly.
        ui_props = bpy.context.window_manager.blenderkitUI
        if not getattr(self, "asset_type", ""):
            self.asset_type = ui_props.asset_type

        if not self.render_locally:
            # Use server-side thumbnail regeneration
            success = upload.mark_for_thumbnail(
                asset_id=self.asset_data["id"],
                api_key=preferences.api_key,
                use_gpu=settings.thumbnail_use_gpu,
                samples=settings.thumbnail_samples,
                resolution=int(settings.thumbnail_resolution),
                denoising=settings.thumbnail_denoising,
                background_lightness=settings.thumbnail_background_lightness,
                thumbnail_render_engine=settings.thumbnail_render_engine,
                angle=settings.thumbnail_angle,
                snap_to=settings.thumbnail_snap_to,
            )
            if success:
                self.report(
                    {"INFO"}, "Asset marked for server-side thumbnail regeneration"
                )
            else:
                self.report(
                    {"ERROR"}, "Failed to mark asset for thumbnail regeneration"
                )
            return {"FINISHED"}

        # Local thumbnail generation (original functionality)
        tempdir = tempfile.mkdtemp()

        an_slug = paths.slugify(self.asset_data["name"])
        thumb_path = os.path.join(tempdir, an_slug)

        # asset type can be model or printable
        self.asset_type = self.asset_type or ui_props.asset_type
        args_dict = {
            "type": self.asset_type,
            "asset_name": self.asset_data["name"],
            "asset_data": self.asset_data,
            # "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
            "do_download": True,
            "upload_after_render": True,
        }
        thumbnail_args = {
            "type": self.asset_type,
            "thumbnail_render_engine": settings.thumbnail_render_engine,
            "thumbnail_angle": settings.thumbnail_angle,
            "thumbnail_snap_to": settings.thumbnail_snap_to,
            "thumbnail_background_lightness": settings.thumbnail_background_lightness,
            "thumbnail_resolution": settings.thumbnail_resolution,
            "thumbnail_samples": settings.thumbnail_samples,
            "thumbnail_denoising": settings.thumbnail_denoising,
        }

        args_dict.update(thumbnail_args)
        start_model_thumbnailer(self, json_args=args_dict, wait=False)
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        # Get search results from history
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        self.asset_data = sr[self.asset_index]
        # Prepopulate asset_type so draw() can safely access it.
        self.asset_type = (
            self.asset_data.get("assetType", "")
            if isinstance(self.asset_data, dict)
            else ""
        ).upper() or bpy.context.window_manager.blenderkitUI.asset_type

        return wm.invoke_props_dialog(self, width=400)


class GenerateMaterialThumbnailOperator(bpy.types.Operator):
    """Generate default thumbnail with Cycles renderer"""

    bl_idname = "object.blenderkit_generate_material_thumbnail"
    bl_label = "Blendkit Material Thumbnail Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bpy.context.view_layer.objects.active is not None

    def check(self, context):
        return True

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports autothumb)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        layout = self.layout
        settings = get_thumbnail_settings()
        layout.prop(settings, "thumbnail_generator_type")
        layout.prop(settings, "thumbnail_scale")
        layout.prop(settings, "thumbnail_background")
        if settings.thumbnail_background:
            layout.prop(settings, "thumbnail_background_lightness")
        layout.prop(settings, "thumbnail_resolution")
        layout.prop(settings, "thumbnail_samples")
        layout.prop(settings, "thumbnail_denoising")
        layout.prop(settings, "adaptive_subdivision")

    def execute(self, context):
        asset = bpy.context.active_object.active_material
        tempdir = tempfile.mkdtemp()
        filepath = os.path.join(tempdir, "material_thumbnailer_cycles.blend")
        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"

        # save a copy of actual scene but don't interfere with the users models
        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=False, copy=True)

        path_can_be_relative = True
        thumb_dir = os.path.dirname(bpy.data.filepath)
        if thumb_dir == "":  # file not saved
            thumb_dir = tempdir
            path_can_be_relative = False
        an_slug = paths.slugify(asset.name)

        thumb_path = os.path.join(thumb_dir, an_slug)

        if path_can_be_relative:
            rel_thumb_path = os.path.join("//", an_slug)
        else:
            rel_thumb_path = thumb_path

        # auto increase number of the generated thumbnail.
        i = 0
        while os.path.isfile(thumb_path + ".png"):
            thumb_path = os.path.join(thumb_dir, an_slug + "_" + str(i).zfill(4))
            rel_thumb_path = os.path.join("//", an_slug + "_" + str(i).zfill(4))
            i += 1

        asset.blenderkit.thumbnail = rel_thumb_path + ".png"
        bkit = asset.blenderkit
        settings = get_thumbnail_settings()

        if not utils.elevated_experimental_enabled():
            reset_thumbnail_render_engine(settings)

        args_dict = {
            "type": "material",
            "asset_name": asset.name,
            "filepath": filepath,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
        }

        thumbnail_args = {
            "thumbnail_render_engine": settings.thumbnail_render_engine,
            "thumbnail_type": settings.thumbnail_generator_type,
            "thumbnail_scale": settings.thumbnail_scale,
            "thumbnail_background": settings.thumbnail_background,
            "thumbnail_background_lightness": settings.thumbnail_background_lightness,
            "thumbnail_resolution": settings.thumbnail_resolution,
            "thumbnail_samples": settings.thumbnail_samples,
            "thumbnail_denoising": settings.thumbnail_denoising,
            "adaptive_subdivision": settings.adaptive_subdivision,
            "texture_size_meters": bkit.texture_size_meters,
        }
        args_dict.update(thumbnail_args)
        start_material_thumbnailer(
            self, json_args=args_dict, props=asset.blenderkit, wait=False
        )

        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)


class ReGenerateMaterialThumbnailOperator(bpy.types.Operator):
    """
    Generate default thumbnail with Cycles renderer and upload it.
    Works also for assets from search results, without being downloaded before.
    By default marks the asset for server-side thumbnail regeneration.
    """

    bl_idname = "object.blenderkit_regenerate_material_thumbnail"
    bl_label = "Blendkit Material Thumbnail Re-Generator"
    bl_options = {"REGISTER", "INTERNAL"}

    asset_index: IntProperty(  # type: ignore[valid-type]
        name="Asset Index", description="asset index in search results", default=-1
    )

    render_locally: BoolProperty(  # type: ignore[valid-type]
        name="Render Locally",
        description="Render thumbnail locally instead of using server-side rendering",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return True  # bpy.context.view_layer.objects.active is not None

    def check(self, context):
        return True

    def draw(self, context):
        # local import to avoid circular import (ui_panels imports autothumb)
        from . import ui_panels

        # this timer is there to not let double clicks through the popups down to the asset bar.
        ui_panels.set_overlay_panel_active()
        settings = get_thumbnail_settings()
        layout = self.layout
        layout.prop(self, "render_locally")
        layout.label(text="Server-side rendering may take several hours", icon="INFO")
        layout.prop(settings, "thumbnail_generator_type")
        layout.prop(settings, "thumbnail_scale")
        layout.prop(settings, "thumbnail_background")
        if settings.thumbnail_background:
            layout.prop(settings, "thumbnail_background_lightness")
        layout.prop(settings, "thumbnail_resolution")
        layout.prop(settings, "thumbnail_samples")
        layout.prop(settings, "thumbnail_denoising")
        layout.prop(settings, "adaptive_subdivision")

    def execute(self, context):
        if not self.asset_index > -1:
            return {"CANCELLED"}

        # Get search results from history
        history_step = search.get_active_history_step()
        sr = history_step.get("search_results", [])
        asset_data = sr[self.asset_index]

        preferences = bpy.context.preferences.addons[__package__].preferences
        settings = preferences.thumbnail_settings

        if not utils.elevated_experimental_enabled():
            reset_thumbnail_render_engine(settings)

        if not self.render_locally:
            # Use server-side thumbnail regeneration
            success = upload.mark_for_thumbnail(
                asset_id=asset_data["id"],
                api_key=preferences.api_key,
                use_gpu=settings.thumbnail_use_gpu,
                samples=settings.thumbnail_samples,
                resolution=int(settings.thumbnail_resolution),
                denoising=settings.thumbnail_denoising,
                background_lightness=settings.thumbnail_background_lightness,
                thumbnail_type=settings.thumbnail_generator_type,
                thumbnail_render_engine=settings.thumbnail_render_engine,
                scale=settings.thumbnail_scale,
                background=settings.thumbnail_background,
                adaptive_subdivision=settings.adaptive_subdivision,
            )
            if success:
                self.report(
                    {"INFO"}, "Asset marked for server-side thumbnail regeneration"
                )
            else:
                self.report(
                    {"ERROR"}, "Failed to mark asset for thumbnail regeneration"
                )
            return {"FINISHED"}

        # Local thumbnail generation (original functionality)
        an_slug = paths.slugify(asset_data["name"])

        tempdir = tempfile.mkdtemp()

        thumb_path = os.path.join(tempdir, an_slug)

        args_dict = {
            "type": "material",
            "asset_name": asset_data["name"],
            "asset_data": asset_data,
            "thumbnail_path": thumb_path,
            "tempdir": tempdir,
            "do_download": True,
            "upload_after_render": True,
        }
        thumbnail_args = {
            "thumbnail_render_engine": settings.thumbnail_render_engine,
            "thumbnail_type": settings.thumbnail_generator_type,
            "thumbnail_scale": settings.thumbnail_scale,
            "thumbnail_background": settings.thumbnail_background,
            "thumbnail_background_lightness": settings.thumbnail_background_lightness,
            "thumbnail_resolution": settings.thumbnail_resolution,
            "thumbnail_samples": settings.thumbnail_samples,
            "thumbnail_denoising": settings.thumbnail_denoising,
            "adaptive_subdivision": settings.adaptive_subdivision,
            "texture_size_meters": utils.get_param(
                asset_data, "textureSizeMeters", 1.0
            ),
        }
        args_dict.update(thumbnail_args)
        start_material_thumbnailer(self, json_args=args_dict, wait=False)

        return {"FINISHED"}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=400)


def register_thumbnailer():
    bpy.utils.register_class(GenerateThumbnailOperator)
    bpy.utils.register_class(ReGenerateThumbnailOperator)
    bpy.utils.register_class(GenerateMaterialThumbnailOperator)
    bpy.utils.register_class(ReGenerateMaterialThumbnailOperator)


def unregister_thumbnailer():
    bpy.utils.unregister_class(GenerateThumbnailOperator)
    bpy.utils.unregister_class(ReGenerateThumbnailOperator)
    bpy.utils.unregister_class(GenerateMaterialThumbnailOperator)
    bpy.utils.unregister_class(ReGenerateMaterialThumbnailOperator)
