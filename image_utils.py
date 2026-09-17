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
from dataclasses import dataclass
from functools import lru_cache
import os
import time

import bpy


bk_logger = logging.getLogger(__name__)


@dataclass
class IMG:
    name: str
    filepath: str

    def gl_load(self):
        """Imitates bpy.types.Image.gl_load() behavior."""
        return None


def get_orig_render_settings():
    rs = bpy.context.scene.render
    ims = rs.image_settings

    vs = bpy.context.scene.view_settings

    orig_settings = {
        "file_format": ims.file_format,
        "quality": ims.quality,
        "color_mode": ims.color_mode,
        "compression": ims.compression,
        "exr_codec": ims.exr_codec,
        "view_transform": vs.view_transform,
    }
    return orig_settings


def set_orig_render_settings(orig_settings):
    rs = bpy.context.scene.render
    ims = rs.image_settings
    vs = bpy.context.scene.view_settings

    ims.file_format = orig_settings["file_format"]
    ims.quality = orig_settings["quality"]
    ims.color_mode = orig_settings["color_mode"]
    ims.compression = orig_settings["compression"]
    ims.exr_codec = orig_settings["exr_codec"]

    vs.view_transform = orig_settings["view_transform"]


def img_save_as(
    img,
    filepath="//",
    file_format="JPEG",
    quality=90,
    color_mode="RGB",
    compression=15,
    view_transform="Raw",
    exr_codec="DWAA",
):
    """Uses Blender 'save render' to save images - BLender isn't really able so save images with other methods correctly."""

    ors = get_orig_render_settings()

    rs = bpy.context.scene.render
    vs = bpy.context.scene.view_settings

    ims = rs.image_settings
    ims.file_format = file_format
    ims.quality = quality
    ims.color_mode = color_mode
    ims.compression = compression
    ims.exr_codec = exr_codec
    vs.view_transform = view_transform

    img.save_render(filepath=bpy.path.abspath(filepath), scene=bpy.context.scene)

    set_orig_render_settings(ors)


def set_colorspace(img, colorspace: str = ""):
    """sets image colorspace, but does so in a try statement, because some people might actually replace the default
    colorspace settings, and it literally can't be guessed what these people use, even if it will mostly be the filmic addon.
    """
    try:
        if colorspace == "":
            colorspace = guess_colorspace()

        if hasattr(img, "colorspace_settings") and colorspace:
            if colorspace == "Non-Color":
                img.colorspace_settings.is_data = True
            else:
                img.colorspace_settings.name = colorspace

    except Exception:
        bk_logger.exception("Colorspace '%s' not found: ", colorspace)


@lru_cache(maxsize=1)
def list_available_image_colorspaces():
    """Lists available color spaces in blender by creating a temporary image if needed.

    Returns:
        List of color space names.
    """
    # Check if there are existing images
    temp_image = None
    if bpy.data.images:
        img = bpy.data.images[0]
    else:
        # Create temporary image
        temp_image = bpy.data.images.new(
            "TempImage_ForColorSpaceList", width=1, height=1
        )
        img = temp_image

    # Get available color spaces
    color_spaces = [
        cs.identifier
        for cs in img.colorspace_settings.bl_rna.properties["name"].enum_items
    ]

    # Clean up temporary image if created
    if temp_image:
        bpy.data.images.remove(temp_image)

    return color_spaces


def guess_colorspace() -> str:
    """Tries to guess the colorspace from the current display device and available color spaces."""
    display_device = bpy.context.scene.display_settings.display_device
    if display_device == "sRGB":
        return "sRGB"
    if display_device == "ACES":
        return "aces"

    # detect available color spaces on image data
    all_clr_spaces = list_available_image_colorspaces()

    # try to match display device with color space
    for cs in all_clr_spaces:
        if display_device.lower() in cs.lower():
            return cs

    # fallback
    if "sRGB" in all_clr_spaces:
        return "sRGB"
    return ""


