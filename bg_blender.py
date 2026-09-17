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
import re
import sys
import threading

import bpy
from bpy.props import EnumProperty

from . import utils, reports


def _safe_eval_target(eval_path: str, name: str):
    """Try resolving eval_path; fallback to bpy.data.objects by name; return None if missing."""
    try:
        return eval(eval_path)
    except Exception:
        return bpy.data.objects.get(name) if name else None


bk_logger = logging.getLogger(__name__)
bg_processes = []


class ThreadCom:  # object passed to threads to read background process stdout info
    """Object to pass data between thread and"""

    def __init__(
        self,
        eval_path_computing,
        eval_path_state,
        eval_path,
        process_type,
        proc,
        location=None,
        name="",
    ):
        # self.obname=ob.name
        self.name = name
        self.eval_path_computing = eval_path_computing  # property that gets written to.
        self.eval_path_state = eval_path_state  # property that gets written to.
        self.eval_path = eval_path  # property that gets written to.
        self.process_type = process_type
        self.outtext = ""
        self.proc = proc
        self.lasttext = ""
        self.message = ""  # the message to be sent.
        self.progress = 0.0
        self.location = location
        self.error = False
        self.log = ""


def threadread(tcom: ThreadCom):
    """Reads stdout of background process.

    This thread basically waits for a stdout line to come in,
    fills the data, dies."""
    found = False
    while not found:
        if tcom.proc.poll() is not None:
            return  # process terminated
        inline = tcom.proc.stdout.readline()
        inline = inline.decode("utf-8")
        # ignore empty lines
        if inline.strip() == "":
            continue
        # Background Blender already formats logs; strip a leading emoji/prefix to avoid double branding.
        line = inline.strip()
        line = re.sub(r"^(?:[🐞ℹ️⚠️❌🔥]\s*)?blendkit:\s*", "", line, flags=re.IGNORECASE)
        bk_logger.info(line)
        progress = re.findall(r"progress\{(.*?)\}", inline)
        if len(progress) > 0:
            if type(progress[0]) == int or type(progress[0]) == float:
                tcom.progress = progress
                return

            tcom.outtext = f"{progress[0]}"
            return

        s = inline.find("progress{")
        if s > -1:
            e = inline.find("}")
            tcom.outtext = inline[s + 9 : e]
            found = True
            if tcom.outtext.find("%") > -1:
                tcom.progress = float(re.findall(r"\d+\.\d+|\d+", tcom.outtext)[0])
            return
        if s == -1:
            s = inline.find("Remaining")
            if s > -1:
                # e=inline.find('}')
                tcom.outtext = inline[s : s + 18]
                found = True
                return


def progress(text, n=None):
    """function for reporting during the script, works for background operations in the header."""
    # for i in range(n+1):
    # sys.stdout.flush()
    text = str(text)
    if n is None:
        n = ""
    else:
        n = " " + " " + str(int(n * 1000) / 1000) + "% "

    try:
        output = "progress{%s%s}\n" % (text, n)
        sys.stdout.write(output)
        sys.stdout.flush()
    except Exception as e:
        bk_logger.exception(
            "background progress reporting race condition", exc_info=False
        )
        bk_logger.error(f"Error details: {e}")


# @bpy.app.handlers.persistent
def bg_update():
    """monitoring of background process"""
    text = ""
    # utils.p('timer search')
    # utils.p('start bg_blender timer bg_update')
    global bg_processes
    if len(bg_processes) == 0:
        # utils.p('end bg_blender timer bg_update')

        return 2
    # cleanup dead processes first
    remove_processes = []
    for p in bg_processes:
        if p[1].proc.poll() is not None:
            remove_processes.append(p)

    for p in remove_processes:
        bk_logger.info(str(p[1].outtext))
        estring = p[1].eval_path_computing + " = False"
        target = _safe_eval_target(p[1].eval_path, p[1].name)
        if target is not None:
            try:
                exec(estring)
            except Exception as e:
                bk_logger.exception(
                    "Exception executing eval_path_computing.", exc_info=False
                )
                bk_logger.error(f"Error details: {e}")
        bg_processes.remove(p)

    # Parse process output
    for p in bg_processes:
        # proc=p[1].proc
        readthread = p[0]
        tcom = p[1]
        if not readthread.is_alive():
            readthread.join()
            # readthread.
            estring = None
            if tcom.error:
                estring = tcom.eval_path_computing + " = False"
            tcom.lasttext = tcom.outtext
            if tcom.outtext != "":
                tcom.outtext = ""
                text = tcom.lasttext.replace("'", "")  # noqa: F841 needed in exec()
                estring = tcom.eval_path_state + " = text"

            if "finished successfully" in tcom.lasttext:
                bk_logger.info(str(tcom.lasttext))
                bg_processes.remove(p)
                estring = tcom.eval_path_computing + " = False"
            else:
                readthread = threading.Thread(
                    target=threadread, args=([tcom]), daemon=True
                )
                readthread.start()
                p[0] = readthread
            if estring:
                target = _safe_eval_target(tcom.eval_path, tcom.name)
                if target is not None:
                    try:
                        exec(estring)
                    except Exception as e:
                        bk_logger.exception(
                            "Exception while reading from background process.",
                            exc_info=False,
                        )
                        bk_logger.error(f"Error details: {e}")
                else:
                    bk_logger.debug(
                        "Skipping state update; target missing for %s", tcom.name
                    )

    # if len(bg_processes) == 0:
    #     bpy.app.timers.unregister(bg_update)
    if len(bg_processes) > 0:
        # utils.p('end bg_blender timer bg_update')

        return 0.3
    # utils.p('end bg_blender timer bg_update')

    return 1.0


