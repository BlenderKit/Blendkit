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

# This module is for analyzing the asset and filling the tags automatically.
# 1 part of the module effectively fills tags for the assets,
# the 2nd part finds possible problems in the asset.

import bpy

from . import utils


RENDER_OBTYPES = ["MESH", "CURVE", "SURFACE", "METABALL", "TEXT"]

_BLE_5_PLUS = bpy.app.version >= (5, 0, 0)


def _image_tile_count(image) -> int:
    """Return the number of tiles for a UDIM image, 1 for regular images."""
    if getattr(image, "source", "") == "TILED" and hasattr(image, "tiles"):
        return max(1, len(image.tiles))
    return 1


def check_material(props, mat):
    e = bpy.context.scene.render.engine
    shaders = []
    textures = []
    props.texture_count = 0
    props.node_count = 0
    props.total_megapixels = 0
    total_pixels = 0
    props.is_procedural = True

    if e == "CYCLES":
        if mat.node_tree is not None:
            checknodes = mat.node_tree.nodes[:]
            while len(checknodes) > 0:
                n = checknodes.pop()
                props.node_count += 1
                if n.type == "GROUP":  # dive deeper here.
                    checknodes.extend(n.node_tree.nodes)
                if (
                    len(n.outputs) == 1
                    and n.outputs[0].type == "SHADER"
                    and n.type != "GROUP"
                ):
                    if n.type not in shaders:
                        shaders.append(n.type)
                if n.type == "TEX_IMAGE":
                    if n.image is not None:
                        mattype = "image based"
                        props.is_procedural = False
                        if n.image not in textures:
                            textures.append(n.image)
                            props.texture_count += 1
                            # Multiply per-tile pixel area by tile count so that
                            # UDIM images (source='TILED') report the correct total.
                            n_tiles = _image_tile_count(n.image)
                            total_pixels += n_tiles * n.image.size[0] * n.image.size[1]

                            maxres = max(n.image.size[0], n.image.size[1])
                            props.texture_resolution_max = max(
                                props.texture_resolution_max, maxres
                            )
                            minres = min(n.image.size[0], n.image.size[1])
                            if props.texture_resolution_min == 0:
                                props.texture_resolution_min = minres
                            else:
                                props.texture_resolution_min = min(
                                    props.texture_resolution_min, minres
                                )
    props.total_megapixels = round(total_pixels / (1024 * 1024))
    props.shaders = ""
    for s in shaders:
        if s.startswith("BSDF_"):
            s = s[5:]
        s = s.lower().replace("_", " ")
        props.shaders += s + ", "


def check_render_engine(props, obs):
    ob = obs[0]
    m = None

    e = bpy.context.scene.render.engine
    mattype = None
    materials = []
    shaders = []
    textures = []
    props.uv = False
    props.texture_count = 0
    props.total_megapixels = 0
    total_pixels = 0
    props.node_count = 0
    for ob in obs:
        # TODO , this is duplicated here for other engines, otherwise this should be more clever.
        for ms in ob.material_slots:
            if ms.material is not None:
                m = ms.material
                if m.name not in materials:
                    materials.append(m.name)
        if ob.type == "MESH" and len(ob.data.uv_layers) > 0:
            props.uv = True

    if e == "BLENDER_RENDER":
        props.engine = "BLENDER_INTERNAL"
    elif e == "CYCLES":
        props.engine = "CYCLES"

        #  TODO: Clean this up, it's a mess.
        for mname in materials:
            m = bpy.data.materials[mname]
            if m is not None and m.node_tree is not None:
                checknodes = m.node_tree.nodes[:]
                while len(checknodes) > 0:
                    n = checknodes.pop()
                    props.node_count += 1
                    if n.type == "GROUP":  # dive deeper here.
                        if n.node_tree is not None:
                            checknodes.extend(n.node_tree.nodes)
                    if (
                        len(n.outputs) == 1
                        and n.outputs[0].type == "SHADER"
                        and n.type != "GROUP"
                    ):
                        if n.type not in shaders:
                            shaders.append(n.type)
                    if n.type == "TEX_IMAGE":
                        if n.image is not None and n.image not in textures:
                            props.is_procedural = False
                            mattype = "image based"

                            textures.append(n.image)
                            props.texture_count += 1
                            # Multiply per-tile pixel area by tile count so that
                            # UDIM images (source='TILED') report the correct total.
                            n_tiles = _image_tile_count(n.image)
                            total_pixels += n_tiles * n.image.size[0] * n.image.size[1]

                            maxres = max(n.image.size[0], n.image.size[1])
                            props.texture_resolution_max = max(
                                props.texture_resolution_max, maxres
                            )
                            minres = min(n.image.size[0], n.image.size[1])
                            if props.texture_resolution_min == 0:
                                props.texture_resolution_min = minres
                            else:
                                props.texture_resolution_min = min(
                                    props.texture_resolution_min, minres
                                )

        props.total_megapixels = round(total_pixels / (1024 * 1024))
        # if mattype == None:
        #    mattype = 'procedural'
        # tags['material type'] = mattype

    elif e == "BLENDER_GAME":
        props.engine = "BLENDER_GAME"

    # write to object properties.
    props.materials = ""
    props.shaders = ""
    for m in materials:
        props.materials += m + ", "
    for s in shaders:
        if s.startswith("BSDF_"):
            s = s[5:]
        s = s.lower()
        s = s.replace("_", " ")
        props.shaders += s + ", "


