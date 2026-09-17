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
import logging
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from typing import Optional, Tuple, Union
import math

from mathutils import Matrix, Vector

import blf
import bpy
from bpy import app

import gpu
from gpu_extras.batch import batch_for_shader

from .image_utils import IMG

bk_logger = logging.getLogger(__name__)

cached_images = {}

cached_gpu_textures = {}

# Persistent scratch image reused for thumbnail->GPU texture conversion.
# Loading and removing a fresh bpy.data.images for every thumbnail triggers a
# full depsgraph relations rebuild (DEG_relations_tag_update) on each
# add/remove, which scales with scene complexity and makes asset-bar mouse-over
# very slow in huge scenes. Reusing one image (just reload its filepath) avoids
# that cost entirely.
_scratch_image = None
_SCRATCH_IMAGE_NAME = ".blenderkit_thumb_scratch"

_cached_image_shader: Optional[gpu.types.GPUShader] = None

SEGMENTS_DEFAULT = 4


def _resolve_region_dimensions(region) -> Tuple[float, float]:
    width = getattr(region, "width", None) if region else None
    height = getattr(region, "height", None) if region else None

    if width is None or width <= 0 or height is None or height <= 0:
        ctx_region = getattr(bpy.context, "region", None)
        if ctx_region is not None:
            width = width or getattr(ctx_region, "width", None)
            height = height or getattr(ctx_region, "height", None)

    width = float(width or 1.0)
    height = float(height or 1.0)
    return width, height


@contextmanager
def overlay_matrix_guard(region=None, *args, **kwargs):
    """Ensure viewport overlays draw in screen space regardless of other handlers."""

    pushed = False
    try:
        try:
            gpu.matrix.push()
            pushed = True
            gpu.matrix.load_identity()
            width, height = _resolve_region_dimensions(region)
            _set_overlay_projection(width, height)
        except Exception:  # noqa: BLE001
            bk_logger.exception("Failed to prepare overlay matrix state")
        yield
    finally:
        if pushed:
            try:
                gpu.matrix.pop()
            except Exception:  # noqa: BLE001
                bk_logger.exception("Failed to restore overlay matrix state")