def analyze_image_is_true_hdr(image):
    import numpy

    scene = bpy.context.scene
    ui_props = bpy.context.window_manager.blenderkitUI
    size = image.size
    imageWidth = size[0]
    imageHeight = size[1]
    tempBuffer = numpy.empty(imageWidth * imageHeight * 4, dtype=numpy.float32)
    image.pixels.foreach_get(tempBuffer)
    image.blenderkit.true_hdr = bool(numpy.amax(tempBuffer) > 1.05)


def _save_hdr_thumbnail_image(
    hdr_image,
    output_path: str,
    max_thumbnail_size: int,
    use_custom_tone: bool,
    exposure: float,
    gamma: float,
):
    import numpy

    image_width, image_height = hdr_image.size
    ratio = image_width / image_height
    thumbnail_width = min(image_width, max_thumbnail_size)
    thumbnail_height = min(image_height, int(max_thumbnail_size / ratio))

    # Read once so we can both detect HDR and safely create a scaled temp image.
    pixel_count = image_width * image_height
    pixel_buffer = numpy.empty(pixel_count * 4, dtype=numpy.float32)
    hdr_image.pixels.foreach_get(pixel_buffer)
    hdr_image.blenderkit.true_hdr = bool(numpy.amax(pixel_buffer) > 1.05)

    source_image = hdr_image
    temp_image = None

    if thumbnail_width < image_width:
        temp_name = f"{hdr_image.name}_thumb_tmp"
        temp_image = bpy.data.images.new(
            temp_name,
            width=image_width,
            height=image_height,
            alpha=False,
            float_buffer=True,
        )
        temp_image.pixels.foreach_set(pixel_buffer)
        temp_image.scale(thumbnail_width, thumbnail_height)
        source_image = temp_image

    try:
        scene = bpy.context.scene
        view_settings = scene.view_settings
        orig_exposure = view_settings.exposure
        orig_gamma = view_settings.gamma

        try:
            if use_custom_tone:
                view_settings.exposure = exposure
                view_settings.gamma = gamma

            img_save_as(
                source_image,
                filepath=output_path,
                view_transform="Standard",
            )
        finally:
            view_settings.exposure = orig_exposure
            view_settings.gamma = orig_gamma
    finally:
        if temp_image is not None:
            bpy.data.images.remove(temp_image)


def generate_hdr_thumbnail_preview(
    hdr_image,
    use_custom_tone: bool,
    exposure: float,
    gamma: float,
    max_preview_size: int = 256,
) -> str:
    from . import paths

    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_", ".") else "_" for c in hdr_image.name
    )
    preview_dir = paths.get_temp_dir(subdir="hdr_thumbnail_preview")
    preview_path = os.path.join(preview_dir, f"{safe_name}_preview.jpg")

    _save_hdr_thumbnail_image(
        hdr_image=hdr_image,
        output_path=preview_path,
        max_thumbnail_size=max_preview_size,
        use_custom_tone=use_custom_tone,
        exposure=exposure,
        gamma=gamma,
    )
    return preview_path


def generate_hdr_thumbnail():
    ui_props = bpy.context.window_manager.blenderkitUI
    hdr_image = (
        ui_props.hdr_upload_image
    )  # bpy.data.images.get(ui_props.hdr_upload_image)

    base, ext = os.path.splitext(hdr_image.filepath)
    thumb_path = base + ".jpg"
    _save_hdr_thumbnail_image(
        hdr_image=hdr_image,
        output_path=thumb_path,
        max_thumbnail_size=2048,
        use_custom_tone=ui_props.hdr_use_custom_thumbnail_tone,
        exposure=ui_props.hdr_thumbnail_exposure,
        gamma=ui_props.hdr_thumbnail_gamma,
    )


def find_color_mode(image):
    if not isinstance(image, bpy.types.Image):
        raise (TypeError)
    else:
        depth_mapping = {
            8: "BW",
            24: "RGB",
            32: "RGBA",  # can also be bw.. but image.channels doesn't work.
            96: "RGB",
            128: "RGBA",
        }
        return depth_mapping.get(image.depth, "RGB")