""" ISSUE:https://github.com/BlenderKit/BlenderKit/issues/1251 #1258
Commenting this function out, some user has reported this function got executed and failed due to missing add-on in Blender 4.2.
Even though it is not called from anywhere, Python somehow went in here. So we are just commenting it out. In order to enable the func:
1. add-on object_print3d_utils had some bug in it, needs to be checked if it was fixed (are there any other better add-on for it?)
2. add-on object_print3d_utils is no longer preinstalled in Blender 4.2+, needs to be installed from extensions.blender.org -> "3D-Print Toolbox"
def check_printable(props, obs):
    if len(obs) != 1:
        return

    addon_name = "object_print3d_utils"
    was_enabled, _ = addon_utils.check(addon_name)
    addon_utils.enable(addon_name)

    from object_print3d_utils import operators as ops

    check_cls = (
        ops.MESH_OT_print3d_check_solid,  # ops.Print3DCheckSolid,
        ops.MESH_OT_print3d_check_intersections,  # ops.Print3DCheckIntersections,
        ops.MESH_OT_print3d_check_degenerate,  # ops.Print3DCheckDegenerate,
        ops.MESH_OT_print3d_check_distorted,  # ops.Print3DCheckDistorted,
        ops.MESH_OT_print3d_check_thick,  # ops.Print3DCheckThick,
        ops.MESH_OT_print3d_check_sharp,  # ops.Print3DCheckSharp,
    )

    info = []
    for cls in check_cls:
        cls.main_check(obs[0], info)

    printable = True
    for item in info:
        passed = item[0].endswith(" 0")
        if not passed:
            printable = False

    props.printable_3d = printable
    if not was_enabled:
        addon_utils.disable(addon_name)
"""


def check_rig(props, obs):
    for ob in obs:
        if ob.type == "ARMATURE":
            props.rig = True


def has_keyframes(obj):
    """Checks if object has animation data with keyframes.

    This function only checks for keyframes,
    may return false negatives for objects animated with constraints, drivers, etc.
    """
    if obj.animation_data is None:
        return False

    a = obj.animation_data.action
    if a is None:
        return False

    # should work from at least Blender4.2+
    if _BLE_5_PLUS:
        # combined fcurves ranges
        # check if start and end frames are different
        if a.curve_frame_range[0] != a.curve_frame_range[1]:
            return True
    else:
        # older Blender versions
        for c in a.fcurves:
            if len(c.keyframe_points) > 1:
                return True
    return False


def check_anim(props, obs):
    animated = False
    for ob in obs:
        if has_keyframes(ob):
            animated = True
            break
    if animated:
        props.animated = True


def check_meshprops(props, obs):
    """checks polycount, manifold, mesh parts (not implemented)"""
    face_count = 0
    face_count_render = 0
    tris = 0
    quads = 0
    ngons = 0
    vertices_count = 0

    edges_counts = {}
    manifold = True

    for ob in obs:
        if ob.type != "MESH" and ob.type != "CURVE":
            continue

        ob_eval = None
        if ob.type == "CURVE":
            # depsgraph = bpy.context.evaluated_depsgraph_get()
            # object_eval = ob.evaluated_get(depsgraph)
            mesh = ob.to_mesh()
        else:
            mesh = ob.data

        if mesh == None:  # One-point CURVE, can happen sometimes #1318
            continue

        fco = len(mesh.polygons)
        face_count += fco
        vertices_count += len(mesh.vertices)
        fcor = fco
        for f in mesh.polygons:
            # face sides counter
            if len(f.vertices) == 3:
                tris += 1
            elif len(f.vertices) == 4:
                quads += 1
            elif len(f.vertices) > 4:
                ngons += 1

            # manifold counter
            for i, v in enumerate(f.vertices):
                v1 = f.vertices[i - 1]
                e = (min(v, v1), max(v, v1))
                edges_counts[e] = edges_counts.get(e, 0) + 1

        # all meshes have to be manifold for this to work.
        manifold = manifold and not any(
            i in edges_counts.values() for i in [0, 1, 3, 4]
        )

        for m in ob.modifiers:
            if m.type == "SUBSURF" or m.type == "MULTIRES":
                fcor *= 4**m.render_levels
            if (
                m.type == "SOLIDIFY"
            ):  # this is rough estimate, not to waste time with evaluating all nonmanifold edges
                fcor *= 2
            if m.type == "ARRAY":
                fcor *= m.count
            if m.type == "MIRROR":
                fcor *= 2
            if m.type == "DECIMATE":
                fcor *= m.ratio
        face_count_render += fcor

        if ob_eval:
            ob_eval.to_mesh_clear()

    # write out props
    props.face_count = int(face_count)
    props.face_count_render = int(face_count_render)
    if quads > 0 and tris == 0 and ngons == 0:
        props.mesh_poly_type = "QUAD"
    elif quads > tris and quads > ngons:
        props.mesh_poly_type = "QUAD_DOMINANT"
    elif tris > quads and tris > quads:
        props.mesh_poly_type = "TRI_DOMINANT"
    elif quads == 0 and tris > 0 and ngons == 0:
        props.mesh_poly_type = "TRI"
    elif ngons > quads and ngons > tris:
        props.mesh_poly_type = "NGON"
    else:
        props.mesh_poly_type = "OTHER"

    props.manifold = manifold


