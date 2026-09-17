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
import queue
from typing import Tuple

import bpy
from bpy.app.handlers import persistent

from . import utils


bk_logger = logging.getLogger(__name__)


@persistent
def scene_load(context):
    if bpy.app.background is True:
        return
    if not (bpy.app.timers.is_registered(queue_worker)):
        bpy.app.timers.register(queue_worker)


def get_queue():
    # we pick just a random one of blender types, to try to get a persistent queue
    t = bpy.types.Scene
    if not hasattr(t, "task_queue"):
        t.task_queue = queue.Queue()
    return t.task_queue


class task_object:
    def __init__(
        self,
        command="",
        arguments=(),
        wait: float = 0,
        only_last=False,
        fake_context=False,
        fake_context_area="VIEW_3D",
    ):
        self.command = command
        self.arguments = arguments
        self.wait = wait
        self.only_last = only_last
        self.fake_context = fake_context
        self.fake_context_area = fake_context_area


def add_task(
    task: Tuple,
    wait: float = 0,
    only_last=False,
    fake_context=False,
    fake_context_area="VIEW_3D",
):
    q = get_queue()
    taskob = task_object(
        task[0],
        task[1],
        wait=wait,
        only_last=only_last,
        fake_context=fake_context,
        fake_context_area=fake_context_area,
    )
    q.put(taskob)


# @bpy.app.handlers.persistent
def queue_worker():
    # utils.p('start queue worker timer')

    # bk_logger.debug('timer queue worker')
    time_step = 0.3
    q = get_queue()
    # save some performance by returning early
    if q.empty():
        return time_step
    back_to_queue = []  # delayed events
    stashed = {}
    # first round we get all tasks that are supposed to be stashed and run only once (only_last option)
    # stashing finds tasks with the property only_last and same command and executes only the last one.
    while not q.empty():
        task = q.get()
        if task.only_last:
            # this now makes the keys not only by task, but also two arguments.
            # by now stashing is only used for ratings, where the first argument is url, second rating type.
            # This enables fast rating of multiple assets while allowing larger delay for uploading of ratings.
            # this avoids a duplicate request error on the server
            stashed[f"{task.command}-{task.arguments[0]}-{task.arguments[1]}"] = task
        else:
            back_to_queue.append(task)
    # return tasks to que except for stashed
    for task in back_to_queue:
        q.put(task)
    # return stashed tasks to queue
    for k in stashed.keys():
        q.put(stashed[k])
    # second round, execute or put back waiting tasks.
    back_to_queue = []
    while not q.empty():
        # print('window manager', bpy.context.window_manager)
        task = q.get()

        if task.wait > 0:
            task.wait -= time_step
            back_to_queue.append(task)
        else:
            bk_logger.log(
                5, "task queue task: %s %s", task.command, task.arguments[10:]
            )
            try:
                if task.fake_context:
                    fc = utils.get_fake_context(
                        bpy.context, area_type=task.fake_context_area
                    )
                    if not fc.get("region"):
                        bk_logger.debug(
                            "skipping task %s: no %s area available for fake context",
                            task.command,
                            task.fake_context_area,
                        )
                        continue
                    if bpy.app.version < (4, 0, 0):
                        task.command(fc, *task.arguments)
                    else:
                        with bpy.context.temp_override(**fc):
                            task.command(*task.arguments)
                else:
                    task.command(*task.arguments)
            except Exception:
                bk_logger.exception(
                    "task queue failed task: %s %s",
                    task.command,
                    task.arguments[10:],
                )
                # bk_logger.exception('Got exception on main handler')
                # raise
        # print('queue while 2')
    for task in back_to_queue:
        q.put(task)
    # utils.p('end queue worker timer')
    return time_step


def register():
    bpy.app.handlers.load_post.append(scene_load)


def unregister():
    bpy.app.handlers.load_post.remove(scene_load)