def _ortho_projection_matrix(width: float, height: float, *, near=-100.0, far=100.0):
    """Return a pixel-aligned orthographic projection matrix."""

    if width <= 0.0:
        width = 1.0
    if height <= 0.0:
        height = 1.0
    if far == near:
        far = near + 0.001

    sx = 2.0 / width
    sy = 2.0 / height
    sz = -2.0 / (far - near)
    tx = -1.0
    ty = -1.0
    tz = -(far + near) / (far - near)

    return Matrix(
        (
            (sx, 0.0, 0.0, tx),
            (0.0, sy, 0.0, ty),
            (0.0, 0.0, sz, tz),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def _set_overlay_projection(width: float, height: float):
    """Set the 2D projection matrix used by Blendkit overlays."""

    try:
        projection = _ortho_projection_matrix(width, height)
        gpu.matrix.load_projection_matrix(projection)
    except Exception:  # noqa: BLE001
        bk_logger.exception("overlay_matrix_guard: Failed to load projection matrix")


VERTEX_SHADER_LEGACY = """
uniform mat4 ModelViewProjectionMatrix;
in vec2 pos;
in vec2 texCoord;
out vec2 uv;

void main()
{
    uv = texCoord;
    gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
}
"""


FRAGMENT_SHADER_LEGACY = """
in vec2 uv;
out vec4 fragColor;
uniform sampler2D image;
uniform float transparency;
uniform int color_space_mode;

vec3 linear_to_srgb(vec3 linear_color)
{
    vec3 cutoff = vec3(0.0031308);
    vec3 lower = linear_color * 12.92;
    vec3 higher = 1.055 * pow(max(linear_color, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
    return mix(lower, higher, step(cutoff, linear_color));
}

void main()
{
    vec4 color = texture(image, uv);
    if (color_space_mode == 1) {
        color.rgb = linear_to_srgb(color.rgb);
    }
    color.a *= transparency;
    fragColor = color;
}
"""


def create_image_shader_info():
    """Return GPU shader info for the runtime image shader."""
    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.vertex_in(0, "VEC2", "pos")
    shader_info.vertex_in(1, "VEC2", "texCoord")

    stage_iface = gpu.types.GPUStageInterfaceInfo("uv_iface")
    stage_iface.smooth("VEC2", "uv")
    shader_info.vertex_out(stage_iface)

    shader_info.push_constant("MAT4", "ModelViewProjectionMatrix")
    shader_info.push_constant("FLOAT", "transparency")
    shader_info.push_constant("INT", "color_space_mode")
    shader_info.sampler(0, "FLOAT_2D", "image")

    shader_info.fragment_out(0, "VEC4", "fragColor")
    shader_info.vertex_source(
        """
        void main()
        {
            uv = texCoord;
            gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
        }
    """
    )
    shader_info.fragment_source(
        """
        void main()
        {
            vec4 color = texture(image, uv);
            if (color_space_mode == 1) {
                vec3 cutoff = vec3(0.0031308);
                vec3 lower = color.rgb * 12.92;
                vec3 higher = 1.055 * pow(max(color.rgb, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
                color.rgb = mix(lower, higher, step(cutoff, color.rgb));
            }
            color.a *= transparency;
            fragColor = color;
        }
    """
    )
    return shader_info


def create_image_shader():
    """Return a cached shader that supports transparency across Blender versions.
    Features:
        - sRGB conversion for UI overlays
        - transparency
    """
    global _cached_image_shader

    if _cached_image_shader is not None:
        return _cached_image_shader

    shader = None

    create_info_supported = (
        hasattr(gpu, "shader")
        and hasattr(gpu.shader, "create_from_info")
        and hasattr(gpu.types, "GPUShaderCreateInfo")
    )

    if create_info_supported:
        try:
            shader_info = create_image_shader_info()
            shader = gpu.shader.create_from_info(shader_info)
        except Exception:  # noqa: BLE001
            bk_logger.exception("Failed to create image shader")
            shader = None

    if shader is None:
        try:
            shader = gpu.types.GPUShader(VERTEX_SHADER_LEGACY, FRAGMENT_SHADER_LEGACY)
        except Exception:  # noqa: BLE001
            bk_logger.exception("Failed to create image shader")

    if shader is None:
        # fallback to builtin shader
        # mainly for MacOS builds that have issues with custom shaders
        if app.version < (4, 0, 0):
            shader = gpu.shader.from_builtin("2D_IMAGE")
        else:
            shader = gpu.shader.from_builtin("IMAGE")

    _cached_image_shader = shader
    return shader


def get_ui_scale() -> float:
    """Get the UI scale

    Returns:
        The UI scale factor as a float.
    """
    return bpy.context.preferences.system.dpi / 96.0
    # sources:
    # "sys" values are from system,
    # and for current monitor on which the blender is running
    sys_ps = bpy.context.preferences.system.pixel_size
    # dpi scaling 72 =-> 1.0, 126 -> 1.75 (dpi -> sys_ui_scale)
    # 96 / dpi gives correct scale factor
    sys_dpi = bpy.context.preferences.system.dpi
    # global scaler
    sys_sc = bpy.context.preferences.system.ui_scale
    # local ui scaler (can be set by user per blender window)
    view_sc = bpy.context.preferences.view.ui_scale


def _get_flat_shader_2d():
    if app.version < (4, 0, 0):
        shader_name = "2D_UNIFORM_COLOR"
    else:
        shader_name = "UNIFORM_COLOR"
    return gpu.shader.from_builtin(shader_name)


def draw_rect(x, y, width, height, color):
    """Used for drawing 2D rectangle backgrounds."""
    xmax = x + width
    ymax = y + height
    points = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1, 2), (2, 3, 0))

    shader = _get_flat_shader_2d()
    batch = batch_for_shader(shader, "TRIS", {"pos": points}, indices=indices)

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_rect_outline(x, y, width, height, color, line_width=1.0):
    """Used for drawing 2D rectangle outlines."""
    xmax = x + width
    ymax = y + height
    coords = (
        (x, y),  # (x, y)
        (x, ymax),  # (x, y)
        (xmax, ymax),  # (x, y)
        (xmax, y),  # (x, y)
    )
    indices = ((0, 1), (1, 2), (2, 3), (3, 0))

    shader = _get_flat_shader_2d()
    batch = batch_for_shader(shader, "LINES", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(line_width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_line2d(x1, y1, x2, y2, width, color):
    """Used for drawing line from dragged thumbnail to the 3D bounding box."""
    coords = ((x1, y1), (x2, y2))
    indices = ((0, 1),)

    shader = _get_flat_shader_2d()

    batch = batch_for_shader(shader, "LINES", {"pos": coords}, indices=indices)
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(max(1.0, width))
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _parse_radius_value(
    value,
    *,
    max_radius: float,
    min_dimension: float,
    ui_scale: float = 1.0,
) -> float:
    """Return a clamped radius in pixels.

    Accepts raw pixel values, strings with percentages (e.g. "50%"),
    mapping types containing ``percent``/``pct``/``ratio`` or ``px`` keys,
    and falls back to treating anything else as raw pixels.
    """

    def clamp_radius(radius: float) -> float:
        return max(0.0, min(radius, max_radius))

    effective_scale = ui_scale if ui_scale > 0.0 else 1.0

    def scale_px_value(px_value: float) -> float:
        return clamp_radius(px_value * effective_scale)

    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            number = text[:-1].strip()
            try:
                pct = float(number) / 100.0
            except ValueError:
                return 0.0
            radius_px = pct * min_dimension
            return clamp_radius(radius_px)
        # plain numeric string interpreted as pixels
        try:
            value = float(text)
        except ValueError:
            return 0.0
        return scale_px_value(value)

    if isinstance(value, Mapping):
        if "percent" in value:
            try:
                pct = float(value["percent"]) / 100.0
            except (TypeError, ValueError):
                pct = 0.0
            radius_px = pct * min_dimension
            return clamp_radius(radius_px)
        if "pct" in value:
            try:
                pct = float(value["pct"]) / 100.0
            except (TypeError, ValueError):
                pct = 0.0
            radius_px = pct * min_dimension
            return clamp_radius(radius_px)
        if "ratio" in value:
            try:
                ratio = float(value["ratio"])
            except (TypeError, ValueError):
                ratio = 0.0
            radius_px = ratio * min_dimension
            return clamp_radius(radius_px)
        if "px" in value:
            try:
                px_value = float(value["px"])
            except (TypeError, ValueError):
                px_value = 0.0
            return scale_px_value(px_value)

    try:
        numeric_value = float(value)  # type: ignore
    except (TypeError, ValueError):
        numeric_value = 0.0
    return scale_px_value(numeric_value)


def _rounded_rect_outline(
    x: float,
    y: float,
    width: float,
    height: float,
    radius: Union[tuple[Union[str, float], ...], str, float] = (0.0,),
    segments: int = SEGMENTS_DEFAULT,
):
    if width <= 0 or height <= 0:
        return []
    min_dimension = min(width, height)
    max_radius = max(0.0, min_dimension / 2.0)

    if isinstance(radius, (tuple, list)):
        raw_radii = list(radius)
    else:
        raw_radii = [radius]
    if not raw_radii:
        raw_radii = [0.0]
    ui_scale = get_ui_scale()
    parsed_radii = [
        _parse_radius_value(
            value,
            max_radius=max_radius,
            min_dimension=min_dimension,
            ui_scale=ui_scale,
        )
        for value in raw_radii
    ]
    while len(parsed_radii) < 4:
        parsed_radii.append(parsed_radii[-1])
    radii = parsed_radii[:4]

    r_tl, r_tr, r_br, r_bl = radii

    if all(r == 0.0 for r in radii):
        outline = [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
        ]
        outline.append(outline[0])
        return outline

    steps = max(1, int(segments))
    outline = []
    steps = max(1, int(segments))
    outline = []

    def emit_corner(cx, cy, start_angle, end_angle, radius_value, fallback_point):
        if radius_value <= 0.0:
            outline.append(fallback_point)
            return
        for step in range(steps + 1):
            t = step / steps
            angle = start_angle + (end_angle - start_angle) * t
            outline.append(
                (
                    cx + math.cos(angle) * radius_value,
                    cy + math.sin(angle) * radius_value,
                )
            )

    emit_corner(
        x + r_tl,
        y + height - r_tl,
        math.pi,
        math.pi / 2.0,
        r_tl,
        (x, y + height),
    )
    emit_corner(
        x + width - r_tr,
        y + height - r_tr,
        math.pi / 2.0,
        0.0,
        r_tr,
        (x + width, y + height),
    )
    emit_corner(
        x + width - r_br,
        y + r_br,
        0.0,
        -math.pi / 2.0,
        r_br,
        (x + width, y),
    )
    emit_corner(
        x + r_bl,
        y + r_bl,
        -math.pi / 2.0,
        -math.pi,
        r_bl,
        (x, y),
    )

    if outline and outline[0] != outline[-1]:
        outline.append(outline[0])
    return outline


def _rounded_rect_mesh(
    x: float,
    y: float,
    width: float,
    height: float,
    radius: Union[tuple[Union[str, float], ...], str, float],
    crop: Tuple[float, float, float, float],
    segments: int = SEGMENTS_DEFAULT,
):
    if width <= 0.0 or height <= 0.0:
        return None
    outline = _rounded_rect_outline(
        x,
        y,
        width,
        height,
        radius,
        segments=segments,
    )
    if not outline:
        return None
    loop = outline[:-1] if len(outline) > 1 and outline[0] == outline[-1] else outline
    if len(loop) < 3:
        return None
    crop_u0, crop_v0, crop_u1, crop_v1 = crop
    u_span = crop_u1 - crop_u0
    v_span = crop_v1 - crop_v0
    if u_span == 0.0:
        u_span = 1.0
    if v_span == 0.0:
        v_span = 1.0
    coords = list(loop)
    try:
        inv_width = 1.0 / width
    except ZeroDivisionError:
        inv_width = 0.0
    try:
        inv_height = 1.0 / height
    except ZeroDivisionError:
        inv_height = 0.0
    uvs = []
    for vx, vy in coords:
        rel_x = (vx - x) * inv_width
        rel_y = (vy - y) * inv_height
        u = crop_u0 + rel_x * u_span
        v = crop_v0 + rel_y * v_span
        uvs.append((u, v))
    indices = [(0, idx, idx + 1) for idx in range(1, len(coords) - 1)]
    return coords, uvs, indices


def draw_rounded_rect_with_border(
    x: float,
    y: float,
    width: float,
    height: float,
    radius: Union[tuple[Union[str, float], ...], str, float] = (0.0,),
    fill_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    border_color: Optional[Tuple[float, float, float, float]] = None,
    border_thickness: float = 1.0,
):
    if width <= 0 or height <= 0:
        return
    outline = _rounded_rect_outline(x, y, width, height, radius)
    if not outline:
        return
    loop = outline[:-1] if len(outline) > 1 and outline[0] == outline[-1] else outline
    if len(loop) < 3:
        return
    shader = _get_flat_shader_2d()
    indices = [(0, idx, idx + 1) for idx in range(1, len(loop) - 1)]
    batch = batch_for_shader(shader, "TRIS", {"pos": loop}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", fill_color)
    batch.draw(shader)
    if border_color and border_thickness > 0:
        gpu.state.line_width_set(border_thickness)
        if outline[0] == outline[-1]:
            line_points = outline
        else:
            line_points = outline + [outline[0]]
        line_batch = batch_for_shader(shader, "LINE_STRIP", {"pos": line_points})
        shader.uniform_float("color", border_color)
        line_batch.draw(shader)
        gpu.state.line_width_set(1.0)


def draw_strikethrough_line(x_start, x_end, y, color, thickness):
    if x_end <= x_start:
        return
    draw_line2d(x_start, y, x_end, y, thickness, color)


def create_shader_info():
    """Added for Blender 4.5+ in which the gpu.shader.from_builtin("UNIFORM_COLOR") silently stopped working.
    Interestingly for draw_rect_3d UNIFORM_COLOR still works just fine.
    https://github.com/BlenderKit/BlenderKit/issues/1574
    """
    if app.version < (4, 5, 0):
        return bk_logger.warning("Unexpected call to create_shader_info()!")
    shader_info = gpu.types.GPUShaderCreateInfo()
    shader_info.vertex_in(0, "VEC3", "pos")
    shader_info.push_constant("MAT4", "ModelViewProjectionMatrix")
    shader_info.push_constant("VEC4", "color")
    shader_info.fragment_out(0, "VEC4", "fragColor")
    shader_info.vertex_source(
        """
        void main() {
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
        }
    """
    )
    shader_info.fragment_source(
        """
        void main() {
            fragColor = color;
        }
    """
    )
    return shader_info


def draw_lines(vertices, indices, color):
    """Used for drawing 3D bounding box."""
    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    elif app.version < (4, 5, 0):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    else:
        shader_info = create_shader_info()
        shader = gpu.shader.create_from_info(shader_info)

    batch = batch_for_shader(shader, "LINES", {"pos": vertices}, indices=indices)
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_rect_3d(coords, color):
    """Used for drawing 3D rectangle backgrounds."""
    indices = [(0, 1, 2), (2, 3, 0)]
    if app.version < (4, 0, 0):
        shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    else:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _resolve_color_space_mode() -> int:
    """Return shader color conversion mode for the current drawing context.

    area over non-3D means UI overlay, so we need to apply sRGB conversion."""
    area = getattr(bpy.context, "area", None)
    if area is None:
        return 0

    # Blender 5.0+ node editors already expect linear data, so avoid extra conversion there
    node_editor_types = {"NODE_EDITOR", "VIEW_3D"}

    if area.type in node_editor_types:
        return 0

    return 1


def draw_image_runtime(
    x: float,
    y: float,
    width: float,
    height: float,
    image: Union[bpy.types.Image, IMG],
    transparency: Optional[float] = 1.0,
    crop: Tuple[float, float, float, float] = (0, 0, 1, 1),
    batch: Optional[gpu.types.GPUBatch] = None,
    corner_radius: Optional[Union[tuple[Union[str, float], ...], str, float]] = None,
    corner_segments: int = SEGMENTS_DEFAULT,
) -> Optional[gpu.types.GPUBatch]:
    """Draws an image at given location with given size.

    Supports optional rounded corner clipping by supplying ``corner_radius``.

    Returns:
        The batch object if successful, or None if the image is invalid.
    """
    if width <= 0.0 or height <= 0.0 or not image.name or not image.filepath:
        return None

    image_shader = create_image_shader()
    rounded_segments = max(1, int(corner_segments))
    cache_key = (
        image.filepath,
        float(width),
        float(height),
        tuple(float(component) for component in crop),
        repr(corner_radius) if corner_radius is not None else None,
        rounded_segments,
    )

    texture = None
    if batch is None:
        ci = cached_images.get(cache_key)
        if ci is not None:
            batch = ci["batch"]
            image_shader = ci["image_shader"]
            texture = ci["texture"]

    if batch is None:
        coords = None
        uvs = None
        indices = None
        if corner_radius is not None:
            mesh_data = _rounded_rect_mesh(
                0,
                0,
                width,
                height,
                corner_radius,
                crop,
                rounded_segments,
            )
            if mesh_data:
                coords, uvs, indices = mesh_data
        if coords is None or uvs is None or indices is None:
            coords = [(0, 0), (width, 0), (0, height), (width, height)]
            uvs = [
                (crop[0], crop[1]),
                (crop[2], crop[1]),
                (crop[0], crop[3]),
                (crop[2], crop[3]),
            ]
            indices = [(0, 1, 2), (2, 1, 3)]
        batch = batch_for_shader(
            image_shader, "TRIS", {"pos": coords, "texCoord": uvs}, indices=indices
        )
        texture = path_to_gpu_texture(image.filepath)
        cached_images[cache_key] = {
            "batch": batch,
            "image_shader": image_shader,
            "texture": texture,
        }

    if batch is None or image_shader is None:
        return None

    if texture is None:
        texture = path_to_gpu_texture(image.filepath)

    if texture is None:
        return None

    color_space_mode = _resolve_color_space_mode()

    gpu.state.blend_set("ALPHA")

    image_shader.bind()
    image_shader.uniform_sampler("image", texture)

    # may not be available in simple shader
    try:
        # set floats
        image_shader.uniform_float("transparency", transparency)

        # set color space mode
        image_shader.uniform_int("color_space_mode", color_space_mode)
    except Exception:
        pass

    gpu.matrix.push()
    gpu.matrix.translate((x, y))
    batch.draw(image_shader)
    gpu.matrix.pop()

    return batch


def _unpack_scratch_image(img) -> None:
    """Drop any packed data from the scratch image so the next reload re-reads
    the file from disk.

    When "Automatically Pack Resources" (``bpy.data.use_autopack``) is on,
    Blender re-packs the reused scratch image after every ``reload()``. Once it
    is packed, ``reload()`` reads the stale packed bytes instead of the new
    ``filepath``, so every thumbnail would render as the first image loaded.
    Removing the packed data forces a fresh read. Unpacking only edits image
    data (no datablock add/remove), so it avoids the depsgraph relations rebuild
    that loading a fresh image per thumbnail would trigger in big scenes.
    """
    if getattr(img, "packed_file", None) is None:
        return
    with suppress(Exception):
        img.unpack(method="REMOVE")


def _get_scratch_image():
    """Return a single persistent bpy.types.Image reused for all thumbnail
    conversions, avoiding per-thumbnail image add/remove (which forces a
    depsgraph relations rebuild)."""
    global _scratch_image
    if _scratch_image is not None:
        try:
            # access something to verify the datablock is still valid
            _scratch_image.name
            return _scratch_image
        except (ReferenceError, AttributeError):
            _scratch_image = None

    img = bpy.data.images.get(_SCRATCH_IMAGE_NAME)
    if img is None:
        img = bpy.data.images.new(_SCRATCH_IMAGE_NAME, 1, 1)
    img.use_fake_user = False
    try:
        img.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    _scratch_image = img
    return img


def _legacy_path_to_gpu_texture(path: str) -> Optional[gpu.types.GPUTexture]:
    """Original load+remove path, kept as a fallback if the scratch-image
    approach fails for some reason."""
    img = bpy.data.images.load(path, check_existing=False)
    img.gl_load()
    tex = gpu.texture.from_image(img)
    bpy.data.images.remove(img)
    return tex


def _gl_texture_limit_px() -> Optional[int]:
    """Return the System > GL Texture Limit as an integer pixel size, or None
    when there is no limit ('CLAMP_OFF') or it can't be determined."""
    try:
        value = bpy.context.preferences.system.gl_texture_limit
    except Exception:  # noqa: BLE001
        return None
    if not value or value == "CLAMP_OFF":
        return None
    try:
        return int(value.split("_")[1])  # e.g. 'CLAMP_128' -> 128
    except (IndexError, ValueError):
        return None


# Below this GL Texture Limit, gl_load()/from_image() would clamp thumbnails
# enough to look blurry, so we bypass it via a full-resolution pixel upload.
# At 512+ the clamped result is still sharp enough, so we keep the cheap path.
_FULLRES_BYPASS_THRESHOLD = 512


def path_to_gpu_texture(path: str) -> Optional[gpu.types.GPUTexture]:
    """Convert an image file path to a GPU texture.

    Reuses a single persistent scratch image (reloading its filepath) instead
    of adding/removing a fresh bpy.data.images per call. gpu.texture.from_image
    returns an independent snapshot, so the returned texture stays valid after
    the scratch image is reloaded for the next thumbnail.

    This single-image reuse also works when "Automatically Pack Resources" is
    enabled: the scratch image is unpacked before each reload (see
    _unpack_scratch_image), so we never have to fall back to loading a fresh
    bpy.data.images per thumbnail (which would trigger a costly depsgraph
    relations rebuild in big scenes).

    Normally the texture is built with gl_load()/from_image(), which is cheap
    but honours the user's System > GL Texture Limit. When that limit is set
    aggressively low (< 512) and the image is bigger than the limit, we instead
    upload the image's full-resolution pixels into an RGBA16F texture, bypassing
    the clamp so previews stay sharp. Colour matches: image.pixels are already
    linear-decoded, exactly what the draw shader expects.

    Returns:
        The GPU texture if successful, or None if the image is invalid.
    """
    # check if exists and is file [prevent exception for missing files]
    if path in cached_gpu_textures:
        return cached_gpu_textures[path]

    if not os.path.exists(path) or not os.path.isfile(path):
        # do not spam log with warnings, just return None
        return None

    try:
        img = _get_scratch_image()
        if img is None:
            return None
        img.filepath = path
        img.filepath_raw = path
        # The scratch image is created via images.new() => source 'GENERATED'
        # (a 1x1 black image). Without switching it to 'FILE', reload() never
        # reads the file and every thumbnail/icon ends up a 1x1 black texture.
        if img.source != "FILE":
            img.source = "FILE"
        # Drop any auto-packed data first so reload() re-reads `path` from disk.
        _unpack_scratch_image(img)
        img.reload()

        width, height = img.size
        channels = img.channels
        limit = _gl_texture_limit_px()
        needs_bypass = (
            limit is not None
            and limit < _FULLRES_BYPASS_THRESHOLD
            and max(width, height) > limit
            and channels == 4
            and width > 0
            and height > 0
        )

        if needs_bypass:
            # Full-resolution upload that ignores the GL Texture Limit clamp.
            buf = gpu.types.Buffer("FLOAT", width * height * channels)
            img.pixels.foreach_get(buf)
            tex = gpu.types.GPUTexture((width, height), format="SRGB8_A8", data=buf)
        else:
            img.gl_load()
            tex = gpu.texture.from_image(img)
    except Exception as e:
        bk_logger.warning(
            "scratch-image path_to_gpu_texture failed (%s), using legacy load",
            e,
        )
        try:
            tex = _legacy_path_to_gpu_texture(path)
        except Exception:
            return None

    cached_gpu_textures[path] = tex
    return tex


def get_text_size(
    font_id: int = 0, text: str = "", text_size: float = 16, dpi: int = 72
):
    if app.version < (4, 0, 0):
        blf.size(font_id, text_size, dpi)
    else:
        blf.size(font_id, text_size)
    return blf.dimensions(font_id, text)


def draw_text(text, x, y, size, color=(1, 1, 1, 0.5), halign="LEFT", valign="TOP"):
    font_id = 1
    if type(text) != str:
        text = str(text)
    blf.color(font_id, color[0], color[1], color[2], color[3])
    if app.version < (4, 0, 0):
        blf.size(font_id, size, 72)
    else:
        blf.size(font_id, size)
    if halign != "LEFT":
        width, height = blf.dimensions(font_id, text)
        if halign == "RIGHT":
            x -= width
        elif halign == "CENTER":
            x -= width // 2
        if valign == "CENTER":
            y -= height // 2
        # bottom could be here but there's no reason for it
    blf.position(font_id, x, y, 0)

    blf.draw(font_id, text)


def draw_bbox(
    location: Vector,
    rotation: Vector,
    bbox_min: Vector,
    bbox_max: Vector,
    progress: Optional[float] = None,
    color: Tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0),
) -> None:
    """Draw a 3D wireframe bounding box with an optional progress fill."""
    import mathutils

    rot_euler = mathutils.Euler(rotation)

    side_min = Vector(bbox_min)
    side_max = Vector(bbox_max)
    v0 = Vector(side_min)
    v1 = Vector((side_max.x, side_min.y, side_min.z))
    v2 = Vector((side_max.x, side_max.y, side_min.z))
    v3 = Vector((side_min.x, side_max.y, side_min.z))
    v4 = Vector((side_min.x, side_min.y, side_max.z))
    v5 = Vector((side_max.x, side_min.y, side_max.z))
    v6 = Vector((side_max.x, side_max.y, side_max.z))
    v7 = Vector((side_min.x, side_max.y, side_max.z))

    arrow_x = side_min.x + (side_max.x - side_min.x) / 2
    arrow_y = side_min.y - (side_max.x - side_min.x) / 2
    v8 = Vector((arrow_x, arrow_y, side_min.z))

    vertices = [v0, v1, v2, v3, v4, v5, v6, v7, v8]
    for v in vertices:
        v.rotate(rot_euler)
        v += Vector(location)

    lines = [
        [0, 1],
        [1, 2],
        [2, 3],
        [3, 0],
        [4, 5],
        [5, 6],
        [6, 7],
        [7, 4],
        [0, 4],
        [1, 5],
        [2, 6],
        [3, 7],
        [0, 8],
        [1, 8],
    ]
    draw_lines(vertices, lines, color)
    if progress is not None:
        # Draw side fill quads based on progress along +Z of the local bbox
        color = (color[0], color[1], color[2], 0.2)
        progress = progress * 0.01
        vz0 = (v4 - v0) * progress + v0
        vz1 = (v5 - v1) * progress + v1
        vz2 = (v6 - v2) * progress + v2
        vz3 = (v7 - v3) * progress + v3
        rects = (
            (v0, v1, vz1, vz0),
            (v1, v2, vz2, vz1),
            (v2, v3, vz3, vz2),
            (v3, v0, vz0, vz3),
        )
        for r in rects:
            draw_rect_3d(r, color)


def draw_proxor_download(
    location: Vector,
    rotation: Vector,
    proxor_data: dict,
    progress: Optional[float] = None,
    color: Tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0),
) -> None:
    """Draw full proxor (mesh, lines, points) during download.

    Uses ``visibility_input`` to Z-clip the proxor based on *progress*.
    GPU batches are created and discarded each frame (same pattern as
    ``draw_bbox`` / ``draw_lines``).
    """
    from mathutils import Euler

    from .bk_proxor._blender.draw import (
        ProxorLiteDrawBuilder,
        _get_mvp,
        default_draw_context,
        draw_arrow_batch,
    )

    vis = progress if progress is not None else 100
    ctx = default_draw_context(
        mesh_color_mode="CUSTOM",
        line_color_mode="CUSTOM",
        point_color_mode="CUSTOM",
        custom_color=color,
        mesh_shading_mode="FLAT",
        use_gradient=True,
        visibility_input=vis,
        use_outline=True,
        outline_color=(*color[:3], 1.0),
    )

    # Reuse a single builder instance across frames (cheaper than rebuilding).
    builder = draw_proxor_download.__dict__.setdefault(
        "_builder", ProxorLiteDrawBuilder()
    )
    draw_data = builder.build_draw_data(proxor_data, ctx)
    if not draw_data:
        return

    # World-space transform for this proxor.
    mat = Matrix.Translation(Vector(location)) @ Euler(rotation).to_matrix().to_4x4()

    gpu.matrix.push()
    try:
        gpu.matrix.multiply_matrix(mat)

        # Draw mesh first so its depth blocks the outline interior.
        # depth_mask_set(True) writes depth for front faces; the outline pass
        # then uses LESS_EQUAL to clip back faces that are deeper than those
        # front faces (interior), keeping only the rim visible.
        mesh = draw_data.get("mesh")
        if mesh:
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.depth_mask_set(True)
            gpu.state.blend_set("ALPHA")
            gpu.state.face_culling_set("BACK")
            shader = mesh["shader"]
            for batch in mesh.get("batches") or []:
                if batch is not None:
                    batch.draw(shader)
            gpu.state.face_culling_set("NONE")
            gpu.state.depth_mask_set(False)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

        # Draw outline after mesh: interior back faces are at greater Z than the
        # front faces already in the depth buffer, so LESS_EQUAL clips them.
        outline = draw_data.get("outline")
        if outline and outline["shader"] is not None:
            shader = outline["shader"]
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.depth_mask_set(False)
            gpu.state.blend_set("ALPHA")
            gpu.state.face_culling_set("FRONT")
            shader.bind()
            shader.uniform_float("ModelViewProjectionMatrix", _get_mvp())
            shader.uniform_float("outlineWidth", float(ctx.outline_width))
            shader.uniform_float("outlineColor", ctx.outline_color)
            for batch in outline.get("batches") or []:
                if batch is not None:
                    batch.draw(shader)
            gpu.state.face_culling_set("NONE")
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

        # Draw lines
        line = draw_data.get("line")
        if line:
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.depth_mask_set(False)
            gpu.state.blend_set("ALPHA")
            shader = line["shader"]
            shader.uniform_float("lineWidth", 1.0)
            line["batch"].draw(shader)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

        # Draw points
        pts = draw_data.get("points")
        if pts:
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.depth_mask_set(False)
            gpu.state.blend_set("ALPHA")
            shader = pts["shader"]
            gpu.state.point_size_set(3.0)
            shader.bind()
            try:
                shader.uniform_float("pointSize", 3.0)
            except Exception:  # noqa: BLE001
                pass
            if not pts["has_colors"] and pts["color"] is not None:
                shader.uniform_float("color", pts["color"])
            pts["batch"].draw(shader)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

        # Draw floor-level forward arrow (matches the default green bbox arrow)
        arrow = draw_data.get("arrow")
        if arrow:
            draw_arrow_batch(arrow, float(getattr(ctx, "arrow_width", 2.0)))
    finally:
        gpu.matrix.pop()
