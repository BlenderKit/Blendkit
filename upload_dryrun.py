# Local upload dry-run.
#
# Runs the same scene-preparation pipeline as a real BlenderKit upload (the
# ``upload_bg.py`` background script) on the active model, but skips all
# server-side communication. The result is a .blend file on disk that you can
# open and inspect to verify whether the upload-side scene assembly is correct
# (object hierarchy, instance collections, packed images, etc.).
#
# Trigger from the Python console:
#     bpy.ops.object.blenderkit_upload_dryrun()
# or via Operator Search ("BlenderKit Dry-Run Upload").

import json
import os
import subprocess
import tempfile
import threading
from typing import Any

import bpy

from . import paths, upload, utils


def _addon_module_name() -> str:
    """Return the package name to pass to upload_bg.py for relative imports."""
    return __package__ or "blenderkit"


def _bg_script_path() -> str:
    """Resolve the absolute path to upload_bg.py inside the installed addon."""
    return os.path.join(os.path.dirname(__file__), "upload_bg.py")


def _build_export_data(mainmodel: bpy.types.Object) -> dict[str, Any]:
    """Build the minimal export_data dict required by upload_bg.py model branch."""
    obs = utils.get_hierarchy_with_instances(mainmodel)

    instance_collection_names: list[str] = []
    seen: set[str] = set()
    objects_in_instance_cols: set[str] = set()
    for ob in obs:
        ic = getattr(ob, "instance_collection", None)
        if ic is None:
            continue
        if ic.name not in seen:
            seen.add(ic.name)
            instance_collection_names.append(ic.name)
        try:
            inner = list(ic.all_objects)
        except AttributeError:
            inner = list(ic.objects)
        for io in inner:
            objects_in_instance_cols.add(io.name)

    obnames = [ob.name for ob in obs if ob.name not in objects_in_instance_cols]

    temp_dir = tempfile.mkdtemp(prefix="bk_dryrun_")
    _, ext = os.path.splitext(bpy.data.filepath)
    if not ext:
        ext = ".blend"
    source_filepath = os.path.join(temp_dir, "export_blenderkit" + ext)

    return {
        "models": obnames,
        "instance_collections": instance_collection_names,
        "temp_dir": temp_dir,
        "source_filepath": source_filepath,
        "assetBaseId": "dryrun",
        "id": "dryrun",
        "binary_path": bpy.app.binary_path,
        "debug_value": bpy.app.debug_value,
        "thumbnail_path": "",
    }


def run_dryrun_for_active_model(
    open_result: bool = True,
) -> tuple[bool, str]:
    """Run the upload-bg pipeline on the active model and return (ok, blend_path).

    Steps:
      1. Resolve the active model's root.
      2. Save a copy of the current scene to a temp dir.
      3. Spawn a child Blender that runs ``upload_bg.py`` against that copy.
      4. Optionally open the resulting blend in another Blender window.

    Nothing is uploaded to the server.

    The child process is launched asynchronously: this function returns as soon
    as the child has started. Use the operator wrapper for UI feedback.
    """
    mainmodel = utils.get_active_model()
    if mainmodel is None:
        return False, "No active object."

    export_data = _build_export_data(mainmodel)
    upload_data: dict[str, Any] = {
        "name": mainmodel.name,
        "assetType": "model",
        "assetBaseId": export_data["assetBaseId"],
        "id": export_data["id"],
    }

    # Save the source copy that upload_bg.py will reopen.
    if bpy.app.version >= (3, 0, 0):
        bpy.context.preferences.filepaths.file_preview_type = "NONE"
    # Match the real upload pipeline: project view-layer eye-hide / layer
    # collection exclude state onto datablock-level hide_viewport so the
    # saved blend preserves visibility after append in the bg script.
    _vis = upload._snapshot_and_project_visibility(bpy.context)
    try:
        bpy.ops.wm.save_as_mainfile(
            filepath=export_data["source_filepath"], compress=False, copy=True
        )
    finally:
        upload._restore_visibility(_vis)

    # Write the JSON expected by upload_bg.py.
    json_path = os.path.join(export_data["temp_dir"], "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"export_data": export_data, "upload_data": upload_data}, f)

    # Spawn a fresh Blender to run upload_bg.py with the same args layout the
    # Go client uses: <json_path> <addon_module_name>.
    bg_script = _bg_script_path()
    cmd = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "-noaudio",
        "--python-exit-code",
        "1",
        "--python",
        bg_script,
        "--",
        json_path,
        _addon_module_name(),
    ]
    print("[bk-dryrun] Running:", " ".join(cmd))

    out_blend = os.path.join(
        export_data["temp_dir"], upload_data["assetBaseId"] + ".blend"
    )

    def worker():
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except Exception as e:
            print(f"[bk-dryrun] Failed to start subprocess: {e}")
            return
        print("[bk-dryrun] === stdout ===")
        print(proc.stdout)
        if proc.stderr:
            print("[bk-dryrun] === stderr ===")
            print(proc.stderr)
        if proc.returncode != 0:
            print(f"[bk-dryrun] upload_bg.py failed (exit {proc.returncode}).")
            return
        if not os.path.exists(out_blend):
            print(f"[bk-dryrun] Output blend not found: {out_blend}")
            return
        print(f"[bk-dryrun] OK. Output: {out_blend}")
        if open_result:
            try:
                subprocess.Popen([bpy.app.binary_path, out_blend])
            except Exception as e:
                print(f"[bk-dryrun] Could not open result in new Blender: {e}")

    t = threading.Thread(target=worker, name="bk-dryrun", daemon=True)
    t.start()

    return True, out_blend


class OBJECT_OT_blenderkit_upload_dryrun(bpy.types.Operator):
    """Run the BlenderKit upload preprocessing locally, without uploading.

    Saves a copy of the scene, runs upload_bg.py against it in a child Blender,
    and (optionally) opens the resulting .blend in another Blender window so
    you can inspect the upload-time scene assembly.
    """

    bl_idname = "object.blenderkit_upload_dryrun"
    bl_label = "BlenderKit Dry-Run Upload"
    bl_options = {"REGISTER"}

    open_result: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Open Result",
        description="Open the produced .blend in a new Blender window",
        default=True,
    )

    def execute(self, context):
        ok, msg = run_dryrun_for_active_model(open_result=self.open_result)
        if ok:
            self.report(
                {"INFO"},
                "Dry-run started in background. Result will open in a new "
                "Blender window when ready. See system console for progress.",
            )
            context.window_manager["blenderkit_dryrun_path"] = msg
            return {"FINISHED"}
        self.report({"ERROR"}, msg)
        return {"CANCELLED"}


def register():
    bpy.utils.register_class(OBJECT_OT_blenderkit_upload_dryrun)


def unregister():
    bpy.utils.unregister_class(OBJECT_OT_blenderkit_upload_dryrun)
