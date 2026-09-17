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
import os
import sys
import shutil
import zipfile

import addon_utils  # type: ignore[import-not-found]
import bpy


# Datablock collections (on bpy.data) that can hold an asset_mark and that a
# BlenderKit asset file might contain. Used to enforce "exactly one asset per
# uploaded/unpacked .blend".
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
    scene other than *keep*. This makes the file expose exactly one asset, so
    the asset browser never shows stray/duplicate entries from historical data.
    """
    if bpy.app.version < (3, 0, 0):
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


# Map dependencies into a single subdirectory inside the zip and rewrite paths to relative
def _zip_arc_for(p: str, deps_dirs: set[str]) -> str:
    base = os.path.basename(p)
    return os.path.join("caches", base)


def _arc_for_path(p: str, deps_dirs: set[str]) -> str:
    pn = os.path.normpath(bpy.path.abspath(p))
    best_root = ""
    for d in deps_dirs:
        dn = os.path.normpath(d)
        if pn.startswith(dn) and len(dn) > len(best_root):
            best_root = dn
    if best_root:
        rel = os.path.relpath(pn, best_root)
        return os.path.join("caches", os.path.basename(best_root), rel)
    return os.path.join("caches", os.path.basename(pn))


def get_deps_files_and_dirs():
    """Get all dependencies files and directories."""
    deps_files: set[str] = set()
    deps_dirs: set[str] = set()

    # Alembic/USD and similar cache files
    for cf in bpy.data.cache_files:  # type: ignore[attr-defined]
        fp = bpy.path.abspath(cf.filepath)
        if fp and os.path.isfile(fp):
            deps_files.add(fp)

    # Volumes (OpenVDB). Include file; for sequences include containing directory
    for v in getattr(bpy.data, "volumes", []):
        fp = bpy.path.abspath(getattr(v, "filepath", ""))
        if not fp:
            continue
        if os.path.isdir(fp):
            deps_dirs.add(fp)
        elif os.path.isfile(fp):
            # Heuristic: sequence often resides in the directory of the file
            if getattr(v, "is_sequence", False):
                deps_dirs.add(os.path.dirname(fp))
            else:
                deps_files.add(fp)

    # Movie clips
    for clip in bpy.data.movieclips:  # type: ignore[attr-defined]
        fp = bpy.path.abspath(clip.filepath)
        if fp and os.path.isfile(fp):
            deps_files.add(fp)

    # Movie/sequence image textures (e.g. mp4 plugged into an Image Texture node).
    # pack_all() does not pack images with source in {'MOVIE', 'SEQUENCE'}, so we
    # bundle the underlying file(s) into the zip alongside the .blend instead.
    for img in bpy.data.images:
        src = getattr(img, "source", "")
        if src not in ("MOVIE", "SEQUENCE"):
            continue
        fp = bpy.path.abspath(img.filepath)
        if not fp:
            continue
        if src == "MOVIE":
            if os.path.isfile(fp):
                deps_files.add(fp)
        else:  # SEQUENCE: bundle the containing directory
            d = os.path.dirname(fp)
            if d and os.path.isdir(d):
                deps_dirs.add(d)

    # Fluid domain caches (directories)
    for ob in bpy.data.objects:
        for mod in ob.modifiers:
            if (
                getattr(mod, "type", "") == "FLUID"
                and getattr(mod, "fluid_type", "") == "DOMAIN"
            ):
                domain = getattr(mod, "domain_settings", None)
                if domain is not None:
                    cache_dir = getattr(domain, "cache_directory", "")
                    if cache_dir:
                        cdir = bpy.path.abspath(cache_dir)
                        if os.path.isdir(cdir):
                            deps_dirs.add(cdir)

    # Rewrite datablock paths to relative locations
    for cf in bpy.data.cache_files:  # type: ignore[attr-defined]
        fp = bpy.path.abspath(cf.filepath)
        if fp and os.path.isfile(fp):
            cf.filepath = "//" + _arc_for_path(fp, deps_dirs).replace(os.sep, "/")

    for v in getattr(bpy.data, "volumes", []):
        fp = bpy.path.abspath(getattr(v, "filepath", ""))
        if fp:
            if os.path.isdir(fp):
                target = os.path.join("caches", os.path.basename(fp))
            else:
                target = _arc_for_path(fp, deps_dirs)
            v.filepath = "//" + target.replace(os.sep, "/")

    for clip in bpy.data.movieclips:  # type: ignore[attr-defined]
        fp = bpy.path.abspath(clip.filepath)
        if fp and os.path.isfile(fp):
            clip.filepath = "//" + _arc_for_path(fp, deps_dirs).replace(os.sep, "/")

    # Rewrite movie/sequence image filepaths to point at the bundled copy.
    for img in bpy.data.images:
        src = getattr(img, "source", "")
        if src not in ("MOVIE", "SEQUENCE"):
            continue
        fp = bpy.path.abspath(img.filepath)
        if not fp:
            continue
        if src == "MOVIE":
            if os.path.isfile(fp):
                new_path = "//" + _arc_for_path(fp, deps_dirs).replace(os.sep, "/")
                img.filepath = new_path
                try:
                    img.filepath_raw = new_path
                except Exception:
                    pass
        else:  # SEQUENCE
            d = os.path.dirname(fp)
            if d and os.path.isdir(d):
                target = os.path.join(
                    "caches", os.path.basename(d), os.path.basename(fp)
                )
                new_path = "//" + target.replace(os.sep, "/")
                img.filepath = new_path
                try:
                    img.filepath_raw = new_path
                except Exception:
                    pass

    for ob in bpy.data.objects:
        for mod in ob.modifiers:
            if (
                getattr(mod, "type", "") == "FLUID"
                and getattr(mod, "fluid_type", "") == "DOMAIN"
            ):
                domain = getattr(mod, "domain_settings", None)
                if domain is not None:
                    cache_dir = getattr(domain, "cache_directory", "")
                    if cache_dir:
                        domain.cache_directory = "//" + _zip_arc_for(
                            cache_dir, deps_dirs
                        ).replace(os.sep, "/")
    return deps_files, deps_dirs


def _write_collection_asset_metadata(coll, upload_data: dict) -> None:
    """Populate the collection's asset_data from upload_data.

    Mirrors the structured tagging done by unpack_asset_bg._write_metadata so
    the asset browser shows the same information for an in-progress upload as
    for a downloaded asset.
    """
    ad = coll.asset_data
    if ad is None:
        return

    tags = ad.tags
    for t in list(tags):
        tags.remove(t)
    for t in upload_data.get("tags", []):
        tags.new(str(t))

    author_name = upload_data.get("author", "")
    description = upload_data.get("description", "")
    license_ = upload_data.get("license", "")
    copyright_ = upload_data.get("copyright", "")

    ad.author = author_name
    ad.description = description
    if hasattr(ad, "license"):
        ad.license = license_
    if hasattr(ad, "copyright"):
        ad.copyright = copyright_

    # structured key:value tags so the metadata is searchable in the asset browser
    other_meta: dict = {}
    if upload_data.get("assetType"):
        other_meta["asset_type"] = upload_data["assetType"]
    params = upload_data.get("parameters", {}) or {}
    # Downloaded assets store parameters as a list of {parameterType, value}
    # dicts (server format), while a fresh upload uses a plain dict. Normalize
    # the list form so re-uploading a downloaded/modified asset does not fail
    # with "'list' object has no attribute 'get'".
    if isinstance(params, (list, tuple)):
        normalized: dict = {}
        for p in params:
            if isinstance(p, dict) and "parameterType" in p:
                normalized[p["parameterType"]] = p.get("value")
        params = normalized
    if params.get("condition"):
        other_meta["condition"] = params["condition"]
    if params.get("pbrType"):
        other_meta["pbr_type"] = params["pbrType"]
    if params.get("engine"):
        other_meta["engine"] = params["engine"]
    if params.get("style"):
        other_meta["style"] = params["style"]
    if params.get("animated"):
        other_meta["animated"] = "yes"
    if params.get("simulation"):
        other_meta["simulation"] = "yes"
    if author_name:
        other_meta["author_name"] = author_name
    if license_:
        other_meta["license"] = license_
    if copyright_:
        other_meta["copyright"] = copyright_

    if description:
        words = description.split()
        current = ""
        idx = 0
        for word in words:
            if len(current) + len(word) + 1 <= 59:
                current += (" " if current else "") + word
            else:
                if current:
                    other_meta[f"d{idx:02}"] = current
                idx += 1
                current = word
        if current:
            other_meta[f"d{idx:02}"] = current

    for key, value in other_meta.items():
        tags.new(f"{key}:{value}")


def build_model_asset_collection(
    allobs: list, upload_data: dict, thumbnail_path: str = ""
):
    """Create a named collection containing *allobs*, link it under the active
    scene collection, mark it as the single asset for this model/printable
    upload, and populate its asset metadata from *upload_data*.

    Only the collection is the asset — any pre-existing asset_mark on the
    appended objects is cleared so the asset browser shows exactly one entry
    that drags in the full hierarchy. If *thumbnail_path* is given, it is
    loaded as the collection's preview.
    """
    g = bpy.data.collections.new(upload_data["name"])
    for o in allobs:
        g.objects.link(o)
    bpy.context.scene.collection.children.link(g)

    if bpy.app.version < (3, 0, 0):
        return g

    # defensive: drop any pre-existing object asset marks brought in from the
    # source .blend so the upload has a single asset entity (the collection)
    for ob in allobs:
        if getattr(ob, "asset_data", None) is not None:
            try:
                ob.asset_clear()
            except Exception:
                pass

    if g.asset_data is None:
        g.asset_mark()

    _write_collection_asset_metadata(g, upload_data)

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            if _op_poll(bpy.ops.ed.lib_id_load_custom_preview, g):
                _op_call(
                    bpy.ops.ed.lib_id_load_custom_preview,
                    g,
                    filepath=thumbnail_path,
                )
        except Exception as e:
            print(f"Could not load custom preview onto collection asset: {e}")

    return g


def _op_poll(op_callable, data_block) -> bool:
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
    if hasattr(bpy.context, "temp_override"):
        with bpy.context.temp_override(id=data_block):
            return op_callable(**kwargs)
    override = bpy.context.copy()
    override["id"] = data_block
    return op_callable(override, **kwargs)


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
    # args order must match the order in blenderkit/client/main.go:PackBlendFile()!
    BLENDKIT_EXPORT_DATA = sys.argv[-2]
    patch_imports(sys.argv[-1])
    addon_utils.enable(sys.argv[-1])

    from . import (  # we can do relative import because we set the __package__
        append_link,
    )

    try:
        # bg_blender.progress('preparing scene - append data')
        with open(BLENDKIT_EXPORT_DATA, "r", encoding="utf-8") as s:
            data = json.load(s)

        export_data = data["export_data"]
        upload_data = data["upload_data"]

        bpy.data.scenes.new("upload")  # type: ignore[union-attr]
        for s in bpy.data.scenes:  # type: ignore
            if s.name != "upload":
                bpy.data.scenes.remove(s)  # type: ignore

        asset_block = (
            None  # the data-block to mark as asset (collection for model/printable)
        )
        if upload_data["assetType"] in ["model", "printable"]:
            obnames = export_data["models"]
            main_source, allobs = append_link.append_objects(
                file_name=export_data["source_filepath"],
                obnames=obnames,
                rotation=(0, 0, 0),
            )
            g = build_model_asset_collection(
                allobs,
                upload_data,
                thumbnail_path=export_data.get("thumbnail_path", ""),
            )
            asset_block = g  # collection is the asset, not the root object

            try:
                from .bk_proxor._blender import generate as proxor_generate
                from .bk_proxor import prx_format as proxor_prx_format

                proxor_objects = [o for o in allobs if getattr(o, "type", "") == "MESH"]
                if proxor_objects:
                    print(
                        f"Generating proxor in background for {len(proxor_objects)} objects"
                    )
                    payload = proxor_generate.generate_proxor_multi(
                        proxor_objects,
                        include_normals=True,
                    )
                    if payload is not None:
                        prxc_path = os.path.join(
                            export_data["temp_dir"],
                            upload_data["assetBaseId"] + ".prxc",
                        )
                        proxor_prx_format.write_prx(
                            prxc_path,
                            payload,
                            name=proxor_objects[0].name,
                            compress=True,
                            include_mesh=proxor_generate.EXPORT_INCLUDE_MESH,
                            include_lines=proxor_generate.EXPORT_INCLUDE_LINES,
                            include_points=proxor_generate.EXPORT_INCLUDE_POINTS,
                            include_colors=proxor_generate.EXPORT_INCLUDE_COLORS,
                        )
                        print(f"Proxor saved to {prxc_path}")
                    else:
                        print("Proxor generation returned no data")
                else:
                    print("Proxor: no mesh objects found in export list")
            except Exception as e:
                print(f"Proxor generation failed in background: {e}")
        elif upload_data["assetType"] == "scene":
            sname = export_data["scene"]
            main_source = append_link.append_scene(
                file_name=export_data["source_filepath"], scenename=sname
            )
            bpy.data.scenes.remove(bpy.data.scenes["upload"])  # type: ignore
            main_source.name = sname
            asset_block = main_source
        elif upload_data["assetType"] == "material":
            matname = export_data["material"]
            main_source = append_link.append_material(
                file_name=export_data["source_filepath"], matname=matname
            )
            asset_block = main_source
        elif upload_data["assetType"] == "brush":
            brushname = export_data["brush"]
            main_source = append_link.append_brush(
                file_name=export_data["source_filepath"], brushname=brushname
            )
            asset_block = main_source
        elif upload_data["assetType"] == "nodegroup":
            toolname = export_data["nodegroup"]
            main_source, _ = append_link.append_nodegroup(
                file_name=export_data["source_filepath"], nodegroupname=toolname
            )
            asset_block = main_source
        if asset_block is not None and asset_block.asset_data is None:
            asset_block.asset_mark()

        # Enforce the single-asset invariant: only asset_block may be marked.
        # This clears any stray marks brought in from the source .blend so the
        # uploaded file exposes exactly one asset and nothing else.
        if asset_block is not None:
            enforce_single_asset_mark(asset_block)

        try:
            # this needs to be in try statement because blender throws an error if not all textures aren't packed,
            # and we want to ignore that. Blender sometimes wants to pack textures that aren't actually needed
            # and are somehow still in the project.
            bpy.ops.file.pack_all()
        except Exception as e:
            print(f"Exception {type(e)} during pack_all(): {e}")

        # Blender 5.0+ does not pack all tiles of UDIM (source='TILED') images via
        # pack_all(). Iterate and explicitly pack any tiled images whose tiles are not
        # yet fully packed so that every UDIM tile file is included in the upload.
        for image in bpy.data.images:
            if getattr(image, "source", "") != "TILED":
                continue
            n_tiles = len(image.tiles) if hasattr(image, "tiles") else 0
            n_packed = len(image.packed_files)
            print(
                f"UDIM image '{image.name}': {n_tiles} tile(s), "
                f"{n_packed} packed file(s), filepath='{image.filepath}'"
            )
            if n_packed < n_tiles:
                try:
                    image.pack()
                    print(
                        f"  Explicitly packed UDIM image '{image.name}': "
                        f"{len(image.packed_files)} packed file(s)"
                    )
                except Exception as e:
                    print(f"  Could not pack UDIM image '{image.name}': {e}")

        main_source.blenderkit.uploading = False
        # write ID here.
        main_source.blenderkit.asset_base_id = export_data["assetBaseId"]
        main_source.blenderkit.id = export_data["id"]

        fpath = os.path.join(
            export_data["temp_dir"], upload_data["assetBaseId"] + ".blend"
        )

        # if this isn't here, blender crashes.
        if bpy.app.version >= (3, 0, 0):
            bpy.context.preferences.filepaths.file_preview_type = "NONE"

        try:
            # this needs to be in try statement because blender throws an error if not all textures aren't packed,
            # and we want to ignore that. Blender sometimes wants to pack textures that aren't actually needed
            # and are somehow still in the project. The problem might be when file isn't saved for reasons like full disk,
            # but it's much more rare.
            bpy.ops.wm.save_as_mainfile(filepath=fpath, compress=True, copy=False)
        except Exception as e:
            print(f"Exception {type(e)} during save_as_mainfile(): {e}")

        # Rename .prxc to use the server-assigned assetBaseId (it may have been
        # generated with a fallback name when assetBaseId was not yet known).
        prxc_target = os.path.join(
            export_data["temp_dir"], upload_data["assetBaseId"] + ".prxc"
        )
        if not os.path.exists(prxc_target):
            old_prxc = os.path.join(export_data["temp_dir"], "proxor.prxc")
            if os.path.exists(old_prxc):
                os.rename(old_prxc, prxc_target)

        # Remove temp source copy
        try:
            os.remove(export_data["source_filepath"])
        except Exception as e:
            print(f"Exception {type(e)} during source cleanup: {e}")

        # Build a single zip containing the .blend and only dependencies referenced by the file
        try:
            deps_files, deps_dirs = get_deps_files_and_dirs()

            # skip next steps if there are no dependencies
            if not deps_files and not deps_dirs:
                print("No dependencies found, skipping zip creation")
                sys.exit(0)

            # Re-save the .blend to include updated relative paths
            try:
                bpy.ops.wm.save_mainfile(filepath=fpath)
            except Exception as e:
                print(f"Exception {type(e)} during save_mainfile(): {e}")

            # Create one zip with .blend and referenced caches/media
            zip_path = os.path.join(
                export_data["temp_dir"], upload_data["assetBaseId"] + ".zip"
            )
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Put .blend at root with stable name
                zf.write(fpath, os.path.basename(fpath))
                # Add files
                for fp in sorted(deps_files):
                    if os.path.isfile(fp):
                        arc = _arc_for_path(fp, deps_dirs)
                        zf.write(fp, arc)
                # Add directories recursively
                for d in sorted(deps_dirs):
                    if os.path.isdir(d):
                        for r, _, fs in os.walk(d):
                            for fn in fs:
                                sp = os.path.join(r, fn)
                                arc = _arc_for_path(sp, deps_dirs)
                                zf.write(sp, arc)
        except Exception as e:
            print(f"Exception {type(e)} during building asset zip: {e}")
    except Exception as e:
        print(f"Exception {type(e)} in upload_bg.py: {e}")
        sys.exit(1)
