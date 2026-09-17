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

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.request
import uuid
import logging

import bpy

bk_logger = logging.getLogger(__name__)

_INT32_MIN = -2_147_483_648
_INT32_MAX = 2_147_483_647


def _sanitize_for_idprops(value):
    """Recursively sanitize a value so it can be stored as a Blender IDProperty.
    Large integers that would overflow int32 are converted to strings.
    """
    if isinstance(value, int):
        if value < _INT32_MIN or value > _INT32_MAX:
            return str(value)
        return value
    if isinstance(value, dict):
        return {k: _sanitize_for_idprops(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_idprops(v) for v in value]
    return value


_ASSET_TYPE_DIRS = {
    "models",
    "materials",
    "hdrs",
    "scenes",
    "brushes",
    "textures",
    "nodegroups",
    "printables",
    "addons",
}


def get_texture_filepath(tex_dir_path, image, resolution="blend", source_path=""):
    if source_path:
        path = source_path
    elif len(image.packed_files) > 0:
        path = image.packed_files[0].filepath
    else:
        path = image.filepath
    # backslashes needs to be replaced because bpy.path.basename(path)
    # does not work on Mac for Windows paths
    path = path or ""
    path = path.replace("\\", "/")
    image_file_name = bpy.path.basename(path)
    if image_file_name == "":
        image_file_name = image.name.split(".")[0]

    # check if there is already an image with same name and thus also assigned path
    # (can happen easily with generated tex sets and more materials)
    file_path_original = os.path.join(tex_dir_path, image_file_name)
    file_path_final = file_path_original

    i = 0
    done = False
    while not done:
        is_solo = True
        for image1 in bpy.data.images:
            if image != image1 and image1.filepath == file_path_final:
                is_solo = False
                fpleft, fpext = os.path.splitext(file_path_original)
                file_path_final = fpleft + str(i).zfill(3) + fpext
                i += 1
        if is_solo:
            done = True

    return file_path_final


def get_resolution_from_file_path(file_path):
    possible_resolutions = {
        "_0_5K_": "resolution_0_5K",
        "_1K_": "resolution_1K",
        "_2K_": "resolution_2K",
        "_4K_": "resolution_4K",
        "_8K_": "resolution_8K",
    }
    for res in possible_resolutions:
        if res in file_path:
            return possible_resolutions[res]
    return "blend"


def _resolve_author_name(asset_data: dict) -> str:
    author = asset_data.get("author") or {}
    full_name = author.get("fullName") or ""
    if full_name:
        return full_name
    first = author.get("firstName") or ""
    last = author.get("lastName") or ""
    return f"{first} {last}".strip()


def _resolve_thumbnail_url(asset_data: dict) -> str:
    for key in ("thumbnailMiddleUrl", "thumbnailSmallUrl", "thumbnailLargeUrl"):
        url = asset_data.get(key)
        if url:
            return str(url)

    for file in asset_data.get("files", []):
        if file.get("fileType") not in (
            "thumbnail",
            "photo_thumbnail",
            "wire_thumbnail",
        ):
            continue
        for key in (
            "thumbnailMiddleUrl",
            "thumbnailSmallUrl",
            "fileThumbnailLarge",
            "fileThumbnail",
        ):
            url = file.get(key)
            if url:
                return str(url)

    return ""


def _library_dir_from_fpath(blend_path: str) -> str:
    """Derive library root from a blend file path by stripping the asset_type folder.

    Expected structure: <library>/<asset_type>/<asset_id>/<file>.blend
    Returns the portion up to <library>. Falls back to two levels above the blend file directory.
    """
    if not blend_path:
        return ""

    norm_path = os.path.abspath(blend_path)
    parts = norm_path.split(os.sep)
    for idx, part in enumerate(parts):
        if part.lower() in _ASSET_TYPE_DIRS and idx > 0:
            return os.sep.join(parts[:idx])

    # Fallback: go two levels up from the blend file directory
    dir_path = os.path.dirname(norm_path)
    return os.path.abspath(os.path.join(dir_path, os.pardir, os.pardir))


def _download_thumbnail(url: str) -> str:
    """Download the thumbnail image from the given URL and save it to the same directory as the current .blend file.

    Returns the file path of the downloaded thumbnail, or an empty string if the download failed.
    """
    if not url:
        return ""
    base_name = "preview.png"
    target_dir = os.path.dirname(bpy.data.filepath)
    if not target_dir:
        return ""
    target_path = os.path.join(target_dir, base_name)
    if os.path.exists(target_path):
        return target_path
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Blendkit")
        req.add_header("Accept", "image/*")
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(target_path, "wb") as handle:
                handle.write(response.read())
        return target_path
    except Exception:
        return ""


def _sanitize_preview_image(preview_path: str) -> str:
    """Some thumbnail images have issues libEx support.

    This function tries to sanitize the image by re-saving it as PNG from the blender.
    """
    if not preview_path or not os.path.exists(preview_path):
        return ""
    base_dir = os.path.dirname(preview_path)
    base_name = os.path.splitext(os.path.basename(preview_path))[0]
    sanitized_path = os.path.join(base_dir, f"{base_name}_clean.png")
    if os.path.exists(sanitized_path):
        return sanitized_path
    img = None
    try:
        img = bpy.data.images.load(preview_path, check_existing=False)
        img.filepath_raw = sanitized_path
        img.file_format = "PNG"
        img.save()
        return sanitized_path
    except Exception:
        return ""
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass


def _op_poll(op_callable, data_block) -> bool:
    """Check if the operator can run in the context of the given data block."""
    try:
        if hasattr(bpy.context, "temp_override"):
            with bpy.context.temp_override(id=data_block):
                return op_callable.poll()
        override = bpy.context.copy()
        override["id"] = data_block
        return op_callable.poll(override)
    except Exception:
        return False


def _op_call(op_callable, data_block, **kwargs):
    """Call the operator in the context of the given data block."""
    if hasattr(bpy.context, "temp_override"):
        with bpy.context.temp_override(id=data_block):
            return op_callable(**kwargs)
    override = bpy.context.copy()
    override["id"] = data_block
    return op_callable(override, **kwargs)


def _apply_asset_preview(data_block, asset_data: dict) -> None:
    """Apply asset preview image to the asset data block.

    It first tries to download the thumbnail from the URL provided in asset data.
    If that fails, it falls back to generating a preview within Blender."""
    if data_block is None:
        return
    print("🖼️  applying asset preview")
    url = _resolve_thumbnail_url(asset_data)
    preview_path = _download_thumbnail(url) if url else ""
    if preview_path:
        clean_path = _sanitize_preview_image(preview_path)
        if clean_path:
            preview_path = clean_path
        try:
            loaded = False
            if _op_poll(bpy.ops.ed.lib_id_load_custom_preview, data_block):
                result = _op_call(
                    bpy.ops.ed.lib_id_load_custom_preview,
                    data_block,
                    filepath=preview_path,
                )
                loaded = "FINISHED" in result
            if loaded:
                print("  Thumbnail preview applied successfully.")
                return
        except Exception as e:
            print(
                "Failed to load thumbnail preview, falling back to generating preview: "
                f"{e}"
            )

    try:
        if _op_poll(bpy.ops.ed.lib_id_generate_preview, data_block):
            _op_call(bpy.ops.ed.lib_id_generate_preview, data_block)
            print("  Generated preview applied successfully.")
    except Exception:
        print("Failed to generate preview, asset will have no preview")
        return


def _write_metadata(data_block, asset_data: dict) -> None:
    """Write asset metadata to the asset data block.

    This includes tags, author, and description."""
    if data_block is None:
        return
    print("📝  writing asset metadata")
    tags = data_block.asset_data.tags
    for t in tags:
        tags.remove(t)
    tags = data_block.asset_data.tags
    for t in asset_data.get("tags", []):
        tags.new(str(t))

    # assign more metadata in tags, so it is searchable in asset browser, and also visible in metadata panel
    other_meta = {}

    if asset_data.get("assetBaseId"):
        other_meta["id"] = asset_data["assetBaseId"]
    if asset_data.get("assetType"):
        other_meta["asset_type"] = asset_data.get("assetType", "")
    if asset_data.get("sourceAppVersion"):
        other_meta["source_app_version"] = asset_data.get("sourceAppVersion", "")

    # further custom meta from dictParameters
    dict_parameters = asset_data.get("dictParameters", {})
    if "category" in dict_parameters:
        other_meta["category"] = dict_parameters["category"]
    if "condition" in dict_parameters:
        other_meta["condition"] = dict_parameters["condition"]
    if "pbrType" in dict_parameters:
        other_meta["pbr_type"] = dict_parameters["pbrType"]
    if "materialStyle" in dict_parameters:
        other_meta["material_style"] = dict_parameters["materialStyle"]
    if "engine" in dict_parameters:
        other_meta["engine"] = dict_parameters["engine"]
    if "animated" in dict_parameters and dict_parameters["animated"]:
        other_meta["animated"] = "yes"
    if "simulation" in dict_parameters and dict_parameters["simulation"]:
        other_meta["simulation"] = "yes"

    description = asset_data.get("description", "")
    author_name = _resolve_author_name(asset_data)

    data_block.asset_data.author = author_name
    other_meta[f"author_name"] = author_name

    data_block.asset_data.description = description
    if hasattr(data_block.asset_data, "copyright"):
        cop = asset_data.get("copyright", "")
        data_block.asset_data.copyright = cop
        other_meta[f"copyright"] = cop
    if hasattr(data_block.asset_data, "license"):
        lic = asset_data.get("license", "")
        data_block.asset_data.license = lic
        other_meta[f"license"] = lic

    if description:
        # we must split by whole words and with max length of 64 chars this includes the key
        words = description.split()
        current_tag = ""
        dp_index = 0
        for word in words:
            if len(current_tag) + len(word) + 1 <= 59:
                current_tag += (" " if current_tag else "") + word
            else:
                if current_tag:
                    other_meta[f"d{dp_index:02}"] = current_tag
                dp_index += 1
                current_tag = word
        if current_tag:
            other_meta[f"d{dp_index:02}"] = current_tag

    # ad additional metadata to tags
    for key, value in other_meta.items():
        tags.new(f"{key}:{value}")


def _sanitize_catalog_segment(segment: str) -> str:
    cleaned = (segment or "").strip()
    cleaned = cleaned.replace(":", "-").replace("/", "-").replace("\\", "-")
    return cleaned or "Uncategorized"


def _resolve_category_segments(asset_data: dict) -> list[str]:
    category_slug = asset_data.get("category") or asset_data.get(
        "dictParameters", {}
    ).get("category")
    if not category_slug:
        return []

    parts = [p for p in str(category_slug).split("-") if p]
    return [_sanitize_catalog_segment(part) for part in parts]


def _resolve_catalog_path_parts(asset_data: dict) -> list[str]:
    asset_type = (asset_data.get("assetType") or "").lower()
    catalog_map = {
        "model": "Models",
        "material": "Materials",
        "hdr": "HDRIs",
        "hdri": "HDRIs",
        "printable": "Printables",
        "scene": "Scenes",
        "brush": "Brushes",
        "texture": "Textures",
        "nodegroup": "Node Groups",
        "addon": "Add-ons",
    }

    parts = []
    top_level = catalog_map.get(asset_type)
    if top_level:
        parts.append(top_level)

    parts.extend(_resolve_category_segments(asset_data))
    bk_logger.debug(
        "Resolved catalog path parts: %s for asset type '%s' and category '%s'",
        parts,
        asset_type,
        asset_data.get("category"),
    )
    return parts


def _ensure_catalog_exists(
    library_path: str, catalog_path: str, catalog_simple_name: str
) -> str:
    """Ensure that an asset catalog exists for the given path.

    Returns the catalog ID if it exists or was created successfully, otherwise returns an empty string.
    """
    # TODO use python exposed API,  (currently only C API is available))
    head = (
        "# This is an Asset Catalog Definition file for Blender.\n"
        "#\n"
        "# Empty lines and lines starting with `#` will be ignored.\n"
        "# The first non-ignored line should be the version indicator.\n"
        '# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"\n'
        "\n"
        "VERSION 1\n"
    )

    # check if file exists in library, if not create it
    # this is needed to assign asset to catalog, otherwise it will be assigned to "unc
    cat_path = os.path.join(library_path, "blender_assets.cats.txt")
    if not os.path.exists(cat_path):
        try:
            with open(cat_path, "w", encoding="utf-8") as f:
                f.write(head)
        except Exception as e:
            traceback.print_exc()
            return ""
    # create file if it does not exists with uuid and name
    # get all catalogs in the file, if there is one with same name, return its uuid
    cats = {}
    # read existing catalogs
    with open(cat_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) != 3:
                continue
            cat_uuid, cat_path_entry, _ = parts
            cats[cat_path_entry] = cat_uuid

    # use regex to found the library name
    if catalog_path in cats:
        return cats[catalog_path]

    # create new catalog entry
    new_uuid = str(uuid.uuid4())
    cats[catalog_path] = new_uuid

    # write new catalog entry to file
    try:
        with open(cat_path, "a", encoding="utf-8") as f:
            f.write(f"{new_uuid}:{catalog_path}:{catalog_simple_name}\n")
        return new_uuid
    except Exception as e:
        traceback.print_exc()
        return ""


def _assign_asset_catalog(
    data_block, asset_data: dict, blend_path: str | None = None
) -> None:
    """Assign the asset to a catalog based on its type and category hierarchy."""
    if data_block is None or data_block.asset_data is None:
        return
    print("📁  assigning asset to catalog")

    if not blend_path:
        print("Asset catalog assignment skipped: blend path missing.")
        return

    library_dir = _library_dir_from_fpath(blend_path)
    library_dir = os.path.abspath(bpy.path.abspath(library_dir))
    print("Resolved library directory: '%s'" % library_dir)
    if not os.path.exists(library_dir):
        try:
            os.makedirs(library_dir, exist_ok=True)
        except Exception:
            print(f"Asset catalog assignment skipped: cannot create '{library_dir}'.")
            return

    path_parts = _resolve_catalog_path_parts(asset_data)
    print(f"Resolved catalog path parts: {path_parts}")
    if not path_parts:
        print(
            "Asset catalog assignment skipped: could not resolve catalog path from asset data."
        )
        return

    catalog_path = "/".join(path_parts)
    catalog_simple_name = path_parts[-1]

    print(
        "Resolved catalog path: '%s' and simple name: '%s' for asset with type '%s'"
        % (
            catalog_path,
            catalog_simple_name,
            asset_data.get("assetType"),
        )
    )
    catalog_id = _ensure_catalog_exists(library_dir, catalog_path, catalog_simple_name)
    if not catalog_id:
        print("Asset catalog assignment skipped: failed to create catalog entry.")
        return
    print(f"Assigning asset to catalog '{catalog_path}' with ID {catalog_id}")
    asset_meta = data_block.asset_data
    if hasattr(asset_meta, "catalog_id"):
        try:
            asset_meta.catalog_id = catalog_id
        except AttributeError:
            print("Asset catalog assignment skipped: catalog_id is read-only.")
    else:
        print(
            "Asset catalog assignment skipped: asset_data does not have catalog_id attribute."
        )


def _match_asset_by_name(datablocks, asset_data):
    """Return the data-block whose name matches the asset name, or None."""
    name = (asset_data.get("name") or "").strip()
    if not name:
        return None
    for db in datablocks:
        if db.name == name:
            return db
    lname = name.lower()
    for db in datablocks:
        if db.name.lower() == lname:
            return db
    return None


def _is_official_nodegroup(ng) -> bool:
    """Official Blender node groups must not be treated as downloadable assets."""
    ad = getattr(ng, "asset_data", None)
    if ad is None:
        return False
    if hasattr(ad, "copyright") and ad.copyright == "Blender Foundation":
        return True
    try:
        return bool(ad.is_property_readonly("author"))
    except Exception:
        return False


def _mark_single_asset(datablocks, asset_data, skip=None, fallback_to_first=False):
    """Mark exactly one data-block from *datablocks* as the scene's asset.

    Materials and node groups have no wrapping collection, so the data-block
    itself must be the asset. A downloaded .blend can contain several of these
    (nested node groups, helper materials), but we want a single asset entry
    that lands in the correct catalog.

    Selection order: a data-block already marked as an asset (upload marks the
    main one) -> a data-block whose name matches the asset name -> optionally
    the first available data-block. Any other asset-marked data-block in
    *datablocks* is cleared so the scene exposes exactly one asset.
    """
    can_mark = bpy.app.version >= (3, 0, 0)
    items = [db for db in datablocks if skip is None or not skip(db)]
    if not items:
        return None

    marked = [db for db in items if getattr(db, "asset_data", None) is not None]
    if marked:
        chosen = _match_asset_by_name(marked, asset_data) or marked[0]
    else:
        chosen = _match_asset_by_name(items, asset_data)
        if chosen is None and fallback_to_first:
            chosen = items[0]

    if chosen is None:
        return None

    if can_mark:
        if getattr(chosen, "asset_data", None) is None:
            chosen.asset_mark()
        # guarantee a single asset per scene: clear any other marks
        for db in items:
            if db is not chosen and getattr(db, "asset_data", None) is not None:
                db.asset_clear()
        # store asset_data so the data-block can be identified as a BlenderKit
        # asset (rating, bookmarking, etc.) after being dragged in
        chosen["asset_data"] = _sanitize_for_idprops(asset_data)

    return chosen


# Datablock collections (on bpy.data) that can hold an asset_mark and that a
# Blendkit asset file might contain. Used to enforce "exactly one asset per
# unpacked .blend".
_MARKABLE_DATA_COLLECTIONS = (
    "objects",
    "collections",
    "materials",
    "node_groups",
    "brushes",
    "worlds",
    "images",
)


def enforce_single_asset_mark(keep):
    """Guarantee that *keep* is the only asset-marked datablock in the file.

    Clears asset marks from every other markable datablock (objects,
    collections, materials, node groups, brushes, worlds, images) and from any
    scene other than *keep*. This makes the unpacked file expose exactly one
    asset, healing historical files that arrive with stray/duplicate marks.
    """
    if bpy.app.version < (3, 0, 0) or keep is None:
        return
    for coll_name in _MARKABLE_DATA_COLLECTIONS:
        data_coll = getattr(bpy.data, coll_name, None)
        if not data_coll:
            continue
        for db in data_coll:
            if db is keep:
                continue
            if getattr(db, "asset_data", None) is not None:
                try:
                    db.asset_clear()
                except Exception as e:
                    print(f"Could not clear stray asset mark on {db!r}: {e}")
    for scene in bpy.data.scenes:
        if scene is keep:
            continue
        if getattr(scene, "asset_data", None) is not None:
            try:
                scene.asset_clear()
            except Exception as e:
                print(f"Could not clear stray asset mark on scene {scene!r}: {e}")


def unpack_asset(data):
    """Unpack asset data into the current Blender file.

    This function handles unpacking textures, writing metadata,
    applying previews, and assigning the asset to a catalog based on its type.
    """
    asset_data = data["asset_data"]

    # assume unpack is true
    unpack = True
    if data.get("prefs", {}).get("unpack_files") is False:
        unpack = False

    # assume write_metadata is true
    write_metadata = True
    if data.get("prefs", {}).get("create_asset_library") is False:
        write_metadata = False

    if unpack:
        print("🗃️  unpacking asset")
        resolution = get_resolution_from_file_path(bpy.data.filepath)

        # TODO - passing resolution inside asset data might not be the best solution
        tex_dir_path = paths.get_texture_directory(asset_data, resolution=resolution)
        tex_dir_abs = bpy.path.abspath(tex_dir_path)
        if not os.path.exists(tex_dir_abs):
            try:
                os.mkdir(tex_dir_abs)
            except Exception as e:
                traceback.print_exc()

        bpy.data.use_autopack = False
        for image in bpy.data.images:
            if image.name == "Render Result":
                continue  # skip rendered images

            # Keep per-packed-file paths (UDIM/sequence) so image.unpack writes all frames/tiles.
            if len(image.packed_files) > 0:
                unpack_paths = []
                for pf in image.packed_files:
                    pf_path = get_texture_filepath(
                        tex_dir_path,
                        image,
                        resolution=resolution,
                        source_path=pf.filepath,
                    )
                    unpack_paths.append(pf_path)
                    pf.filepath = pf_path  # bpy.path.abspath(pf_path)

                image_path = get_texture_filepath(
                    tex_dir_path,
                    image,
                    resolution=resolution,
                    source_path=image.filepath,
                )
                image.filepath = image_path  # bpy.path.abspath(image_path)
                image.filepath_raw = image_path  # bpy.path.abspath(image_path)
                print(
                    f"🖼️  unpacking file: {image.name} - {image.filepath}, "
                    f"{len(unpack_paths)} packed file(s)"
                )
                image.unpack(method="WRITE_ORIGINAL")
            else:
                fp = get_texture_filepath(
                    tex_dir_path,
                    image,
                    resolution=resolution,
                    source_path=image.filepath,
                )
                print(f"🖼️  unpacking file: {image.name} - {image.filepath}, {fp}")
                image.filepath = fp  # bpy.path.abspath(fp)
                image.filepath_raw = fp  # bpy.path.abspath(fp)

    # mark asset browser asset
    print("🏷️  marking asset")
    data_block = None
    if asset_data["assetType"] in ("model", "printable"):
        # Mark the main collection as the asset instead of the root object.
        # When upload_bg.py prepares a model for upload it places ALL objects
        # (including children) as direct members of a single named collection that
        # is a direct child of the scene collection.  If we mark only the root
        # object, Blender's asset browser will import just that one object and
        # its children are left behind, resulting in an empty appearing in the
        # scene.  Marking the collection lets Blender create a proper collection
        # instance that shows every object in the hierarchy.
        #
        # IMPORTANT: never rely on bpy.context.visible_objects here. This script
        # runs in a headless background Blender where the view layer / visibility
        # is unreliable, which historically caused the collection lookup to fail
        # and the root object (locator) to be marked instead — landing the asset
        # in "Unassigned". Instead we trust the upload-time collection mark and
        # fall back to name / membership heuristics that don't need a context.
        can_mark = bpy.app.version >= (3, 0, 0)
        scene_collection = bpy.context.scene.collection
        candidate_collections = list(scene_collection.children)

        # Choose the asset collection, in order of reliability:
        #  1. a collection upload already marked as an asset
        #  2. a collection whose name matches the asset name
        #  3. a collection that actually contains root objects (parent is None)
        #  4. the first child collection
        main_collection = next(
            (
                c
                for c in candidate_collections
                if getattr(c, "asset_data", None) is not None
            ),
            None,
        )
        if main_collection is None:
            main_collection = _match_asset_by_name(candidate_collections, asset_data)
        if main_collection is None:
            main_collection = next(
                (
                    c
                    for c in candidate_collections
                    if any(ob.parent is None for ob in c.objects)
                ),
                None,
            )
        if main_collection is None and candidate_collections:
            main_collection = candidate_collections[0]

        if main_collection is not None:
            # Single asset per scene: clear object-level marks (upload marks the
            # root object too) and any other top-level collection marks brought
            # in from the source file, so only this collection is the asset.
            for ob in bpy.data.objects:
                if getattr(ob, "asset_data", None) is not None:
                    ob.asset_clear()
            for col in candidate_collections:
                if (
                    col is not main_collection
                    and getattr(col, "asset_data", None) is not None
                ):
                    col.asset_clear()
            if can_mark and getattr(main_collection, "asset_data", None) is None:
                main_collection.asset_mark()
            # Store asset_data on the collection so that collection-instance
            # EMPTYs added via Blender's native asset browser can be identified
            # as Blendkit assets (rating, bookmarking, etc.).
            main_collection["asset_data"] = _sanitize_for_idprops(asset_data)
            data_block = main_collection
        else:
            # Fallback: no collection at all – mark a single root object.
            root_objects = [ob for ob in bpy.data.objects if ob.parent is None]
            chosen = _match_asset_by_name(root_objects, asset_data) or (
                root_objects[0] if root_objects else None
            )
            if chosen is not None:
                for ob in bpy.data.objects:
                    if ob is not chosen and getattr(ob, "asset_data", None) is not None:
                        ob.asset_clear()
                if can_mark and getattr(chosen, "asset_data", None) is None:
                    chosen.asset_mark()
                chosen["asset_data"] = _sanitize_for_idprops(asset_data)
                data_block = chosen
    elif asset_data["assetType"] == "material":
        # Materials have no wrapping collection, so mark the single main
        # material as the asset (and clear any extras) so it lands in the
        # Materials catalog instead of leaving stray "Unassigned" entries.
        data_block = _mark_single_asset(
            bpy.data.materials, asset_data, fallback_to_first=True
        )
    elif asset_data["assetType"] == "scene":
        if bpy.app.version >= (3, 0, 0):
            bpy.context.scene.asset_mark()
            data_block = bpy.context.scene
    elif asset_data["assetType"] == "brush":
        # Brushes have no wrapping collection; mark the single main brush.
        # Using _mark_single_asset (instead of requiring a pre-existing mark)
        # lets historical brushes that arrive unmarked be re-marked correctly.
        data_block = _mark_single_asset(
            bpy.data.brushes, asset_data, fallback_to_first=True
        )
    elif asset_data["assetType"] == "nodegroup":
        # Node groups have no wrapping collection either; mark the single main
        # node group (skipping official Blender ones and nested helper groups)
        # so it gets its own Node Groups catalog entry.
        data_block = _mark_single_asset(
            bpy.data.node_groups, asset_data, skip=_is_official_nodegroup
        )

    # Final invariant: exactly one asset is marked in the file. Clear any stray
    # marks of other types (e.g. a marked material inside a model file from a
    # historical buggy upload) so only data_block remains the asset.
    if bpy.app.version >= (3, 0, 0) and data_block is not None:
        enforce_single_asset_mark(data_block)

    if bpy.app.version >= (3, 0, 0) and data_block is not None and write_metadata:
        _write_metadata(data_block, asset_data)
        _apply_asset_preview(data_block, asset_data)
        _assign_asset_catalog(
            data_block,
            asset_data,
            blend_path=data.get("fpath"),
        )

    # if this isn't here, blender crashes when saving file.
    if bpy.app.version >= (3, 0, 0):
        bpy.context.preferences.filepaths.file_preview_type = "NONE"

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, compress=False)
    # now try to delete the .blend1 file
    try:
        os.remove(bpy.data.filepath + "1")
    except Exception as e:
        traceback.print_exc()

    bpy.ops.wm.quit_blender()
    sys.exit()


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

    bpy.ops.preferences.extension_repo_add(  # type: ignore[attr-defined]
        name=parts[1], type="LOCAL"
    )  # Local is enough
    print(f"- Local repository {parts[1]} added")


if __name__ == "__main__":
    # args order must match the order in blenderkit/client/download.go:UnpackAsset()!
    json_path = sys.argv[-2]
    patch_imports(
        sys.argv[-1]
    )  # will be something like: "bl_ext.user_default.blenderkit" or "bl_ext.blenderkit_com.blenderkit", or just "blenderkit" on Blender < 4.2

    from . import paths

    print(json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    unpack_asset(data)