def find_image_depth(image):
    if not isinstance(image, bpy.types.Image):
        raise (TypeError)
    else:
        depth_mapping = {
            8: "8",
            24: "8",
            32: "8",  # can also be bw.. but image.channels doesn't work.
            96: "16",
            128: "16",
        }
        return depth_mapping.get(image.depth, "8")


def can_erase_alpha(na):
    alpha = na[3::4]
    alpha_sum = alpha.sum()
    if alpha_sum == alpha.size:
        bk_logger.info("image can have alpha erased")
    return alpha_sum == alpha.size


def is_image_black(na):
    r = na[::4]
    g = na[1::4]
    b = na[2::4]

    rgbsum = r.sum() + g.sum() + b.sum()

    if rgbsum == 0:
        bk_logger.info("image can have alpha channel dropped")
    return rgbsum == 0


def is_image_bw(na):
    r = na[::4]
    g = na[1::4]
    b = na[2::4]

    rg_equal = r == g
    gb_equal = g == b
    rgbequal = rg_equal.all() and gb_equal.all()
    if rgbequal:
        bk_logger.info("image is black and white, can have channels reduced")

    return rgbequal


def numpytoimage(a, iname, width=0, height=0, channels=3):
    t = time.time()
    foundimage = False

    for image in bpy.data.images:
        if (
            image.name[: len(iname)] == iname
            and image.size[0] == a.shape[0]
            and image.size[1] == a.shape[1]
        ):
            i = image
            foundimage = True
    if not foundimage:
        if channels == 4:
            bpy.ops.image.new(
                name=iname,
                width=width,
                height=height,
                color=(0, 0, 0, 1),
                alpha=True,
                generated_type="BLANK",
                float=True,
            )
        if channels == 3:
            bpy.ops.image.new(
                name=iname,
                width=width,
                height=height,
                color=(0, 0, 0),
                alpha=False,
                generated_type="BLANK",
                float=True,
            )

    i = None

    for image in bpy.data.images:
        if (
            image.name[: len(iname)] == iname
            and image.size[0] == width
            and image.size[1] == height
        ):
            i = image
    if i is None:
        i = bpy.data.images.new(
            iname,
            width,
            height,
            alpha=False,
            float_buffer=False,
            stereo3d=False,
            is_data=False,
            tiled=False,
        )

    # dropping this re-shaping code -  just doing flat array for speed and simplicity
    #    d = a.shape[0] * a.shape[1]
    #    a = a.swapaxes(0, 1)
    #    a = a.reshape(d)
    #    a = a.repeat(channels)
    #    a[3::4] = 1
    i.pixels.foreach_set(a)  # this gives big speedup!
    bk_logger.info("\ntime " + str(time.time() - t))
    return i


def imagetonumpy_flat(i):
    t = time.time()

    import numpy

    width = i.size[0]
    height = i.size[1]

    size = width * height * i.channels
    na = numpy.empty(size, numpy.float32)
    i.pixels.foreach_get(na)

    # dropping this re-shaping code -  just doing flat array for speed and simplicity
    #    na = na[::4]
    #    na = na.reshape(height, width, i.channels)
    #    na = na.swapaxnes(0, 1)

    return na


def imagetonumpy(i):
    t = time.time()

    import numpy as np

    width = i.size[0]
    height = i.size[1]

    size = width * height * i.channels
    na = np.empty(size, np.float32)
    i.pixels.foreach_get(na)

    # dropping this re-shaping code -  just doing flat array for speed and simplicity
    # na = na[::4]
    na = na.reshape(height, width, i.channels)
    na = na.swapaxes(0, 1)

    return na


def downscale(i):
    minsize = 128

    sx, sy = i.size[:]
    sx = round(sx / 2)
    sy = round(sy / 2)
    if sx > minsize and sy > minsize:
        i.scale(sx, sy)


def get_rgb_mean(i):
    """checks if normal map values are ok."""
    import numpy

    na = imagetonumpy_flat(i)

    r = na[::4]
    g = na[1::4]
    b = na[2::4]

    rmean = r.mean()
    gmean = g.mean()
    bmean = b.mean()

    # rmedian = numpy.median(r)
    # gmedian = numpy.median(g)
    # bmedian = numpy.median(b)

    #    return(rmedian,gmedian, bmedian)
    return (rmean, gmean, bmean)