process_types = (
    ("UPLOAD", "Upload", ""),
    ("THUMBNAILER", "Thumbnailer", ""),
)

process_sources = (
    ("MODEL", "Model", "set of objects"),
    ("SCENE", "Scene", "set of scenes"),
    ("HDR", "HDR", "HDR image"),
    ("MATERIAL", "Material", "any .blend Material"),
    ("TEXTURE", "Texture", "a texture, or texture set"),
    ("BRUSH", "Brush", "brush, can be any type of blender brush"),
    ("NODEGROUP", "Node Group", "node group, can be any type of blender node group"),
    ("PRINTABLE", "Printable", "3D printable model"),
)


class KillBgProcess(bpy.types.Operator):
    """Remove processes in background"""

    bl_idname = "object.kill_bg_process"
    bl_label = "Kill Background Process"
    bl_options = {"REGISTER"}

    process_type: EnumProperty(  # type: ignore[valid-type]
        name="Type",
        items=process_types,
        description="Type of process",
        default="UPLOAD",
    )

    process_source: EnumProperty(  # type: ignore[valid-type]
        name="Source",
        items=process_sources,
        description="Source of process",
        default="MODEL",
    )

    def execute(self, context):
        # first do the easy stuff...TODO all cases.
        props = utils.get_upload_props()
        if self.process_type == "UPLOAD":
            props.uploading = False
        if self.process_type == "THUMBNAILER":
            props.is_generating_thumbnail = False
            if hasattr(props, "is_generating_wire_thumbnail"):
                props.is_generating_wire_thumbnail = False
        # print('killing', self.process_source, self.process_type)
        # then go kill the process. this wasn't working for unsetting props and that was the reason for changing to the method above.

        global bg_processes
        processes = bg_processes
        for p in processes:
            tcom = p[1]
            # print(tcom.process_type, self.process_type)
            if tcom.process_type == self.process_type:
                source = _safe_eval_target(tcom.eval_path, tcom.name)
                kill = False
                # TODO HDR - add killing of process
                if source is not None:
                    if (
                        source.bl_rna.name == "Object"
                        and self.process_source == "MODEL"
                    ):
                        if source.name == bpy.context.active_object.name:
                            kill = True
                    if source.bl_rna.name == "Scene" and self.process_source == "SCENE":
                        if source.name == bpy.context.scene.name:
                            kill = True
                    if source.bl_rna.name == "Image" and self.process_source == "HDR":
                        ui_props = bpy.context.window_manager.blenderkitUI
                        if source.name == ui_props.hdr_upload_image.name:
                            kill = False

                    if (
                        source.bl_rna.name == "Material"
                        and self.process_source == "MATERIAL"
                    ):
                        if (
                            source.name
                            == bpy.context.active_object.active_material.name
                        ):
                            kill = True
                    if source.bl_rna.name == "Brush" and self.process_source == "BRUSH":
                        brush = utils.get_active_brush()
                        if brush is not None and source.name == brush.name:
                            kill = True
                    if (
                        source.bl_rna.name == "Object"
                        and self.process_source == "PRINTABLE"
                    ):
                        if source.name == bpy.context.active_object.name:
                            kill = True
                if kill:
                    estring = tcom.eval_path_computing + " = False"
                    exec(estring)
                    processes.remove(p)
                    tcom.proc.kill()

        return {"FINISHED"}


def add_bg_process(
    location=None,
    name=None,
    eval_path_computing="",
    eval_path_state="",
    eval_path="",
    process_type="",
    process=None,
):
    """adds process for monitoring"""
    global bg_processes
    tcom = ThreadCom(
        eval_path_computing,
        eval_path_state,
        eval_path,
        process_type,
        process,
        location,
        name,
    )
    readthread = threading.Thread(target=threadread, args=([tcom]), daemon=True)
    readthread.start()

    bg_processes.append([readthread, tcom])
    # if not bpy.app.timers.is_registered(bg_update):
    #     bpy.app.timers.register(bg_update, persistent=True)


def register():
    bpy.utils.register_class(KillBgProcess)
    if not bpy.app.background:
        bpy.app.timers.register(bg_update)


def unregister():
    bpy.utils.unregister_class(KillBgProcess)
    if bpy.app.timers.is_registered(bg_update):
        bpy.app.timers.unregister(bg_update)
