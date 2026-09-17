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

from __future__ import annotations

import json
import math
import os
import sys
from traceback import print_exc
from typing import Any, Union

import bpy


def get_obnames(BLENDKIT_EXPORT_DATA: str):
    with open(BLENDKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
        data = json.load(s)
    obnames = eval(data["models"])
    return obnames


def center_objs_for_thumbnail(obs: list[Any]) -> None:
    """Center and scale objects for optimal thumbnail framing.

    Steps:
    1. Center objects in world space (handles parent-child hierarchy)
    2. Adjust camera distance based on object bounds
    3. Scale helper objects to fit the model in frame

    Args:
        obs: List of Blender objects to center and frame.
    """
    scene = bpy.context.scene
    parent = obs[0]

    # Handle instanced collections (linked objects)
    if parent.type == "EMPTY" and parent.instance_collection is not None:
        obs = parent.instance_collection.objects[:]

    # Get top-level parent
    while parent.parent is not None:
        parent = parent.parent

    # Reset parent rotation for accurate snapping
    parent.rotation_euler = (0, 0, 0)
    parent.location = (0, 0, 0)
    bpy.context.view_layer.update()

    # Calculate bounding box in world space
    minx, miny, minz, maxx, maxy, maxz = utils.get_bounds_worldspace(obs)

    # Center object at world origin
    cx = (maxx - minx) / 2 + minx
    cy = (maxy - miny) / 2 + miny
    for ob in scene.collection.objects:
        ob.select_set(False)

    # Making the hierarchy root the active object is NOT required for centering
    # (we set its transform directly below). In Blender 4.2 the root (e.g. an
    # armature/empty) is often placed in an excluded/linked collection that is
    # not part of the render view layer, and a name-based membership test is
    # unreliable in that case, so assigning it as active can still raise
    # RuntimeError. Guard it and carry on; child objects inherit the transform.
    try:
        bpy.context.view_layer.objects.active = parent
    except RuntimeError:
        bg_blender.progress(
            "WARNING: could not set active object for centering, proceeding anyway"
        )
        pass
    parent.location = (-cx, -cy, 0)

    # Adjust camera position and scale based on object size
    cam_z = scene.camera.parent.parent
    cam_z.location.z = maxz / 2

    # Calculate diagonal size of object for scaling
    dx = maxx - minx
    dy = maxy - miny
    dz = maxz - minz
    r = math.sqrt(dx * dx + dy * dy + dz * dz)

    # Scale scene elements to fit object
    scaler = bpy.context.view_layer.objects["scaler"]
    scaler.scale = (r, r, r)
    coef = 0.7  # Camera distance coefficient
    r *= coef
    cam_z.scale = (r, r, r)
    bpy.context.view_layer.update()


def render_thumbnails() -> None:
    """Render the current scene to a still image (no animation)."""
    bpy.ops.render.render(write_still=True, animation=False)


def set_render_engine(scene: Any, requested_engine: str) -> str:
    """Set the scene render engine based on the requested value.

    Args:
        scene: The Blender scene to configure.
        requested_engine: The engine identifier coming from the addon. This is a
            real Blender engine id as produced by ``utils.available_render_engines``
            (e.g. "CYCLES", "BLENDER_EEVEE_NEXT"), not a shorthand like "EEVEE".

    Returns:
        The engine identifier that was actually set on the scene.
    """

    try:
        scene.render.engine = requested_engine
        return scene.render.engine
    except Exception:
        bk_logger.warning(
            "Requested render engine '%s' is not available. Falling back to current engine '%s'.",
            requested_engine,
            scene.render.engine,
        )
    return scene.render.engine  # Return current engine if fallback fails


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


def replace_materials(
    obs: list[Any], material_name: str
) -> Union[bpy.types.Material, None]:
    """Replace all materials on the given objects with a wireframe material.

    Args:
        obs: List of Blender objects to modify.
        material_name: Name of the wireframe material to use.
    """
    # Create or get the wireframe material
    if material_name in bpy.data.materials:
        material = bpy.data.materials[material_name]
    else:
        bg_blender.progress(f"Material {material_name} not found")
        return

    # Assign the wireframe material to all objects
    for ob in obs:
        if ob.type == "MESH":
            # Clear all material slots and add the specified material
            ob.data.materials.clear()
            ob.data.materials.append(material)
    return material


def _set_geo_node_default(node_group: Any, name: str, value: Any) -> None:
    """Set the default value of a node group input socket by its display name.

    Setting the interface default (instead of a per-modifier input) is robust
    for appended/localized objects, where per-modifier id-properties may not be
    writable. Newly added modifiers inherit these defaults.

    Args:
        node_group: The Geometry Nodes node group.
        name: The display name of the input socket.
        value: The value to assign.
    """
    for item in node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            item.default_value = value
            return
    bg_blender.progress(f"WARNING: wireframe node input '{name}' not found")


def _set_modifier_input(mod: Any, node_group: Any, name: str, value: Any) -> bool:
    """Set a value on a Geometry Nodes *modifier* input by socket display name.

    Value-type inputs (int/float/bool/vector) are stored on the modifier under
    the socket *identifier* (e.g. "Socket_11"), not the display name, plus a
    companion "<identifier>_use_attribute" flag that must be 0 for the value to
    be used. Returns True if the socket was found and written.

    Args:
        mod: The Geometry Nodes modifier instance.
        node_group: The node group assigned to the modifier.
        name: The display name of the input socket.
        value: The value to assign.
    """
    for item in node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            ident = item.identifier
            try:
                mod[ident] = value
            except TypeError:
                return False
            use_attr = f"{ident}_use_attribute"
            if use_attr in mod:
                mod[use_attr] = 0
            return True
    return False


def setup_wireframe(
    obs: list[Any],
    render_height: float,
    pixel_thickness: float = 2.0,
) -> None:
    """Set up objects for wireframe thumbnail rendering.

    For each mesh object add the "bkit wireframe node" Geometry Nodes modifier,
    which builds quad-accurate wire geometry with a screen-constant (pixel)
    thickness. The base and wire materials are assigned inside the node group
    through its "Base Material" / "Wire Material" inputs, so no material slots
    need to be changed on the object.

    The node group subdivides the base surface (for smooth shading) while the
    wire geometry is generated from the original, un-subdivided edges only, so
    the wireframe always shows the control-cage topology over the smooth surface.

    The Geometry Nodes group needs a few scalar inputs describing the active
    camera and render resolution, which cannot be read inside Geometry Nodes.
    All objects share the same camera/resolution, so these are set once on the
    node group's interface defaults and inherited by every modifier.

    Args:
        obs: List of Blender objects to modify.
        render_height: Final render resolution height in pixels.
        pixel_thickness: Wireframe thickness in pixels.
    """
    base_name = "bkit wireframe base"
    color_name = "bkit wireframe color"
    node_group_name = "bkit wireframe node"

    base_material = bpy.data.materials.get(base_name)
    if base_material is None:
        bg_blender.progress(f"ERROR: Material {base_name} not found")
        return

    color_material = bpy.data.materials.get(color_name)
    if color_material is None:
        bg_blender.progress(f"ERROR: Material {color_name} not found")
        return

    node_group = bpy.data.node_groups.get(node_group_name)
    if node_group is None:
        bg_blender.progress(f"ERROR: node group '{node_group_name}' not found")
        return

    # Gather camera/render parameters that Geometry Nodes cannot read itself and
    # bake them into the node group interface defaults (shared by all objects).
    scene = bpy.context.scene
    camera = scene.camera
    cam_data = camera.data
    _set_geo_node_default(node_group, "Pixel Thickness", pixel_thickness)
    # Taper/cull wires once their on-screen length drops below this many pixels.
    _set_geo_node_default(node_group, "Min Wire Pixels", pixel_thickness * 0.1)
    _set_geo_node_default(node_group, "Tan Half FOV", math.tan(cam_data.angle_y / 2))
    _set_geo_node_default(node_group, "Render Height", float(render_height))
    _set_geo_node_default(node_group, "Is Ortho", cam_data.type == "ORTHO")
    _set_geo_node_default(node_group, "Ortho Scale", cam_data.ortho_scale)

    # NOTE: base/wire materials are assigned directly inside the node group's
    # "Set Material" nodes. Blender does not copy Material (datablock) interface
    # defaults onto newly created modifiers, and writing them onto the modifier
    # instance is unreliable, so we intentionally do not set them here. The
    # existence checks above only guard that the referenced materials are present.

    for ob in obs:
        if ob.type != "MESH":
            continue

        # Disable any existing Subdivision Surface modifier and read its level.
        subd_level = min(int(get_subd_level(ob, disable=True)), 2)

        # Add the wireframe Geometry Nodes modifier (inherits interface defaults)
        mod = ob.modifiers.new(name="bkit wireframe node", type="NODES")
        mod.node_group = node_group

        # Apply the per-object subdivision level to the modifier input.
        if subd_level:
            _set_modifier_input(mod, node_group, "Subdivision Level", subd_level)

        ob.update_tag()

    bpy.context.view_layer.update()


def get_subd_level(obj: Any, disable: bool = False) -> int:
    for mod in obj.modifiers:
        if mod.type == "SUBSURF":
            # and is enabled
            if not mod.show_render:
                continue
            if disable:
                mod.show_viewport = False
                mod.show_render = False
            return mod.render_levels
    return 0


def _str_to_color(s: str) -> Union[tuple[float, float, float], None]:
    """Convert a color string to an RGB tuple.

    Args:
        s: Color string in the format "#RRGGBB" or "R,G,B".

    Returns:
        A tuple of (R, G, B) values as floats in the range [0.0, 1.0], or None.
    """
    hex_size = 7  # e.g. "#RRGGBB"
    rgb_size = 5  # e.g. "R,G,B"
    rgb_count = 3
    s = s.strip()
    if s.startswith("#") and len(s) == hex_size:
        r = int(s[1:3], 16) / 255.0
        g = int(s[3:5], 16) / 255.0
        b = int(s[5:7], 16) / 255.0
        return (r, g, b)
    if len(s) == rgb_size:
        parts = s.split(",")
        if len(parts) == rgb_count:
            try:
                r = float(parts[0].strip())
                g = float(parts[1].strip())
                b = float(parts[2].strip())

            except ValueError:
                pass
            else:
                return (r, g, b)
    # Default to None
    return None


def get_scene_diagonal(scene: Any) -> float:
    """Calculate the diagonal length of the scene's bounding box.

    Args:
        scene: The Blender scene to analyze.

    Returns:
        The diagonal length of the scene's bounding box.
    """
    minx, miny, minz, maxx, maxy, maxz = utils.get_bounds_worldspace(scene.objects)
    dx = maxx - minx
    dy = maxy - miny
    dz = maxz - minz
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def place_light_probe(scene: Any, objects: list[Any]) -> None:
    """Place a light probe in the scene based on the bounding box of the given objects.

    Args:
        scene: The Blender scene to modify.
        objects: List of Blender objects to consider for bounding box calculation.
    """
    # Calculate bounding box in world space
    minx, miny, minz, maxx, maxy, maxz = utils.get_bounds_worldspace(objects)

    # Calculate center and size of the bounding box
    center_x = (maxx + minx) / 2
    center_y = (maxy + miny) / 2
    center_z = (maxz + minz) / 2
    size_x = (maxx - minx) * 1.1
    size_y = (maxy - miny) * 1.1
    size_z = (maxz - minz) * 1.1

    # Create a new light probe if it doesn't exist
    if "LightProbe" not in bpy.data.objects:
        bpy.ops.object.lightprobe_add(
            type="VOLUME", location=(center_x, center_y, center_z)
        )
        light_probe = bpy.context.active_object
        light_probe.name = "LightProbe"
    else:
        light_probe = bpy.data.objects["LightProbe"]
        light_probe.location = (center_x, center_y, center_z)
    # do not set "world" contribution, otherwise we can stick with cycles
    # Adjust the size of the light probe based on the bounding box size
    light_probe.scale = (size_x / 2, size_y / 2, size_z / 2)
    # set resolution
    light_probe.data.resolution_x = 10
    light_probe.data.resolution_y = 10
    light_probe.data.resolution_z = 10
    # low samples
    light_probe.data.bake_samples = 16

    # bias
    light_probe.data.intensity = 0

    light_probe.data.normal_bias = 0.01
    light_probe.data.view_bias = 0.01
    light_probe.data.facing_bias = 0

    light_probe.data.validity_threshold = 0.01

    light_probe.data.dilation_threshold = 0
    light_probe.data.dilation_radius = 2.5

    # max distance
    # get scene diagonal

    light_probe.data.capture_distance = get_scene_diagonal(scene)

    # bake lights
    # make sure it is active and selected
    bpy.context.view_layer.objects.active = light_probe
    light_probe.select_set(True)

    # do not set "world" contribution, otherwise we can stick with cycles
    bpy.ops.object.lightprobe_cache_bake(subset="ALL")


def set_hq_eevee_settings(scene: Any) -> None:
    """Set high-quality Eevee render settings for the given scene.

    Args:
        scene: The Blender scene to configure.
    """
    try:
        # enable also nice things like soft shadows and ambient occlusion for Eevee
        scene.eevee.use_shadows = True
        scene.eevee.shadow_ray_count = 4
        scene.eevee.shadow_step_count = 10

        scene.eevee.use_volumetric_shadows = True

        # ray tracing for new blender ?
        scene.eevee.use_raytracing = True
        scene.eevee.ray_tracing_method = "PROBE"

        scene.eevee.use_fast_gi = True
        scene.eevee.ray_tracing_options.trace_max_roughness = 0.001
        scene.eevee.fast_gi_ray_count = 4
        scene.eevee.fast_gi_step_count = 8
        scene.eevee.fast_gi_quality = 0.95

        scene.eevee.direct_light_intensity = 1
        scene.eevee.indirect_light_intensity = 1

        scene.render.use_high_quality_normals = True

    except Exception:
        bk_logger.exception("Failed to set high-quality Eevee settings")
        return


if __name__ == "__main__":
    try:
        # args order must match the order in blenderkit/autothumb.py:get_thumbnailer_args()!
        BLENDKIT_EXPORT_DATA = sys.argv[-3]
        BLENDKIT_EXPORT_API_KEY = sys.argv[-2]
        patch_imports(sys.argv[-1])
        bpy.ops.preferences.addon_enable(module=sys.argv[-1])

        from . import append_link, bg_blender, bg_utils, client_lib, utils

        with open(BLENDKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
            data = json.load(s)
        thumbnail_use_gpu = data.get("thumbnail_use_gpu")

        # before loading other stuff capture current mesh lights
        mesh_lights = [
            ob
            for ob in bpy.context.scene.objects
            if ob.type == "MESH" and ob.name.startswith("light")
        ]

        if data.get("do_download"):
            # if this isn't here, blender crashes.
            if bpy.app.version >= (3, 0, 0):
                bpy.context.preferences.filepaths.file_preview_type = "NONE"

            # need to save the file, so that asset doesn't get downloaded into addon directory
            temp_blend_path = os.path.join(data["tempdir"], "temp.blend")
            bpy.ops.wm.save_as_mainfile(filepath=temp_blend_path)

            bg_blender.progress("Downloading asset")
            asset_data = data["asset_data"]
            has_url, download_url, file_name = client_lib.get_download_url(
                asset_data, utils.get_scene_id(), BLENDKIT_EXPORT_API_KEY
            )
            asset_data["files"][0]["url"] = download_url
            asset_data["files"][0]["file_name"] = file_name
            if has_url is not True:
                bg_blender.progress(
                    "couldn't download asset for thumbnail re-rendering"
                )
            bg_blender.progress("downloading asset")
            fpath = bg_utils.download_asset_file(
                asset_data, api_key=BLENDKIT_EXPORT_API_KEY
            )
            data["filepath"] = fpath
            main_object, allobs = append_link.link_collection(
                fpath,
                location=(0, 0, 0),
                rotation=(0, 0, 0),
                link=True,
                name=asset_data["name"],
                parent=None,
            )
            allobs = [main_object]
        else:
            bg_blender.progress("preparing thumbnail scene")
            obnames = get_obnames(BLENDKIT_EXPORT_DATA)
            main_object, allobs = append_link.append_objects(
                file_name=data["filepath"], obnames=obnames, link=True
            )
        bpy.context.view_layer.update()

        camdict = {
            "GROUND": "camera ground",
            "WALL": "camera wall",
            "CEILING": "camera ceiling",
            "FLOAT": "camera float",
        }

        bpy.context.scene.camera = bpy.data.objects[camdict[data["thumbnail_snap_to"]]]
        center_objs_for_thumbnail(allobs)
        bpy.context.scene.render.filepath = data["thumbnail_path"]
        render_engine = set_render_engine(
            bpy.context.scene, data.get("thumbnail_render_engine", "CYCLES")
        )
        bg_blender.progress(f"using render engine {render_engine}")
        if render_engine == "CYCLES" and thumbnail_use_gpu is True:
            bpy.context.scene.cycles.device = "GPU"
            compute_device_type = data.get("cycles_compute_device_type")
            if compute_device_type is not None:
                # DOCS:https://github.com/dfelinto/blender/blob/master/intern/cycles/blender/addon/properties.py
                bpy.context.preferences.addons[
                    "cycles"
                ].preferences.compute_device_type = compute_device_type
                bpy.context.preferences.addons["cycles"].preferences.refresh_devices()

        fdict = {
            "ANGLE_1": 1,
            "ANGLE_2": 2,
            "FRONT": 3,
            "SIDE": 4,
            "TOP": 5,
        }
        scene = bpy.context.scene
        scene.frame_set(fdict[data["thumbnail_angle"]])

        snapdict = {
            "GROUND": "Ground",
            "WALL": "Wall",
            "CEILING": "Ceiling",
            "FLOAT": "Float",
        }

        collection = bpy.context.scene.collection.children[
            snapdict[data["thumbnail_snap_to"]]
        ]
        collection.hide_viewport = False
        collection.hide_render = False
        collection.hide_select = False
        main_object.rotation_euler = (0, 0, 0)

        # Add material replacement for printable assets
        # works directly with the specific material that has a color node for input
        if data.get("type") == "PRINTABLE":
            material = replace_materials(allobs, "PrintableMaterial")
            # Find the BaseColor node in this material
            base_color_node = material.node_tree.nodes.get("BaseColor")
            if base_color_node:
                # randomize the color value, needs to be defined by random hue and saturation = 0.95, we need to convert it to RGB then
                # random_color = (random.random(), 0.95, 0.5)
                # # convert to RGB
                # random_color = colorsys.hsv_to_rgb(
                #     random_color[0], random_color[1], random_color[2]
                # )
                random_color = data["thumbnail_material_color"]
                base_color_node.outputs[0].default_value = (
                    random_color[0],
                    random_color[1],
                    random_color[2],
                    1,
                )
                # now let's make background color complementary to the material color
                bpy.data.materials["bkit background"].node_tree.nodes[
                    "BaseColor"
                ].outputs["Color"].default_value = (
                    1 - random_color[0],
                    1 - random_color[1],
                    1 - random_color[2],
                    1,
                )

        # replace materials and add wireframe geometry nodes if we need to
        # render a wireframe thumbnail
        if data.get("thumbnail_render_type") == "WIREFRAME":
            setup_wireframe(allobs, render_height=int(data["thumbnail_resolution"]))

        bpy.data.materials["bkit background"].node_tree.nodes["Value"].outputs[
            "Value"
        ].default_value = data["thumbnail_background_lightness"]

        if render_engine == "CYCLES":
            scene.cycles.samples = data["thumbnail_samples"]
            bpy.context.view_layer.cycles.use_denoising = data["thumbnail_denoising"]
        elif "EEVEE" in render_engine:
            # Eevee uses TAA render samples instead of Cycles samples.
            scene.eevee.taa_render_samples = data["thumbnail_samples"]
            set_hq_eevee_settings(scene)

            # material light do not work well for eevee, we should replace them with area lights, but for now we will just disable them
            for ob in mesh_lights:
                # replace with area light if we have a light mesh, but only for eevee, as cycles can handle it
                # create area light
                light_data = bpy.data.lights.new(name="AreaLight", type="AREA")
                # calculate size from approximate dimensions of the mesh light
                light_data.size = (
                    max(ob.dimensions.x, ob.dimensions.y, ob.dimensions.z) * 0.5
                )
                light_data.energy = 1000

                # jitter shadows
                light_data.use_shadow_jitter = True
                light_data.shadow_jitter_overblur = 20
                light_data.shadow_filter_radius = 2

                light_object = bpy.data.objects.new(
                    name="AreaLight", object_data=light_data
                )
                bpy.context.collection.objects.link(light_object)

                # position the area light at the same location as the mesh light
                light_object.location = ob.location

                # move to same place and rotation and scale as the mesh light
                light_object.rotation_euler = ob.rotation_euler
                light_object.parent = ob.parent
                light_object.matrix_parent_inverse = ob.matrix_parent_inverse

                # hide the mesh light
                ob.hide_render = True
                ob.hide_viewport = True
                ob.hide_set(True)

        # Light probe is an Eevee-only irradiance volume; baking it for Cycles
        # wastes time and has no effect, so only place it for non-Cycles engines.
        if render_engine != "CYCLES":
            place_light_probe(bpy.context.scene, allobs)

        bpy.context.view_layer.update()

        bpy.context.scene.render.resolution_x = int(data["thumbnail_resolution"])
        bpy.context.scene.render.resolution_y = int(data["thumbnail_resolution"])

        # Force JPEG output so the produced file always matches the ".jpg" path
        # the addon stores (props.thumbnail / props.wire_thumbnail) and the
        # uploader expects. The thumbnail_path in data.json has no extension, so
        # Blender appends one based on this format; without forcing it here the
        # file could be written as .png (whatever the thumbnailer.blend has
        # saved) while the addon looks for a .jpg, breaking preview and upload.
        image_settings = bpy.context.scene.render.image_settings
        image_settings.file_format = "JPEG"
        image_settings.quality = 90

        # cleanup
        if data.get("do_download"):
            # remove temp
            os.remove(temp_blend_path)

        bg_blender.progress("rendering thumbnail")
        render_thumbnails()

        # save scene in current state, so that we can re-render it later if needed
        output_path = data["thumbnail_path"] + ".blend"
        bg_blender.progress(f"scene saving {output_path}")
        bpy.ops.wm.save_as_mainfile(
            filepath=output_path, compress=True, check_existing=False
        )

        if not data.get("upload_after_render") or not data.get("asset_data"):
            bg_blender.progress(
                "background autothumbnailer finished successfully (no upload)"
            )

            sys.exit(0)
        # get sub type if we are not generating for main beauty thumbnail
        filetype = "thumbnail"
        if data.get("thumbnail_upload_type"):
            filetype = data["thumbnail_upload_type"].lower()
        bg_blender.progress("uploading thumbnail")
        fpath = data["thumbnail_path"] + ".jpg"
        ok = client_lib.complete_upload_file_blocking(
            api_key=BLENDKIT_EXPORT_API_KEY,
            asset_id=data["asset_data"]["id"],
            filepath=fpath,
            filetype=filetype,
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