def check_nmap_mean_ok(i):
    """checks if normal map values are in standard range."""

    rmean, gmean, bmean = get_rgb_mean(i)

    # we could/should also check blue, but some ogl substance exports have 0-1, while 90% nmaps have 0.5 - 1.
    nmap_ok = 0.45 < rmean < 0.55 and 0.45 < gmean < 0.55

    return nmap_ok


def check_nmap_ogl_vs_dx(i, mask=None, generated_test_images=False):
    """
    checks if normal map is directX or OpenGL.
    Returns - String value - DirectX and OpenGL
    """
    import numpy

    width = i.size[0]
    height = i.size[1]

    rmean, gmean, bmean = get_rgb_mean(i)

    na = imagetonumpy(i)

    if mask:
        mask = imagetonumpy(mask)

    red_x_comparison = numpy.zeros((width, height), numpy.float32)
    green_y_comparison = numpy.zeros((width, height), numpy.float32)

    if generated_test_images:
        red_x_comparison_img = numpy.empty(
            (width, height, 4), numpy.float32
        )  # images for debugging purposes
        green_y_comparison_img = numpy.empty(
            (width, height, 4), numpy.float32
        )  # images for debugging purposes

    ogl = numpy.zeros((width, height), numpy.float32)
    dx = numpy.zeros((width, height), numpy.float32)

    if generated_test_images:
        ogl_img = numpy.empty(
            (width, height, 4), numpy.float32
        )  # images for debugging purposes
        dx_img = numpy.empty(
            (width, height, 4), numpy.float32
        )  # images for debugging purposes

    for y in range(0, height):
        for x in range(0, width):
            # try to mask with UV mask image
            if mask is None or mask[x, y, 3] > 0:
                last_height_x = ogl[max(x - 1, 0), min(y, height - 1)]
                last_height_y = ogl[max(x, 0), min(y - 1, height - 1)]

                diff_x = (na[x, y, 0] - rmean) / ((na[x, y, 2] - 0.5))
                diff_y = (na[x, y, 1] - gmean) / ((na[x, y, 2] - 0.5))
                calc_height = (last_height_x + last_height_y) - diff_x - diff_y
                calc_height = calc_height / 2
                ogl[x, y] = calc_height
                if generated_test_images:
                    rgb = calc_height * 0.1 + 0.5
                    ogl_img[x, y] = [rgb, rgb, rgb, 1]

                # green channel
                last_height_x = dx[max(x - 1, 0), min(y, height - 1)]
                last_height_y = dx[max(x, 0), min(y - 1, height - 1)]

                diff_x = (na[x, y, 0] - rmean) / ((na[x, y, 2] - 0.5))
                diff_y = (na[x, y, 1] - gmean) / ((na[x, y, 2] - 0.5))
                calc_height = (last_height_x + last_height_y) - diff_x + diff_y
                calc_height = calc_height / 2
                dx[x, y] = calc_height
                if generated_test_images:
                    rgb = calc_height * 0.1 + 0.5
                    dx_img[x, y] = [rgb, rgb, rgb, 1]

    ogl_std = ogl.std()
    dx_std = dx.std()

    bk_logger.info("OpenGL std: %s, DirectX std: %s", ogl_std, dx_std)
    bk_logger.info("Image name: %s", i.name)
    #    if abs(mean_ogl) > abs(mean_dx):
    if abs(ogl_std) > abs(dx_std):
        bk_logger.info("this is probably a DirectX texture")
    else:
        bk_logger.info("this is probably an OpenGL texture")

    if generated_test_images:
        # red_x_comparison_img = red_x_comparison_img.swapaxes(0,1)
        # red_x_comparison_img = red_x_comparison_img.flatten()
        #
        # green_y_comparison_img = green_y_comparison_img.swapaxes(0,1)
        # green_y_comparison_img = green_y_comparison_img.flatten()
        #
        # numpytoimage(red_x_comparison_img, 'red_' + i.name, width=width, height=height, channels=1)
        # numpytoimage(green_y_comparison_img, 'green_' + i.name, width=width, height=height, channels=1)

        ogl_img = ogl_img.swapaxes(0, 1)
        ogl_img = ogl_img.flatten()

        dx_img = dx_img.swapaxes(0, 1)
        dx_img = dx_img.flatten()

        numpytoimage(ogl_img, "OpenGL", width=width, height=height, channels=1)
        numpytoimage(dx_img, "DirectX", width=width, height=height, channels=1)

    if abs(ogl_std) > abs(dx_std):
        return "DirectX"
    return "OpenGL"