def count_objects(props, obs):
    ob_types = {}
    count = len(obs)
    for ob in obs:
        otype = ob.type.lower()
        ob_types[otype] = ob_types.get(otype, 0) + 1
    props.object_count = count


def check_modifiers(props, obs):
    # modif_mapping = {
    # }
    modifiers = []
    for ob in obs:
        for m in ob.modifiers:
            mtype = m.type
            mtype = mtype.replace("_", " ")
            mtype = mtype.lower()
            # mtype = mtype.capitalize()
            if mtype not in modifiers:
                modifiers.append(mtype)
            if m.type == "SMOKE":
                if m.smoke_type == "FLOW":
                    smt = m.flow_settings.smoke_flow_type
                    if smt == "BOTH" or smt == "FIRE":
                        modifiers.append("fire")

    # for mt in modifiers:
    effectmodifiers = [
        "soft body",
        "fluid simulation",
        "particle system",
        "collision",
        "smoke",
        "cloth",
        "dynamic paint",
    ]
    for m in modifiers:
        if m in effectmodifiers:
            props.simulation = True
    if ob.rigid_body is not None:
        props.simulation = True
        modifiers.append("rigid body")
    finalstr = ""
    for m in modifiers:
        finalstr += m
        finalstr += ","
    props.modifiers = finalstr


def get_autotags():
    """call all analysis functions"""
    ui = bpy.context.window_manager.blenderkitUI
    if ui.asset_type == "MODEL" or ui.asset_type == "PRINTABLE":
        ob = utils.get_active_model()
        obs = utils.get_hierarchy(ob)
        props = ob.blenderkit
        if props.name == "":
            props.name = ob.name

        # reset some properties here, because they might not get re-filled at all when they aren't needed anymore.
        props.texture_resolution_max = 0
        props.texture_resolution_min = 0

        # disabled printing checking, some 3d print addon bug.
        # bug fixed, could be enabled in the future
        # also disable because add-on is not installed in Blender 4.2+, has to be installed from extensions.blender.org
        # check the commented out function for more details
        # check_printable( props, obs)

        check_render_engine(props, obs)

        dim, bbox_min, bbox_max = utils.get_dimensions(obs)
        props.dimensions = dim
        props.bbox_min = bbox_min
        props.bbox_max = bbox_max

        check_rig(props, obs)
        check_anim(props, obs)
        check_meshprops(props, obs)
        check_modifiers(props, obs)
        count_objects(props, obs)

    elif ui.asset_type == "SCENE":
        scene = bpy.context.scene
        props = scene.blenderkit
        if props.name == "":
            props.name = scene.name
        dim, bbox_min, bbox_max = utils.get_scene_dimensions(scene)
        props.dimensions = dim
        props.bbox_min = bbox_min
        props.bbox_max = bbox_max
        scene_objects = list(scene.objects)
        check_meshprops(props, scene_objects)
        count_objects(props, scene_objects)

    elif ui.asset_type == "MATERIAL":
        # reset some properties here, because they might not get re-filled at all when they aren't needed anymore.

        mat = utils.get_active_asset()
        props = mat.blenderkit
        props.texture_resolution_max = 0
        props.texture_resolution_min = 0
        check_material(props, mat)

    elif ui.asset_type == "HDR":
        # reset some properties here, because they might not get re-filled at all when they aren't needed anymore.

        hdr = utils.get_active_asset()
        props = hdr.blenderkit
        props.texture_resolution_max = max(hdr.size[0], hdr.size[1])


class AutoFillTags(bpy.types.Operator):
    """Fill tags for asset. Now run before upload, no need to interact from user side"""

    bl_idname = "object.blenderkit_auto_tags"
    bl_label = "Generate Auto Tags for Blendkit"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return utils.uploadable_asset_poll()

    def execute(self, context):
        get_autotags()
        return {"FINISHED"}


def register_asset_inspector():
    bpy.utils.register_class(AutoFillTags)


def unregister_asset_inspector():
    bpy.utils.unregister_class(AutoFillTags)


if __name__ == "__main__":
    register()  # type: ignore
    # TODO: fix call to missing function