def make_possible_reductions_on_image(
    teximage, input_filepath, do_reductions=False, do_downscale=False
):
    """checks the image and saves it to drive with possibly reduced channels.
    Also can remove the image from the asset if the image is pure black
    - it finds it's usages and replaces the inputs where the image is used
    with zero/black color.
    currently implemented file type conversions:
    PNG->JPG
    """
    colorspace = teximage.colorspace_settings.name
    teximage.colorspace_settings.name = "Non-Color"
    # teximage.colorspace_settings.name = 'sRGB' color correction mambo jambo.

    JPEG_QUALITY = 90
    # is_image_black(na)
    # is_image_bw(na)

    rs = bpy.context.scene.render
    ims = rs.image_settings

    orig_file_format = ims.file_format
    orig_quality = ims.quality
    orig_color_mode = ims.color_mode
    orig_compression = ims.compression
    orig_depth = ims.color_depth

    # if is_image_black(na):
    #     # just erase the image from the asset here, no need to store black images.
    #     pass;

    # fp = teximage.filepath

    # setup  image depth, 8 or 16 bit.
    # this should normally divide depth with number of channels, but blender always states that number of channels is 4, even if there are only 3

    bk_logger.info("Image name: %s", teximage.name)
    bk_logger.info("Image depth: %s", teximage.depth)
    bk_logger.info("Image channels: %s", teximage.channels)

    bpy.context.scene.display_settings.display_device = "None"

    image_depth = find_image_depth(teximage)

    ims.color_mode = find_color_mode(teximage)
    # image_depth = str(max(min(int(teximage.depth / 3), 16), 8))
    bk_logger.info("resulting depth set to: %s", image_depth)

    fp = input_filepath
    if do_reductions:
        na = imagetonumpy_flat(teximage)

        if can_erase_alpha(na):
            bk_logger.info("Image file format: %s", teximage.file_format)
            if teximage.file_format == "PNG":
                bk_logger.info("Changing type of image to JPG")
                base, ext = os.path.splitext(fp)
                teximage["original_extension"] = ext

                fp = fp.replace(".png", ".jpg")
                fp = fp.replace(".PNG", ".jpg")

                teximage.name = teximage.name.replace(".png", ".jpg")
                teximage.name = teximage.name.replace(".PNG", ".jpg")

                teximage.file_format = "JPEG"
                ims.quality = JPEG_QUALITY
                ims.color_mode = "RGB"
                image_depth = "8"

            if is_image_bw(na):
                ims.color_mode = "BW"

    ims.file_format = teximage.file_format
    ims.color_depth = image_depth

    # all pngs with max compression
    if ims.file_format == "PNG":
        ims.compression = 100
    # all jpgs brought to reasonable quality
    if ims.file_format == "JPG":
        ims.quality = JPEG_QUALITY

    if do_downscale:
        downscale(teximage)

    # it's actually very important not to try to change the image filepath and packed file filepath before saving,
    # blender tries to re-pack the image after writing to image.packed_image.filepath and reverts any changes.
    teximage.save_render(filepath=bpy.path.abspath(fp), scene=bpy.context.scene)
    if len(teximage.packed_files) > 0:
        teximage.unpack(method="REMOVE")
    teximage.filepath = fp
    teximage.filepath_raw = fp
    teximage.reload()

    teximage.colorspace_settings.name = colorspace

    ims.file_format = orig_file_format
    ims.quality = orig_quality
    ims.color_mode = orig_color_mode
    ims.compression = orig_compression
    ims.color_depth = orig_depth
